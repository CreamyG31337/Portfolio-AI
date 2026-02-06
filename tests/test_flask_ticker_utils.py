from types import ModuleType
from unittest.mock import patch

import pandas as pd

from web_dashboard import ticker_utils


def test_get_yfinance_ticker_candidates_handles_class_shares() -> None:
    candidates = ticker_utils._get_yfinance_ticker_candidates("TECK.B")
    assert candidates == ["TECK.B", "TECK-B", "TECK-B.TO"]


def test_get_ticker_info_uses_class_share_alias_for_yfinance() -> None:
    requested_symbols: list[str] = []

    class FakeTicker:
        def __init__(self, symbol: str) -> None:
            requested_symbols.append(symbol)
            self._symbol = symbol

        @property
        def info(self) -> dict:
            if self._symbol == "TECK-B.TO":
                return {
                    "symbol": "TECK-B.TO",
                    "longName": "Teck Resources Limited",
                    "currency": "CAD",
                    "exchange": "TSX",
                    "sector": "Basic Materials",
                    "industry": "Metals & Mining",
                    "trailingPE": 12.5,
                }
            return {}

    fake_yf = ModuleType("yfinance")
    fake_yf.Ticker = FakeTicker  # type: ignore[attr-defined]

    with patch.dict("sys.modules", {"yfinance": fake_yf}):
        result = ticker_utils.get_ticker_info("TECK.B", supabase_client=None, postgres_client=None)

    assert result["found"] is True
    assert result["basic_info"] is not None
    assert result["basic_info"]["ticker"] == "TECK.B"
    assert result["basic_info"]["company_name"] == "Teck Resources Limited"
    assert result["basic_info"]["currency"] == "CAD"
    assert requested_symbols == ["TECK.B", "TECK-B", "TECK-B.TO"]


def test_get_ticker_price_history_uses_class_share_alias_for_yfinance() -> None:
    requested_symbols: list[str] = []
    date_index = pd.date_range("2026-01-01", periods=4, tz="UTC")
    date_index.name = "Date"

    class FakeTicker:
        def __init__(self, symbol: str) -> None:
            requested_symbols.append(symbol)
            self._symbol = symbol

        def history(self, start=None, end=None, auto_adjust=False) -> pd.DataFrame:  # noqa: ANN001
            if self._symbol == "TECK-B.TO":
                return pd.DataFrame({"Close": [50.0, 52.0, 51.5, 53.0]}, index=date_index)
            return pd.DataFrame()

    fake_yf = ModuleType("yfinance")
    fake_yf.Ticker = FakeTicker  # type: ignore[attr-defined]

    with patch.dict("sys.modules", {"yfinance": fake_yf}):
        history = ticker_utils.get_ticker_price_history(
            "TECK.B", supabase_client=None, days=60, fund=None
        )

    assert not history.empty
    assert requested_symbols == ["TECK.B", "TECK-B", "TECK-B.TO"]
    assert list(history.columns) == ["date", "price", "normalized"]
    assert history["normalized"].iloc[0] == 100.0
