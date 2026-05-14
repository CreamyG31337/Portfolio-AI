"""Tests for etf_article_sector_infer."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

web_dashboard = Path(__file__).resolve().parent.parent / "web_dashboard"
if str(web_dashboard) not in sys.path:
    sys.path.insert(0, str(web_dashboard))

from etf_article_sector_infer import (  # noqa: E402
    article_row_tickers,
    dominant_sector_for_holdings,
)


def test_article_row_tickers_from_array() -> None:
    row = {"tickers": ["aapl", " MSFT "]}
    assert article_row_tickers(row) == ["AAPL", "MSFT"]


def test_article_row_tickers_legacy_single() -> None:
    row = {"ticker": "nvda"}
    assert article_row_tickers(row) == ["NVDA"]


def test_dominant_sector_picks_mode() -> None:
    pg = MagicMock()

    def q(sql: str, params: tuple) -> list:
        t = params[0]
        if t == "AAPL":
            return [{"sector": "Technology"}]
        if t == "MSFT":
            return [{"sector": "Technology"}]
        if t == "JNJ":
            return [{"sector": "Healthcare"}]
        return []

    pg.execute_query.side_effect = q
    out = dominant_sector_for_holdings(pg, None, ["AAPL", "MSFT", "JNJ"])
    assert out == "Technology"


def test_dominant_sector_none_when_empty() -> None:
    pg = MagicMock()
    pg.execute_query.return_value = []
    assert dominant_sector_for_holdings(pg, None, ["ZZZZ"]) is None
