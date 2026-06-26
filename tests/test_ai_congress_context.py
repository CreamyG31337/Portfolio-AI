#!/usr/bin/env python3
"""Tests for congress trades AI context helpers."""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "web_dashboard"))

from web_dashboard.ai_context_builder import format_congress_trades
from web_dashboard.routes.ai_routes import (
    _coerce_bool_flag,
    _congress_lookup_tickers,
)


def test_coerce_bool_flag() -> None:
    assert _coerce_bool_flag(True) is True
    assert _coerce_bool_flag(False) is False
    assert _coerce_bool_flag("false") is False
    assert _coerce_bool_flag("true") is True
    assert _coerce_bool_flag(None, default=False) is False


def test_congress_lookup_tickers_strips_exchange_suffix() -> None:
    lookup = _congress_lookup_tickers(["XMA.TO", "AMD", "mu"])
    assert "XMA.TO" in lookup
    assert "XMA" in lookup
    assert "AMD" in lookup
    assert "MU" in lookup


def test_format_congress_trades_empty_returns_blank() -> None:
    assert format_congress_trades([]) == ""


def test_format_congress_trades_with_rows() -> None:
    text = format_congress_trades(
        [{"transaction_date": "2026-06-01", "ticker": "AMD", "politician": "Smith",
          "chamber": "House", "type": "Purchase", "amount": "1001-15000"}],
        days=30,
    )
    assert "Congress Trades (Last 30 Days)" in text
    assert "AMD" in text
