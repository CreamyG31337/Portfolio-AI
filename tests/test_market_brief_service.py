"""Unit tests for market brief benchmark snapshot builder."""

from unittest.mock import MagicMock

import pytest

from market_brief_service import fetch_benchmark_snapshot


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
