"""Tests for the SEC filing-watch ticker collector (ROADMAP G2)."""

import types
from unittest.mock import MagicMock

from web_dashboard.scheduler.jobs_sec_filings import _collect_tickers


def _make_query(rows):
    query = MagicMock()
    query.select.return_value = query
    query.eq.return_value = query
    query.in_.return_value = query
    query.range.return_value = query
    query.execute.return_value = types.SimpleNamespace(data=list(rows))
    return query


def _make_client(funds_rows, holdings_rows, watchlist_rows):
    queries = {
        "funds": _make_query(funds_rows),
        "latest_positions": _make_query(holdings_rows),
        "watched_tickers_v2": _make_query(watchlist_rows),
    }
    raw = MagicMock()
    raw.table.side_effect = lambda name: queries[name]
    client = MagicMock()
    client.supabase = raw
    return client, queries


def test_collect_tickers_filters_holdings_to_production_funds():
    funds = [{"name": "Project Chimera"}]
    holdings = [{"ticker": "aapl", "fund": "Project Chimera"}]
    watchlist = [{"ticker": "GME"}, {"ticker": "aapl"}]
    client, queries = _make_client(funds, holdings, watchlist)

    tickers = _collect_tickers(client)

    queries["latest_positions"].in_.assert_called_once_with("fund", ["Project Chimera"])
    assert tickers == ["AAPL", "GME"]


def test_collect_tickers_unfiltered_when_funds_lookup_empty():
    funds: list[dict] = []
    holdings = [{"ticker": "AAA", "fund": "Project Chimera"}]
    watchlist = [{"ticker": "BBB"}]
    client, queries = _make_client(funds, holdings, watchlist)

    tickers = _collect_tickers(client)

    queries["latest_positions"].in_.assert_not_called()
    assert tickers == ["AAA", "BBB"]
