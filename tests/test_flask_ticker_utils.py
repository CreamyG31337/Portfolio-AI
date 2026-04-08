from types import ModuleType, SimpleNamespace
from unittest.mock import patch

import pandas as pd

from web_dashboard import ticker_utils


class _EqExecSelect:
    def __init__(self, root: "_FakeSupabaseClient") -> None:
        self._root = root

    def eq(self, *args, **kwargs):
        return self

    def execute(self):
        return SimpleNamespace(data=[self._root.securities_row.copy()])


class _EqExecUpdate:
    def __init__(self, root: "_FakeSupabaseClient") -> None:
        self._root = root

    def eq(self, *args, **kwargs):
        return self

    def execute(self):
        return SimpleNamespace(data=[])


class _SecuritiesTable:
    def __init__(self, root: "_FakeSupabaseClient") -> None:
        self._root = root

    def select(self, *args, **kwargs):
        return _EqExecSelect(self._root)

    def update(self, payload):
        self._root.last_update = payload
        return _EqExecUpdate(self._root)


class _FakeSupabaseClient:
    """Minimal client: supabase.table('securities').select().eq().execute() / update()."""

    def __init__(self) -> None:
        self.securities_row = {
            "ticker": "TECK.B",
            "company_name": "Unknown",
            "description": "placeholder",
            "use_alt_logo": False,
        }
        self.last_update: dict | None = None
        self.supabase = self

    def table(self, name: str):
        assert name == "securities"
        return _SecuritiesTable(self)


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
    # Must fall within get_ticker_price_history's rolling window (last ``days`` from UTC now).
    end_day = pd.Timestamp.now(tz="UTC").normalize()
    date_index = pd.date_range(end=end_day, periods=4, freq="-1D", tz="UTC").sort_values()
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


def test_get_ticker_info_refreshes_unknown_company_name_from_db_row() -> None:
    requested_symbols: list[str] = []
    fake_client = _FakeSupabaseClient()

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
        with patch(
            "web_dashboard.utils.logo_utils.get_ticker_logo_url",
            return_value=None,
        ):
            result = ticker_utils.get_ticker_info(
                "TECK.B", supabase_client=fake_client, postgres_client=None
            )

    assert result["basic_info"] is not None
    assert result["basic_info"]["company_name"] == "Teck Resources Limited"
    assert result["basic_info"]["sector"] == "Basic Materials"
    assert requested_symbols == ["TECK.B", "TECK-B", "TECK-B.TO"]
    assert fake_client.last_update is not None
    assert fake_client.last_update["company_name"] == "Teck Resources Limited"
