"""Normalize allowlisted YouTube captions into ``research_articles`` (Phase K2).

K1 (``youtube_captions``) fetches + cleans caption text. K2 lands that text as an
article-shaped row so the **existing** summarize / ticker-extract / meta / dossier
paths consume it — no parallel "video insights" store, no separate meta stack.

Decisions made here (documented in ``docs/PHASE_JK_PLAN.md``):

- ``article_type = 'YouTube Transcript'`` — exact string; source-ROI grain.
- ``url`` = canonical ``https://www.youtube.com/watch?v={id}`` — the unique key,
  so a re-run upserts instead of duplicating.
- ``source`` = ``youtube:{channel_id}`` (falls back to ``youtube:@handle`` then a
  slug of the channel name). Never bare ``youtube.com``: ``track_record_service``
  slices ROI by ``source``, and one host label would average a trusted IR channel
  together with every macro pundit.
- Collector facts (``video_id`` / ``channel_id`` / ``duration_s`` /
  ``caption_lang`` / ``caption_kind``) go in ``research_articles.source_metadata``
  (additive JSONB, migration ``2026-07_add_article_source_metadata.sql``) rather
  than ``claims``, which the summarizer owns and overwrites.
- Length policy v0 = **stitch + single summarize** with a hard ``content`` cap
  (``YOUTUBE_TRANSCRIPT_MAX_CHARS``, default 64k chars ≈ 75-minute call) and a
  larger summarizer budget for this article type. Map-reduce chunking is a K3+
  concern; ``source_metadata.truncated`` flags rows that lost their tail.

Summarize is **mandatory**, not optional: ``meta_analysis_service`` only embeds
``title`` + ``conclusion`` + ``sentiment``, so an un-summarized transcript is
invisible to every downstream consumer that matters.
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from youtube_captions import (
    CaptionFetchError,
    CaptionResult,
    fetch_caption_text,
    watch_url_for,
)

logger = logging.getLogger(__name__)

ARTICLE_TYPE = "YouTube Transcript"
SOURCE_PREFIX = "youtube:"

# Hard cap on the stored ``content`` body. 64k chars is ~16k tokens — well past
# the summarizer budget, but the full text is still worth keeping for embeddings
# and future re-summarize / chunking passes.
_CONTENT_MAX_CHARS_DEFAULT = 64_000
_CONTENT_MAX_CHARS_ENV = "YOUTUBE_TRANSCRIPT_MAX_CHARS"

# ``research_articles.source`` is VARCHAR(100); UC channel ids are 24 chars.
_SOURCE_MAX_LEN = 100
_SLUG_RE = re.compile(r"[^a-z0-9]+")

IngestStatus = Literal[
    "saved",  # row landed with summarize + tickers inline
    "queued",  # row landed; enrichment enqueued on the AI task queue
    "skipped_exists",  # already ingested (idempotent re-run)
    "skipped_duration",  # outside the source's min/max duration window
    "soft_fail",  # CaptionFetchError — blocked / no_captions / age_restricted / ...
    "error",  # unexpected failure; nothing persisted
]


def content_max_chars() -> int:
    """Configured hard cap for the stored transcript body."""
    raw = (os.environ.get(_CONTENT_MAX_CHARS_ENV) or "").strip()
    if not raw:
        return _CONTENT_MAX_CHARS_DEFAULT
    try:
        value = int(raw)
    except ValueError:
        logger.warning(
            "Ignoring non-integer %s=%r; using %s",
            _CONTENT_MAX_CHARS_ENV,
            raw,
            _CONTENT_MAX_CHARS_DEFAULT,
        )
        return _CONTENT_MAX_CHARS_DEFAULT
    if value <= 0:
        logger.warning(
            "Ignoring non-positive %s=%s; using %s",
            _CONTENT_MAX_CHARS_ENV,
            value,
            _CONTENT_MAX_CHARS_DEFAULT,
        )
        return _CONTENT_MAX_CHARS_DEFAULT
    return value


def source_label(
    *,
    channel_id: str | None = None,
    handle: str | None = None,
    channel: str | None = None,
) -> str:
    """Channel-grain ``source`` label for a transcript row.

    Channel grain (not ``youtube.com``) so source-ROI can rank an IR channel
    separately from a macro commentator. Falls back through handle → channel
    name slug → ``youtube:unknown`` so the column is never bare-host or null.
    """
    cid = (channel_id or "").strip()
    if cid:
        return f"{SOURCE_PREFIX}{cid}"[:_SOURCE_MAX_LEN]

    raw_handle = (handle or "").strip()
    if raw_handle:
        return f"{SOURCE_PREFIX}@{raw_handle.lstrip('@')}"[:_SOURCE_MAX_LEN]

    slug = _SLUG_RE.sub("-", (channel or "").strip().lower()).strip("-")
    if slug:
        return f"{SOURCE_PREFIX}{slug}"[:_SOURCE_MAX_LEN]
    return f"{SOURCE_PREFIX}unknown"


def normalize_caption_kind(raw: str | None) -> str:
    """Collapse K1's fetch-specific kinds to the ``manual``/``auto`` contract."""
    value = (raw or "").strip().lower()
    if value in ("manual", "vtt_manual"):
        return "manual"
    return "auto"


