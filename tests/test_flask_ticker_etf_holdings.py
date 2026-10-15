"""Flask: /api/ticker/<ticker>/etf-holdings (ETF holdings panel on ticker details)."""

from datetime import date
from unittest.mock import MagicMock, patch

import pytest


def _has_plotly() -> bool:
    try:
        import plotly.graph_objs  # noqa: F401
    except ImportError:
        return False
    return True


skip_without_plotly = pytest.mark.skipif(
    not _has_plotly(),
    reason="plotly required to import web_dashboard.app (see conftest)",
)


@pytest.fixture
def auth_ok():
    with patch(
        "auth.auth_manager.verify_session",
        return_value={"user_id": "u1", "email": "user@example.com"},
    ), patch(
        "flask_auth_utils.refresh_token_if_needed_flask",
        return_value=(True, None, None, None),
    ):
        yield


def _pg_client(execute_query=None):
    pc = MagicMock()
    pc.execute_query = execute_query if execute_query is not None else MagicMock()
    return pc


class FakeAliasesTable:
    """Fake supabase `.table("ticker_symbol_aliases")` for the select/in_ read
    the endpoint's link_ticker lookup uses."""

    def __init__(self, rows=None, error=None):
        self.rows = {(r['ticker'] or '').upper(): r['yahoo_symbol'] for r in (rows or [])}
        self.error = error
        self._chunk = None

    def select(self, _cols):
        if self.error:
            raise self.error
        return self

    def in_(self, _col, chunk):
        self._chunk = list(chunk)
        return self

    def execute(self):
        chunk, self._chunk = self._chunk, None
        return MagicMock(data=[
            {'ticker': t, 'yahoo_symbol': self.rows[t]}
            for t in chunk if t in self.rows
        ])


def _sb_client(alias_rows=None, alias_error=None):
    sb = MagicMock()
    table = FakeAliasesTable(rows=alias_rows, error=alias_error)
    sb.supabase.table.side_effect = lambda name: (
        table if name == 'ticker_symbol_aliases' else MagicMock()
    )
    return sb


@skip_without_plotly
def test_ticker_etf_holdings_tracked(client, auth_ok):
    client.set_cookie("auth_token", "test.jwt.token")
    # Rows come back from the DB already ordered by weight desc (ORDER BY in SQL)
    rows = [
        {"holding_ticker": "SENS", "holding_name": "Senseonics", "shares_held": 900000, "weight_percent": 4.02},
        {"holding_ticker": "AME", "holding_name": "Amplify Energy Corp", "shares_held": 250000, "weight_percent": 3.21},
    ]
    execute_query = MagicMock(side_effect=[
        [{"latest_date": date(2026, 10, 10)}],  # MAX(date) lookup
        rows,                                   # holdings for that date
    ])
    with patch("routes.etf_routes._get_postgres_client", return_value=_pg_client(execute_query)), \
         patch("routes.etf_routes.SupabaseClient", return_value=_sb_client()):
        resp = client.get("/api/ticker/buzz/etf-holdings")

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["success"] is True
    assert body["is_tracked_etf"] is True
    assert body["as_of"] == "2026-10-10"
    assert body["holding_count"] == 2
    assert [h["ticker"] for h in body["holdings"]] == ["SENS", "AME"]  # weight desc preserved
    assert body["holdings"][0]["shares"] == 900000
    assert body["holdings"][0]["weight_percent"] == 4.02
    assert [h["link_ticker"] for h in body["holdings"]] == ["SENS", "AME"]  # no alias, no slash

    # Ticker uppercased/stripped and passed as a SQL parameter (never interpolated)
    assert execute_query.call_args_list[0].args[1] == ("BUZZ",)
    assert execute_query.call_args_list[1].args[1] == ("2026-10-10", "BUZZ")


@skip_without_plotly
def test_ticker_etf_holdings_untracked_is_not_an_error(client, auth_ok):
    client.set_cookie("auth_token", "test.jwt.token")
    execute_query = MagicMock(return_value=[{"latest_date": None}])
    with patch("routes.etf_routes._get_postgres_client", return_value=_pg_client(execute_query)), \
         patch("routes.etf_routes.SupabaseClient", return_value=_sb_client()):
        resp = client.get("/api/ticker/AAPL/etf-holdings")

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["success"] is True
    assert body["is_tracked_etf"] is False
    assert body["as_of"] is None
    assert body["holdings"] == []
    assert body["holding_count"] == 0
    # Only the MAX(date) lookup ran; no holdings query for untracked tickers
    assert execute_query.call_count == 1


