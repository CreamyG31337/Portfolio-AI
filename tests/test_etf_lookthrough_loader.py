"""Tests for ETF look-through fundamentals loader (mocked Supabase / Postgres)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from web_dashboard.signals.etf_lookthrough_loader import (
    _SECURITIES_CHUNK_SIZE,
    resolve_signal_fundamentals,
)


def _etf_row(ticker: str = "BUZZ") -> dict[str, Any]:
    return {
        "ticker": ticker,
        "company_name": "VanEck Social Sentiment ETF",
        "trailing_pe": 99.0,
    }


def _stock_row(ticker: str, **metrics: Any) -> dict[str, Any]:
    return {"ticker": ticker, "company_name": f"{ticker} Inc", **metrics}


def _wire_chunked_supabase(
    client: MagicMock, rows_for_chunks: list[list[dict]]
) -> list[list[str]]:
    """Attach .in_ chunk capture + sequential execute responses."""
    calls: list[list[str]] = []
    exec_results = []
    for rows in rows_for_chunks:
        r = MagicMock()
        r.data = rows
        exec_results.append(r)

    def _in_(_col: str, chunk: list[str]) -> MagicMock:
        calls.append(list(chunk))
        m = MagicMock()
        idx = len(calls) - 1
        m.execute.return_value = exec_results[idx] if idx < len(exec_results) else MagicMock(data=[])
        return m

    client.supabase.table.return_value.select.return_value.in_.side_effect = _in_
    return calls


class TestResolveSignalFundamentals:
    def test_non_etf_passthrough(self) -> None:
        row = _stock_row("AAPL", return_on_equity=0.2)
        sb = MagicMock()
        assert resolve_signal_fundamentals("AAPL", row, sb) is row
        sb.supabase.table.assert_not_called()

    def test_none_row_passthrough(self) -> None:
        sb = MagicMock()
        assert resolve_signal_fundamentals("AAPL", None, sb) is None

    def test_etf_with_holdings_returns_lookthrough(self) -> None:
        etf = _etf_row("BUZZ")
        pg = MagicMock()
        pg.execute_query.return_value = [
            {"date": "2026-04-01", "holding_ticker": "AAPL", "weight_percent": 60.0},
            {"date": "2026-04-01", "holding_ticker": "MSFT", "weight_percent": 40.0},
        ]
        sb = MagicMock()
        _wire_chunked_supabase(
            sb,
            [
                [
                    _stock_row("AAPL", return_on_equity=0.20, revenue_growth=0.15, trailing_pe=20.0),
                    _stock_row("MSFT", return_on_equity=0.30, revenue_growth=0.10, trailing_pe=30.0),
                ]
            ],
        )

        result = resolve_signal_fundamentals("BUZZ", etf, sb, postgres_client=pg)
        assert result is not None
        assert "_lookthrough" in result
        meta = result["_lookthrough"]
        assert meta["etf_ticker"] == "BUZZ"
        assert meta["as_of"] == "2026-04-01"
        assert meta["holdings_total"] == 2
        assert meta["holdings_with_fundamentals"] == 2
        assert meta["weight_with_fundamentals"] == 1.0
        # Weighted ROE: 0.6*0.20 + 0.4*0.30 = 0.24
        assert result["return_on_equity"] == 0.24
        assert "company_name" not in result

    def test_untracked_etf_returns_row_unchanged(self) -> None:
        etf = _etf_row("GHOST")
        pg = MagicMock()
        pg.execute_query.return_value = []
        sb = MagicMock()
        assert resolve_signal_fundamentals("GHOST", etf, sb, postgres_client=pg) is etf
        sb.supabase.table.assert_not_called()

    def test_db_error_returns_row_unchanged(self) -> None:
        etf = _etf_row("BUZZ")
        pg = MagicMock()
        pg.execute_query.side_effect = RuntimeError("connection refused")
        sb = MagicMock()
        assert resolve_signal_fundamentals("BUZZ", etf, sb, postgres_client=pg) is etf

    def test_chunking_over_200_holdings(self) -> None:
        etf = _etf_row("SPY")
        n = _SECURITIES_CHUNK_SIZE + 50  # 250
        holdings = [
            {
                "date": "2026-04-01",
                "holding_ticker": f"T{i:03d}",
                "weight_percent": 1.0,
            }
            for i in range(n)
        ]
        pg = MagicMock()
        pg.execute_query.return_value = holdings

        # Two chunks: 200 + 50; give one holding scored fundamentals so coverage works
        chunk0_rows = [_stock_row(f"T{i:03d}") for i in range(_SECURITIES_CHUNK_SIZE)]
        chunk0_rows[0] = _stock_row("T000", return_on_equity=0.15)
        chunk1_rows = [_stock_row(f"T{i:03d}") for i in range(_SECURITIES_CHUNK_SIZE, n)]

        sb = MagicMock()
        calls = _wire_chunked_supabase(sb, [chunk0_rows, chunk1_rows])

        result = resolve_signal_fundamentals("SPY", etf, sb, postgres_client=pg)
        assert result is not None
        assert "_lookthrough" in result
        assert len(calls) == 2
        assert len(calls[0]) == _SECURITIES_CHUNK_SIZE
        assert len(calls[1]) == 50
        assert result["_lookthrough"]["holdings_total"] == n
