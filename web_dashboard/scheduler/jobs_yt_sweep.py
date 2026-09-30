"""YouTube holdings sweep job (Phase K8 — pull retrieval).

The K3 allowlist poll asks *"what did my 13 curated channels say?"*. This job asks
*"what does YouTube have about the things we actually own?"* — it searches by
company name for every non-fund production holding, confirms the hits are about
the issuer (``yt_holdings_search``), and lands captions for the best of them
through the same K2 ``ingest_video`` path.

Search is listing-only and costs **no caption quota** (§13), so the search half
runs across the whole book every time. Only the ingest half is budgeted.

Two things this job does that the hand-run script did not have to care about:

**Pre-filter against ``research_articles``.** ``ingest_video`` fetches captions
*before* its own ``article_exists`` check, so handing it a video already in the
table spends a caption fetch to learn nothing. On a one-shot manual run that is a
rounding error; on a nightly job it is the entire budget, every night, forever —
the top-scored hit for each name never changes. The K3 poll pre-filters for the
same reason (``jobs_yt.poll_source``).

**Round-robin the budget across holdings.** Ordering the fetch queue by score
globally lets a handful of well-covered names take every fetch, so the long tail
of the book is never reached. Taking each holding's best unlanded hit in turn
spends the same budget on coverage instead of depth, which is what §26 says this
retrieval path is *for*.
"""

from __future__ import annotations

import logging
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

# Path boilerplate matches the other job modules: project root must sit ahead of
# web_dashboard so the root ``utils`` package is not shadowed.
_web_dashboard_path = str(Path(__file__).resolve().parent.parent)
if _web_dashboard_path not in sys.path:
    sys.path.insert(0, _web_dashboard_path)
