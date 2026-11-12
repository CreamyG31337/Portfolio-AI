"""Tests for ARK trade notification ledger service (ROADMAP §2.8 L4)."""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
import uuid

import pytest
import requests

from web_dashboard.ark_stance_service import (
    ARK_FUNDS,
    SOURCE,
    STANCE,
    is_foreign_ticker,
    record_ark_stances,
)
from web_dashboard.idea_stance_service import entry_as_of


def _trade(
    ticker: str = "TSLA",
    fund: str = "ARKK",
    date_str: str = "2026-11-05",
    direction: str = "Buy",
    shares: int = 1000,
    etf_percent: float = 0.05,
) -> dict:
    return {
        "fund": fund,
        "date": date_str,
        "ticker": ticker,
        "company": "Tesla Inc",
        "direction": direction,
        "cusip": "US88160R1014",
        "shares": shares,
        "etf_percent": etf_percent,
    }


def _mock_api(trades_by_fund: dict[str, list[dict]]):
    def _get(url, *args, **kwargs):
        resp = MagicMock()
        resp.status_code = 200
        for fund, trades in trades_by_fund.items():
            if f"symbol={fund}" in url:
                resp.json.return_value = {"trades": trades}
                return resp
        resp.json.return_value = {"trades": []}
        return resp
    return _get


@patch("web_dashboard.ark_stance_service.record_stance_safe", return_value=True)
@patch("requests.get")
def test_wash_buy_ignored(mock_get: MagicMock, mock_record: MagicMock) -> None:
    """A fund's Buy is ignored if the SAME fund also Sold that ticker on the same day."""
    mock_get.side_effect = _mock_api({
        "ARKK": [
            _trade(ticker="AAPL", fund="ARKK", direction="Buy", shares=500),
            _trade(ticker="AAPL", fund="ARKK", direction="Sell", shares=300),
        ]
    })
    pg = MagicMock()
    pg.execute_query.return_value = []

    stats = record_ark_stances(pg, pause_seconds=0, funds=("ARKK",))

    assert stats["trades_fetched"] == 2
    assert stats["skipped_wash"] == 1
    assert stats["candidates"] == 0
    assert stats["stances_written"] == 0
    mock_record.assert_not_called()


@patch("web_dashboard.ark_stance_service.record_stance_safe", return_value=True)
@patch("requests.get")
def test_foreign_ticker_skipped(mock_get: MagicMock, mock_record: MagicMock) -> None:
    """Tickers containing space or starting with digit are skipped as foreign listings."""
    mock_get.side_effect = _mock_api({
        "ARKK": [
            _trade(ticker="1234 HK", direction="Buy"),
            _trade(ticker="005930", direction="Buy"),
            _trade(ticker="MOG A", direction="Buy"),
        ]
    })
    pg = MagicMock()
    pg.execute_query.return_value = []

    stats = record_ark_stances(pg, pause_seconds=0, funds=("ARKK",))

    assert stats["skipped_foreign"] == 3
    assert stats["candidates"] == 0
    assert stats["stances_written"] == 0
    mock_record.assert_not_called()


@patch("web_dashboard.ark_stance_service.record_stance_safe", return_value=True)
@patch("requests.get")
def test_throttle_existing_row_in_db_skips(mock_get: MagicMock, mock_record: MagicMock) -> None:
    """Existing row within 30 days in DB causes candidate to be skipped."""
    mock_get.side_effect = _mock_api({
        "ARKK": [_trade(ticker="TSLA", date_str="2026-11-05", direction="Buy")]
    })
    pg = MagicMock()
    # Simulate DB finding an existing precursor:ark_buy within 30 days
    pg.execute_query.return_value = [{"1": 1}]

    stats = record_ark_stances(pg, pause_seconds=0, funds=("ARKK",))

    assert stats["candidates"] == 1
    assert stats["skipped_throttle"] == 1
    assert stats["stances_written"] == 0
    mock_record.assert_not_called()


@patch("web_dashboard.ark_stance_service.record_stance_safe", return_value=True)
@patch("requests.get")
def test_throttle_two_buys_ten_days_apart_in_one_run(mock_get: MagicMock, mock_record: MagicMock) -> None:
    """Two buys of the same ticker 10 days apart in one run writes only the first stance."""
    mock_get.side_effect = _mock_api({
        "ARKK": [
            _trade(ticker="TSLA", date_str="2026-11-01", direction="Buy", shares=1000),
            _trade(ticker="TSLA", date_str="2026-11-11", direction="Buy", shares=2000),
        ]
    })
    pg = MagicMock()
    pg.execute_query.return_value = []

    stats = record_ark_stances(pg, pause_seconds=0, funds=("ARKK",))

    assert stats["candidates"] == 2
    assert stats["skipped_throttle"] == 1
    assert stats["stances_written"] == 1
    assert mock_record.call_count == 1
    call_kwargs = mock_record.call_args.kwargs
    assert call_kwargs["ticker"] == "TSLA"
    assert call_kwargs["source"] == SOURCE
    assert call_kwargs["stance"] == STANCE


