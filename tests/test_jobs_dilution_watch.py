"""Tests for the dilution-watch ticker collector (ROADMAP G3)."""

import types
from unittest.mock import MagicMock

from web_dashboard.scheduler.jobs_dilution_watch import _collect_tickers


def _make_query(rows):
    """A Supabase-style query mock whose chain returns itself.

    Supports ``.select().eq().in_().range().execute()`` in any order; a single
    ``.range().execute()`` returns all ``rows`` (a page smaller than the
    1000-row cap, which terminates the pagination loop).
    """
    query = MagicMock()
    query.select.return_value = query
    query.eq.return_value = query
    query.in_.return_value = query
    query.range.return_value = query
    query.execute.return_value = types.SimpleNamespace(data=list(rows))
    return query


def _make_client(funds_rows, holdings_rows, watchlist_rows):
    funds_q = _make_query(funds_rows)
    holdings_q = _make_query(holdings_rows)
    watchlist_q = _make_query(watchlist_rows)

    queries = {
        "funds": funds_q,
        "latest_positions": holdings_q,
        "watched_tickers_v2": watchlist_q,
    }

    raw = MagicMock()
    raw.table.side_effect = lambda name: queries[name]

    client = MagicMock()
    client.supabase = raw
    return client, funds_q, holdings_q, watchlist_q


def test_collect_tickers_filters_holdings_to_production_funds():
    """Holdings query is scoped to production funds; result is the sorted,
    uppercased union of holdings + active watchlist."""
    funds = [{"name": "Project Chimera"}, {"name": "TFSA"}]
    holdings = [
        {"ticker": "real1", "fund": "Project Chimera"},
        {"ticker": "glo.to", "fund": "TFSA"},
    ]
    watchlist = [{"ticker": "watch1"}, {"ticker": "real1"}]
    client, _funds_q, holdings_q, _wl_q = _make_client(funds, holdings, watchlist)

    tickers = _collect_tickers(client)

    holdings_q.in_.assert_called_once_with("fund", ["Project Chimera", "TFSA"])
    assert tickers == ["GLO.TO", "REAL1", "WATCH1"]


def test_collect_tickers_unfiltered_when_funds_lookup_empty():
    """If the production-fund lookup is empty, holdings are queried WITHOUT
    the ``.in_`` fund filter (unfiltered fallback)."""
    funds: list[dict] = []
    holdings = [
        {"ticker": "AAA", "fund": "Project Chimera"},
        {"ticker": "BBB", "fund": "TEST_fund_abc123"},
    ]
    watchlist = [{"ticker": "CCC"}]
    client, _funds_q, holdings_q, _wl_q = _make_client(funds, holdings, watchlist)

    tickers = _collect_tickers(client)

    holdings_q.in_.assert_not_called()
    assert tickers == ["AAA", "BBB", "CCC"]
