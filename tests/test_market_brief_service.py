"""Unit tests for market brief benchmark snapshot + Phase H4 regime history."""

from datetime import date
from unittest.mock import MagicMock

import pytest

from market_brief_service import (
    fetch_benchmark_snapshot,
    format_regime_history_block,
    run_market_daily_brief,
)


def test_fetch_benchmark_snapshot_computes_1d_pct(monkeypatch):
    """Single ticker with two closes yields 1d_pct in digest and text."""
    rows = [
        {"date": "2026-04-01", "close": 110.0},
        {"date": "2026-03-31", "close": 100.0},
    ]
    mock_table = MagicMock()
    mock_table.select.return_value = mock_table
    mock_table.eq.return_value = mock_table
    mock_table.order.return_value = mock_table
    mock_table.limit.return_value = mock_table
    mock_table.execute.return_value = MagicMock(data=rows)

    mock_sb = MagicMock()
    mock_sb.supabase.table.return_value = mock_table

    monkeypatch.setattr(
        "market_brief_service.BRIEF_BENCHMARK_TICKERS",
        ["SPY"],
    )

    text, digest = fetch_benchmark_snapshot(mock_sb)

    assert "SPY" in text
    assert "1d_pct=" in text
    assert digest["tickers"]["SPY"]["pct_change_1d"] == pytest.approx(10.0)
    assert digest["as_of_ny"]


def test_fetch_benchmark_snapshot_insufficient_history(monkeypatch):
    mock_table = MagicMock()
    mock_table.select.return_value = mock_table
    mock_table.eq.return_value = mock_table
    mock_table.order.return_value = mock_table
    mock_table.limit.return_value = mock_table
    mock_table.execute.return_value = MagicMock(data=[{"date": "2026-04-01", "close": 100.0}])

    mock_sb = MagicMock()
    mock_sb.supabase.table.return_value = mock_table

    monkeypatch.setattr("market_brief_service.BRIEF_BENCHMARK_TICKERS", ["SPY"])

    text, digest = fetch_benchmark_snapshot(mock_sb)

    assert "insufficient" in text.lower() or "insufficient_history" in str(digest)


def test_format_regime_history_block_empty() -> None:
    assert format_regime_history_block([]) == ""


def test_format_regime_history_block_oldest_to_newest() -> None:
    # Newest-first input (as returned by fetch); output is chronological.
    rows = [
        {
            "brief_date": date(2026, 7, 15),
            "regime": {
                "risk_regime": "RISK_OFF",
                "breadth_proxy": "LEADERSHIP_NARROW",
                "volatility_state": "ELEVATED",
                "regime_confidence": 0.7,
            },
        },
        {
            "brief_date": date(2026, 7, 14),
            "regime": {
                "risk_regime": "MIXED",
                "breadth_proxy": "UNCLEAR",
                "volatility_state": "CALM",
                "regime_confidence": 0.5,
            },
        },
        {
            "brief_date": date(2026, 7, 13),
            "regime": {
                "risk_regime": "RISK_ON",
                "breadth_proxy": "LEADERSHIP_BROAD",
                "volatility_state": "CALM",
                "regime_confidence": 0.6,
            },
        },
    ]
    block = format_regime_history_block(rows)
    assert "### Regime - last 3 sessions (oldest to newest)" in block
    assert "2026-07-13: RISK_ON" in block
    assert "2026-07-15: RISK_OFF" in block
    # Oldest line appears before newest.
    assert block.index("2026-07-13") < block.index("2026-07-15")
    assert "confidence=0.70" in block


def test_run_market_daily_brief_includes_regime_history_when_flag_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("META_ANALYSIS_TREND_MEMORY", "true")
    captured: dict[str, str] = {}

    def _fake_collect(*_a, prompt: str = "", **_kw):
        captured["prompt"] = prompt
        return (
            '{"headline":"ok","narrative":"n","regime":{"risk_regime":"NEUTRAL",'
            '"regime_confidence":0.5,"breadth_proxy":"UNCLEAR",'
            '"volatility_state":"UNKNOWN","macro_themes":[],'
            '"leadership_note":"","caveats":[]}}',
            "test-model",
        )

    monkeypatch.setattr(
        "market_brief_service.fetch_benchmark_snapshot",
        lambda _sb: ("^GSPC 1d_pct=+0.1%", {"tickers": {}}),
    )
    monkeypatch.setattr(
        "market_brief_service.fetch_recent_regime_history",
        lambda *_a, **_k: [
            {
                "brief_date": date(2026, 7, 14),
                "regime": {
                    "risk_regime": "RISK_OFF",
                    "breadth_proxy": "LEADERSHIP_NARROW",
                    "volatility_state": "ELEVATED",
                    "regime_confidence": 0.8,
                },
            }
        ],
    )
    monkeypatch.setattr(
        "market_brief_service.collect_with_summary_model_chain", _fake_collect
    )
    monkeypatch.setattr("market_brief_service.get_summarizing_model", lambda _k: "m")

    pg = MagicMock()
    pg.execute_update.return_value = 1
    pg.execute_query.return_value = [{"brief_date": date(2026, 7, 15)}]
    ollama = MagicMock()
    sb = MagicMock()

    run_market_daily_brief(ollama, pg, sb, brief_date=date(2026, 7, 15))
    assert "Prior regime history" in captured["prompt"]
    assert "RISK_OFF" in captured["prompt"]
    assert "### Regime - last 1 sessions" in captured["prompt"]


def test_run_market_daily_brief_omits_history_when_flag_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("META_ANALYSIS_TREND_MEMORY", "false")
    captured: dict[str, str] = {}

    def _fake_collect(*_a, prompt: str = "", **_kw):
        captured["prompt"] = prompt
        return (
            '{"headline":"ok","narrative":"n","regime":{"risk_regime":"NEUTRAL",'
            '"regime_confidence":0.5,"breadth_proxy":"UNCLEAR",'
            '"volatility_state":"UNKNOWN","macro_themes":[],'
            '"leadership_note":"","caveats":[]}}',
            "test-model",
        )

    monkeypatch.setattr(
        "market_brief_service.fetch_benchmark_snapshot",
        lambda _sb: ("^GSPC 1d_pct=+0.1%", {"tickers": {}}),
    )

    def _should_not_fetch(*_a, **_k):
        raise AssertionError("fetch_recent_regime_history should not run when flag off")

    monkeypatch.setattr(
        "market_brief_service.fetch_recent_regime_history", _should_not_fetch
    )
    monkeypatch.setattr(
        "market_brief_service.collect_with_summary_model_chain", _fake_collect
    )
    monkeypatch.setattr("market_brief_service.get_summarizing_model", lambda _k: "m")

    pg = MagicMock()
    pg.execute_update.return_value = 1
    pg.execute_query.return_value = [{"brief_date": date(2026, 7, 15)}]

    run_market_daily_brief(MagicMock(), pg, MagicMock(), brief_date=date(2026, 7, 15))
    assert "(none)" in captured["prompt"]
    assert "### Regime - last" not in captured["prompt"]