@skip_without_plotly
def test_ticker_etf_holdings_empty_latest_result(client, auth_ok):
    """MAX(date) returning no rows at all is also untracked, not an error."""
    client.set_cookie("auth_token", "test.jwt.token")
    execute_query = MagicMock(return_value=[])
    with patch("routes.etf_routes._get_postgres_client", return_value=_pg_client(execute_query)), \
         patch("routes.etf_routes.SupabaseClient", return_value=_sb_client()):
        resp = client.get("/api/ticker/NVDA/etf-holdings")

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["success"] is True
    assert body["is_tracked_etf"] is False
    assert body["holdings"] == []


@skip_without_plotly
def test_ticker_etf_holdings_db_error_returns_500(client, auth_ok):
    client.set_cookie("auth_token", "test.jwt.token")
    execute_query = MagicMock(side_effect=RuntimeError("connection refused"))
    with patch("routes.etf_routes._get_postgres_client", return_value=_pg_client(execute_query)), \
         patch("routes.etf_routes.SupabaseClient", return_value=_sb_client()):
        resp = client.get("/api/ticker/BUZZ/etf-holdings")

    assert resp.status_code == 500
    body = resp.get_json()
    assert body["success"] is False


# --- link_ticker (share-class aliases for holding links) ---


@skip_without_plotly
def test_ticker_etf_holdings_link_ticker(client, auth_ok):
    """link_ticker comes from a recorded alias row when one exists, from the
    slash rule for slash spellings without one, and is the ticker unchanged
    otherwise.  The displayed ticker always stays the holdings spelling."""
    client.set_cookie("auth_token", "test.jwt.token")
    rows = [
        {"holding_ticker": "BRKB", "holding_name": "Berkshire Hathaway", "shares_held": 100, "weight_percent": 5.0},
        {"holding_ticker": "BF/B", "holding_name": "Brown-Forman Corp", "shares_held": 90, "weight_percent": 4.0},
        {"holding_ticker": "FOXA", "holding_name": "Fox Corp Class A", "shares_held": 80, "weight_percent": 3.0},
        {"holding_ticker": "SENS", "holding_name": "Senseonics", "shares_held": 70, "weight_percent": 2.0},
    ]
    execute_query = MagicMock(side_effect=[
        [{"latest_date": date(2026, 10, 10)}],
        rows,
    ])
    alias_rows = [{"ticker": "BRKB", "yahoo_symbol": "BRK-B"}]
    with patch("routes.etf_routes._get_postgres_client", return_value=_pg_client(execute_query)), \
         patch("routes.etf_routes.SupabaseClient", return_value=_sb_client(alias_rows=alias_rows)):
        resp = client.get("/api/ticker/buzz/etf-holdings")

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["success"] is True
    assert {h["ticker"]: h["link_ticker"] for h in body["holdings"]} == {
        "BRKB": "BRK-B",  # recorded alias row
        "BF/B": "BF-B",   # slash fallback (no alias row)
        "FOXA": "FOXA",   # real ticker, unchanged
        "SENS": "SENS",   # plain ticker, unchanged
    }


@skip_without_plotly
def test_ticker_etf_holdings_alias_lookup_error_falls_back_to_slash_rule(client, auth_ok):
    """A Supabase failure (client construction or table read) never fails the
    endpoint: the slash rule still applies and plain tickers stay unchanged."""
    client.set_cookie("auth_token", "test.jwt.token")
    rows = [
        {"holding_ticker": "BF/B", "holding_name": "Brown-Forman Corp", "shares_held": 90, "weight_percent": 4.0},
        {"holding_ticker": "BRKB", "holding_name": "Berkshire Hathaway", "shares_held": 100, "weight_percent": 5.0},
    ]
    for supabase_patch in (
        patch("routes.etf_routes.SupabaseClient", side_effect=RuntimeError("supabase down")),
        patch("routes.etf_routes.SupabaseClient", return_value=_sb_client(alias_error=RuntimeError(
            'relation "ticker_symbol_aliases" does not exist'
        ))),
    ):
        execute_query = MagicMock(side_effect=[
            [{"latest_date": date(2026, 10, 10)}],
            rows,
        ])
        with patch("routes.etf_routes._get_postgres_client", return_value=_pg_client(execute_query)), \
             supabase_patch:
            resp = client.get("/api/ticker/buzz/etf-holdings")

        assert resp.status_code == 200
        body = resp.get_json()
        assert body["success"] is True
        assert {h["ticker"]: h["link_ticker"] for h in body["holdings"]} == {
            "BF/B": "BF-B",  # slash rule still applied
            "BRKB": "BRKB",  # nothing derivable without the alias table
        }
