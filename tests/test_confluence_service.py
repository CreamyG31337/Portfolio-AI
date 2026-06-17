"""Tests for cross-signal confluence scorer (ROADMAP G4)."""

from datetime import UTC, date, datetime
from unittest.mock import MagicMock, patch

from web_dashboard.confluence_service import (
    FAMILY_SIGNALS,
    MIN_SCORE_LEDGER,
    MIN_SCORE_PERSIST,
    _apply_stance_flips,
    _detect_social_spike_tickers,
    build_confluence_events_from_hits,
    fetch_recent_confluence_events,
    persist_confluence_event,
    run_confluence_scan,
)


def test_build_events_direction_split_and_min_score():
    hits = {
        "AAA": {
            "bullish": {"insider_cluster", "signals", "congress_purchase"},
            "risk": set(),
            "details": {},
        },
        "BBB": {
            "bullish": set(),
            "risk": {"dilution_flag", "filing_risk"},
            "details": {},
        },
        "CCC": {
            "bullish": {"social_spike"},
            "risk": set(),
            "details": {},
        },
    }
    events = build_confluence_events_from_hits(hits)
    by_ticker = {(e["ticker"], e["direction"]): e for e in events}
    assert ("AAA", "bullish") in by_ticker
    assert by_ticker[("AAA", "bullish")]["score"] == 3
    assert ("BBB", "risk") in by_ticker
    assert by_ticker[("BBB", "risk")]["score"] == 2
    assert ("CCC", "bullish") not in by_ticker  # score 1 < MIN_SCORE_PERSIST


def test_signals_family_single_bucket():
    hits = {
        "XYZ": {
            "bullish": {FAMILY_SIGNALS, "insider_cluster"},
            "risk": set(),
            "details": {FAMILY_SIGNALS: {"trend": "UPTREND", "breakout": True}},
        },
    }
    events = build_confluence_events_from_hits(hits)
    assert len(events) == 1
    assert events[0]["families"] == sorted([FAMILY_SIGNALS, "insider_cluster"])


def test_stance_flip_bullish_and_bearish():
    hits: dict = {}
    _apply_stance_flips(
        hits,
        [
            {"ticker": "A", "to_stance": "BULLISH", "from_stance": "NEUTRAL"},
            {"ticker": "B", "to_stance": "SELL", "from_stance": "BUY"},
            {"ticker": "C", "to_stance": "WATCH", "from_stance": "NEUTRAL"},
        ],
    )
    assert "stance_flip_bullish" in hits["A"]["bullish"]
    assert "stance_flip_bearish" in hits["B"]["risk"]
    assert not hits.get("C", {}).get("bullish") and not hits.get("C", {}).get("risk")


def test_social_spike_skips_insufficient_history():
    pg = MagicMock()
    pg.execute_query.return_value = [
        {"ticker": "LOW", "day": date(2026, 6, 10), "activity": 10},
        {"ticker": "LOW", "day": date(2026, 6, 11), "activity": 12},
    ]
    assert _detect_social_spike_tickers(pg, ["LOW"]) == set()


def test_social_spike_detects_spike():
    pg = MagicMock()
    rows = []
    for i in range(8):
        rows.append({"ticker": "SPIKE", "day": date(2026, 6, 1 + i), "activity": 10})
    rows.append({"ticker": "SPIKE", "day": date(2026, 6, 10), "activity": 100})
    pg.execute_query.return_value = rows
    assert "SPIKE" in _detect_social_spike_tickers(pg, ["SPIKE"])


def test_persist_dedupes_same_families():
    pg = MagicMock()
    pg.execute_query.return_value = [{"?column?": 1}]
    event = {
        "ticker": "AAA",
        "direction": "bullish",
        "score": 2,
        "families": ["insider_cluster", "signals"],
        "details": {},
        "as_of": datetime(2026, 6, 16, tzinfo=UTC),
    }
    assert persist_confluence_event(pg, event) is False
    pg.execute_update.assert_not_called()


def test_persist_inserts_when_not_deduped():
    pg = MagicMock()
    pg.execute_query.return_value = []
    event = {
        "ticker": "AAA",
        "direction": "bullish",
        "score": 2,
        "families": ["insider_cluster", "signals"],
        "details": {},
        "as_of": datetime(2026, 6, 16, tzinfo=UTC),
    }
    assert persist_confluence_event(pg, event) is True
    pg.execute_update.assert_called_once()


@patch("web_dashboard.confluence_service.record_stance_safe")
@patch("web_dashboard.confluence_service.compute_confluence_for_tickers")
@patch("web_dashboard.confluence_service.collect_scope_tickers")
def test_run_scan_writes_stance_at_threshold(mock_tickers, mock_compute, mock_stance):
    mock_tickers.return_value = ["AAA"]
    mock_compute.return_value = [
        {
            "ticker": "AAA",
            "direction": "bullish",
            "score": MIN_SCORE_LEDGER,
            "families": ["a", "b", "c"],
            "details": {},
            "as_of": datetime(2026, 6, 16, tzinfo=UTC),
        },
        {
            "ticker": "BBB",
            "direction": "bullish",
            "score": MIN_SCORE_PERSIST,
            "families": ["a", "b"],
            "details": {},
            "as_of": datetime(2026, 6, 16, tzinfo=UTC),
        },
    ]
    pg = MagicMock()
    pg.execute_query.return_value = []
    mock_stance.return_value = True

    stats = run_confluence_scan(pg, MagicMock())

    assert stats["inserted"] == 2
    assert stats["stances_written"] == 1
    mock_stance.assert_called_once()
    assert mock_stance.call_args.kwargs["source"] == "confluence"
    assert mock_stance.call_args.kwargs["stance"] == "BULLISH"


def test_fetch_recent_swallows_missing_table():
    pg = MagicMock()
    pg.execute_query.side_effect = Exception("relation does not exist")
    assert fetch_recent_confluence_events(pg) == []
