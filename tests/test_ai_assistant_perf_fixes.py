"""Regression tests for AI Assistant page load & context generation latency fixes."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
import requests

project_root = Path(__file__).resolve().parent.parent
web_dashboard = project_root / "web_dashboard"
for p in (str(project_root), str(web_dashboard)):
    if p not in sys.path:
        sys.path.insert(0, p)

import ollama_client  # noqa: E402
from ai_context_builder import format_fundamentals_table  # noqa: E402
from ai_assistant_candidates import build_signal_fallback_candidates  # noqa: E402
from action_queue_service import build_action_queue_items  # noqa: E402


class TestOllamaModelListFastFailAndCaching:
    def setup_method(self) -> None:
        ollama_client._clear_model_list_cache()

    def teardown_method(self) -> None:
        ollama_client._clear_model_list_cache()

    def test_probe_session_has_zero_retries_and_caches_unreachable_secondary(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OLLAMA_BASE_URL", "http://primary-ok:11434")
        monkeypatch.setenv("OLLAMA_BASE_URL_2", "http://laptop-asleep:11435")
        monkeypatch.delenv("OLLAMA_BASE_URL_NVIDIA", raising=False)

        client = ollama_client.OllamaClient(base_url="http://primary-ok:11434")
        # probe_session must have zero retries to prevent 4x timeout amplification
        adapter = client.probe_session.get_adapter("http://primary-ok:11434")
        assert adapter.max_retries.total == 0

        calls: list[tuple[str, object]] = []

        def fake_probe_get(url: str, timeout: object = None, **kwargs: object) -> MagicMock:
            calls.append((url, timeout))
            if "laptop-asleep" in url:
                raise requests.exceptions.ConnectTimeout("timed out")
            resp = MagicMock()
            resp.status_code = 200
            resp.raise_for_status = lambda: None
            resp.json.return_value = {"models": [{"name": "granite4.1:8b"}]}
            return resp

        monkeypatch.setattr(client.probe_session, "get", fake_probe_get)

        # First call probes both hosts with short (connect, read) tuple timeout
        models_first = client.list_available_models()
        assert models_first == ["granite4.1:8b"]
        assert len(calls) == 2
        assert all(isinstance(t, tuple) and t[0] <= 3.0 for _, t in calls)

        # Second call within TTL hits in-process cache -> zero new HTTP calls
        calls.clear()
        models_second = client.list_available_models()
        assert models_second == ["granite4.1:8b"]
        assert calls == []

        # Forced refresh skips the sleeping secondary host during cooldown
        models_forced = client.list_available_models(force_refresh=True)
        assert models_forced == ["granite4.1:8b"]
        assert len(calls) == 1
        assert "primary-ok" in calls[0][0]


class TestFundamentalsStalenessFix:
    def test_fresh_non_dividend_stock_not_marked_stale(self) -> None:
        """A ticker updated <24h ago with div_yield=None / trailing_pe=None must NOT re-fetch yfinance."""
        fresh_ts = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        positions_df = pd.DataFrame(
            [
                {
                    "ticker": "PLTR",
                    "securities": {
                        "sector": "Technology",
                        "industry": "Software",
                        "country": "US",
                        "market_cap": 150_000_000_000,
                        "trailing_pe": None,
                        "dividend_yield": None,
                        "fifty_two_week_high": 85.0,
                        "fifty_two_week_low": 20.0,
                        "last_updated": fresh_ts,
                    },
                }
            ]
        )

        with patch("market_data.data_fetcher.MarketDataFetcher") as mock_fetcher_cls:
            table = format_fundamentals_table(positions_df)
            mock_fetcher_cls.assert_not_called()

        assert "PLTR" in table
        assert "85.0" in table

    def test_completely_empty_fundamentals_still_marked_stale(self) -> None:
        """If all 4 core metrics are None (never populated), still fetch from yfinance."""
        fresh_ts = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        positions_df = pd.DataFrame(
            [
                {
                    "ticker": "NEWCO",
                    "securities": {
                        "sector": "Technology",
                        "industry": "Software",
                        "country": "US",
                        "market_cap": "N/A",
                        "trailing_pe": None,
                        "dividend_yield": None,
                        "fifty_two_week_high": None,
                        "fifty_two_week_low": None,
                        "last_updated": fresh_ts,
                    },
                }
            ]
        )

        mock_fetcher = MagicMock()
        mock_fetcher.fetch_fundamentals.return_value = {
            "trailingPE": "25.4",
            "dividendYield": "N/A",
            "fiftyTwoWeekHigh": "50.0",
            "fiftyTwoWeekLow": "12.0",
        }
        mock_sb = MagicMock()
        with (
            patch("market_data.data_fetcher.MarketDataFetcher", return_value=mock_fetcher),
            patch("market_data.price_cache.PriceCache"),
            patch("config.settings.get_settings"),
            patch("web_dashboard.supabase_client.SupabaseClient", return_value=mock_sb),
        ):
            table = format_fundamentals_table(positions_df)

        mock_fetcher.fetch_fundamentals.assert_called_once_with("NEWCO")
        assert "25.4" in table


class TestSignalAnalysisRecencyAndPrefetchReuse:
    def test_action_queue_uses_date_cutoff_and_populates_out_params(self) -> None:
        mock_sb = MagicMock()
        watchlist = [{"ticker": "NVDA", "priority_tier": "A"}]
        sig_rows = [
            {
                "ticker": "NVDA",
                "analysis_date": "2026-11-27",
                "overall_signal": "HOLD",
                "confidence_score": 0.6,
                "fear_risk_signal": {"fear_level": "LOW"},
                "structure_signal": {"trend": "UPTREND"},
                "timing_signal": {},
                "explanation": "steady",
            }
        ]
        sig_table = MagicMock()
        sig_table.select.return_value.in_.return_value.gte.return_value.order.return_value.execute.return_value = MagicMock(
            data=sig_rows
        )
        sec_table = MagicMock()
        sec_table.select.return_value.in_.return_value.execute.return_value = MagicMock(
            data=[{"ticker": "NVDA", "company_name": "NVIDIA"}]
        )
        funds_table = MagicMock()
        funds_table.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[{"fund_type": "RRSP"}]
        )

        def _table(name: str):
            if name == "signal_analysis":
                return sig_table
            if name == "securities":
                return sec_table
            if name == "funds":
                return funds_table
            return MagicMock()

        mock_sb.supabase.table.side_effect = _table

        signals_out: dict = {}
        watchlist_out: list = []
        with patch("action_queue_service.get_active_watchlist_rows", return_value=watchlist):
            actions = build_action_queue_items(
                mock_sb,
                "RRSP Lance Webull",
                limit=10,
                positions_df=pd.DataFrame(columns=["ticker"]),
                latest_signals_out=signals_out,
                watchlist_out=watchlist_out,
            )

        assert actions == []
        assert "NVDA" in signals_out
        assert watchlist_out == watchlist
        # Confirm .gte("analysis_date", ...) was invoked on signal_analysis
        sig_table.select.return_value.in_.return_value.gte.assert_called_once()
        gte_args = sig_table.select.return_value.in_.return_value.gte.call_args[0]
        assert gte_args[0] == "analysis_date"

    def test_signal_fallback_reuses_prefetched_data_without_requerying_signals(self) -> None:
        mock_sb = MagicMock()
        sec_table = MagicMock()
        sec_table.select.return_value.in_.return_value.execute.return_value = MagicMock(
            data=[{"ticker": "AAPL", "sector": "Technology"}]
        )
        queried_tables: list[str] = []

        def _table(name: str):
            queried_tables.append(name)
            if name == "securities":
                return sec_table
            return MagicMock()

        mock_sb.supabase.table.side_effect = _table

        rows = build_signal_fallback_candidates(
            mock_sb,
            fund="RRSP Lance Webull",
            held_tickers=set(),
            limit=5,
            prefetched_watchlist=[{"ticker": "AAPL"}],
            prefetched_signals={
                "AAPL": {
                    "ticker": "AAPL",
                    "overall_signal": "BUY",
                    "confidence_score": 0.85,
                    "fear_risk_signal": {"fear_level": "LOW"},
                }
            },
        )
        assert len(rows) == 1
        assert rows[0]["ticker"] == "AAPL"
        assert "signal_analysis" not in queried_tables


class TestAiRoutesPerfStructure:
    def test_formatted_models_reuses_cached_ollama_models(self) -> None:
        from routes import ai_routes

        with patch.object(
            ai_routes,
            "_get_cached_ollama_models",
            return_value=["granite4.1:8b"],
        ) as mock_cached, patch.object(
            ai_routes,
            "list_available_models",
            side_effect=AssertionError("Should reuse _get_cached_ollama_models"),
        ):
            # Call underlying wrapped function to bypass flask cache
            fn = getattr(ai_routes._get_formatted_ai_models, "__wrapped__", ai_routes._get_formatted_ai_models)
            models = fn()

        mock_cached.assert_called_once()
        assert any(m["id"] == "granite4.1:8b" for m in models)