@patch("web_dashboard.ark_stance_service.record_stance_safe", return_value=True)
@patch("requests.get")
def test_idempotent_uuid_generation(mock_get: MagicMock, mock_record: MagicMock) -> None:
    """source_ref_id is uuid.uuid5(uuid.NAMESPACE_URL, f'ark-buy:{date}:{ticker}')."""
    trade_date = "2026-11-05"
    ticker = "NVDA"
    expected_uuid = uuid.uuid5(uuid.NAMESPACE_URL, f"ark-buy:{trade_date}:{ticker}")

    mock_get.side_effect = _mock_api({
        "ARKK": [_trade(ticker=ticker, date_str=trade_date, direction="Buy")]
    })
    pg = MagicMock()
    pg.execute_query.return_value = []

    stats = record_ark_stances(pg, pause_seconds=0, funds=("ARKK",))

    assert stats["stances_written"] == 1
    call_kwargs = mock_record.call_args.kwargs
    assert call_kwargs["source_ref_id"] == expected_uuid
    assert call_kwargs["metadata"]["ark"]["trade_date"] == trade_date
    assert call_kwargs["metadata"]["ark"]["funds"] == ["ARKK"]
    assert call_kwargs["metadata"]["ark"]["rule"] == "first ARK active-fund buy in 30d -> BEARISH"
    assert call_kwargs["metadata"]["ark"]["study"] == "roadmap L3b"


def test_as_of_is_next_weekday_after_trade_date() -> None:
    """as_of is the first weekday strictly after trade date at 21:00 UTC."""
    # Tuesday -> Wednesday
    tue = datetime(2026, 11, 3, 20, 0, tzinfo=UTC)
    assert entry_as_of(tue).date().isoformat() == "2026-11-04"
    assert entry_as_of(tue).hour == 21

    # Friday -> Monday
    fri = datetime(2026, 11, 6, 20, 0, tzinfo=UTC)
    assert entry_as_of(fri).date().isoformat() == "2026-11-09"
    assert entry_as_of(fri).hour == 21

    # Saturday -> Monday
    sat = datetime(2026, 11, 7, 20, 0, tzinfo=UTC)
    assert entry_as_of(sat).date().isoformat() == "2026-11-09"
    assert entry_as_of(sat).hour == 21


@patch("web_dashboard.ark_stance_service.record_stance_safe", return_value=True)
@patch("requests.get")
def test_api_error_for_one_fund_does_not_stop_others(mock_get: MagicMock, mock_record: MagicMock) -> None:
    """Failure fetching one fund logs a warning and proceeds with remaining funds."""
    def _flaky_get(url, *args, **kwargs):
        if "symbol=ARKK" in url:
            raise requests.RequestException("ARKK endpoint timeout")
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {
            "trades": [_trade(ticker="COIN", fund="ARKW", direction="Buy")]
        }
        return resp

    mock_get.side_effect = _flaky_get
    pg = MagicMock()
    pg.execute_query.return_value = []

    stats = record_ark_stances(pg, pause_seconds=0, funds=("ARKK", "ARKW"))

    assert stats["api_errors"] == 1
    assert stats["trades_fetched"] == 1
    assert stats["candidates"] == 1
    assert stats["stances_written"] == 1
    assert mock_record.call_count == 1
    assert mock_record.call_args.kwargs["ticker"] == "COIN"


@patch("web_dashboard.ark_stance_service.record_stance_safe")
@patch("requests.get")
def test_dry_run_writes_nothing(mock_get: MagicMock, mock_record: MagicMock) -> None:
    """dry_run=True computes candidates and throttle without writing to stance_history."""
    mock_get.side_effect = _mock_api({
        "ARKK": [_trade(ticker="TSLA", direction="Buy")]
    })
    pg = MagicMock()
    pg.execute_query.return_value = []

    stats = record_ark_stances(pg, dry_run=True, pause_seconds=0, funds=("ARKK",))

    assert stats["candidates"] == 1
    assert stats["stances_written"] == 0
    mock_record.assert_not_called()
