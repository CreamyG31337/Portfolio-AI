"""YouTube allowlist poll job (Phase K3).

Polls every enabled ``youtube_sources`` row for new videos and lands them through
the **existing** K2 path (``yt_articles.ingest_video``). This module owns
discovery, cursors, caps, and source health only — caption fetch (K1), article
normalization/upsert and summarize (K2) are not reimplemented here.

Per source: mark ``last_polled_at`` → list newest-first candidates (flat
playlist metadata, capped by ``max_videos_per_poll``) → walk them until the cursor is
hit → skip anything already in ``research_articles`` → ``ingest_video`` the rest.

**Cursor rule** (``last_video_id`` / ``last_seen_at``): the walk stops at
``last_video_id``, and after the walk the cursor advances to the **newest listed
video id** — not to the newest one that succeeded — but *only* when nothing in
this poll failed for a retriable reason (``blocked`` / ``unknown`` /
``dependency``, i.e. rate-limit or environment problems that a later poll can
plausibly clear). Failures that will never resolve on retry (``no_captions``,
``age_restricted``, ``unavailable``, ``parse``) and skips (duration gate, already
ingested) count as *considered*, so a channel that posts one caption-less video
does not stall the cursor forever. A retriable failure leaves the cursor where it
was, so the next poll re-walks the same window and picks the video back up. When
a listing call itself fails, nothing is walked and the cursor is untouched.

Caps: ``youtube_sources.max_videos_per_poll`` (default 5) bounds one source, and
``YOUTUBE_INGEST_MAX_PER_RUN`` (default 20) bounds ingests across all sources in
one run. Once the global cap is hit the remaining sources are still marked polled
but not walked, and no cursor advances for them.

Soft-fail isolation: ``ingest_video`` returns a status instead of raising, and
every per-video and per-source step here is wrapped, so one blocked video (or one
dead channel) never aborts the run.

Allowlist only. Discovery never leaves ``youtube_sources``; ``kind='search'``
runs the row's curated ``query_text`` with a tiny N and does not expand by
ticker. TODO (K4+): if ticker-scoped IR search is added, restrict the expansion
to production holdings + watchlist before it goes anywhere near open-web YouTube.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence

# Path boilerplate matches the other job modules: project root must sit ahead of
# web_dashboard so the root ``utils`` package is not shadowed.
_web_dashboard_path = str(Path(__file__).resolve().parent.parent)
if _web_dashboard_path not in sys.path:
    sys.path.insert(0, _web_dashboard_path)
_project_root = str(Path(__file__).resolve().parent.parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)
elif sys.path[0] != _project_root:
    sys.path.remove(_project_root)
    sys.path.insert(0, _project_root)

logger = logging.getLogger(__name__)

JOB_ID = "youtube_caption_ingest"

_MAX_PER_RUN_ENV = "YOUTUBE_INGEST_MAX_PER_RUN"
_MAX_PER_RUN_DEFAULT = 20
_MAX_VIDEOS_PER_POLL_DEFAULT = 5

# Reasons a later poll can plausibly clear. Anything else is treated as settled
# for this video, so the cursor may move past it (see the module docstring).
RETRIABLE_REASONS: frozenset[str] = frozenset({"blocked", "unknown", "dependency"})

# Captions are genuinely absent for this channel/video — worth surfacing on the
# source row. ``blocked`` deliberately does not clear ``captions_ok``: that is an
# egress/rate-limit problem, not a statement about the channel's captions.
_CAPTIONS_MISSING_REASONS: frozenset[str] = frozenset({"no_captions"})

# Pause between videos. Caption providers block per egress IP on volume, and the
# listing/VTT fallback shares that address, so pacing is the main defence short
# of ``YOUTUBE_PROXY_URL``.
_SLEEP_BETWEEN_VIDEOS_S = 3.0
_SLEEP_BETWEEN_SOURCES_S = 2.0


def max_per_run() -> int:
    """Global ingest cap for one poll run."""
    raw = (os.environ.get(_MAX_PER_RUN_ENV) or "").strip()
    if not raw:
        return _MAX_PER_RUN_DEFAULT
    try:
        value = int(raw)
    except ValueError:
        logger.warning(
            "Ignoring non-integer %s=%r; using %s",
            _MAX_PER_RUN_ENV,
            raw,
            _MAX_PER_RUN_DEFAULT,
        )
        return _MAX_PER_RUN_DEFAULT
    if value <= 0:
        logger.warning(
            "Ignoring non-positive %s=%s; using %s",
            _MAX_PER_RUN_ENV,
            value,
            _MAX_PER_RUN_DEFAULT,
        )
        return _MAX_PER_RUN_DEFAULT
    return value


@dataclass
class SourcePollResult:
    """What one ``youtube_sources`` row did in this run."""

    source_id: Optional[int]
    label: str
    listed: int = 0
    considered: int = 0
    # Videos this source actually sent to ``ingest_video`` — the quantity the
    # global cap bounds, since that is what costs network + LLM time.
    attempted: int = 0
    landed: int = 0
    skipped_exists: int = 0
    skipped_duration: int = 0
    soft_failed: int = 0
    errors: int = 0
    listing_error: Optional[str] = None
    cursor_advanced_to: Optional[str] = None
    capped: bool = False
    last_reason: Optional[str] = None


@dataclass
class PollSummary:
    """Aggregate of one poll run, for the job log line and for tests."""

    sources_polled: int = 0
    landed: int = 0
    considered: int = 0
    attempted: int = 0
    skipped_exists: int = 0
    skipped_duration: int = 0
    soft_failed: int = 0
    errors: int = 0
    listing_errors: int = 0
    capped: bool = False
    results: list[SourcePollResult] = field(default_factory=list)

    @property
    def message(self) -> str:
        parts = [
            f"{self.sources_polled} sources",
            f"{self.landed} landed",
            f"{self.attempted} fetched",
            f"{self.considered} considered",
            f"{self.skipped_exists} already",
            f"{self.skipped_duration} duration-skip",
            f"{self.soft_failed} soft-fail",
            f"{self.errors} error",
            f"{self.listing_errors} listing-error",
        ]
        if self.capped:
            parts.append("global cap hit")
        return ", ".join(parts)


def production_holdings(supabase_client: Any | None = None) -> list[str]:
    """Holdings-scoped relevance input — production funds only.

    Same shape as ``scripts/yt_article_ingest.py`` and the transcript queue
    handler: relevance scoring should reflect what the production funds actually
    hold, and TEST funds must not widen it.
    """
    try:
        if supabase_client is None:
            from supabase_client import SupabaseClient

            supabase_client = SupabaseClient(use_service_role=True)
        funds = (
            supabase_client.supabase.table("funds")
            .select("name")
            .eq("is_production", True)
            .execute()
        )
        names = [f["name"] for f in (funds.data or [])]
        if not names:
            return []
        positions = (
            supabase_client.supabase.table("latest_positions")
            .select("ticker")
            .in_("fund", names)
            .execute()
        )
        return sorted(
            {str(p["ticker"]) for p in (positions.data or []) if p.get("ticker")}
        )
    except Exception as exc:
        logger.warning("Could not load production holdings: %s", exc)
        return []


def load_enabled_sources(
    postgres_client: Any, *, source_id: Optional[int] = None
) -> list[dict[str, Any]]:
    """Enabled allowlist rows in a stable order (never disabled rows)."""
    if source_id is not None:
        rows = postgres_client.execute_query(
            "SELECT * FROM youtube_sources WHERE enabled = true AND id = %s",
            (source_id,),
        )
    else:
        rows = postgres_client.execute_query(
            "SELECT * FROM youtube_sources WHERE enabled = true ORDER BY id"
        )
    return [dict(row) for row in (rows or [])]


def _source_label(row: Mapping[str, Any]) -> str:
    return str(
        row.get("label")
        or row.get("channel_id")
        or row.get("handle")
        or row.get("query_text")
        or f"source {row.get('id')}"
    )


def _per_poll_limit(row: Mapping[str, Any]) -> int:
    try:
        value = int(row.get("max_videos_per_poll") or _MAX_VIDEOS_PER_POLL_DEFAULT)
    except (TypeError, ValueError):
        value = _MAX_VIDEOS_PER_POLL_DEFAULT
    return max(1, value)


def _update_source(
    postgres_client: Any, source_id: Optional[int], assignments: dict[str, Any]
) -> None:
    """Best-effort health/cursor write. Never raises into the poll loop."""
    if source_id is None or not assignments:
        return
    sets = [f"{column} = {expr}" for column, (expr, _) in assignments.items()]
    params = tuple(
        value for _, (_, value) in assignments.items() if value is not _NO_PARAM
    )
    sql = (
        "UPDATE youtube_sources SET "
        + ", ".join(sets)
        + ", updated_at = NOW() WHERE id = %s"
    )
    try:
        postgres_client.execute_update(sql, params + (source_id,))
    except Exception as exc:
        logger.warning("Could not update youtube_sources id=%s: %s", source_id, exc)


class _NoParam:
    """Marker for SQL assignments that carry no bound parameter."""


_NO_PARAM = _NoParam()


def mark_polled(postgres_client: Any, source_id: Optional[int]) -> None:
    """Stamp the attempt before any network work, so a crash still shows it."""
    _update_source(postgres_client, source_id, {"last_polled_at": ("NOW()", _NO_PARAM)})


def mark_source_outcome(
    postgres_client: Any,
    source_id: Optional[int],
    *,
    any_success: bool,
    failure_reason: Optional[str],
    cursor_video_id: Optional[str],
) -> None:
    """Write the post-walk health + cursor fields for one source.

    ``any_success`` (a video landed, was already present, or was cleanly
    duration-skipped) resets the failure streak; a failure increments it and
    records the K1 reason. Both can be true in one poll — a partially successful
    poll is still progress, so success wins on the streak and the reason is kept
    for ops visibility.
    """
    assignments: dict[str, Any] = {}
    if any_success:
        assignments["last_success_at"] = ("NOW()", _NO_PARAM)
        assignments["consecutive_failures"] = ("0", _NO_PARAM)
        assignments["captions_ok"] = ("true", _NO_PARAM)
    elif failure_reason:
        assignments["consecutive_failures"] = (
            "consecutive_failures + 1",
            _NO_PARAM,
        )
    if failure_reason:
        assignments["last_error_reason"] = ("%s", failure_reason[:32])
        if failure_reason in _CAPTIONS_MISSING_REASONS and not any_success:
            assignments["captions_ok"] = ("false", _NO_PARAM)
    elif any_success:
        assignments["last_error_reason"] = ("NULL", _NO_PARAM)

    if cursor_video_id:
        assignments["last_video_id"] = ("%s", cursor_video_id[:16])
        assignments["last_seen_at"] = ("NOW()", _NO_PARAM)

    _update_source(postgres_client, source_id, assignments)


def poll_source(
    row: Mapping[str, Any],
    *,
    postgres_client: Any,
    research_repo: Any,
    owned_tickers: Sequence[str] | None = None,
    ollama_client: Any | None = None,
    list_fn: Callable[..., Sequence[Any]] | None = None,
    ingest_fn: Callable[..., Any] | None = None,
    remaining_budget: int = _MAX_PER_RUN_DEFAULT,
    dry_run: bool = False,
    sleep_fn: Callable[[float], None] | None = None,
) -> SourcePollResult:
    """Poll one allowlist row. Never raises; failures land in the result."""
    from yt_captions import CaptionFetchError, list_source_videos

    source_id = row.get("id")
    result = SourcePollResult(source_id=source_id, label=_source_label(row))
    listing = list_fn or list_source_videos
    ingest = ingest_fn
    if ingest is None:
        from yt_articles import ingest_video as ingest

    sleep = sleep_fn if sleep_fn is not None else time.sleep

    if not dry_run:
        mark_polled(postgres_client, source_id)

    if remaining_budget <= 0:
        result.capped = True
        return result

    per_poll = min(_per_poll_limit(row), remaining_budget)
    try:
        candidates = list(listing(row, limit=per_poll))
    except CaptionFetchError as exc:
        result.listing_error = exc.reason
        result.last_reason = exc.reason
        logger.warning(
            "Listing failed for youtube_sources id=%s (%s): %s",
            source_id,
            exc.reason,
            exc,
        )
        if not dry_run:
            mark_source_outcome(
                postgres_client,
                source_id,
                any_success=False,
                failure_reason=exc.reason,
                cursor_video_id=None,
            )
        return result
    except Exception as exc:
        result.listing_error = "unknown"
        result.last_reason = "unknown"
        logger.error(
            "Unexpected listing error for youtube_sources id=%s: %s",
            source_id,
            exc,
            exc_info=True,
        )
        if not dry_run:
            mark_source_outcome(
                postgres_client,
                source_id,
                any_success=False,
                failure_reason="unknown",
                cursor_video_id=None,
            )
        return result

    result.listed = len(candidates)
    if not candidates:
        logger.info("No videos listed for %s (id=%s)", result.label, source_id)
        return result

    cursor = str(row.get("last_video_id") or "").strip()
    newest_listed = candidates[0].video_id
    any_success = False
    retriable_failure = False
    failure_reason: Optional[str] = None

    for index, candidate in enumerate(candidates):
        if candidate.video_id == cursor:
            # Newest-first walk reached the previous cursor: everything below it
            # was handled by an earlier poll.
            break
        if result.attempted >= remaining_budget:
            result.capped = True
            break

        watch_url = candidate.watch_url
        try:
            if research_repo.article_exists(watch_url):
                result.skipped_exists += 1
                result.considered += 1
                any_success = True
                continue
        except Exception as exc:
            # Not fatal: ingest_video repeats this check before writing.
            logger.warning("article_exists check failed for %s: %s", watch_url, exc)

        if dry_run:
            result.considered += 1
            logger.info(
                "[dry-run] would ingest %s (%s) for %s",
                candidate.video_id,
                (candidate.title or "")[:60],
                result.label,
            )
            continue

        if index > 0:
            sleep(_SLEEP_BETWEEN_VIDEOS_S)

        result.attempted += 1
        try:
            outcome = ingest(
                watch_url,
                research_repo=research_repo,
                source_row=row,
                owned_tickers=list(owned_tickers or []),
                ollama_client=ollama_client,
            )
        except Exception as exc:
            # ingest_video is meant to soft-fail rather than raise; if it does
            # raise, keep walking the allowlist anyway.
            result.errors += 1
            failure_reason = "unknown"
            retriable_failure = True
            logger.error(
                "ingest_video raised for %s (source id=%s): %s",
                candidate.video_id,
                source_id,
                exc,
                exc_info=True,
            )
            continue

        status = getattr(outcome, "status", "error")
        reason = getattr(outcome, "reason", None)
        result.considered += 1
        if status in ("saved", "queued"):
            result.landed += 1
            any_success = True
        elif status == "skipped_exists":
            result.skipped_exists += 1
            any_success = True
        elif status == "skipped_duration":
            result.skipped_duration += 1
            any_success = True
        elif status == "soft_fail":
            result.soft_failed += 1
            failure_reason = reason or "unknown"
            if failure_reason in RETRIABLE_REASONS:
                retriable_failure = True
        else:
            result.errors += 1
            failure_reason = reason or "unknown"
            retriable_failure = True

    result.last_reason = failure_reason

    # Cursor rule: advance to the newest *listed* id, so permanently un-ingestable
    # videos (no captions, age-restricted) cannot stall the source. A retriable
    # failure or a cap hit leaves the cursor put so the next poll re-walks.
    cursor_video_id: Optional[str] = None
    if (
        result.considered > 0
        and not retriable_failure
        and not result.capped
        and not dry_run
    ):
        cursor_video_id = newest_listed
        result.cursor_advanced_to = newest_listed

    if not dry_run and (any_success or failure_reason or cursor_video_id):
        mark_source_outcome(
            postgres_client,
            source_id,
            any_success=any_success,
            failure_reason=failure_reason,
            cursor_video_id=cursor_video_id,
        )

    return result


def poll_youtube_sources(
    *,
    postgres_client: Any,
    research_repo: Any,
    owned_tickers: Sequence[str] | None = None,
    ollama_client: Any | None = None,
    list_fn: Callable[..., Sequence[Any]] | None = None,
    ingest_fn: Callable[..., Any] | None = None,
    max_videos: Optional[int] = None,
    source_id: Optional[int] = None,
    dry_run: bool = False,
    sleep_fn: Callable[[float], None] | None = None,
) -> PollSummary:
    """Walk every enabled allowlist row, capped globally. Never raises per source."""
    summary = PollSummary()
    budget = max_per_run() if max_videos is None else max(0, int(max_videos))
    sleep = sleep_fn if sleep_fn is not None else time.sleep

    rows = load_enabled_sources(postgres_client, source_id=source_id)
    if not rows:
        logger.info("No enabled youtube_sources rows to poll")
        return summary

    logger.info(
        "Polling %s enabled youtube_sources (global cap %s videos)%s",
        len(rows),
        budget,
        " [dry-run]" if dry_run else "",
    )

    for index, row in enumerate(rows):
        if index > 0 and not dry_run:
            sleep(_SLEEP_BETWEEN_SOURCES_S)
        try:
            result = poll_source(
                row,
                postgres_client=postgres_client,
                research_repo=research_repo,
                owned_tickers=owned_tickers,
                ollama_client=ollama_client,
                list_fn=list_fn,
                ingest_fn=ingest_fn,
                remaining_budget=budget,
                dry_run=dry_run,
                sleep_fn=sleep_fn,
            )
        except Exception as exc:
            # Defensive: poll_source is already fully guarded, but one bad row
            # must never take the whole allowlist down.
            logger.error(
                "Unexpected failure polling youtube_sources id=%s: %s",
                row.get("id"),
                exc,
                exc_info=True,
            )
            summary.sources_polled += 1
            summary.errors += 1
            continue

        summary.sources_polled += 1
        summary.results.append(result)
        summary.landed += result.landed
        summary.attempted += result.attempted
        summary.considered += result.considered
        summary.skipped_exists += result.skipped_exists
        summary.skipped_duration += result.skipped_duration
        summary.soft_failed += result.soft_failed
        summary.errors += result.errors
        if result.listing_error:
            summary.listing_errors += 1
        if result.capped:
            summary.capped = True

        budget -= result.attempted
        if budget <= 0:
            summary.capped = True
            logger.info(
                "Global cap of %s videos reached; %s sources left unpolled this run",
                max_per_run() if max_videos is None else max_videos,
                len(rows) - index - 1,
            )
            break

    logger.info("YouTube allowlist poll: %s", summary.message)
    return summary


def youtube_caption_ingest_job() -> None:
    """Scheduled Phase K3 poll of the ``youtube_sources`` allowlist."""
    start_time = time.time()
    target_date = datetime.now(timezone.utc).date()

    try:
        from scheduler.scheduler_core import log_job_execution
    except Exception:  # pragma: no cover - scheduler always ships this
        def log_job_execution(*_args: Any, **_kwargs: Any) -> None:
            return None

    try:
        from utils.job_tracking import mark_job_completed, mark_job_failed, mark_job_started

        try:
            mark_job_started(JOB_ID, target_date)
        except Exception:
            pass

        logger.info("Starting YouTube allowlist poll job...")

        try:
            from postgres_client import PostgresClient
            from research_repository import ResearchRepository
            from yt_articles import ingest_video  # noqa: F401 - fail fast on import
        except ImportError as exc:
            duration_ms = int((time.time() - start_time) * 1000)
            message = f"Missing dependency: {exc}"
            try:
                log_job_execution(JOB_ID, False, message, duration_ms)
            except Exception as log_error:
                logger.warning("Failed to log job execution: %s", log_error)
            logger.error("❌ %s", message)
            try:
                mark_job_failed(JOB_ID, target_date, None, message, duration_ms=duration_ms)
            except Exception:
                pass
            return

        ollama_client = None
        try:
            from ollama_client import get_ollama_client

            ollama_client = get_ollama_client()
        except Exception as exc:
            # Embeddings are optional; the body and summary are what matter.
            logger.warning("Ollama client unavailable (no embeddings): %s", exc)

        summary = poll_youtube_sources(
            postgres_client=PostgresClient(),
            research_repo=ResearchRepository(),
            owned_tickers=production_holdings(),
            ollama_client=ollama_client,
        )

        duration_ms = int((time.time() - start_time) * 1000)
        message = summary.message
        try:
            log_job_execution(JOB_ID, True, message, duration_ms)
        except Exception as log_error:
            logger.warning("Failed to log job execution: %s", log_error)
        try:
            mark_job_completed(JOB_ID, target_date, None, [], duration_ms=duration_ms, message=message)
        except Exception:
            pass
        logger.info("✅ %s", message)

    except Exception as exc:
        duration_ms = int((time.time() - start_time) * 1000)
        message = f"Error: {exc}"
        try:
            log_job_execution(JOB_ID, False, message, duration_ms)
        except Exception as log_error:
            logger.warning("Failed to log job execution error: %s", log_error)
        try:
            from utils.job_tracking import mark_job_failed

            mark_job_failed(JOB_ID, target_date, None, message, duration_ms=duration_ms)
        except Exception:
            pass
        logger.error("❌ YouTube allowlist poll job failed: %s", exc, exc_info=True)
