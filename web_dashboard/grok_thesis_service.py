"""Grok Bot weekday thesis evidence sweep: thesis queue + web-research review ingest.

The Bot pulls a few active Insights theses, reads recent filings, press releases and
news on the web, and posts a verdict plus cited sources. Reviews land in
``grok_thesis_reviews``; each source is mirrored into ``thesis_evidence`` as a
``grok_review`` row so it shows on the thesis page.

Advisory only, like the X briefs: nothing here touches ``last_reviewed_at``,
disposition, intent or ``thesis_entries``. The thesis evaluation job reads the latest
review as untrusted context (the Bot summarised pages written by strangers).
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import urlparse

from grok_bot_service import GrokBotRequestError, utc_today
from prompt_safety import contains_instruction_like_text, sanitize_for_llm

logger = logging.getLogger(__name__)

THESIS_QUEUE_LIMIT = 5
DAILY_THESIS_CAP = 5
MAX_REVIEWS_PER_REQUEST = 5
# 82 active theses at 5 per weekday is a ~16-weekday rotation, so 14 days keeps the
# queue full while stopping a thesis from being re-reviewed every few days.
REVIEW_INTERVAL_DAYS = 14
MAX_SOURCES_PER_REVIEW = 8
MAX_SUMMARY_CHARS = 8000
MAX_SOURCE_TITLE_CHARS = 300
MAX_SOURCE_SNIPPET_CHARS = 1000
MAX_URL_CHARS = 2000
THESIS_TEXT_CHARS = 4000
RECENT_ENTRY_CHARS = 600
RECENT_ENTRY_COUNT = 3
KNOWN_URLS_LIMIT = 40
LAST_REVIEW_SUMMARY_CHARS = 800

VERDICTS = frozenset({"supports", "contradicts", "mixed", "no_change"})
RELATIONS = frozenset({"supports", "contradicts", "context"})
EVIDENCE_KIND = "grok_review"
CREATED_BY = "grok_bot"
_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


# --- queue -----------------------------------------------------------------


def count_theses_reviewed_on(pg: Any, review_date: date, *, exclude_thesis: str | None = None) -> int:
    rows = pg.execute_query(
        """
        SELECT COUNT(DISTINCT thesis_id)::int AS n
        FROM grok_thesis_reviews
        WHERE review_date = %s AND (%s::uuid IS NULL OR thesis_id <> %s::uuid)
        """,
        (review_date, exclude_thesis, exclude_thesis),
    )
    return int((rows[0] or {}).get("n") or 0) if rows else 0


def build_thesis_queue(
    pg: Any, *, today: date | None = None, limit: int = THESIS_QUEUE_LIMIT
) -> list[dict[str, Any]]:
    """Active theses due a Grok review: never-reviewed first, then oldest review.

    Returns at most ``limit - theses already reviewed today`` items, so it is empty
    after a full day's run.
    """
    day = today or utc_today()
    headroom = min(limit, DAILY_THESIS_CAP - count_theses_reviewed_on(pg, day))
    if headroom <= 0:
        return []
    cutoff = day - timedelta(days=REVIEW_INTERVAL_DAYS)
    rows = pg.execute_query(
        """
        SELECT t.id, t.ticker, t.title, t.disposition, t.intent, t.created_at,
               r.last_review_date
        FROM ticker_theses t
        LEFT JOIN LATERAL (
            SELECT MAX(g.review_date) AS last_review_date
            FROM grok_thesis_reviews g WHERE g.thesis_id = t.id
        ) r ON TRUE
        WHERE t.status = 'active'
          AND (r.last_review_date IS NULL OR r.last_review_date <= %s)
        ORDER BY r.last_review_date ASC NULLS FIRST, t.created_at ASC
        LIMIT %s
        """,
        (cutoff, headroom),
    )
    if not rows:
        return []
    ids = [str(r["id"]) for r in rows]
    entries = _recent_entries(pg, ids)
    last_reviews = _last_reviews(pg, ids)
    known = _known_urls(pg, ids)
    items: list[dict[str, Any]] = []
    for row in rows:
        tid = str(row["id"])
        thread = entries.get(tid, [])
        opening = next((e for e in thread if e.get("entry_kind") == "opening"), None)
        recent = [e for e in thread if e is not opening][-RECENT_ENTRY_COUNT:]
        last = last_reviews.get(tid)
        items.append(
            {
                "thesis_id": tid,
                "ticker": str(row.get("ticker") or ""),
                "title": str(row.get("title") or ""),
                "disposition": row.get("disposition"),
                "intent": row.get("intent"),
                "thesis_text": _clip((opening or {}).get("body"), THESIS_TEXT_CHARS),
                "recent_entries": [
                    {
                        "kind": e.get("entry_kind"),
                        "author": e.get("author_kind"),
                        "at": _iso(e.get("created_at")),
                        "body": _clip(e.get("body"), RECENT_ENTRY_CHARS),
                    }
                    for e in recent
                ],
                "last_review_date": _iso(row.get("last_review_date")),
                "last_review_verdict": (last or {}).get("verdict"),
                "last_review_summary": _clip((last or {}).get("summary"), LAST_REVIEW_SUMMARY_CHARS),
                "known_urls": known.get(tid, [])[:KNOWN_URLS_LIMIT],
            }
        )
    return items


def _recent_entries(pg: Any, ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    rows = pg.execute_query(
        """
        SELECT thesis_id, entry_kind, author_kind, body, created_at
        FROM thesis_entries
        WHERE thesis_id = ANY(%s::uuid[])
        ORDER BY created_at ASC
        """,
        (ids,),
    )
    out: dict[str, list[dict[str, Any]]] = {}
    for row in rows or []:
        out.setdefault(str(row["thesis_id"]), []).append(dict(row))
    return out


def _last_reviews(pg: Any, ids: list[str]) -> dict[str, dict[str, Any]]:
    rows = pg.execute_query(
        """
        SELECT DISTINCT ON (thesis_id) thesis_id, verdict, summary
        FROM grok_thesis_reviews
        WHERE thesis_id = ANY(%s::uuid[])
        ORDER BY thesis_id, review_date DESC
        """,
        (ids,),
    )
    return {str(r["thesis_id"]): dict(r) for r in rows or []}


def _known_urls(pg: Any, ids: list[str]) -> dict[str, list[str]]:
    rows = pg.execute_query(
        """
        SELECT thesis_id, url
        FROM thesis_evidence
        WHERE thesis_id = ANY(%s::uuid[]) AND url IS NOT NULL AND url <> ''
        ORDER BY created_at DESC
        """,
        (ids,),
    )
    out: dict[str, list[str]] = {}
    for row in rows or []:
        urls = out.setdefault(str(row["thesis_id"]), [])
        url = str(row["url"])
        if url not in urls:
            urls.append(url)
    return out


# --- ingest ----------------------------------------------------------------


def parse_review_payloads(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not payload or not isinstance(payload, dict):
        raise GrokBotRequestError("JSON object required")
    if "reviews" in payload:
        raw_list = payload.get("reviews")
        if not isinstance(raw_list, list) or not raw_list:
            raise GrokBotRequestError("reviews must be a non-empty list")
        if len(raw_list) > MAX_REVIEWS_PER_REQUEST:
            raise GrokBotRequestError(f"at most {MAX_REVIEWS_PER_REQUEST} reviews per request")
        return [_normalize_review(item) for item in raw_list]
    return [_normalize_review(payload)]


def _normalize_review(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise GrokBotRequestError("each review must be an object")
    thesis_id = str(item.get("thesis_id") or "").strip().lower()
    if not _UUID_RE.match(thesis_id):
        raise GrokBotRequestError("thesis_id must be the UUID from the thesis queue")
    verdict = str(item.get("verdict") or "").strip().lower()
    if verdict not in VERDICTS:
        raise GrokBotRequestError(f"verdict must be one of: {', '.join(sorted(VERDICTS))}")
    summary_raw = item.get("summary")
    if not isinstance(summary_raw, str) or not summary_raw.strip():
        raise GrokBotRequestError("summary is required")
    if len(summary_raw) > MAX_SUMMARY_CHARS:
        raise GrokBotRequestError(f"summary exceeds {MAX_SUMMARY_CHARS} characters")
    summary = sanitize_for_llm(summary_raw, max_chars=MAX_SUMMARY_CHARS).strip()
    if not summary:
        raise GrokBotRequestError("summary is required")
    if contains_instruction_like_text(summary):
        # Not rejected (a filing can quote anything), but leave a trail before an LLM reads it.
        logger.warning("Grok thesis review %s contains instruction-like text", thesis_id[:8])
    return {
        "thesis_id": thesis_id,
        "verdict": verdict,
        "summary": summary,
        "sources": _normalize_sources(item.get("sources")),
        "review_date": _parse_review_date(item.get("review_date")),
    }


def _parse_review_date(raw: Any) -> date:
    if raw is None or raw == "":
        return utc_today()
    try:
        parsed = date.fromisoformat(str(raw).strip()[:10])
    except ValueError as exc:
        raise GrokBotRequestError("review_date must be YYYY-MM-DD") from exc
    today = utc_today()
    if parsed not in (today, today - timedelta(days=1)):
        raise GrokBotRequestError("review_date must be today or yesterday (UTC)")
    return parsed


def _is_allowed_source_url(url: str) -> bool:
    """Web pages only: http(s), a real host, no embedded credentials."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme.lower() not in ("http", "https"):
        return False
    if not parsed.hostname or parsed.username or parsed.password:
        return False
    return True