_project_root = str(Path(__file__).resolve().parent.parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

logger = logging.getLogger(__name__)

JOB_ID = "youtube_holdings_sweep"

_MAX_FETCHES_ENV = "YOUTUBE_SWEEP_MAX_FETCHES"
_MAX_FETCHES_DEFAULT = 15
# Hits to consider per holding. Search is free, so this is only about how deep the
# round-robin can go before a name is exhausted for the night.
_TOP_PER_HOLDING_DEFAULT = 3
_SEARCH_LIMIT_DEFAULT = 12
_SLEEP_BETWEEN_SEARCHES_S = 1.0


def max_fetches() -> int:
    """Caption-fetch ceiling for one run."""
    import os

    raw = (os.environ.get(_MAX_FETCHES_ENV) or "").strip()
    try:
        return max(int(raw), 0) if raw else _MAX_FETCHES_DEFAULT
    except ValueError:
        return _MAX_FETCHES_DEFAULT


@dataclass
class SweepSummary:
    holdings_searched: int = 0
    with_confirmed_hits: int = 0
    planned: int = 0
    landed: int = 0
    skipped_known: int = 0
    skipped_too_old: int = 0
    soft_failed: int = 0
    errors: int = 0
    statuses: dict[str, int] = field(default_factory=dict)
    results: list[dict[str, Any]] = field(default_factory=list)

    @property
    def coverage(self) -> float:
        if not self.holdings_searched:
            return 0.0
        return self.with_confirmed_hits / self.holdings_searched

    @property
    def message(self) -> str:
        return (
            f"{self.with_confirmed_hits}/{self.holdings_searched} holdings covered "
            f"({self.coverage:.0%}); landed {self.landed}, "
            f"skipped_known {self.skipped_known}, skipped_too_old {self.skipped_too_old}, "
            f"soft_fail {self.soft_failed}, errors {self.errors}"
        )


def holdings_rows(
    tickers: Sequence[str] | None = None, *, client: Any | None = None
) -> list[dict[str, Any]]:
    """Production holdings joined to ``securities`` for company_name + sector."""
    if client is None:
        from supabase_client import SupabaseClient

        client = SupabaseClient(use_service_role=True)

    if tickers:
        held = sorted({str(t).strip().upper() for t in tickers if str(t).strip()})
    else:
        funds = (
            client.supabase.table("funds")
            .select("name")
            .eq("is_production", True)
            .execute()
            .data
            or []
        )
        names = [f["name"] for f in funds if f.get("name")]
        if not names:
            return []
        pos = (
            client.supabase.table("latest_positions")
            .select("ticker")
            .in_("fund", names)
            .execute()
            .data
            or []
        )
        held = sorted({str(p["ticker"]) for p in pos if p.get("ticker")})
    if not held:
        return []
    rows = (
        client.supabase.table("securities")
        .select("ticker,company_name,sector")
        .in_("ticker", held)
        .execute()
        .data
        or []
    )
    return [dict(r) for r in rows]


def plan_fetches(
    results: Iterable[Mapping[str, Any]],
    *,
    budget: int,
    is_known: Callable[[str], bool] | None = None,
    is_stale: Callable[[str], bool] | None = None,
) -> tuple[list[tuple[str, Mapping[str, Any]]], int]:
    """Choose which hits to spend caption fetches on.

    Round-robin: every holding's best unlanded hit, then every holding's second,
    and so on until the budget runs out. Returns ``(queue, skipped_known)``.

    ``is_stale(video_id)`` drops too-old videos before they cost a caption fetch.
    It matters beyond one night: a video rejected as too old is never saved, so the
    ``is_known`` pre-filter would re-offer it — and re-spend the budget on it —
    every night forever.
    """
    from yt_captions import watch_url_for

    known = is_known or (lambda _url: False)
    per_ticker: list[list[tuple[str, Mapping[str, Any]]]] = []
    skipped_known = 0

    for entry in results:
        ticker = str(entry.get("ticker") or "")
        fresh: list[tuple[str, Mapping[str, Any]]] = []
        for hit in sorted(
            entry.get("hits") or [], key=lambda h: -int(h.get("score") or 0)
        ):
            video_id = str(hit.get("video_id") or "")
            if not video_id:
                continue
            try:
                if known(watch_url_for(video_id)):
                    skipped_known += 1
                    continue
            except Exception as exc:
                # A failed existence check must not drop the candidate; the
                # ingest path re-checks before writing anyway.
                logger.warning("article_exists check failed for %s: %s", video_id, exc)
            fresh.append((ticker, hit))
        if fresh:
            per_ticker.append(fresh)

    queue: list[tuple[str, Mapping[str, Any]]] = []
    depth = 0
    while len(queue) < budget and per_ticker:
        progressed = False
        for hits in per_ticker:
            if depth >= len(hits):
                continue
            progressed = True
            # Checked here, not in the pre-filter pass, so the metadata lookup only
            # runs for hits that would actually be queued. A stale hit costs no
            # budget: the round-robin simply moves on to the next holding.
            if is_stale is not None and is_stale(str(hits[depth][1].get("video_id") or "")):
                continue
            queue.append(hits[depth])
            if len(queue) >= budget:
                break
        if not progressed:
            break
        depth += 1
    return queue, skipped_known


def _stale_checker(
    max_age_days: int,
    metadata_fn: Callable[[str], Any] | None,
    summary: SweepSummary,
) -> Callable[[str], bool] | None:
    """``is_stale`` for ``plan_fetches``: one metadata call (no caption quota) per hit.

    Unknown dates and lookup failures return False — ``ingest_video`` re-checks the
    date once captions land, so failing open here only costs one fetch, never data.
    """
    if max_age_days <= 0:
        return None
    if metadata_fn is None:
        from yt_captions import fetch_video_metadata as metadata_fn  # type: ignore
    from yt_articles import published_at_from_upload_date

    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)

    def is_stale(video_id: str) -> bool:
        try:
            meta = metadata_fn(video_id)
        except Exception as exc:
            logger.warning("Metadata lookup failed for %s: %s", video_id, exc)
            return False
        published = published_at_from_upload_date(getattr(meta, "upload_date", None))
        if published is None or published >= cutoff:
            return False
        summary.skipped_too_old += 1
        return True

    return is_stale


