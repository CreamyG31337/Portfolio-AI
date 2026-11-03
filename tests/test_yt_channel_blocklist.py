"""K12: blocklisted YouTube channels are never fetched by the sweep or cited as evidence."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from yt_channel_policy import DEFAULT_BLOCKLIST, ChannelBlocklist, load_blocklist


def test_blocks_by_id_or_normalized_name() -> None:
    b = ChannelBlocklist([{"channel_id": "UC1", "name": "Jerry  Romine Stocks"}, {"name": "Dividend Guy"}])
    assert b.blocks(channel_id="UC1")
    assert b.blocks(name="jerry romine stocks")
    assert b.blocks(name="DIVIDEND GUY")
    assert not b.blocks(channel_id="UC2", name="Schwab Network")
    assert not b.blocks()


def test_sql_exclusion_empty_when_nothing_blocked() -> None:
    assert ChannelBlocklist([]).sql_exclusion() == ("", ())
    assert not ChannelBlocklist([])


def test_sql_exclusion_shape() -> None:
    sql, params = ChannelBlocklist([{"channel_id": "UC1", "name": "Dividend Guy"}]).sql_exclusion("ra")
    assert sql.strip().startswith("AND NOT (ra.article_type = 'YouTube Transcript'")
    assert "COALESCE(ra.source_metadata->>'channel_id', '')" in sql  # NULL metadata must not drop rows
    assert sql.count("%s") == 2
    assert params == (["UC1"], ["dividend guy"])


def test_load_blocklist_default_override_and_bad_value() -> None:
    with patch("settings.get_system_setting", return_value=None):
        assert load_blocklist() == [dict(e) for e in DEFAULT_BLOCKLIST]
    with patch("settings.get_system_setting", return_value=[]):
        assert load_blocklist() == []  # explicit empty list blocks nothing
    with patch("settings.get_system_setting", return_value=[{"name": "X"}, {"reason": "no key"}, "junk"]):
        assert load_blocklist() == [{"name": "X"}]
    with patch("settings.get_system_setting", return_value="not a list"):
        assert len(load_blocklist()) == len(DEFAULT_BLOCKLIST)


def test_plan_fetches_skips_blocked_channels_without_spending_budget() -> None:
    from scheduler.jobs_yt_sweep import plan_fetches

    results = [
        {"ticker": "AAA", "hits": [
            {"video_id": "v1", "score": 9, "channel_name": "Jerry Romine Stocks"},
            {"video_id": "v2", "score": 5, "channel_name": "Schwab Network"},
        ]},
        {"ticker": "BBB", "hits": [{"video_id": "v3", "score": 7, "channel_name": "Dividend Guy"}]},
    ]
    blocklist = ChannelBlocklist(DEFAULT_BLOCKLIST)
    queue, _ = plan_fetches(
        results, budget=5, is_blocked=lambda h: blocklist.blocks(name=h.get("channel_name"))
    )
    assert [h["video_id"] for _, h in queue] == ["v2"]


def test_ticker_analysis_article_query_passes_blocklist_params_in_order() -> None:
    from datetime import datetime, timezone

    from ticker_analysis_service import TickerAnalysisService

    svc = object.__new__(TickerAnalysisService)
    svc.postgres = MagicMock()
    svc.postgres.execute_query.return_value = []
    svc.MAX_RESEARCH_ARTICLES = 25
    with patch("pit_time.article_as_of_expr", return_value="fetched_at"), patch(
        "pit_time.article_fresh_publish_predicate", return_value="TRUE"
    ), patch("yt_channel_policy.get_blocklist", return_value=ChannelBlocklist([{"channel_id": "UC1", "name": "N"}])):
        svc._get_research_articles("abc", datetime(2026, 10, 1, tzinfo=timezone.utc))
    sql, params = svc.postgres.execute_query.call_args[0]
    assert "AND NOT (article_type = 'YouTube Transcript'" in sql
    assert sql.count("%s") == len(params)
    assert params[0] == "ABC" and params[3] == ["UC1"] and params[4] == ["n"] and params[-1] == 25


def test_meta_article_query_passes_blocklist_params() -> None:
    from meta_analysis_service import TickerMetaAnalysisService

    pg: Any = MagicMock()
    pg.execute_query.return_value = []
    svc = TickerMetaAnalysisService(ollama=None, supabase=MagicMock(), postgres=pg)
    with patch("pit_time.article_as_of_expr", return_value="fetched_at"), patch(
        "pit_time.article_fresh_publish_predicate", return_value="TRUE"
    ), patch("yt_channel_policy.get_blocklist", return_value=ChannelBlocklist([{"channel_id": "UC1"}])):
        svc._fetch_article_snippets("ABC")
    sql, params = pg.execute_query.call_args[0]
    assert "AND NOT (article_type = 'YouTube Transcript'" in sql
    assert sql.count("%s") == len(params)
    assert params == ("ABC", "ABC", ["UC1"], [])


def test_k13_decision_lists() -> None:
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "web_dashboard" / "scripts"))
    from k5_youtube_source_roi import decision_lists

    res = [
        (("Good Sweep", False), 90, 9.9, 5.5),
        (("Good But Losing Money", False), 50, 6.0, -1.0),  # edge alone is not enough
        (("Curated", True), 70, 7.5, 2.1),  # already allowlisted
        (("Bad Edge", False), 40, -12.4, -2.7),
        (("Bad Excess", False), 40, 0.0, -9.5),
        (("Jerry Romine Stocks", False), 33, -14.1, -6.1),  # already blocked
        (("Meh", False), 40, -2.0, -1.0),
    ]
    promote, block = decision_lists(res, ChannelBlocklist(DEFAULT_BLOCKLIST))
    assert [p[0] for p in promote] == ["Good Sweep"]
    assert [b[0] for b in block] == ["Bad Edge", "Bad Excess"]
