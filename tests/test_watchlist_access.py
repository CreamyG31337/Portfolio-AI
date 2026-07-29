import os
from unittest.mock import MagicMock, patch

import web_dashboard.watchlist_access as wa
from web_dashboard.watchlist_access import (
    get_active_watchlist_rows,
    get_active_watchlist_tickers,
    get_watchlist_status_for_fund,
    parse_ticker_list,
    set_watchlist_active,
    upsert_watchlist_ticker,
)


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, data):
        self._data = data

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, *_args, **_kwargs):
        return self

    def execute(self):
        return _Result(self._data)


class _Supabase:
    def __init__(self, table_data, fail_v2=False):
        self._table_data = table_data
        self._fail_v2 = fail_v2

    def table(self, name):
        if self._fail_v2 and name == "watched_tickers_v2":
            raise RuntimeError("missing table")
        return _Query(self._table_data.get(name, []))


class _Client:
    def __init__(self, table_data, fail_v2=False):
        self.supabase = _Supabase(table_data, fail_v2=fail_v2)


def _reset_strict_mode():
    """Reset the cached strict mode flag so env changes take effect."""
    wa._STRICT_MODE = None


def test_watchlist_access_uses_v2_when_available() -> None:
    _reset_strict_mode()
    client = _Client(
        {
            "watched_tickers_v2": [
                {"fund": "TEST", "ticker": "abc", "priority_tier": "A", "is_active": True},
                {"fund": "TEST", "ticker": "ABC", "priority_tier": "B", "is_active": True},
            ],
            "watched_tickers": [{"ticker": "ZZZ", "priority_tier": "C", "is_active": True}],
        }
    )

    rows = get_active_watchlist_rows(client, fund="TEST")
    assert len(rows) == 1
    assert rows[0]["ticker"] == "ABC"
    assert rows[0]["fund"] == "TEST"


def test_watchlist_access_falls_back_to_legacy_when_v2_missing() -> None:
    _reset_strict_mode()
    client = _Client(
        {"watched_tickers": [{"ticker": "msft", "priority_tier": "B", "is_active": True}]},
        fail_v2=True,
    )

    tickers = get_active_watchlist_tickers(client, fund="RRSP")
    assert tickers == ["MSFT"]


def test_fallback_when_v2_empty() -> None:
    _reset_strict_mode()
    client = _Client(
        {
            "watched_tickers_v2": [],
            "watched_tickers": [
                {"ticker": "GOOG", "priority_tier": "A", "is_active": True},
            ],
        }
    )

    rows = get_active_watchlist_rows(client, fund="TEST")
    assert len(rows) == 1
    assert rows[0]["ticker"] == "GOOG"


def test_no_fallback_when_fallback_disabled() -> None:
    _reset_strict_mode()
    client = _Client(
        {
            "watched_tickers_v2": [],
            "watched_tickers": [
                {"ticker": "GOOG", "priority_tier": "A", "is_active": True},
            ],
        }
    )

    rows = get_active_watchlist_rows(client, fund="TEST", fallback_if_empty=False)
    assert rows == []


def test_strict_mode_disables_fallback() -> None:
    _reset_strict_mode()
    os.environ["WATCHLIST_STRICT"] = "1"
    try:
        wa._STRICT_MODE = None
        client = _Client(
            {
                "watched_tickers_v2": [],
                "watched_tickers": [
                    {"ticker": "AAPL", "priority_tier": "A", "is_active": True},
                ],
            }
        )

        rows = get_active_watchlist_rows(client, fund="TEST")
        assert rows == []
    finally:
        os.environ.pop("WATCHLIST_STRICT", None)
        wa._STRICT_MODE = None


def test_strict_mode_returns_empty_on_v2_failure() -> None:
    _reset_strict_mode()
    os.environ["WATCHLIST_STRICT"] = "1"
    try:
        wa._STRICT_MODE = None
        client = _Client(
            {"watched_tickers": [{"ticker": "AAPL", "is_active": True}]},
            fail_v2=True,
        )

        rows = get_active_watchlist_rows(client, fund="TEST")
        assert rows == []
    finally:
        os.environ.pop("WATCHLIST_STRICT", None)
        wa._STRICT_MODE = None


def test_get_active_watchlist_tickers_sorted() -> None:
    _reset_strict_mode()
    client = _Client(
        {
            "watched_tickers_v2": [
                {"fund": "TEST", "ticker": "ZZZ", "is_active": True},
                {"fund": "TEST", "ticker": "AAA", "is_active": True},
                {"fund": "TEST", "ticker": "MMM", "is_active": True},
            ],
        }
    )

    tickers = get_active_watchlist_tickers(client, fund="TEST")
    assert tickers == ["AAA", "MMM", "ZZZ"]


