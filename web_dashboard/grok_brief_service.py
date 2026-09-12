"""Read-side helpers for Grok Bot X briefs (grok_x_briefs).

The Bot writes briefs through /api/grok/briefs; nothing consumed them until this
module. Used by the Today briefing and the action queue, both of which want a
compact "what did X say about this ticker" line rather than the full markdown.

Brief bodies and post summaries are written by strangers on X. Treat every field
here as untrusted display data: templates escape it, and anything routing it into
an LLM prompt must go through prompt_safety.prepare_untrusted_for_prompt().
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime
from typing import Any

logger = logging.getLogger(__name__)

BRIEF_SUMMARY_CHARS = 240
MAX_THEMES_SHOWN = 6
MAX_POSTS_SHOWN = 3


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def _parse_posts(raw: Any) -> list[dict[str, Any]]:
    """posts is jsonb: psycopg may hand back a list already, or a JSON string."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return []
    if not isinstance(raw, list):
        return []
    return [p for p in raw if isinstance(p, dict)]


def summarize_body(body: str | None, *, limit: int = BRIEF_SUMMARY_CHARS) -> str:
    """One-line gist of a markdown brief.

    The Bot writes '## TICKER (Company)\\n\\n- bullet...'. Drop heading and list
    markers so the briefing shows prose rather than punctuation.
    """
    text = str(body or "").strip()
    if not text:
        return ""
    lines: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith(("- ", "* ")):
            line = line[2:]
        lines.append(line.replace("**", ""))
        if sum(len(part) for part in lines) >= limit:
            break
    joined = " ".join(lines).strip()
    if len(joined) > limit:
        joined = joined[: limit - 1].rstrip() + "…"
    return joined


def fetch_recent_grok_briefs(
    pg: Any,
    *,
    days: int = 2,
    limit: int = 10,
    notable_only: bool = True,
) -> list[dict[str, Any]]:
    """Recent X briefs for the Today briefing, notable first.

    Defaults to notable only: a quiet brief ("nothing on X") is useful in the
    admin page but is noise in a morning briefing.
    """
    if not pg:
        return []
    clauses = ["sweep_date >= CURRENT_DATE - %s::int"]
    params: list[Any] = [max(0, int(days))]
    if notable_only:
        clauses.append("notable")
    rows = pg.execute_query(
        f"""
        SELECT ticker, fund, sweep_date, body, themes, posts, notable,
               cited_urls, status, created_at
        FROM grok_x_briefs
        WHERE {' AND '.join(clauses)}
        ORDER BY sweep_date DESC, notable DESC, created_at DESC
        LIMIT %s
        """,
        tuple(params + [max(1, int(limit))]),
    )
    briefs: list[dict[str, Any]] = []
    for row in rows or []:
        posts = _parse_posts(row.get("posts"))
        briefs.append(
            {
                "ticker": row.get("ticker"),
                "fund": row.get("fund"),
                "sweep_date": _iso(row.get("sweep_date")),
                "notable": bool(row.get("notable")),
                "summary": summarize_body(row.get("body")),
                "themes": [str(t) for t in (row.get("themes") or [])][:MAX_THEMES_SHOWN],
                "post_count": len(posts),
                "posts": [
                    {"url": str(p.get("url") or ""), "summary": str(p.get("summary") or "")}
                    for p in posts[:MAX_POSTS_SHOWN]
                    if p.get("url")
                ],
                "status": row.get("status") or "ingested",
                "created_at": _iso(row.get("created_at")),
            }
        )
    return briefs


def fetch_grok_signal_by_ticker(
    pg: Any,
    tickers: list[str],
    *,
    days: int = 3,
) -> dict[str, dict[str, Any]]:
    """Latest brief per ticker, for decorating action-queue items.

    Returns {ticker: {sweep_date, notable, themes, summary}} — enough to say
    "X had something to say about this name yesterday" next to an action.
    """
    if not pg or not tickers:
        return {}
    try:
        rows = pg.execute_query(
            """
            SELECT DISTINCT ON (ticker)
                   ticker, sweep_date, notable, themes, body
            FROM grok_x_briefs
            WHERE ticker = ANY(%s) AND sweep_date >= CURRENT_DATE - %s::int
            ORDER BY ticker, sweep_date DESC, created_at DESC
            """,
            (list(tickers), max(0, int(days))),
        )
    except Exception as exc:
        logger.debug("grok signal fetch skipped: %s", exc)
        return {}
    out: dict[str, dict[str, Any]] = {}
    for row in rows or []:
        ticker = str(row.get("ticker") or "")
        if not ticker:
            continue
        out[ticker] = {
            "sweep_date": _iso(row.get("sweep_date")),
            "notable": bool(row.get("notable")),
            "themes": [str(t) for t in (row.get("themes") or [])][:MAX_THEMES_SHOWN],
            "summary": summarize_body(row.get("body"), limit=160),
        }
    return out
