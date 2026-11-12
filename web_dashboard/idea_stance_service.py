"""Alpha/Opportunity ideas → ``stance_history`` (ROADMAP §2.8 Z1/Z3).

WHY THIS EXISTS
---------------
Ideas used to be measurable only through a human click: Accept admitted the ticker
into the nightly analysis universe, and only then did a stance get scored. Since June
``idea_triage`` had zero human decisions, so no idea was ever measured.

This job removes the click. Every Alpha Research / Opportunity Discovery article whose
summarizer sentiment is directional (BULLISH / BEARISH) becomes one ``alpha_idea``
stance per ticker. ``stance_outcomes`` then scores it at its usual horizons and the
track record ranks ``alpha_idea`` beside every other source, with no human review.

What is measured is *the idea itself*: "this article said bullish on X". It is not a
second LLM opinion about X. No LLM runs here.

DESIGN DECISIONS (read before changing)
---------------------------------------
* **Event dedupe, not state dedupe.** One article = one call. Two bullish articles on
  the same ticker are two calls and both get scored (``dedupe_on_source_ref``).
* **Entry is the next weekday after we fetched the article.** The outcome scorer
  takes the close on or before ``as_of.date()``. Using the fetch date would credit
  the idea with the same-day move it may have been reporting on: the
  disclosure-vs-transaction-date trap documented in ROADMAP §2.4c. The article's
  real fetch time is kept in metadata.
* **Articles naming more than ``MAX_TICKERS_PER_ARTICLE`` tickers are skipped.**
  One sentiment label over a basket of 10 tickers is not a call on any of them.
* **No ``evidence.article_ids`` in metadata.** The track-record domain table credits
  the domains that informed an LLM stance. Putting idea rows there would change the
  existing H1 numbers. The domain lives under ``metadata.idea.domain`` for an
  idea-specific slice instead.
* **Low-signal ideas are recorded too, with their ``idea_score``.** Whether the inbox
  ranking predicts outcomes is itself a question this data answers.
* **Excluded from stance-flip detection** (``EVENT_STANCE_SOURCES``). Two articles
  disagreeing is not the system changing its mind.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from typing import Any

from stance_history import is_directional_stance, record_stance_safe

logger = logging.getLogger(__name__)

SOURCE = "alpha_idea"
IDEA_ARTICLE_TYPES = ("Alpha Research", "Opportunity Discovery")
MAX_TICKERS_PER_ARTICLE = 3
DEFAULT_LOOKBACK_DAYS = 3
_ENTRY_HOUR_UTC = 21  # ~after the US close; only the date matters to the scorer


def entry_as_of(fetched_at: datetime) -> datetime:
    """First weekday strictly after the fetch date, at ~US close (UTC).

    Holidays are not modelled: the scorer then falls back to the prior close, which
    at worst is the fetch day's own close. Rare and small next to the bias it removes.
    """
    if fetched_at.tzinfo is None:
        fetched_at = fetched_at.replace(tzinfo=UTC)
    day: date = fetched_at.astimezone(UTC).date() + timedelta(days=1)
    while day.weekday() >= 5:  # Sat/Sun → Monday
        day += timedelta(days=1)
    return datetime(day.year, day.month, day.day, _ENTRY_HOUR_UTC, tzinfo=UTC)


def _article_tickers(row: dict[str, Any]) -> list[str]:
    raw = row.get("tickers") or ([row["ticker"]] if row.get("ticker") else [])
    seen: list[str] = []
    for t in raw:
        sym = str(t or "").upper().strip()
        if sym and sym not in seen:
            seen.append(sym)
    return seen


def fetch_directional_ideas(postgres: Any, *, days: int) -> list[dict[str, Any]]:
    """Idea articles from the last ``days`` days whose sentiment is directional."""
    from ideas_quality import LOW_SIGNAL_THRESHOLD, idea_score_sql

    types_sql = ", ".join(f"'{t}'" for t in IDEA_ARTICLE_TYPES)  # module constants
    return postgres.execute_query(
        f"""
        SELECT ra.id::text AS id, ra.ticker, ra.tickers, upper(ra.sentiment) AS sentiment,
               ra.article_type, ra.source, ra.fetched_at, left(ra.title, 160) AS title,
               {idea_score_sql()} AS idea_score,
               ({idea_score_sql()} < {LOW_SIGNAL_THRESHOLD}) AS low_signal
        FROM research_articles ra
        WHERE ra.article_type IN ({types_sql})
          AND ra.fetched_at >= NOW() - (%s || ' days')::interval
          AND upper(COALESCE(ra.sentiment, '')) IN ('BULLISH', 'BEARISH')
        ORDER BY ra.fetched_at ASC
        """,
        (str(int(days)),),
    ) or []


def record_alpha_idea_stances(
    postgres: Any,
    *,
    days: int = DEFAULT_LOOKBACK_DAYS,
    dry_run: bool = False,
) -> dict[str, int]:
    """Write one ``alpha_idea`` stance per (article, ticker). Idempotent.

    ``days`` larger than the nightly default is the backfill path. Dedupe on
    (ticker, source, article id) makes re-runs and overlapping windows safe.
    """
    stats = {
        "articles": 0,
        "skipped_too_many_tickers": 0,
        "skipped_no_ticker": 0,
        "candidates": 0,
        "stances_written": 0,
    }
    for row in fetch_directional_ideas(postgres, days=days):
        stats["articles"] += 1
        stance = row.get("sentiment") or ""
        if not is_directional_stance(stance):
            continue
        tickers = _article_tickers(row)
        if not tickers:
            stats["skipped_no_ticker"] += 1
            continue
        if len(tickers) > MAX_TICKERS_PER_ARTICLE:
            stats["skipped_too_many_tickers"] += 1
            continue
        fetched_at = row.get("fetched_at")
        if not isinstance(fetched_at, datetime):
            continue
        as_of = entry_as_of(fetched_at)
        meta = {
            "idea": {
                "article_id": row["id"],
                "article_type": row.get("article_type"),
                "domain": row.get("source"),
                "title": row.get("title"),
                "idea_score": row.get("idea_score"),
                "low_signal": bool(row.get("low_signal")),
                "ticker_count": len(tickers),
                "fetched_at": fetched_at.isoformat(),
            }
        }
        for ticker in tickers:
            stats["candidates"] += 1
            if dry_run:
                continue
            if record_stance_safe(
                postgres,
                ticker=ticker,
                source=SOURCE,
                stance=stance,
                confidence=None,
                fund_key="",
                source_ref_id=row["id"],
                metadata=meta,
                as_of=as_of,
                dedupe_on_source_ref=True,
            ):
                stats["stances_written"] += 1
    return stats
