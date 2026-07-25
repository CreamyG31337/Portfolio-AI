"""Tests for AI Assistant question matrix, pulse formatting, tools, and GLM tool loop."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from ai_assistant_question_matrix import (
    QUESTION_MATRIX,
    REQUIRED_TOOL_NAMES,
    expected_tools_for_family,
    matrix_by_family,
)
from ai_assistant_tools import (
    TOOL_SCHEMAS,
    AssistantToolContext,
    catalog_tool_names,
    execute_tool,
)
from ai_intelligence_pulse import format_intelligence_pulse, _lean_candidate
from ai_prompts import (
    GLM_SYSTEM_PROMPT_WITH_TOOLS,
    get_system_prompt,
)
from ai_chat_handler import ChatHandler
from glm_transport import GlmMessageResult, _normalize_tool_calls


class TestQuestionMatrix:
    def test_has_expected_families(self) -> None:
        assert len(QUESTION_MATRIX) == 12
        families = {row["family"] for row in QUESTION_MATRIX}
        assert "portfolio_performance" in families
        assert "event_investigation" in families

    def test_required_tools_covered_by_catalog(self) -> None:
        names = catalog_tool_names()
        missing = REQUIRED_TOOL_NAMES - names
        assert not missing, f"missing tools: {missing}"

    def test_each_family_has_expected_tools_in_catalog(self) -> None:
        names = catalog_tool_names()
        for row in QUESTION_MATRIX:
            for tool in row["expected_tools"]:
                assert tool in names, f"{row['family']} expects {tool}"

    def test_matrix_helpers(self) -> None:
        by_f = matrix_by_family()
        assert "news" in by_f
        assert "search_web" in expected_tools_for_family("news")
        assert expected_tools_for_family("nope") == []

    def test_schemas_match_handler_names(self) -> None:
        schema_names = {t["function"]["name"] for t in TOOL_SCHEMAS}
        assert schema_names == catalog_tool_names()


class TestPulseFormatting:
    def test_format_empty_pulse(self) -> None:
        text = format_intelligence_pulse(None)
        assert "No pulse data" in text

    def test_format_market_unavailable_reason(self) -> None:
        text = format_intelligence_pulse(
            {
                "ok": True,
                "market": None,
                "market_unavailable_reason": "research_db:OperationalError",
                "candidates": [],
                "candidate_count": 0,
                "candidate_source": "none",
            }
        )
        assert "unavailable — research_db:OperationalError" in text
        assert "Top candidates (0)" in text
        # Must not imply cash-session closed
        assert "closed" not in text.lower()

    def test_format_with_market_and_candidates(self) -> None:
        pulse = {
            "ok": True,
            "fund": "TEST",
            "market": {
                "headline": "Risk-on session",
                "risk_regime": "RISK_ON",
                "breadth_proxy": "LEADERSHIP_BROAD",
                "volatility_state": "CALM",
                "regime_confidence": 0.7,
                "macro_themes": ["soft landing"],
                "brief_date": "2026-07-24",
            },
            "candidates": [
                {
                    "ticker": "ABC",
                    "advise": "BUY",
                    "confidence": 0.8,
                    "stance": "BULLISH",
                    "entry_zone": "$10-11",
                    "is_held": False,
                    "reason": "queue:BUY",
                }
            ],
            "candidate_count": 1,
        }
        text = format_intelligence_pulse(pulse)
        assert "Today Intelligence Pulse" in text
        assert "Risk-on session" in text
        assert "ABC" in text
        assert "$10-11" in text
        assert "RISK_ON" in text

    def test_format_marks_tension(self) -> None:
        pulse = {
            "ok": True,
            "market": None,
            "market_unavailable_reason": "research_db:X",
            "candidates": [
                {
                    "ticker": "AAA",
                    "advise": "SELL",
                    "confidence": 0.8,
                    "stance": "BUY",
                    "is_held": True,
                    "tension": True,
                    "tension_reason": "signal SELL vs analysis stance BUY",
                    "reason": "signal:SELL",
                }
            ],
            "candidate_count": 1,
        }
        text = format_intelligence_pulse(pulse)
        assert "TENSION" in text
        assert "signal SELL vs analysis stance BUY" in text

    def test_lean_candidate_strips_noise(self) -> None:
        row = {
            "ticker": "xyz",
            "advise": "BUY",
            "confidence": 0.9,
            "research_context": {"meta_conviction": "BULLISH", "analysis_stance": "BUY"},
            "ai_review": {"one_liner": "Aligned with research"},
            "explanation": "long text " * 40,
            "_logo_url": "http://example/logo.png",
        }
        lean = _lean_candidate(row)
        assert lean["ticker"] == "XYZ"
        assert lean["advise"] == "BUY"
        assert lean["meta_conviction"] == "BULLISH"
        assert "_logo_url" not in lean
        assert lean.get("reason")
        assert len(lean["reason"]) <= 120


class TestCandidateTension:
    def test_opposite_sign_stance_flags_tension(self) -> None:
        from ai_assistant_candidates import candidate_tension

        is_t, reason = candidate_tension("SELL", stance="BUY")
        assert is_t is True
        assert reason and "SELL" in reason and "BUY" in reason

    def test_buy_vs_bearish_meta_flags_tension(self) -> None:
        from ai_assistant_candidates import candidate_tension

        is_t, _ = candidate_tension("BUY", stance=None, meta_conviction="BEARISH")
        assert is_t is True

    def test_aligned_no_tension(self) -> None:
        from ai_assistant_candidates import candidate_tension

        assert candidate_tension("BUY", stance="BULLISH")[0] is False

    def test_watch_is_neutral_no_tension(self) -> None:
        from ai_assistant_candidates import candidate_tension

        # WATCH means "wait", not a contradiction with a bullish stance.
        assert candidate_tension("WATCH", stance="BUY")[0] is False
        # HOLD stance is neutral too.
        assert candidate_tension("BUY", stance="HOLD")[0] is False

    def test_annotate_demotes_tension_rows_stably(self) -> None:
        from ai_assistant_candidates import annotate_and_demote_tension

        rows = [
            {"ticker": "AAA", "advise": "SELL", "stance": "BUY"},  # tension
            {"ticker": "BBB", "advise": "BUY", "stance": "BULLISH"},  # clean
            {"ticker": "CCC", "advise": "BUY", "meta_conviction": "BEARISH"},  # tension
        ]
        out = annotate_and_demote_tension(rows)
        # Clean row rises; tension rows sink but keep relative order.
        assert [r["ticker"] for r in out] == ["BBB", "AAA", "CCC"]
        assert out[0].get("tension") is not True
        assert out[1]["tension"] is True
        assert out[1]["tension_reason"]
        assert out[2]["tension"] is True


class TestToolExecutors:
    def test_unknown_tool(self) -> None:
        ctx = AssistantToolContext(user_id="u1", fund="TEST")
        raw = execute_tool("not_a_tool", {}, ctx)
        data = json.loads(raw)
        assert data["ok"] is False
        assert data["reason"] == "unknown_tool"

    def test_get_ticker_setup_missing_ticker(self) -> None:
        ctx = AssistantToolContext(user_id="u1", fund="TEST")
        raw = execute_tool("get_ticker_setup", {}, ctx)
        data = json.loads(raw)
        assert data["ok"] is False
        assert data["reason"] == "missing_ticker"

    def test_get_ticker_setup_ok(self) -> None:
        ctx = AssistantToolContext(user_id="u1", fund="TEST")
        mock_pg = MagicMock()
        mock_pg.execute_query.side_effect = [
            [
                {
                    "ticker": "ABC",
                    "stance": "BUY",
                    "entry_zone": "$5-6",
                    "target_price": "$8",
                    "stop_loss": "$4",
                    "summary": "buy dip",
                    "confidence_score": 0.7,
                    "updated_at": "2026-07-24",
                }
            ],
            [
                {
                    "ticker": "ABC",
                    "unified_conviction": "BULLISH",
                    "confidence_adjusted": 0.65,
                    "narrative": "Meta agrees",
                    "updated_at": "2026-07-24",
                }
            ],
        ]
        with patch("ai_assistant_tools._postgres", return_value=mock_pg):
            raw = execute_tool("get_ticker_setup", {"ticker": "abc"}, ctx)
        data = json.loads(raw)
        assert data["ok"] is True
        assert data["ticker"] == "ABC"
        assert data["entry_zone"] == "$5-6"
        assert data["meta_conviction"] == "BULLISH"

    def test_get_ticker_setup_no_data(self) -> None:
        ctx = AssistantToolContext(user_id="u1", fund="TEST")
        mock_pg = MagicMock()
        mock_pg.execute_query.side_effect = [[], []]
        with patch("ai_assistant_tools._postgres", return_value=mock_pg):
            raw = execute_tool("get_ticker_setup", {"ticker": "ZZZ"}, ctx)
        data = json.loads(raw)
        assert data["ok"] is False
        assert data["reason"] == "no_data"

    def test_get_holdings_snapshot(self) -> None:
        ctx = AssistantToolContext(user_id="u1", fund="TEST")
        df = pd.DataFrame(
            [
                {
                    "ticker": "AAA",
                    "quantity": 10,
                    "current_price": 5.0,
                    "market_value": 50.0,
                },
                {
                    "ticker": "BBB",
                    "quantity": 2,
                    "current_price": 20.0,
                    "market_value": 40.0,
                },
            ]
        )
        with patch(
            "flask_data_utils.get_current_positions_flask",
            return_value=df,
        ):
            raw = execute_tool(
                "get_holdings_snapshot",
                {"tickers": ["AAA"]},
                ctx,
            )
        data = json.loads(raw)
        assert data["ok"] is True
        assert data["count"] == 1
        assert data["holdings"][0]["ticker"] == "AAA"

    def test_list_entry_candidates_sector_filter(self) -> None:
        ctx = AssistantToolContext(user_id="u1", fund="TEST")
        actions = [
            {
                "ticker": "ENRG",
                "action": "BUY",
                "confidence": 0.8,
                "is_held": False,
            },
            {
                "ticker": "TECH",
                "action": "BUY",
                "confidence": 0.9,
                "is_held": False,
            },
        ]
        advise = [
            {"ticker": "ENRG", "advise": "BUY", "confidence": 0.8, "reasons": ["queue:BUY"]},
            {"ticker": "TECH", "advise": "BUY", "confidence": 0.9, "reasons": ["queue:BUY"]},
        ]
        mock_sb = MagicMock()
        mock_sb.supabase.table.return_value.select.return_value.in_.return_value.execute.return_value = MagicMock(
            data=[
                {"ticker": "ENRG", "sector": "Energy"},
                {"ticker": "TECH", "sector": "Technology"},
            ]
        )
        with (
            patch("ai_assistant_tools._supabase", return_value=mock_sb),
            patch(
                "action_queue_service.build_action_queue_items",
                return_value=actions,
            ),
            patch("action_queue_service.attach_research_context"),
            patch("action_queue_service.attach_ai_reviews"),
            patch(
                "advise_service.build_advise_recommendations",
                return_value=advise,
            ),
            patch("ai_assistant_tools._postgres", return_value=MagicMock(execute_query=MagicMock(return_value=[]))),
            patch(
                "flask_data_utils.get_current_positions_flask",
                return_value=pd.DataFrame(columns=["ticker"]),
            ),
        ):
            raw = execute_tool(
                "list_entry_candidates",
                {"sector": "Energy", "limit": 10},
                ctx,
            )
        data = json.loads(raw)
        assert data["ok"] is True
        assert data["count"] == 1
        assert data["candidates"][0]["ticker"] == "ENRG"
        assert data["candidates"][0]["sector"] == "Energy"
        assert data.get("source") == "action_queue"

    def test_list_entry_candidates_signal_fallback(self) -> None:
        ctx = AssistantToolContext(user_id="u1", fund="TEST")
        mock_sb = MagicMock()
        fallback_rows = [
            {
                "ticker": "RMBS",
                "advise": "SELL",
                "confidence": 0.8,
                "is_held": False,
                "reason": "signal:SELL fear=EXTREME",
                "source": "signal_fallback",
                "fear_level": "EXTREME",
            }
        ]
        with (
            patch("ai_assistant_tools._supabase", return_value=mock_sb),
            patch(
                "action_queue_service.build_action_queue_items",
                return_value=[],
            ),
            patch("action_queue_service.attach_research_context"),
            patch("action_queue_service.attach_ai_reviews"),
            patch(
                "advise_service.build_advise_recommendations",
                return_value=[],
            ),
            patch("ai_assistant_tools._postgres", return_value=MagicMock(execute_query=MagicMock(return_value=[]))),
            patch(
                "flask_data_utils.get_current_positions_flask",
                return_value=pd.DataFrame(columns=["ticker"]),
            ),
            patch(
                "ai_assistant_candidates.build_signal_fallback_candidates",
                return_value=fallback_rows,
            ),
        ):
            raw = execute_tool("list_entry_candidates", {"limit": 5}, ctx)
        data = json.loads(raw)
        assert data["ok"] is True
        assert data["source"] == "signal_fallback"
        assert data["candidates"][0]["ticker"] == "RMBS"


class TestHistoryTools:
    def test_portfolio_performance_missing_fund(self) -> None:
        ctx = AssistantToolContext(user_id="u1", fund=None)
        data = json.loads(execute_tool("get_portfolio_performance", {}, ctx))
        assert data["ok"] is False
        assert data["reason"] == "missing_fund"

    def test_portfolio_performance_ok_computes_return_and_drawdown(self) -> None:
        ctx = AssistantToolContext(user_id="u1", fund="TEST")
        # Rising then dipping curve: peak at +20, drawdown to +5 (-15 from peak).
        dates = pd.date_range("2025-01-01", periods=40, freq="D")
        perf = [0.0] + [i * 1.0 for i in range(1, 20)] + [20.0 - j * 0.75 for j in range(20)]
        curve = pd.DataFrame(
            {
                "date": dates,
                "value": [1000 + p * 10 for p in perf],
                "performance_pct": perf,
            }
        )
        with patch(
            "flask_data_utils.calculate_portfolio_value_over_time_flask",
            return_value=curve,
        ):
            data = json.loads(
                execute_tool("get_portfolio_performance", {"window": "all"}, ctx)
            )
        assert data["ok"] is True
        assert data["window"] == "all"
        assert data["peak"]["pct"] == pytest.approx(20.0, abs=0.01)
        assert data["max_drawdown"]["pct"] < 0
        assert len(data["curve"]) <= 12
        assert data["trading_days"] == 40

    def test_portfolio_performance_no_data(self) -> None:
        ctx = AssistantToolContext(user_id="u1", fund="TEST")
        with patch(
            "flask_data_utils.calculate_portfolio_value_over_time_flask",
            return_value=pd.DataFrame(),
        ):
            data = json.loads(execute_tool("get_portfolio_performance", {}, ctx))
        assert data["ok"] is False
        assert data["reason"] == "no_data"

    def test_trade_history_filters_and_summarizes(self) -> None:
        ctx = AssistantToolContext(user_id="u1", fund="TEST")
        trades = pd.DataFrame(
            [
                {"timestamp": "2026-01-10", "ticker": "ABC", "reason": "Opening position", "quantity": 10, "price": 5.0, "total_value": 50.0, "pnl": 0.0, "cost_basis": 50.0, "currency": "USD"},
                {"timestamp": "2026-02-15", "ticker": "ABC", "reason": "SELL: lock gains", "quantity": 10, "price": 7.0, "total_value": 70.0, "pnl": 20.0, "cost_basis": 50.0, "currency": "USD"},
                {"timestamp": "2026-03-01", "ticker": "XYZ", "reason": "Opening position", "quantity": 2, "price": 20.0, "total_value": 40.0, "pnl": 0.0, "cost_basis": 40.0, "currency": "USD"},
            ]
        )
        with patch("flask_data_utils.get_trade_log_flask", return_value=trades):
            data = json.loads(
                execute_tool("get_trade_history", {"ticker": "abc"}, ctx)
            )
        assert data["ok"] is True
        assert data["ticker"] == "ABC"
        assert data["matched"] == 2
        assert {r["ticker"] for r in data["trades"]} == {"ABC"}
        # Most recent first
        assert data["trades"][0]["date"] == "2026-02-15"
        assert data["summary"]["buys"] == 1
        assert data["summary"]["sells"] == 1
        # Realized P&L surfaced on the sell row and aggregated per currency.
        sell_row = data["trades"][0]
        assert sell_row["action"] == "SELL"
        assert sell_row["realized_pnl"] == 20.0
        assert sell_row["currency"] == "USD"
        # Buys have no realized_pnl key.
        assert "realized_pnl" not in data["trades"][1]
        realized = data["summary"]["realized_pnl_by_currency"]
        assert realized["USD"]["pnl"] == 20.0
        assert realized["USD"]["cost_basis"] == 50.0
        assert realized["USD"]["return_pct"] == 40.0
        assert realized["USD"]["sales"] == 1

    def test_trade_history_realized_pnl_per_currency(self) -> None:
        ctx = AssistantToolContext(user_id="u1", fund="TEST")
        # Mixed CAD + USD sells must never be summed into one number.
        trades = pd.DataFrame(
            [
                {"timestamp": "2026-01-05", "ticker": "USA", "reason": "SELL: trim", "quantity": 10, "price": 12.0, "total_value": 120.0, "pnl": 30.0, "cost_basis": 90.0, "currency": "USD"},
                {"timestamp": "2026-01-06", "ticker": "CAN.TO", "reason": "SELL: exit", "quantity": 5, "price": 8.0, "total_value": 40.0, "pnl": -10.0, "cost_basis": 50.0, "currency": "CAD"},
            ]
        )
        with patch("flask_data_utils.get_trade_log_flask", return_value=trades):
            data = json.loads(execute_tool("get_trade_history", {}, ctx))
        realized = data["summary"]["realized_pnl_by_currency"]
        assert realized["USD"]["pnl"] == 30.0
        assert realized["CAD"]["pnl"] == -10.0
        # Two distinct currency buckets, kept separate.
        assert set(realized.keys()) == {"USD", "CAD"}

    def test_trade_history_no_trades(self) -> None:
        ctx = AssistantToolContext(user_id="u1", fund="TEST")
        with patch("flask_data_utils.get_trade_log_flask", return_value=pd.DataFrame()):
            data = json.loads(execute_tool("get_trade_history", {}, ctx))
        assert data["ok"] is False
        assert data["reason"] == "no_trades"

    def test_price_history_biggest_moves(self) -> None:
        ctx = AssistantToolContext(user_id="u1", fund="TEST")
        idx = pd.date_range("2026-01-01", periods=6, freq="D")
        # Big -20% drop on day 3.
        closes = [100.0, 101.0, 102.0, 81.6, 82.0, 83.0]
        price_df = pd.DataFrame({"Close": closes, "Volume": [1000] * 6}, index=idx)
        fake_result = MagicMock()
        fake_result.df = price_df
        fake_fetcher = MagicMock()
        fake_fetcher.fetch_price_data.return_value = fake_result
        with (
            patch("market_data.data_fetcher.MarketDataFetcher", return_value=fake_fetcher),
            patch("market_data.price_cache.PriceCache"),
            patch("config.settings.get_settings"),
        ):
            data = json.loads(
                execute_tool("get_price_history", {"ticker": "abc", "window": "30d"}, ctx)
            )
        assert data["ok"] is True
        assert data["ticker"] == "ABC"
        assert data["bars"] == 6
        assert data["biggest_moves"]
        # The -20% day should be the top move by magnitude.
        assert data["biggest_moves"][0]["pct"] < -15
        assert data["biggest_moves"][0]["date"] == "2026-01-04"
        assert len(data["curve"]) <= 12

    def test_price_history_missing_ticker(self) -> None:
        ctx = AssistantToolContext(user_id="u1", fund="TEST")
        data = json.loads(execute_tool("get_price_history", {}, ctx))
        assert data["ok"] is False
        assert data["reason"] == "missing_ticker"

    def test_search_web_time_range_passthrough(self) -> None:
        ctx = AssistantToolContext(user_id="u1", fund="TEST")
        fake_client = MagicMock()
        fake_client.search.return_value = {
            "results": [{"title": "t", "url": "http://x", "content": "c", "engine": "e"}]
        }
        with patch("searxng_client.get_searxng_client", return_value=fake_client):
            data = json.loads(
                execute_tool(
                    "search_web",
                    {"query": "why did ABC drop", "time_range": "month"},
                    ctx,
                )
            )
        assert data["ok"] is True
        assert data["time_range"] == "month"
        assert fake_client.search.call_args.kwargs["time_range"] == "month"

    def test_search_web_invalid_time_range_defaults_to_week(self) -> None:
        ctx = AssistantToolContext(user_id="u1", fund="TEST")
        fake_client = MagicMock()
        fake_client.search.return_value = {"results": []}
        with patch("searxng_client.get_searxng_client", return_value=fake_client):
            execute_tool("search_web", {"query": "q", "time_range": "decade"}, ctx)
        assert fake_client.search.call_args.kwargs["time_range"] == "week"


class TestSignalFallbackBuilder:
    def test_ranks_sell_before_watch_and_skips_hold(self) -> None:
        from ai_assistant_candidates import build_signal_fallback_candidates

        mock_sb = MagicMock()
        watchlist = [
            {"ticker": "AAA"},
            {"ticker": "BBB"},
            {"ticker": "CCC"},
        ]
        signals = {
            "AAA": {
                "ticker": "AAA",
                "overall_signal": "HOLD",
                "confidence_score": 0.99,
                "fear_risk_signal": {"fear_level": "LOW", "risk_score": 0},
            },
            "BBB": {
                "ticker": "BBB",
                "overall_signal": "WATCH",
                "confidence_score": 0.55,
                "fear_risk_signal": {"fear_level": "MODERATE", "risk_score": 20},
            },
            "CCC": {
                "ticker": "CCC",
                "overall_signal": "SELL",
                "confidence_score": 0.8,
                "fear_risk_signal": {"fear_level": "EXTREME", "risk_score": 75},
            },
        }

        def _table(name: str):
            table = MagicMock()
            if name == "signal_analysis":
                table.select.return_value.in_.return_value.order.return_value.execute.return_value = MagicMock(
                    data=list(signals.values())
                )
            elif name == "securities":
                table.select.return_value.in_.return_value.execute.return_value = MagicMock(
                    data=[
                        {"ticker": "AAA", "sector": "Tech"},
                        {"ticker": "BBB", "sector": "Energy"},
                        {"ticker": "CCC", "sector": "Tech"},
                    ]
                )
            return table

        mock_sb.supabase.table.side_effect = _table

        with patch(
            "ai_assistant_candidates.get_active_watchlist_rows",
            return_value=watchlist,
        ):
            # CCC is held so its SELL is a legitimate (actionable) exit signal.
            rows = build_signal_fallback_candidates(
                mock_sb, fund="TEST", held_tickers={"CCC"}, limit=10
            )
        tickers = [r["ticker"] for r in rows]
        assert "CCC" in tickers
        assert "BBB" in tickers
        assert "AAA" not in tickers  # HOLD skipped
        assert tickers[0] == "CCC"  # SELL first

    def test_skips_non_held_sell(self) -> None:
        from ai_assistant_candidates import build_signal_fallback_candidates

        mock_sb = MagicMock()
        watchlist = [{"ticker": "DDD"}]
        signals = [
            {
                "ticker": "DDD",
                "overall_signal": "SELL",
                "confidence_score": 0.8,
                "fear_risk_signal": {"fear_level": "EXTREME"},
            }
        ]

        def _table(name: str):
            table = MagicMock()
            if name == "signal_analysis":
                table.select.return_value.in_.return_value.order.return_value.execute.return_value = MagicMock(
                    data=signals
                )
            else:
                table.select.return_value.in_.return_value.execute.return_value = MagicMock(
                    data=[{"ticker": "DDD", "sector": "Tech"}]
                )
            return table

        mock_sb.supabase.table.side_effect = _table
        with patch(
            "ai_assistant_candidates.get_active_watchlist_rows",
            return_value=watchlist,
        ):
            # Not held -> a SELL is not actionable and must be dropped.
            rows = build_signal_fallback_candidates(
                mock_sb, fund="TEST", held_tickers=set(), limit=10
            )
            assert rows == []
            # Held -> the SELL is a real exit signal and is kept.
            held_rows = build_signal_fallback_candidates(
                mock_sb, fund="TEST", held_tickers={"DDD"}, limit=10
            )
        assert [r["ticker"] for r in held_rows] == ["DDD"]
        assert held_rows[0]["advise"] == "SELL"
        assert held_rows[0]["is_held"] is True

    def test_sector_and_action_filters(self) -> None:
        from ai_assistant_candidates import build_signal_fallback_candidates

        mock_sb = MagicMock()
        watchlist = [{"ticker": "ENRG"}, {"ticker": "TECH"}]
        signals = [
            {
                "ticker": "ENRG",
                "overall_signal": "WATCH",
                "confidence_score": 0.7,
                "fear_risk_signal": {"fear_level": "LOW"},
            },
            {
                "ticker": "TECH",
                "overall_signal": "WATCH",
                "confidence_score": 0.9,
                "fear_risk_signal": {"fear_level": "LOW"},
            },
        ]

        def _table(name: str):
            table = MagicMock()
            if name == "signal_analysis":
                table.select.return_value.in_.return_value.order.return_value.execute.return_value = MagicMock(
                    data=signals
                )
            else:
                table.select.return_value.in_.return_value.execute.return_value = MagicMock(
                    data=[
                        {"ticker": "ENRG", "sector": "Energy"},
                        {"ticker": "TECH", "sector": "Technology"},
                    ]
                )
            return table

        mock_sb.supabase.table.side_effect = _table
        with patch(
            "ai_assistant_candidates.get_active_watchlist_rows",
            return_value=watchlist,
        ):
            rows = build_signal_fallback_candidates(
                mock_sb, sector_filter="Energy", limit=10
            )
        assert len(rows) == 1
        assert rows[0]["ticker"] == "ENRG"


class TestPrompts:
    def test_glm_tools_prompt(self) -> None:
        prompt = get_system_prompt("glm-5.2", allow_search=True, enable_tools=True)
        assert prompt == GLM_SYSTEM_PROMPT_WITH_TOOLS
        assert "list_entry_candidates" in prompt
        assert "Never invent" in prompt

    def test_glm_without_tools_keeps_search_prompt(self) -> None:
        prompt = get_system_prompt("glm-5.2", allow_search=True, enable_tools=False)
        assert "SearXNG" in prompt
        assert prompt != GLM_SYSTEM_PROMPT_WITH_TOOLS


class TestGlmToolNormalize:
    def test_normalize_tool_calls(self) -> None:
        raw = [
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": "get_ticker_setup", "arguments": {"ticker": "ABC"}},
            }
        ]
        out = _normalize_tool_calls(raw)
        assert out[0]["function"]["name"] == "get_ticker_setup"
        assert '"ticker"' in out[0]["function"]["arguments"]


class TestChatHandlerToolLoop:
    def test_glm_tool_loop_streams_final_answer(self, app: Any) -> None:
        handler = ChatHandler(user_id="u1", model="glm-5.2", fund="TEST")
        assert handler.backend == "glm"

        first = GlmMessageResult(
            content="",
            tool_calls=[
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "get_market_brief",
                        "arguments": "{}",
                    },
                }
            ],
            finish_reason="tool_calls",
        )
        second = GlmMessageResult(
            content="Markets are RISK_ON today.",
            tool_calls=[],
            finish_reason="stop",
        )

        with (
            app.test_request_context("/api/v2/ai/chat", method="POST"),
            patch("glm_config.get_zhipu_api_key", return_value="fake-key"),
            patch(
                "glm_transport.glm_chat_completion_message",
                side_effect=[first, second],
            ),
            patch(
                "ai_assistant_tools.execute_tool",
                return_value=json.dumps(
                    {"ok": True, "headline": "Risk-on", "regime": {"risk_regime": "RISK_ON"}}
                ),
            ),
        ):
            resp = handler._handle_glm_stream(
                full_prompt="What's the market doing?",
                system_prompt="sys",
                conversation_history=[],
                current_query="What's the market doing?",
                enable_tools=True,
            )
            assert resp.mimetype == "text/event-stream"
            chunks = list(resp.response)
            body = "".join(
                c.decode("utf-8") if isinstance(c, (bytes, bytearray)) else str(c)
                for c in chunks
            )

        assert "status" in body
        assert "get_market_brief" in body
        assert "Markets are RISK_ON" in body
        assert '"done": true' in body or '"done":true' in body

    def test_glm_tool_loop_injects_synthesis_nudge_when_forced(self, app: Any) -> None:
        """When the model keeps calling tools to the cap, the forced-final round
        must disable tools AND inject a synthesis nudge so it stops planning."""
        handler = ChatHandler(user_id="u1", model="glm-5.2", fund="TEST")

        keep_calling = GlmMessageResult(
            content="",
            tool_calls=[
                {
                    "id": "call_x",
                    "type": "function",
                    "function": {"name": "get_price_history", "arguments": '{"ticker":"TSM"}'},
                }
            ],
            finish_reason="tool_calls",
        )
        final = GlmMessageResult(
            content="TSM fell 6.98% on 2026-07-01 amid a chip sell-off [source].",
            tool_calls=[],
            finish_reason="stop",
        )
        # 5 tool-calling rounds (0..4) then the forced-final round (5).
        mock_glm = MagicMock(side_effect=[keep_calling] * 5 + [final])

        with (
            app.test_request_context("/api/v2/ai/chat", method="POST"),
            patch("glm_config.get_zhipu_api_key", return_value="fake-key"),
            patch("glm_transport.glm_chat_completion_message", mock_glm),
            patch(
                "ai_assistant_tools.execute_tool",
                return_value=json.dumps({"ok": True, "biggest_moves": [{"date": "2026-07-01", "pct": -6.98}]}),
            ),
        ):
            resp = handler._handle_glm_stream(
                full_prompt="Why did TSM drop?",
                system_prompt="sys",
                conversation_history=[],
                current_query="Why did TSM drop?",
                enable_tools=True,
            )
            body = "".join(
                c.decode("utf-8") if isinstance(c, (bytes, bytearray)) else str(c)
                for c in resp.response
            )

        assert mock_glm.call_count == 6
        final_call = mock_glm.call_args_list[-1]
        # Forced-final round: tools disabled.
        assert final_call.kwargs.get("tools") is None
        # Synthesis nudge injected into the messages for that final call.
        sent_messages = final_call.args[0]
        assert any(
            "no more tool calls" in str(m.get("content", "")).lower()
            for m in sent_messages
        ), "synthesis nudge not injected on forced-final round"
        assert "TSM fell 6.98%" in body