def test_no_fund_filter_returns_all_funds() -> None:
    _reset_strict_mode()
    client = _Client(
        {
            "watched_tickers_v2": [
                {"fund": "TFSA", "ticker": "AAPL", "is_active": True},
                {"fund": "RRSP", "ticker": "MSFT", "is_active": True},
            ],
        }
    )

    rows = get_active_watchlist_rows(client)
    assert len(rows) == 2
    tickers = {r["ticker"] for r in rows}
    assert tickers == {"AAPL", "MSFT"}


def test_parse_ticker_list_dedupes() -> None:
    assert parse_ticker_list("crm\nNOW, iren;CELH crm") == ["CRM", "NOW", "IREN", "CELH"]


@patch("web_dashboard.watchlist_access.get_ticker_currency", create=True)
def test_upsert_watchlist_ticker_calls_ensure_and_upsert(_currency) -> None:
    _currency.side_effect = ImportError("use fallback path")
    client = MagicMock()
    client.ensure_ticker_in_securities.return_value = True
    table = MagicMock()
    client.supabase.table.return_value = table
    table.upsert.return_value = table
    table.execute.return_value = MagicMock(data=[{"ticker": "CRM"}])

    with patch("utils.ticker_utils.get_ticker_currency", return_value="USD"):
        result = upsert_watchlist_ticker(
            client,
            fund="Project Chimera",
            ticker="crm",
            priority_tier="B",
            source="bulk_paste",
        )
    assert result["ok"] is True
    assert result["ticker"] == "CRM"
    client.ensure_ticker_in_securities.assert_called_once_with("CRM", "USD")
    table.upsert.assert_called_once()
    payload = table.upsert.call_args[0][0]
    assert payload["fund"] == "Project Chimera"
    assert payload["ticker"] == "CRM"
    assert payload["source"] == "bulk_paste"


def test_set_watchlist_active_updates() -> None:
    client = MagicMock()
    table = MagicMock()
    client.supabase.table.return_value = table
    table.update.return_value = table
    table.eq.return_value = table
    table.execute.return_value = MagicMock(data=[{"ticker": "NOW"}])

    result = set_watchlist_active(
        client, fund="Project Chimera", ticker="NOW", is_active=False
    )
    assert result["ok"] is True
    table.update.assert_called_once_with({"is_active": False})


def test_get_watchlist_status_for_fund_not_watched() -> None:
    client = MagicMock()
    table = MagicMock()
    client.supabase.table.return_value = table
    table.select.return_value = table
    table.eq.return_value = table
    table.limit.return_value = table
    table.execute.return_value = MagicMock(data=[])

    status = get_watchlist_status_for_fund(client, fund="TEST", ticker="CELH")
    assert status["in_watchlist"] is False
    assert status["ticker"] == "CELH"
    assert status["fund"] == "TEST"


def test_enrich_watchlist_rows_merges_analysis_and_queue() -> None:
    from web_dashboard.watchlist_access import enrich_watchlist_rows

    rows = [
        {
            "fund": "TEST",
            "ticker": "CRM",
            "priority_tier": "B",
            "is_active": True,
            "source": "bulk_paste",
        },
        {
            "fund": "TEST",
            "ticker": "NOW",
            "priority_tier": "B",
            "is_active": True,
            "source": "bulk_paste",
        },
    ]
    postgres = MagicMock()
    postgres.execute_query.side_effect = [
        [
            {
                "ticker": "CRM",
                "analysis_date": "2026-07-01",
                "updated_at": "2026-07-01T12:00:00",
                "sentiment": "BULLISH",
                "stance": "BUY",
                "confidence_score": 0.7,
                "summary": "Strong SaaS narrative",
            }
        ],
        [
            {
                "ticker": "CRM",
                "unified_conviction": "constructive",
                "confidence_adjusted": 0.6,
                "updated_at": "2026-07-02T00:00:00",
            }
        ],
    ]
    supabase = MagicMock()
    task_q = MagicMock()
    legacy_q = MagicMock()

    def _table(name: str):
        return task_q if name == "ai_task_queue" else legacy_q

    supabase.supabase.table.side_effect = _table
    for q in (task_q, legacy_q):
        q.select.return_value = q
        q.in_.return_value = q
        q.eq.return_value = q
        q.execute.return_value = MagicMock(data=[])
    task_q.execute.return_value = MagicMock(
        data=[{"target_key": "NOW", "status": "pending", "analysis_type": "ticker_analysis"}]
    )

    out = enrich_watchlist_rows(rows, supabase_client=supabase, postgres_client=postgres)
    by_ticker = {r["ticker"]: r for r in out}
    assert by_ticker["CRM"]["analyzed"] is True
    assert by_ticker["CRM"]["stance"] == "BUY"
    assert by_ticker["CRM"]["has_meta"] is True
    assert by_ticker["CRM"]["dossier_url"] == "/ticker?ticker=CRM"
    assert by_ticker["NOW"]["analyzed"] is False
    assert by_ticker["NOW"]["queue_status"] == "pending"
