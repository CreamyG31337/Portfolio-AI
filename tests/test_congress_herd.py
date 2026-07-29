"""Tests for congress herd-buy detection (ROADMAP Pillar 5.1a / H5)."""

import types
from unittest.mock import MagicMock, patch

from web_dashboard.congress_herd_service import (
    detect_herd_buys,
    fetch_recent_congress_buys,
    record_congress_herd_stances,
)


def _buy(
    ticker: str,
    politician_id: str,
    *,
    name: str | None = None,
    tx_date: str = "2026-06-01",
    party: str = "D",
    chamber: str = "house",
) -> dict:
    return {
        "politician_id": politician_id,
        "ticker": ticker,
        "politician": name or f"Politician {politician_id}",
        "party": party,
        "chamber": chamber,
        "transaction_date": tx_date,
        "amount": "$1,001 - $15,000",
        "type": "Purchase",
    }


def test_detect_requires_min_distinct_politicians():
    rows = [
        _buy("NVDA", "p1"), _buy("NVDA", "p2"),
        _buy("AAPL", "p3"), _buy("AAPL", "p4"), _buy("AAPL", "p5"),
    ]
    herds = detect_herd_buys(rows, min_politicians=2)
    assert [h["ticker"] for h in herds] == ["AAPL", "NVDA"]
    assert herds[0]["politician_count"] == 3


def test_same_politician_multiple_buys_counts_once():
    rows = [
        _buy("NVDA", "p1", tx_date="2026-06-01"),
        _buy("NVDA", "p1", tx_date="2026-06-05"),
        _buy("NVDA", "p1", tx_date="2026-06-09"),
    ]
    assert detect_herd_buys(rows, min_politicians=2) == []


def test_held_and_watched_priority_sort():
    rows = [
        _buy("DISC", "p1"), _buy("DISC", "p2"), _buy("DISC", "p3"),
        _buy("MINE", "p4"), _buy("MINE", "p5"),
    ]
    herds = detect_herd_buys(
        rows,
        min_politicians=2,
        held_tickers={"MINE"},
        watched_tickers={"WATCH"},
    )
    assert [h["ticker"] for h in herds] == ["MINE", "DISC"]
    assert herds[0]["held"] is True


class _PagedQuery:
    def __init__(self, rows):
        self._rows = rows
        self._start = 0
        self._end = None

    def select(self, *_a, **_k):
        return self

    def eq(self, *_a, **_k):
        return self

    def neq(self, *_a, **_k):
        return self

    def gte(self, *_a, **_k):
        return self

    def order(self, *_a, **_k):
        return self

    def range(self, start, end):
        self._start, self._end = start, end
        return self

    def execute(self):
        return types.SimpleNamespace(data=self._rows[self._start : self._end + 1])


class _PagedSupabase:
    def __init__(self, rows):
        self._rows = rows
        self.supabase = self

    def table(self, _name):
        return _PagedQuery(self._rows)


def test_fetch_recent_congress_buys_paginates_past_1000():
    rows = [_buy(f"T{i:05d}", f"p{i}") for i in range(2300)]
    fetched = fetch_recent_congress_buys(_PagedSupabase(rows), days=30)
    assert len(fetched) == 2300


@patch("web_dashboard.congress_herd_service.record_stance_safe")
@patch("web_dashboard.congress_herd_service.build_congress_herd_buys")
def test_record_congress_herd_stances_writes_bullish(
    mock_build: MagicMock, mock_stance: MagicMock
) -> None:
    mock_build.return_value = [
        {
            "ticker": "NVDA",
            "politician_count": 3,
            "buy_count": 4,
            "latest_buy": "2026-06-10",
            "held": True,
            "watched": False,
        },
        {
            "ticker": "AAPL",
            "politician_count": 2,
            "buy_count": 2,
            "latest_buy": "2026-06-09",
            "held": False,
            "watched": True,
        },
    ]
    mock_stance.return_value = True

    stats = record_congress_herd_stances(MagicMock(), MagicMock(), days=30)

    assert stats == {"herds": 2, "stances_written": 2}
    assert mock_stance.call_count == 2
    first = mock_stance.call_args_list[0].kwargs
    assert first["source"] == "congress_herd"
    assert first["stance"] == "BULLISH"
    assert first["confidence"] is None
    assert first["fund_key"] == ""
    assert first["metadata"]["politician_count"] == 3
    assert first["metadata"]["window_days"] == 30


@patch("web_dashboard.congress_herd_service.record_stance_safe")
@patch("web_dashboard.congress_herd_service.build_congress_herd_buys")
def test_record_congress_herd_stances_empty(
    mock_build: MagicMock, mock_stance: MagicMock
) -> None:
    mock_build.return_value = []
    stats = record_congress_herd_stances(MagicMock(), MagicMock())
    assert stats == {"herds": 0, "stances_written": 0}
    mock_stance.assert_not_called()
