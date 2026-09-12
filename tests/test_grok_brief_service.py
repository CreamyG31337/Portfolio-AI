"""Read-side tests for Grok Bot briefs feeding the Today briefing and action queue."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from unittest.mock import MagicMock

from grok_brief_service import (
    fetch_grok_signal_by_ticker,
    fetch_recent_grok_briefs,
    summarize_body,
)


def _row(ticker: str, *, notable: bool = True, posts: list | None = None, body: str = "body") -> dict:
    return {
        "ticker": ticker,
        "fund": "Project Chimera",
        "sweep_date": date(2026, 9, 12),
        "body": body,
        "themes": ["theme one", "theme two"],
        "posts": posts if posts is not None else [{"url": "https://x.com/a/status/1", "summary": "s"}],
        "notable": notable,
        "cited_urls": ["https://x.com/a/status/1"],
        "status": "ingested",
        "created_at": datetime(2026, 9, 12, 4, 26, tzinfo=UTC),
    }


def test_summarize_body_strips_markdown_heading_and_bullets() -> None:
    body = "## CMI (Cummins)\n\nX chatter mixes **power-systems** demand with criticism.\n\n- One thread cites Q2."
    out = summarize_body(body)
    assert out.startswith("X chatter mixes power-systems demand")
    assert "##" not in out and "**" not in out


def test_summarize_body_truncates_and_handles_empty() -> None:
    assert summarize_body(None) == ""
    assert summarize_body("   ") == ""
    long_body = "word " * 200
    out = summarize_body(long_body, limit=50)
    assert len(out) <= 50
    assert out.endswith("…")


def test_fetch_recent_briefs_is_notable_only_by_default() -> None:
    pg = MagicMock()
    pg.execute_query.return_value = [_row("CMI")]
    briefs = fetch_recent_grok_briefs(pg, days=2, limit=10)
    sql = " ".join(pg.execute_query.call_args.args[0].split())
    assert "AND notable" in sql
    assert pg.execute_query.call_args.args[1] == (2, 10)
    assert briefs[0]["ticker"] == "CMI"
    assert briefs[0]["post_count"] == 1
    assert briefs[0]["sweep_date"] == "2026-09-12"


def test_fetch_recent_briefs_can_include_quiet_ones() -> None:
    pg = MagicMock()
    pg.execute_query.return_value = [_row("XEQT.TO", notable=False, posts=[])]
    briefs = fetch_recent_grok_briefs(pg, notable_only=False)
    sql = " ".join(pg.execute_query.call_args.args[0].split())
    assert "AND notable" not in sql
    assert briefs[0]["post_count"] == 0
    assert briefs[0]["posts"] == []


def test_fetch_recent_briefs_parses_jsonb_string_posts() -> None:
    """psycopg can hand back jsonb as a string; a brief must not lose its posts."""
    pg = MagicMock()
    pg.execute_query.return_value = [
        _row("URNM", posts=json.dumps([{"url": "https://x.com/b/status/2", "summary": "t"}]))
    ]
    briefs = fetch_recent_grok_briefs(pg)
    assert briefs[0]["post_count"] == 1
    assert briefs[0]["posts"][0]["url"] == "https://x.com/b/status/2"


def test_fetch_recent_briefs_drops_posts_without_url() -> None:
    pg = MagicMock()
    pg.execute_query.return_value = [_row("META", posts=[{"summary": "no url"}, {"url": "https://x.com/c/3"}])]
    briefs = fetch_recent_grok_briefs(pg)
    assert [p["url"] for p in briefs[0]["posts"]] == ["https://x.com/c/3"]


def test_fetch_recent_briefs_handles_no_client() -> None:
    assert fetch_recent_grok_briefs(None) == []


def test_fetch_signal_by_ticker_maps_latest_per_ticker() -> None:
    pg = MagicMock()
    pg.execute_query.return_value = [
        {
            "ticker": "CMI",
            "sweep_date": date(2026, 9, 12),
            "notable": True,
            "themes": ["gensets"],
            "body": "## CMI\n\nPower systems demand.",
        }
    ]
    signal = fetch_grok_signal_by_ticker(pg, ["CMI", "META"], days=3)
    assert signal["CMI"]["notable"] is True
    assert signal["CMI"]["sweep_date"] == "2026-09-12"
    assert "Power systems demand" in signal["CMI"]["summary"]
    assert "META" not in signal


def test_fetch_signal_by_ticker_is_quiet_when_table_missing() -> None:
    """The action queue must still render if grok_x_briefs is not migrated yet."""
    pg = MagicMock()
    pg.execute_query.side_effect = Exception('relation "grok_x_briefs" does not exist')
    assert fetch_grok_signal_by_ticker(pg, ["CMI"]) == {}
    assert fetch_grok_signal_by_ticker(pg, []) == {}