def published_at_from_upload_date(upload_date: str | None) -> datetime | None:
    """Parse yt-dlp's ``YYYYMMDD`` upload date into a UTC datetime.

    yt-dlp reports upload date only (no time), so this is midnight UTC on the
    upload day — good enough for the 14d/90d/730d windows every consumer uses.
    Returns ``None`` when metadata was unavailable (transcript-api path with no
    yt-dlp fallback), which leaves ``published_at`` null and makes the row
    invisible to windowed consumers until a later poll fills it in.
    """
    raw = (upload_date or "").strip()
    if not raw:
        return None
    for fmt in ("%Y%m%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    logger.info("Unparseable YouTube upload_date %r", raw)
    return None


@dataclass(frozen=True)
class TranscriptArticle:
    """The ``research_articles``-shaped projection of one captioned video."""

    video_id: str
    url: str
    title: str
    content: str
    source: str
    published_at: datetime | None
    source_metadata: dict[str, Any]
    truncated: bool
    expected_tickers: tuple[str, ...] = ()


def normalize_transcript(
    result: CaptionResult,
    *,
    source_row: Mapping[str, Any] | None = None,
) -> TranscriptArticle:
    """Project a :class:`CaptionResult` (+ optional ``youtube_sources`` row) to article fields."""
    row = dict(source_row or {})
    cap = content_max_chars()
    text = result.text or ""
    truncated = len(text) > cap
    content = text[:cap] if truncated else text

    channel_id = result.channel_id or (row.get("channel_id") or None)
    channel = result.channel or (row.get("label") or None)
    caption_kind = normalize_caption_kind(result.caption_kind)

    expected = tuple(
        str(t).upper().strip()
        for t in (row.get("expected_tickers") or [])
        if str(t).strip()
    )

    # Fall back to the video id rather than a generic stub: ticker meta and the
    # dossier timeline show titles, and "YouTube Transcript" alone is useless.
    title = (result.title or "").strip() or f"YouTube video {result.video_id}"

    metadata: dict[str, Any] = {
        "video_id": result.video_id,
        "channel_id": channel_id,
        "channel": channel,
        "duration_s": result.duration_s,
        "caption_lang": result.language or None,
        "caption_kind": caption_kind,
        "caption_kind_raw": result.caption_kind,
        "fetch_source": result.fetch_source,
        "char_count": len(content),
        "truncated": truncated,
    }
    if row.get("id") is not None:
        metadata["youtube_source_id"] = int(row["id"])
    if row.get("alpha_mechanism"):
        metadata["alpha_mechanism"] = str(row["alpha_mechanism"])

    return TranscriptArticle(
        video_id=result.video_id,
        url=result.watch_url or watch_url_for(result.video_id),
        title=title,
        content=content,
        source=source_label(
            channel_id=channel_id,
            handle=row.get("handle"),
            channel=channel,
        ),
        published_at=published_at_from_upload_date(result.upload_date),
        source_metadata=metadata,
        truncated=truncated,
        expected_tickers=expected,
    )


@dataclass
class EnrichmentResult:
    """Outcome of the summarize + ticker-extraction pass over one transcript."""

    summary: str | None = None
    sector: str | None = None
    tickers: list[str] = field(default_factory=list)
    relevance_score: float | None = None
    summary_data: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return bool(self.summary_data.get("conclusion") or self.summary)


def summarize_transcript(
    *,
    title: str,
    content: str,
    expected_tickers: Sequence[str] = (),
    owned_tickers: Sequence[str] | None = None,
    summarize_fn: Callable[..., Any] | None = None,
) -> EnrichmentResult:
    """Run the same summarize + ticker-extract path as ``symbol_article_scraper_job``.

    ``claim_recent_summary_input`` (the 6h in-process summary-input hash guard
    other ingest paths use) is deliberately **not** applied: exact-URL dedup plus
    ``article_exists`` already stop re-work for a video, and a stitched caption
    body colliding across two different videos is not a real scenario. Chunked
    transcripts would need it — that is a K3+ concern.
    """
    if summarize_fn is None:
        from ollama_client import generate_summary as _generate_summary

        summarize_fn = _generate_summary

    result = EnrichmentResult()
    summary_input = f"Title: {title}\n\n{content}" if title else content
    summary_data = summarize_fn(summary_input, article_type=ARTICLE_TYPE)

    if isinstance(summary_data, str):
        result.summary = summary_data
        summary_data = {}
    elif isinstance(summary_data, dict) and summary_data:
        result.summary = summary_data.get("summary", "")
        from ticker_validator import extract_and_validate_tickers

        validated = extract_and_validate_tickers(summary_data, title, content)
        # Allowlist ``expected_tickers`` lead: an IR channel is registered against
        # a known ticker, so keep it first even if the model missed it.
        merged = list(expected_tickers)
        for ticker in validated:
            if ticker not in merged:
                merged.append(ticker)
        result.tickers = merged

        sectors = summary_data.get("sectors") or []
        if sectors:
            result.sector = sectors[0]
    else:
        summary_data = {}

    result.summary_data = summary_data if isinstance(summary_data, dict) else {}
    if not result.tickers and expected_tickers:
        result.tickers = list(expected_tickers)

    from scheduler.jobs_common import calculate_relevance_score

    result.relevance_score = calculate_relevance_score(
        result.tickers,
        result.sector,
        owned_tickers=list(owned_tickers) if owned_tickers else None,
    )
    return result


@dataclass
class IngestOutcome:
    """What happened to one video. ``reason`` carries the K1 soft-fail code."""

    status: IngestStatus
    video_id: str = ""
    url: str = ""
    article_id: str | None = None
    reason: str | None = None
    message: str | None = None
    title: str | None = None
    source: str | None = None
    char_count: int = 0
    tickers: list[str] = field(default_factory=list)

    @property
    def landed(self) -> bool:
        return self.status in ("saved", "queued")


def transcript_summary_queue_enabled() -> bool:
    """Whether transcript enrichment should go through the AI task queue."""
    try:
        from scheduler.ai_task_workers import (
            QUEUE_JOB_YOUTUBE_TRANSCRIPT_SUMMARY,
            is_ai_queue_job_enabled,
        )

        return bool(is_ai_queue_job_enabled(QUEUE_JOB_YOUTUBE_TRANSCRIPT_SUMMARY))
    except Exception as exc:
        logger.warning(
            "AI queue mode check failed for youtube_transcript_summary "
            "(summarizing inline): %s",
            exc,
        )
        return False


def _duration_allowed(
    duration_s: int | None, source_row: Mapping[str, Any] | None
) -> tuple[bool, str | None]:
    if duration_s is None or not source_row:
        return True, None
    minimum = source_row.get("min_duration_s")
    maximum = source_row.get("max_duration_s")
    if minimum is not None and duration_s < int(minimum):
        return False, f"duration {duration_s}s below min_duration_s={int(minimum)}"
    if maximum is not None and duration_s > int(maximum):
        return False, f"duration {duration_s}s above max_duration_s={int(maximum)}"
    return True, None


def ingest_video(
    url_or_id: str,
    *,
    research_repo: Any,
    source_row: Mapping[str, Any] | None = None,
    owned_tickers: Sequence[str] | None = None,
    ollama_client: Any | None = None,
    force: bool = False,
    use_queue: bool | None = None,
    supabase_client: Any | None = None,
    fetch_fn: Callable[..., CaptionResult] | None = None,
    summarize_fn: Callable[..., Any] | None = None,
    enqueue_fn: Callable[..., Any] | None = None,
) -> IngestOutcome:
    """Land one allowlisted video as a ``YouTube Transcript`` article, end to end.

    Fetch → clean → normalize → upsert → summarize + ticker extract. Caption
    failures soft-fail with the K1 reason code (``blocked`` / ``no_captions`` /
    ``age_restricted`` / ...) so a caller polling an allowlist can keep going.

    When ``youtube_transcript_summary`` is enabled on the AI task queue the row
    lands first and enrichment is enqueued (transcripts are long; this keeps them
    off the inline global AI lock that ``alpha_research`` already contends for).
    Otherwise enrichment runs inline, matching ``symbol_article_scraper_job``.
    """
    fetch = fetch_fn or fetch_caption_text

    try:
        result = fetch(url_or_id)
    except CaptionFetchError as exc:
        logger.info(
            "YouTube caption soft-fail (%s) for %r: %s", exc.reason, url_or_id, exc
        )
        return IngestOutcome(
            status="soft_fail",
            video_id=exc.video_id,
            url=watch_url_for(exc.video_id) if exc.video_id else "",
            reason=exc.reason,
            message=str(exc),
        )

    article = normalize_transcript(result, source_row=source_row)

    allowed, why = _duration_allowed(result.duration_s, source_row)
    if not allowed:
        logger.info("Skipping %s: %s", article.video_id, why)
        return IngestOutcome(
            status="skipped_duration",
            video_id=article.video_id,
            url=article.url,
            reason="duration",
            message=why,
            title=article.title,
        )

    if not force:
        try:
            if research_repo.article_exists(article.url):
                logger.info(
                    "Transcript already ingested (idempotent skip): %s", article.url
                )
                return IngestOutcome(
                    status="skipped_exists",
                    video_id=article.video_id,
                    url=article.url,
                    title=article.title,
                    source=article.source,
                )
        except Exception as exc:
            logger.warning("article_exists check failed for %s: %s", article.url, exc)

    queue_mode = transcript_summary_queue_enabled() if use_queue is None else use_queue

    try:
        if queue_mode:
            return _ingest_queued(
                article,
                research_repo=research_repo,
                enqueue_fn=enqueue_fn,
                supabase_client=supabase_client,
                source_row=source_row,
            )
        return _ingest_inline(
            article,
            research_repo=research_repo,
            owned_tickers=owned_tickers,
            ollama_client=ollama_client,
            summarize_fn=summarize_fn,
        )
    except Exception as exc:
        logger.error(
            "Failed to ingest transcript for %s: %s", article.video_id, exc, exc_info=True
        )
        return IngestOutcome(
            status="error",
            video_id=article.video_id,
            url=article.url,
            reason="save_failed",
            message=str(exc),
            title=article.title,
        )


def _ingest_inline(
    article: TranscriptArticle,
    *,
    research_repo: Any,
    owned_tickers: Sequence[str] | None,
    ollama_client: Any | None,
    summarize_fn: Callable[..., Any] | None,
) -> IngestOutcome:
    enrichment = summarize_transcript(
        title=article.title,
        content=article.content,
        expected_tickers=article.expected_tickers,
        owned_tickers=owned_tickers,
        summarize_fn=summarize_fn,
    )
    if not enrichment.ok:
        # Still persist: the body is the expensive part to re-fetch (YouTube
        # rate-limits hard), and the queue handler or a later force re-run can
        # fill in the CoT fields. Downstream meta simply ignores it until then.
        logger.warning(
            "Summarize produced no conclusion for %s; saving un-enriched",
            article.video_id,
        )

    embedding = None
    if ollama_client is not None:
        try:
            embedding = ollama_client.generate_embedding(article.content)
        except Exception as exc:
            logger.warning("Embedding failed for %s: %s", article.video_id, exc)

    data = enrichment.summary_data
    article_id = research_repo.save_article(
        tickers=enrichment.tickers or None,
        sector=enrichment.sector,
        article_type=ARTICLE_TYPE,
        title=article.title,
        url=article.url,
        summary=enrichment.summary,
        content=article.content,
        source=article.source,
        published_at=article.published_at,
        relevance_score=enrichment.relevance_score,
        embedding=embedding,
        claims=data.get("claims"),
        fact_check=data.get("fact_check"),
        conclusion=data.get("conclusion"),
        sentiment=data.get("sentiment"),
        sentiment_score=data.get("sentiment_score"),
        logic_check=data.get("logic_check"),
        source_metadata=article.source_metadata,
    )
    if not article_id:
        return IngestOutcome(
            status="error",
            video_id=article.video_id,
            url=article.url,
            reason="save_failed",
            message="save_article returned no id",
            title=article.title,
        )

    logger.info(
        "✅ Landed YouTube Transcript %s (%s chars, tickers=%s)",
        article.video_id,
        len(article.content),
        enrichment.tickers or "-",
    )
    return IngestOutcome(
        status="saved",
        video_id=article.video_id,
        url=article.url,
        article_id=article_id,
        title=article.title,
        source=article.source,
        char_count=len(article.content),
        tickers=list(enrichment.tickers),
    )


def _ingest_queued(
    article: TranscriptArticle,
    *,
    research_repo: Any,
    enqueue_fn: Callable[..., Any] | None,
    supabase_client: Any | None,
    source_row: Mapping[str, Any] | None,
) -> IngestOutcome:
    """Persist the body now; enqueue summarize + ticker extraction for a worker."""
    article_id = research_repo.save_article(
        tickers=list(article.expected_tickers) or None,
        sector=None,
        article_type=ARTICLE_TYPE,
        title=article.title,
        url=article.url,
        summary=None,
        content=article.content,
        source=article.source,
        published_at=article.published_at,
        # Provisional: the worker recomputes this from the extracted tickers.
        relevance_score=0.5,
        embedding=None,
        source_metadata=article.source_metadata,
    )
    if not article_id:
        return IngestOutcome(
            status="error",
            video_id=article.video_id,
            url=article.url,
            reason="save_failed",
            message="save_article returned no id",
            title=article.title,
        )

    if enqueue_fn is None:
        from scheduler.ai_task_workers import (
            enqueue_youtube_transcript_summary_tasks as _enqueue,
        )

        enqueue_fn = _enqueue
    if supabase_client is None:
        from supabase_client import SupabaseClient

        supabase_client = SupabaseClient(use_service_role=True)

    row = dict(source_row or {})
    enqueue_fn(
        supabase_client,
        [
            {
                "video_id": article.video_id,
                "article_id": article_id,
                "url": article.url,
                "expected_tickers": list(article.expected_tickers),
                "youtube_source_id": row.get("id"),
            }
        ],
    )
    logger.info(
        "✅ Landed YouTube Transcript %s (%s chars); enrichment queued",
        article.video_id,
        len(article.content),
    )
    return IngestOutcome(
        status="queued",
        video_id=article.video_id,
        url=article.url,
        article_id=article_id,
        title=article.title,
        source=article.source,
        char_count=len(article.content),
        tickers=list(article.expected_tickers),
    )


def enrich_saved_transcript(
    *,
    research_repo: Any,
    article_id: str,
    title: str,
    content: str,
    expected_tickers: Sequence[str] = (),
    owned_tickers: Sequence[str] | None = None,
    ollama_client: Any | None = None,
    summarize_fn: Callable[..., Any] | None = None,
) -> EnrichmentResult:
    """Summarize + ticker-extract an already-saved transcript row, then update it.

    Shared by the AI task queue handler and any force re-enrichment. Uses
    ``update_article_analysis`` so ``content`` / ``url`` / ``published_at`` /
    ``source_metadata`` are preserved.
    """
    enrichment = summarize_transcript(
        title=title,
        content=content,
        expected_tickers=expected_tickers,
        owned_tickers=owned_tickers,
        summarize_fn=summarize_fn,
    )
    if not enrichment.ok:
        raise RuntimeError(
            f"youtube transcript summarize produced no output for article {article_id}"
        )

    embedding = None
    if ollama_client is not None:
        try:
            embedding = ollama_client.generate_embedding(content)
        except Exception as exc:
            logger.warning("Embedding failed for article %s: %s", article_id, exc)

    data = enrichment.summary_data
    research_repo.update_article_analysis(
        article_id,
        summary=enrichment.summary,
        tickers=enrichment.tickers,
        sector=enrichment.sector,
        embedding=embedding,
        relevance_score=enrichment.relevance_score,
        claims=data.get("claims"),
        fact_check=data.get("fact_check"),
        conclusion=data.get("conclusion"),
        sentiment=data.get("sentiment"),
        sentiment_score=data.get("sentiment_score"),
        logic_check=data.get("logic_check"),
    )
    return enrichment