def sweep_holdings(
    *,
    research_repo: Any,
    tickers: Sequence[str] | None = None,
    ollama_client: Any | None = None,
    supabase_client: Any | None = None,
    search_fn: Callable[..., Sequence[Any]] | None = None,
    ingest_fn: Callable[..., Any] | None = None,
    metadata_fn: Callable[[str], Any] | None = None,
    budget: int | None = None,
    max_age_days: int | None = None,
    search_limit: int = _SEARCH_LIMIT_DEFAULT,
    top_per_holding: int = _TOP_PER_HOLDING_DEFAULT,
    include_funds: bool = False,
    ingest: bool = True,
    sleep_fn: Callable[[float], None] | None = None,
) -> SweepSummary:
    """Search every holding, then land captions for the best unlanded hits."""
    from yt_holdings_search import search_holding, sweep_max_age_days, targets_from_holdings

    search = search_fn or search_holding
    sleep = sleep_fn if sleep_fn is not None else time.sleep
    fetch_budget = max_fetches() if budget is None else max(0, int(budget))
    age_limit = sweep_max_age_days() if max_age_days is None else max(0, int(max_age_days))
    summary = SweepSummary()

    rows = holdings_rows(tickers, client=supabase_client)
    targets = targets_from_holdings(rows, include_funds=include_funds)
    if not targets:
        logger.info("No searchable holdings resolved for the sweep")
        return summary

    summary.holdings_searched = len(targets)
    try:
        from yt_proxy_rotation import preflight

        logger.info("VPN exit rotation: %s", preflight())
    except Exception as exc:  # pragma: no cover - never block the sweep on this
        logger.warning("Rotation preflight unavailable: %s", exc)
    logger.info(
        "Sweeping %s holdings (search is free; caption budget %s)",
        len(targets),
        fetch_budget,
    )

    for index, target in enumerate(targets):
        try:
            hits = list(search(target, limit=search_limit, max_age_days=age_limit))[
                :top_per_holding
            ]
        except Exception as exc:
            # One bad name must never take the sweep down.
            logger.warning("Search failed for %s: %s", target.ticker, exc)
            summary.errors += 1
            hits = []
        if hits:
            summary.with_confirmed_hits += 1
        summary.results.append(
            {
                "ticker": target.ticker,
                "company": target.core_name,
                "query": target.query(),
                "confirmed": len(hits),
                "hits": [
                    {
                        "video_id": h.video_id,
                        "title": h.title,
                        "url": h.url,
                        "score": h.score,
                        "views": h.view_count,
                        "matched": list(h.matched),
                    }
                    for h in hits
                ],
            }
        )
        if index < len(targets) - 1:
            sleep(_SLEEP_BETWEEN_SEARCHES_S)

    if not ingest or fetch_budget <= 0:
        logger.info("YouTube holdings sweep (search only): %s", summary.message)
        return summary

    queue, skipped_known = plan_fetches(
        summary.results,
        budget=fetch_budget,
        is_known=getattr(research_repo, "article_exists", None),
        is_stale=_stale_checker(age_limit, metadata_fn, summary),
    )
    summary.planned = len(queue)
    summary.skipped_known = skipped_known

    from yt_articles import ingest_video

    do_ingest = ingest_fn or ingest_video
    owned = _owned_tickers()

    for ticker, hit in queue:
        try:
            outcome = do_ingest(
                str(hit.get("video_id")),
                research_repo=research_repo,
                ollama_client=ollama_client,
                # Search hits have no youtube_sources row. expected_tickers stays
                # empty on purpose: this is not an issuer channel, so tickers must
                # come from the transcript (§26 / is_issuer_channel).
                source_row={"label": f"search:{ticker}", "expected_tickers": []},
                owned_tickers=owned,
                # Flat search listings rarely carry upload_date, so this is the
                # guard that actually bites: the date is known once captions land.
                max_age_days=age_limit,
            )
        except Exception as exc:
            logger.error("Ingest failed for %s: %s", hit.get("video_id"), exc)
            summary.errors += 1
            continue

        status = getattr(outcome, "status", "error")
        summary.statuses[status] = summary.statuses.get(status, 0) + 1
        if status in ("saved", "queued"):
            summary.landed += 1
        elif status == "soft_fail":
            summary.soft_failed += 1
        elif status == "skipped_exists":
            summary.skipped_known += 1
        elif status == "skipped_too_old":
            summary.skipped_too_old += 1
        elif status == "error":
            summary.errors += 1

    logger.info("YouTube holdings sweep: %s", summary.message)
    return summary


def _owned_tickers() -> list[str]:
    try:
        from scheduler.jobs_yt import production_holdings

        return list(production_holdings())
    except Exception as exc:
        logger.warning("Could not resolve production holdings: %s", exc)
        return []


def youtube_holdings_sweep_job() -> None:
    """Scheduled Phase K8 pull retrieval over production holdings."""
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

        logger.info("Starting YouTube holdings sweep job...")

        try:
            from research_repository import ResearchRepository
            from yt_articles import ingest_video  # noqa: F401 - fail fast on import
            from yt_holdings_search import search_holding  # noqa: F401
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
            # Embeddings are optional here, but a NULL one silently excludes the
            # row from every similarity path (K10, ideas-inbox dedup).
            logger.warning("Ollama client unavailable (no embeddings): %s", exc)

        summary = sweep_holdings(
            research_repo=ResearchRepository(),
            ollama_client=ollama_client,
        )

        duration_ms = int((time.time() - start_time) * 1000)
        message = summary.message
        try:
            log_job_execution(JOB_ID, True, message, duration_ms)
        except Exception as log_error:
            logger.warning("Failed to log job execution: %s", log_error)
        try:
            mark_job_completed(
                JOB_ID, target_date, None, [], duration_ms=duration_ms, message=message
            )
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
        logger.error("❌ YouTube holdings sweep failed: %s", exc, exc_info=True)
        try:
            from utils.job_tracking import mark_job_failed

            mark_job_failed(JOB_ID, target_date, None, message, duration_ms=duration_ms)
        except Exception:
            pass
