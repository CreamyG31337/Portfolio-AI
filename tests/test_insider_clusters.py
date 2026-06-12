"""Tests for insider cluster-buy detection (ROADMAP §4.2)."""

import types

from web_dashboard.insider_clusters_service import (
    detect_cluster_buys,
    fetch_recent_insider_buys,
)


def _buy(ticker, name, value=10_000.0, tx_date="2026-06-01", title="Director"):
    return {
        "ticker": ticker,
        "insider_name": name,
        "insider_title": title,
        "transaction_date": tx_date,
        "shares": 1000,
        "value": value,
    }


def test_detect_requires_min_distinct_insiders():
    rows = [
        _buy("AAA", "Alice"), _buy("AAA", "Bob"), _buy("AAA", "Carol"),
        _buy("BBB", "Dave"), _buy("BBB", "Erin"),
    ]
    clusters = detect_cluster_buys(rows, min_insiders=3)
    assert [c["ticker"] for c in clusters] == ["AAA"]
    assert clusters[0]["insider_count"] == 3


def test_same_insider_multiple_buys_counts_once():
    """One insider averaging in over several Form 4s is not a cluster."""
    rows = [
        _buy("AAA", "Alice", tx_date="2026-06-01"),
        _buy("AAA", "Alice", tx_date="2026-06-05"),
        _buy("AAA", "Alice", tx_date="2026-06-09"),
    ]
    assert detect_cluster_buys(rows, min_insiders=3) == []


def test_cluster_aggregates_value_buys_and_latest_date():
    rows = [
        _buy("AAA", "Alice", value=5_000, tx_date="2026-05-20"),
        _buy("AAA", "Bob", value=15_000, tx_date="2026-06-02"),
        _buy("AAA", "Carol", value=None, tx_date="2026-05-28"),
        _buy("AAA", "Alice", value=2_500, tx_date="2026-06-04"),
    ]
    (cluster,) = detect_cluster_buys(rows, min_insiders=3)
    assert cluster["buy_count"] == 4
    assert cluster["total_value"] == 22_500.0  # None value treated as 0
    assert cluster["latest_buy"] == "2026-06-04"
    # Insiders ranked by total value bought.
    assert [i["name"] for i in cluster["insiders"]] == ["Bob", "Alice", "Carol"]


def test_junk_tickers_and_blank_names_filtered():
    rows = [
        _buy("-", "Alice"), _buy("-", "Bob"), _buy("-", "Carol"),
        _buy("AAA", ""), _buy("AAA", "Bob"), _buy("AAA", "Carol"),
    ]
    assert detect_cluster_buys(rows, min_insiders=3) == []


def test_held_and_watched_flags_and_priority_sort():
    rows = [
        # DISC: bigger cluster, but neither held nor watched.
        _buy("DISC", "A"), _buy("DISC", "B"), _buy("DISC", "C"), _buy("DISC", "D"),
        # MINE: held — should outrank DISC despite fewer insiders.
        _buy("MINE", "E"), _buy("MINE", "F"), _buy("MINE", "G"),
    ]
    clusters = detect_cluster_buys(
        rows, min_insiders=3, held_tickers={"mine"}, watched_tickers={"DISC2"}
    )
    assert [c["ticker"] for c in clusters] == ["MINE", "DISC"]
    assert clusters[0]["held"] is True
    assert clusters[1]["held"] is False and clusters[1]["watched"] is False


class _PagedQuery:
    def __init__(self, rows):
        self._rows = rows
        self._start = 0
        self._end = None

    def select(self, *_a, **_k):
        return self

    def eq(self, *_a, **_k):
        return self

    def gte(self, *_a, **_k):
        return self

    def order(self, *_a, **_k):
        return self

    def range(self, start, end):
        self._start, self._end = start, end
        return self

    def execute(self):
        return types.SimpleNamespace(data=self._rows[self._start:self._end + 1])


class _PagedSupabase:
    def __init__(self, rows):
        self._rows = rows
        self.supabase = self

    def table(self, _name):
        return _PagedQuery(self._rows)


def test_fetch_recent_insider_buys_paginates_past_1000():
    rows = [_buy(f"T{i:05d}", f"Insider {i}") for i in range(2300)]
    fetched = fetch_recent_insider_buys(_PagedSupabase(rows), days=30)
    assert len(fetched) == 2300
