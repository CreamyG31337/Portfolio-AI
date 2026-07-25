#!/usr/bin/env python3
"""Unit tests for the A4 wishlist AI Assistant tools.

Covers the five read-only wrappers added on top of the A8 history tools:
get_track_record, get_theses_attention, get_confluence, get_ideas_triage,
get_earnings_calendar. Underlying services are patched so no DB / network is hit.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

from ai_assistant_tools import AssistantToolContext, execute_tool


CTX = AssistantToolContext(user_id="u1", fund="TEST")


def _run(name: str, args: dict) -> dict:
    return json.loads(execute_tool(name, args, CTX))


# --------------------------------------------------------------------------- #
# Catalog wiring
# --------------------------------------------------------------------------- #
class TestWishlistCatalog:
    NEW = {
        "get_track_record",
        "get_theses_attention",
        "get_confluence",
        "get_ideas_triage",
        "get_earnings_calendar",
    }

    def test_all_registered_in_handlers_and_schemas(self) -> None:
        from ai_assistant_tools import TOOL_HANDLERS, catalog_tool_names

        names = catalog_tool_names()
        for n in self.NEW:
            assert n in TOOL_HANDLERS, f"{n} missing from TOOL_HANDLERS"
            assert n in names, f"{n} missing from TOOL_SCHEMAS"

    def test_required_names_cover_new_tools(self) -> None:
        from ai_assistant_question_matrix import REQUIRED_TOOL_NAMES

        assert self.NEW <= REQUIRED_TOOL_NAMES


# --------------------------------------------------------------------------- #
# get_track_record
# --------------------------------------------------------------------------- #
class TestTrackRecord:
    SUMMARY = {
        "horizon_days": 30,
        "total_scored": 12,
        "hit_rate_by_source": {"confluence": 0.75, "action_queue_ai_review": 0.5},
        "hit_rate_by_verdict": {"ALIGNED": 0.8, "TENSION": 0.25},
        "avg_excess_by_source": {"confluence": 0.031, "action_queue_ai_review": -0.01},
        "counts_by_source": {
            "confluence": {"scored": 8, "hits": 6, "misses": 2, "unscoreable": 0},
            "action_queue_ai_review": {"scored": 4, "hits": 2, "misses": 2, "unscoreable": 1},
        },
        "counts_by_verdict": {
            "ALIGNED": {"scored": 10, "hits": 8, "misses": 2, "unscoreable": 0},
            "TENSION": {"scored": 4, "hits": 1, "misses": 3, "unscoreable": 0},
        },
        "best_calls": [{"ticker": "AAA", "source": "confluence", "excess_return": 0.42}],
        "worst_calls": [{"ticker": "BBB", "source": "action_queue_ai_review", "excess_return": -0.3}],
        "by_domain": [
            {"domain": "finance.yahoo.com", "scored": 3.5, "hit_rate": 0.66, "mean_excess": 0.02},
        ],
    }

    def test_ok_projection(self) -> None:
        with patch("ai_assistant_tools._postgres", return_value=MagicMock()), patch(
            "track_record_service.build_track_record_summary", return_value=self.SUMMARY
        ):
            out = _run("get_track_record", {"horizon_days": 30})
        assert out["ok"] is True
        assert out["horizon_days"] == 30
        assert out["total_scored"] == 12
        # Sources ranked by sample size (confluence n=8 first) with pct hit rate.
        assert out["by_source"][0]["source"] == "confluence"
        assert out["by_source"][0]["hit_rate_pct"] == 75.0
        assert out["by_verdict"]["TENSION"]["hit_rate_pct"] == 25.0
        assert out["by_domain"][0]["hit_rate_pct"] == 66.0
        assert out["best_calls"][0]["ticker"] == "AAA"
        assert out["worst_calls"][0]["ticker"] == "BBB"
        assert "note" in out

    def test_horizon_defaults_to_30_when_invalid(self) -> None:
        captured = {}

        def _fake(_pg, *, horizon_days):
            captured["h"] = horizon_days
            return self.SUMMARY

        with patch("ai_assistant_tools._postgres", return_value=MagicMock()), patch(
            "track_record_service.build_track_record_summary", side_effect=_fake
        ):
            _run("get_track_record", {"horizon_days": 999})
        assert captured["h"] == 30

    def test_no_data_when_nothing_scored(self) -> None:
        empty = dict(self.SUMMARY, total_scored=0)
        with patch("ai_assistant_tools._postgres", return_value=MagicMock()), patch(
            "track_record_service.build_track_record_summary", return_value=empty
        ):
            out = _run("get_track_record", {})
        assert out["ok"] is False
        assert out["reason"] == "no_data"


# --------------------------------------------------------------------------- #
# get_theses_attention
# --------------------------------------------------------------------------- #
class TestThesesAttention:
    ROWS = [
        {
            "ticker": "AAA",
            "title": "AAA turnaround thesis",
            "disposition": "BULLISH",
            "attention_reasons": ["tension"],
            "llm_verdict": "TENSION",
            "age_days": 20.0,
            "review_status": "stale",
        },
        {
            "ticker": "BBB",
            "title": "BBB dilution watch",
            "disposition": "BEARISH",
            "attention_reasons": ["weak"],
            "llm_verdict": None,
            "age_days": 5.0,
            "review_status": "due",
        },
    ]

    def test_projection(self) -> None:
        with patch("ai_assistant_tools._postgres", return_value=MagicMock()), patch(
            "user_insights_service.list_theses_attention", return_value=self.ROWS
        ):
            out = _run("get_theses_attention", {})
        assert out["ok"] is True
        assert out["count"] == 2
        assert out["theses"][0]["ticker"] == "AAA"
        assert out["theses"][0]["llm_verdict"] == "TENSION"
        assert out["theses"][0]["reasons"] == ["tension"]

    def test_ticker_filter(self) -> None:
        with patch("ai_assistant_tools._postgres", return_value=MagicMock()), patch(
            "user_insights_service.list_theses_attention", return_value=[self.ROWS[1]]
        ) as mock_attn:
            out = _run("get_theses_attention", {"ticker": "bbb"})
        assert out["ok"] is True
        assert out["count"] == 1
        assert out["theses"][0]["ticker"] == "BBB"
        # Ticker must be passed into the service (SQL filter), not post-filtered.
        assert mock_attn.call_args.kwargs.get("ticker") == "BBB"

    def test_ticker_filter_not_lost_outside_global_top_n(self) -> None:
        """Regression: asking for a ticker must hit the service with that ticker."""
        with patch("ai_assistant_tools._postgres", return_value=MagicMock()), patch(
            "user_insights_service.list_theses_attention",
            return_value=[self.ROWS[1]],
        ) as mock_attn:
            out = _run("get_theses_attention", {"ticker": "BBB", "limit": 5})
        assert out["ok"] is True
        assert mock_attn.call_args.kwargs["ticker"] == "BBB"
        assert mock_attn.call_args.kwargs["limit"] == 5
        assert out["theses"][0]["ticker"] == "BBB"

    def test_no_data(self) -> None:
        with patch("ai_assistant_tools._postgres", return_value=MagicMock()), patch(
            "user_insights_service.list_theses_attention", return_value=[]
        ):
            out = _run("get_theses_attention", {})
        assert out["ok"] is False
        assert out["reason"] == "no_data"


# --------------------------------------------------------------------------- #
# get_confluence
# --------------------------------------------------------------------------- #
class TestConfluence:
    ROWS = [
        {
            "ticker": "AAA",
            "direction": "bullish",
            "score": 4,
            "families": ["insider_cluster", "filing"],
            "as_of": "2026-07-24T12:00:00+00:00",
            "details": {"noise": "dropped"},
        },
        {
            "ticker": "ccc",
            "direction": "risk",
            "score": 3,
            "families": "dilution",  # non-list should normalize
            "as_of": "2026-07-23",
        },
    ]

    def test_projection_and_family_normalization(self) -> None:
        with patch("ai_assistant_tools._postgres", return_value=MagicMock()), patch(
            "confluence_service.fetch_recent_confluence_events", return_value=self.ROWS
        ):
            out = _run("get_confluence", {"days": 7})
        assert out["ok"] is True
        assert out["count"] == 2
        assert out["events"][0]["families"] == ["insider_cluster", "filing"]
        assert out["events"][0]["as_of"] == "2026-07-24"
        # Scalar family becomes a one-element list; ticker upper-cased.
        assert out["events"][1]["ticker"] == "CCC"
        assert out["events"][1]["families"] == ["dilution"]
        assert "details" not in out["events"][0]

    def test_no_data(self) -> None:
        with patch("ai_assistant_tools._postgres", return_value=MagicMock()), patch(
            "confluence_service.fetch_recent_confluence_events", return_value=[]
        ):
            out = _run("get_confluence", {})
        assert out["ok"] is False
        assert out["reason"] == "no_data"


# --------------------------------------------------------------------------- #
# get_ideas_triage
# --------------------------------------------------------------------------- #
class TestIdeasTriage:
    ROWS = [
        {
            "id": "1",
            "title": "Small cap X poised to run",
            "article_type": "Alpha Research",
            "source": "example.com",
            "fetched_at": "2026-07-24T09:00:00+00:00",
            "relevance_score": 0.87,
            "tickers": ["xyz", "abc"],
            "summary": "long body...",
        }
    ]

    def test_projection(self) -> None:
        with patch("ai_assistant_tools._postgres", return_value=MagicMock()), patch(
            "today_briefing_service.fetch_alpha_ideas", return_value=self.ROWS
        ):
            out = _run("get_ideas_triage", {})
        assert out["ok"] is True
        assert out["count"] == 1
        idea = out["ideas"][0]
        assert idea["tickers"] == ["XYZ", "ABC"]
        assert idea["relevance"] == 0.87
        assert idea["fetched_at"] == "2026-07-24"
        assert "summary" not in idea  # dropped to stay lean

    def test_no_data(self) -> None:
        with patch("ai_assistant_tools._postgres", return_value=MagicMock()), patch(
            "today_briefing_service.fetch_alpha_ideas", return_value=[]
        ):
            out = _run("get_ideas_triage", {"ticker": "ZZZ"})
        assert out["ok"] is False
        assert out["reason"] == "no_data"


# --------------------------------------------------------------------------- #
# get_earnings_calendar
# --------------------------------------------------------------------------- #
class TestEarningsCalendar:
    def test_missing_ticker(self) -> None:
        out = _run("get_earnings_calendar", {})
        assert out["ok"] is False
        assert out["reason"] == "missing_ticker"

    def test_next_earnings_date_ignores_past_only(self) -> None:
        from ai_assistant_tools import _next_earnings_date

        past = date.today() - timedelta(days=10)
        future = date.today() + timedelta(days=5)

        class _Tk:
            def __init__(self, earnings):
                self.calendar = {"Earnings Date": earnings}

            def get_earnings_dates(self, limit=8):
                return None

        class _Yf:
            def __init__(self, earnings):
                self._earnings = earnings

            def Ticker(self, _t):
                return _Tk(self._earnings)

        assert _next_earnings_date(_Yf([past]), "AAA") is None
        assert _next_earnings_date(_Yf([past, future]), "AAA") == future

    def test_sorted_by_days_until_with_nulls_last(self) -> None:
        soon = date.today() + timedelta(days=3)
        later = date.today() + timedelta(days=20)

        def _fake(_yf, ticker):
            return {"AAA": later, "BBB": soon, "CCC": None}[ticker]

        with patch("ai_assistant_tools._next_earnings_date", side_effect=_fake):
            out = _run("get_earnings_calendar", {"tickers": ["AAA", "BBB", "CCC"]})
        assert out["ok"] is True
        # BBB (3d) before AAA (20d); CCC (no date) last.
        order = [e["ticker"] for e in out["earnings"]]
        assert order == ["BBB", "AAA", "CCC"]
        assert out["earnings"][0]["days_until"] == 3
        assert out["earnings"][-1]["next_earnings_date"] is None

    def test_caps_tickers_at_10(self) -> None:
        seen: list[str] = []

        def _fake(_yf, ticker):
            seen.append(ticker)
            return date.today() + timedelta(days=1)

        many = [f"T{i}" for i in range(15)]
        with patch("ai_assistant_tools._next_earnings_date", side_effect=_fake):
            out = _run("get_earnings_calendar", {"tickers": many})
        assert out["ok"] is True
        assert len(seen) == 10
        assert len(out["earnings"]) == 10

    def test_single_ticker_arg(self) -> None:
        d = date.today() + timedelta(days=7)
        with patch("ai_assistant_tools._next_earnings_date", return_value=d):
            out = _run("get_earnings_calendar", {"ticker": "aaa"})
        assert out["ok"] is True
        assert out["earnings"][0]["ticker"] == "AAA"
        assert out["earnings"][0]["days_until"] == 7

    def test_no_data_when_all_none(self) -> None:
        with patch("ai_assistant_tools._next_earnings_date", return_value=None):
            out = _run("get_earnings_calendar", {"tickers": ["AAA", "BBB"]})
        assert out["ok"] is False
        assert out["reason"] == "no_data"