def _normalize_sources(raw: Any) -> list[dict[str, str]]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise GrokBotRequestError("sources must be a list")
    if len(raw) > MAX_SOURCES_PER_REVIEW:
        raise GrokBotRequestError(f"at most {MAX_SOURCES_PER_REVIEW} sources per review")
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise GrokBotRequestError("each source must be an object")
        url = sanitize_for_llm(item.get("url"), max_chars=MAX_URL_CHARS).strip()
        if not url or not _is_allowed_source_url(url):
            raise GrokBotRequestError("each source needs an http(s) url")
        relation = str(item.get("relation") or "context").strip().lower()
        if relation not in RELATIONS:
            raise GrokBotRequestError("source relation must be supports, contradicts or context")
        if url in seen:
            continue
        seen.add(url)
        source = {"url": url, "relation": relation}
        title = sanitize_for_llm(item.get("title"), max_chars=MAX_SOURCE_TITLE_CHARS).strip()
        snippet = sanitize_for_llm(item.get("snippet"), max_chars=MAX_SOURCE_SNIPPET_CHARS).strip()
        published = sanitize_for_llm(item.get("published"), max_chars=40).strip()
        if title:
            source["title"] = title
        if snippet:
            source["snippet"] = snippet
        if published:
            source["published"] = published
        out.append(source)
    return out


def store_reviews(pg: Any, reviews: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Upsert each review and replace its thesis_evidence rows. Same thesis + day is idempotent."""
    stored: list[dict[str, Any]] = []
    for review in reviews:
        stored.append(_store_one(pg, review))
    return stored


def _store_one(pg: Any, review: dict[str, Any]) -> dict[str, Any]:
    thesis_id = review["thesis_id"]
    rows = pg.execute_query(
        "SELECT ticker, status FROM ticker_theses WHERE id = %s::uuid", (thesis_id,)
    )
    if not rows or rows[0].get("status") != "active":
        raise GrokBotRequestError("thesis not found or not active", 404)
    ticker = str(rows[0].get("ticker") or "")
    day = review["review_date"]
    if count_theses_reviewed_on(pg, day, exclude_thesis=thesis_id) >= DAILY_THESIS_CAP:
        raise GrokBotRequestError(f"daily cap of {DAILY_THESIS_CAP} theses reached", 429)

    saved = pg.execute_query(
        """
        INSERT INTO grok_thesis_reviews (thesis_id, ticker, review_date, verdict, summary, sources)
        VALUES (%s::uuid, %s, %s, %s, %s, %s::jsonb)
        ON CONFLICT (thesis_id, review_date) DO UPDATE SET
            verdict = EXCLUDED.verdict,
            summary = EXCLUDED.summary,
            sources = EXCLUDED.sources,
            status = 'ingested',
            updated_at = now()
        RETURNING id
        """,
        (thesis_id, ticker, day, review["verdict"], review["summary"], json.dumps(review["sources"])),
    )
    review_id = str(saved[0]["id"])

    # A same-day retry replaces this review's evidence instead of stacking duplicates.
    pg.execute_update(
        "DELETE FROM thesis_evidence WHERE evidence_kind = %s AND ref_id = %s::uuid",
        (EVIDENCE_KIND, review_id),
    )
    existing = pg.execute_query(
        "SELECT url FROM thesis_evidence WHERE thesis_id = %s::uuid AND url IS NOT NULL",
        (thesis_id,),
    )
    known = {str(r["url"]) for r in existing or []}
    filed = 0
    for source in review["sources"]:
        if source["url"] in known:
            continue
        # ticker_theses.updated_at is left alone on purpose: Bot input must not look
        # like the thesis author edited it.
        pg.execute_update(
            """
            INSERT INTO thesis_evidence
                (thesis_id, evidence_kind, ref_id, url, title, snippet, relation, created_by)
            VALUES (%s::uuid, %s, %s::uuid, %s, %s, %s, %s, %s)
            """,
            (
                thesis_id,
                EVIDENCE_KIND,
                review_id,
                source["url"],
                source.get("title"),
                source.get("snippet"),
                source["relation"],
                CREATED_BY,
            ),
        )
        known.add(source["url"])
        filed += 1
    return {
        "thesis_id": thesis_id,
        "ticker": ticker,
        "review_id": review_id,
        "review_date": day.isoformat(),
        "verdict": review["verdict"],
        "evidence_filed": filed,
        "evidence_skipped_duplicate": len(review["sources"]) - filed,
    }


# --- consumers -------------------------------------------------------------


def review_excerpt_for_prompt(
    pg: Any, thesis_id: str, *, days: int = 21, max_chars: int = 1500
) -> tuple[str, list[str]]:
    """Latest Grok review of this thesis, wrapped as untrusted data for an LLM prompt.

    The Bot summarised web pages written by third parties, so the text goes through
    prepare_untrusted_for_prompt() like the X briefs. Empty when nothing is recent.
    """
    if not pg or not thesis_id:
        return "", []
    try:
        rows = pg.execute_query(
            """
            SELECT id, review_date, verdict, summary, sources
            FROM grok_thesis_reviews
            WHERE thesis_id = %s::uuid AND review_date >= CURRENT_DATE - %s::int
            ORDER BY review_date DESC
            LIMIT 1
            """,
            (thesis_id, max(0, int(days))),
        )
    except Exception as exc:
        logger.debug("grok thesis review excerpt skipped for %s: %s", thesis_id, exc)
        return "", []
    if not rows:
        return "", []
    from prompt_safety import prepare_untrusted_for_prompt

    row = rows[0]
    sources = row.get("sources") or []
    if isinstance(sources, str):
        try:
            sources = json.loads(sources)
        except ValueError:
            sources = []
    lines = [
        f"- [{s.get('relation')}] {s.get('title') or s.get('url')}"
        for s in sources
        if isinstance(s, dict)
    ]
    text = f"[{_iso(row.get('review_date'))}] verdict: {row.get('verdict')}\n{row.get('summary') or ''}"
    if lines:
        text += "\nSources:\n" + "\n".join(lines)
    wrapped = prepare_untrusted_for_prompt(text, source="grok_thesis_review", max_chars=max_chars)
    return (
        f"Grok web-research review (untrusted, for context only):\n{wrapped}",
        [str(row.get("id"))],
    )


def mark_reviews_evaluated(pg: Any, review_ids: list[str]) -> int:
    """Best effort: flip consumed reviews to 'evaluated' after the advisory reply is posted."""
    ids = [str(i) for i in (review_ids or []) if i]
    if not pg or not ids:
        return 0
    try:
        pg.execute_update(
            """
            UPDATE grok_thesis_reviews SET status = 'evaluated', updated_at = now()
            WHERE id = ANY(%s::uuid[]) AND status = 'ingested'
            """,
            (ids,),
        )
        return len(ids)
    except Exception as exc:
        logger.debug("marking grok thesis reviews evaluated failed: %s", exc)
        return 0


# --- helpers ---------------------------------------------------------------


def _clip(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)
