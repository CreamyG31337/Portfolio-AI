"""Fail-first unit tests for rebuild_fund_from_date (F1–F6).

These MUST fail against the unfixed rebuild_from_date.py and pass after fixes.
No real DB or network access — all dependencies are mocked.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from web_dashboard.utils.rebuild_from_date import rebuild_fund_from_date

FUND = "TEST Rebuild Mock"
RANGE_START = date(2026, 1, 5)
FROZEN_TODAY = date(2026, 1, 16)
ET = ZoneInfo("America/New_York")


@dataclass
class FakeTrade:
    timestamp: datetime
    ticker: str
    shares: Decimal
    price: Decimal
    action: str
    reason: str
    currency: str = "USD"


def _et(d: date, hour: int = 10) -> datetime:
    return datetime(d.year, d.month, d.day, hour, 0, 0, tzinfo=ET)


def _weekdays(start: date, end: date) -> list[date]:
    out: list[date] = []
    cur = start
    while cur <= end:
        if cur.weekday() < 5:
            out.append(cur)
        cur += timedelta(days=1)
    return out


def _is_weekday(d: date) -> bool:
    return d.weekday() < 5


def _price_df(closes: dict[date, float]) -> pd.DataFrame:
    idx = pd.DatetimeIndex(
        [datetime.combine(d, datetime.min.time()) for d in sorted(closes)]
    )
    return pd.DataFrame(
        {"Close": [closes[d] for d in sorted(closes)]},
        index=idx,
    )


@pytest.fixture
def trading_days() -> list[date]:
    return _weekdays(RANGE_START, FROZEN_TODAY)


@pytest.fixture
def rebuild_harness():
    """Patch in-function imports; freeze today to FROZEN_TODAY."""
    real_datetime = datetime

    class FrozenDateTime(real_datetime):
        @classmethod
        def now(cls, tz: Any = None) -> datetime:
            base = real_datetime(
                FROZEN_TODAY.year, FROZEN_TODAY.month, FROZEN_TODAY.day, 17, 0, 0
            )
            if tz is not None:
                return base.replace(tzinfo=tz)
            return base

    mock_supabase = MagicMock(name="SupabaseClient")
    sb = MagicMock(name="supabase")
    mock_supabase.supabase = sb

    deleted_tables: list[str] = []
    funds_row = {"fund_type": "rrsp", "dividend_mode": "cash"}

    def table_side_effect(name: str) -> MagicMock:
        table = MagicMock(name=f"table:{name}")
        if name == "funds":
            table.select.return_value.eq.return_value.limit.return_value.execute.return_value = (
                MagicMock(data=[funds_row])
            )
        # Count queries for dry-run / day-loss messaging
        table.select.return_value.eq.return_value.gte.return_value.execute.return_value = (
            MagicMock(data=[{"count": 0}], count=0)
        )
        delete_result = MagicMock(data=[])

        def tracked_delete(*_a: Any, **_k: Any) -> MagicMock:
            deleted_tables.append(name)
            chain = MagicMock()
            chain.eq.return_value.gte.return_value.execute.return_value = delete_result
            return chain

        table.delete = tracked_delete
        table.update.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
        return table

    sb.table.side_effect = table_side_effect

    mock_repo = MagicMock(name="SupabaseRepository")
    mock_repo.get_trade_history.return_value = []
    mock_repo.save_portfolio_snapshot = MagicMock()

    mock_fetcher = MagicMock(name="MarketDataFetcher")
    empty = MagicMock()
    empty.df = pd.DataFrame()
    mock_fetcher.fetch_price_data.return_value = empty

    mock_market_hours = MagicMock(name="MarketHours")
    mock_market_hours.is_trading_day.side_effect = _is_weekday

    def set_prices(by_ticker: dict[str, dict[date, float]]) -> None:
        def _fetch(ticker: str, start: Any = None, end: Any = None) -> MagicMock:
            result = MagicMock()
            closes = by_ticker.get(ticker, {})
            result.df = _price_df(closes) if closes else pd.DataFrame()
            return result

        mock_fetcher.fetch_price_data.side_effect = _fetch

    def set_dividend_mode(mode: str, fund_type: str = "rrsp") -> None:
        funds_row["dividend_mode"] = mode
        funds_row["fund_type"] = fund_type

    patches = [
        patch("web_dashboard.supabase_client.SupabaseClient", return_value=mock_supabase),
        patch(
            "data.repositories.supabase_repository.SupabaseRepository",
            return_value=mock_repo,
        ),
        patch("market_data.data_fetcher.MarketDataFetcher", return_value=mock_fetcher),
        patch("market_data.market_hours.MarketHours", return_value=mock_market_hours),
        patch("utils.timezone_utils.get_trading_timezone", return_value=ET),
        patch("scheduler.jobs_metrics.populate_performance_metrics_job", return_value=None),
        patch("cache_version.bump_cache_version", return_value=None),
        patch("web_dashboard.utils.rebuild_from_date.datetime", FrozenDateTime),
        patch(
            "web_dashboard.utils.rebuild_from_date._check_job_cancelled",
            return_value=False,
        ),
        patch("web_dashboard.utils.rebuild_from_date._update_job_status"),
    ]
    started = [p.start() for p in patches]
    mock_update_status = started[-1]

    harness = {
        "repo": mock_repo,
        "deleted_tables": deleted_tables,
        "update_job_status": mock_update_status,
        "set_trades": lambda trades: setattr(
            mock_repo, "get_trade_history", MagicMock(return_value=list(trades))
        )
        or mock_repo.get_trade_history,  # noqa: B018 — keep setattr pattern clear
        "set_prices": set_prices,
        "set_dividend_mode": set_dividend_mode,
        "saved_snapshots": lambda: list(mock_repo.save_portfolio_snapshot.call_args_list),
    }

    # Fix set_trades to be a proper function
    def _set_trades(trades: list[FakeTrade]) -> None:
        mock_repo.get_trade_history.return_value = list(trades)

    harness["set_trades"] = _set_trades

    try:
        yield harness
    finally:
        for p in patches:
            p.stop()


def _positions_by_date(save_calls: list) -> dict[date, dict[str, Decimal]]:
    out: dict[date, dict[str, Decimal]] = {}
    for c in save_calls:
        snap = c.args[0]
        d = snap.timestamp.date()
        out[d] = {p.ticker: Decimal(str(p.shares)) for p in snap.positions}
    return out


def _prices_by_date(save_calls: list) -> dict[date, dict[str, Decimal]]:
    out: dict[date, dict[str, Decimal]] = {}
    for c in save_calls:
        snap = c.args[0]
        d = snap.timestamp.date()
        out[d] = {
            p.ticker: Decimal(str(p.current_price))
            for p in snap.positions
            if p.current_price is not None
        }
    return out


def test_sparse_trade_dates_write_all_trading_day_snapshots(
    rebuild_harness: dict,
    trading_days: list[date],
) -> None:
    """F2: trades on 2 days inside a 10-weekday range → 10 snapshots."""
    h = rebuild_harness
    day_a, day_b = trading_days[0], trading_days[4]
    h["set_trades"](
        [
            FakeTrade(_et(day_a), "AAA", Decimal("10"), Decimal("5"), "BUY", "entry"),
            FakeTrade(_et(day_b), "AAA", Decimal("2"), Decimal("6"), "BUY", "add"),
        ]
    )
    h["set_prices"]({"AAA": {d: 10.0 + i * 0.1 for i, d in enumerate(trading_days)}})

    result = rebuild_fund_from_date(FUND, RANGE_START)

    assert result["success"] is True
    by_date = _positions_by_date(h["saved_snapshots"]())
    assert len(by_date) == len(trading_days), (
        f"expected {len(trading_days)} trading-day snapshots, got {len(by_date)}: "
        f"{sorted(by_date)}"
    )
    assert set(by_date) == set(trading_days)


def test_historical_share_counts_are_not_aliased_to_final(
    rebuild_harness: dict,
    trading_days: list[date],
) -> None:
    """F3: buy 26 day1, sell 13 day5 → day3=26, day7=13."""
    h = rebuild_harness
    d1, d5, d3, d7 = trading_days[0], trading_days[4], trading_days[2], trading_days[6]
    h["set_trades"](
        [
            FakeTrade(_et(d1), "MNST", Decimal("26"), Decimal("50"), "BUY", "open"),
            FakeTrade(_et(d5), "MNST", Decimal("13"), Decimal("60"), "SELL", "trim"),
        ]
    )
    h["set_prices"]({"MNST": {d: 55.0 for d in trading_days}})

    result = rebuild_fund_from_date(FUND, RANGE_START)

    assert result["success"] is True
    by_date = _positions_by_date(h["saved_snapshots"]())
    assert d3 in by_date and by_date[d3]["MNST"] == Decimal("26")
    assert d7 in by_date and by_date[d7]["MNST"] == Decimal("13")


def test_dividend_word_in_buy_reason_is_not_skipped(
    rebuild_harness: dict,
    trading_days: list[date],
) -> None:
    """F4: cash fund keeps action=BUY even when reason mentions dividends."""
    h = rebuild_harness
    h["set_dividend_mode"]("cash", fund_type="rrsp")
    d0 = trading_days[0]
    h["set_trades"](
        [
            FakeTrade(
                _et(d0),
                "PEP",
                Decimal("6"),
                Decimal("148.99"),
                "BUY",
                "decades of dividend growth and stable cash flows",
            ),
        ]
    )
    h["set_prices"]({"PEP": {d: 150.0 for d in trading_days}})

    result = rebuild_fund_from_date(FUND, RANGE_START)

    assert result["success"] is True
    by_date = _positions_by_date(h["saved_snapshots"]())
    last = by_date[trading_days[-1]]
    assert "PEP" in last
    assert last["PEP"] == Decimal("6")


def test_mislabeled_dividend_action_is_still_skipped(
    rebuild_harness: dict,
    trading_days: list[date],
) -> None:
    """F4: action=DIVIDEND is skipped (documents Phase 4.3 data repair need).

    Reason deliberately avoids \\b(drip|dividend)\\b so the old reason-filter
    would KEEP this row — only action-based skip removes it.
    """
    h = rebuild_harness
    h["set_dividend_mode"]("cash", fund_type="rrsp")
    d0 = trading_days[0]
    h["set_trades"](
        [
            FakeTrade(
                _et(d0),
                "KO",
                Decimal("24"),
                Decimal("68.97"),
                "DIVIDEND",
                "reinvested cash distribution from holdings",
            ),
        ]
    )
    h["set_prices"]({"KO": {d: 70.0 for d in trading_days}})

    result = rebuild_fund_from_date(FUND, RANGE_START)

    assert result["success"] is True
    by_date = _positions_by_date(h["saved_snapshots"]())
    for d, positions in by_date.items():
        assert "KO" not in positions, f"KO should be skipped on {d}, got {positions}"


def test_job_id_path_emits_step4_status_without_nameerror(
    rebuild_harness: dict,
    trading_days: list[date],
) -> None:
    """F1: job_id path must not NameError on Step 4 status update."""
    h = rebuild_harness
    d0 = trading_days[0]
    h["set_trades"](
        [FakeTrade(_et(d0), "AAA", Decimal("1"), Decimal("10"), "BUY", "open")]
    )
    h["set_prices"]({"AAA": {d: 11.0 for d in trading_days}})

    result = rebuild_fund_from_date(FUND, RANGE_START, job_id="123")

    assert result["success"] is True, result.get("message")
    assert "NameError" not in str(result.get("message", ""))
    status_messages = [
        c.args[2] if len(c.args) >= 3 else c.kwargs.get("message", "")
        for c in h["update_job_status"].call_args_list
    ]
    assert any(
        "Step 4" in str(m) and "ticker" in str(m).lower() for m in status_messages
    ), f"expected Step 4 ticker status update, got: {status_messages}"


def test_missing_price_carries_forward_or_skips_entire_day(
    rebuild_harness: dict,
    trading_days: list[date],
) -> None:
    """F5: gap day carries prior close; never-priced held ticker skips the day."""
    h = rebuild_harness
    d0, d1, d2 = trading_days[0], trading_days[1], trading_days[2]

    h["set_trades"](
        [FakeTrade(_et(d0), "AAA", Decimal("10"), Decimal("5"), "BUY", "open")]
    )
    h["set_prices"]({"AAA": {d0: 10.0, d1: 11.0}})  # d2 absent

    result_dry = rebuild_fund_from_date(FUND, RANGE_START, dry_run=True)
    assert result_dry["success"] is True
    assert "Price carry-forwards:" in result_dry["message"]
    assert "AAA" in result_dry["message"]
    assert f"{d2}←{d1}" in result_dry["message"]

    result_a = rebuild_fund_from_date(FUND, RANGE_START)
    assert result_a["success"] is True
    prices_a = _prices_by_date(h["saved_snapshots"]())
    assert d2 in prices_a, "day with gap must still be written via carry-forward"
    assert prices_a[d2]["AAA"] == Decimal("11.0")

    h["repo"].save_portfolio_snapshot.reset_mock()
    h["deleted_tables"].clear()
    h["set_trades"](
        [FakeTrade(_et(d0), "BBB", Decimal("3"), Decimal("20"), "BUY", "open")]
    )
    h["set_prices"]({})

    result_b = rebuild_fund_from_date(FUND, RANGE_START)
    assert result_b["success"] is True or result_b["success"] is False
    assert h["saved_snapshots"]() == [], (
        "held ticker with no price ever must not produce partial-day snapshots; "
        f"got {len(h['saved_snapshots']())} saves"
    )


def test_day_loss_guard_aborts_without_deleting(
    rebuild_harness: dict,
    trading_days: list[date],
) -> None:
    """F6: would-write fewer days than span → abort before deletes."""
    h = rebuild_harness
    d0 = trading_days[0]
    h["set_trades"](
        [FakeTrade(_et(d0), "ZZZ", Decimal("1"), Decimal("9"), "BUY", "open")]
    )
    h["set_prices"]({})  # 0 writable days under F5

    result = rebuild_fund_from_date(
        FUND,
        RANGE_START,
        dry_run=False,
        allow_day_loss=False,
    )

    assert result["success"] is False
    assert h["deleted_tables"] == [], (
        f"day-loss guard must abort before deletes; deleted={h['deleted_tables']}"
    )
    msg = str(result.get("message", "")).lower()
    assert "day" in msg and (
        "loss" in msg or "fewer" in msg or "abort" in msg or "lost" in msg
    ), msg

    h["deleted_tables"].clear()
    h["repo"].save_portfolio_snapshot.reset_mock()
    result_override = rebuild_fund_from_date(
        FUND,
        RANGE_START,
        dry_run=True,
        allow_day_loss=True,
    )
    assert h["deleted_tables"] == []
    assert h["saved_snapshots"]() == []
    assert result_override.get("dry_run") is True or "dry" in str(
        result_override.get("message", "")
    ).lower()


def test_pre_window_trades_seed_fifo_state(
    rebuild_harness: dict,
    trading_days: list[date],
) -> None:
    """F2 seeding: buy before start_date must appear in every rebuilt snapshot.

    CURRENT (broken rewrite): accumulator starts empty at start_date → ticker
    missing from all snapshots (FAIL).
    FIXED: seed FIFO with trades dated before start_date (PASS).
    """
    h = rebuild_harness
    pre_window = RANGE_START - timedelta(days=1)  # 2026-01-04 (Sunday)
    # Use Friday before the window so the buy is a real calendar date with
    # an unambiguous "before start_date" ordering.
    while pre_window.weekday() >= 5:
        pre_window -= timedelta(days=1)

    h["set_trades"](
        [
            FakeTrade(
                _et(pre_window),
                "FTS.TO",
                Decimal("47"),
                Decimal("70.00"),
                "BUY",
                "utility with decades of dividend growth",
            ),
        ]
    )
    h["set_prices"]({"FTS.TO": {d: 78.0 for d in trading_days}})

    result = rebuild_fund_from_date(FUND, RANGE_START)

    assert result["success"] is True, result.get("message")
    by_date = _positions_by_date(h["saved_snapshots"]())
    assert len(by_date) == len(trading_days), (
        f"expected {len(trading_days)} snapshots, got {len(by_date)}: {sorted(by_date)}"
    )
    for d in trading_days:
        assert d in by_date, f"missing snapshot for {d}"
        assert "FTS.TO" in by_date[d], f"FTS.TO missing on {d} — pre-window seed dropped"
        assert by_date[d]["FTS.TO"] == Decimal("47")

        # Cost basis must also survive seeding (47 * 70 = 3290)
    for c in h["saved_snapshots"]():
        snap = c.args[0]
        pos = next(p for p in snap.positions if p.ticker == "FTS.TO")
        assert pos.cost_basis == Decimal("3290.00") or pos.cost_basis == Decimal("3290")


def test_off_calendar_dividend_applies_on_next_trading_day(
    rebuild_harness: dict,
    trading_days: list[date],
) -> None:
    """Off-calendar trades use <= cursor: Sunday DRIP appears from next weekday.

    CURRENT (date equality): Sunday DIVIDEND never matches a trading_day → share
    count stays at pre-DRIP forever (FAIL).
    FIXED (advancing cursor): absent before Sunday, present from next trading day.
    """
    h = rebuild_harness
    # TFSA-style reinvest: DIVIDEND rows must add shares
    h["set_dividend_mode"]("reinvest", fund_type="tfsa")

    # trading_days[0]=Mon Jan 5 ... trading_days[4]=Fri Jan 9, then Mon Jan 12
    buy_day = trading_days[0]
    friday = trading_days[4]
    sunday = friday + timedelta(days=2)
    assert sunday.weekday() == 6
    next_monday = trading_days[5]
    assert next_monday == sunday + timedelta(days=1)

    h["set_trades"](
        [
            FakeTrade(
                _et(buy_day),
                "AOS",
                Decimal("10"),
                Decimal("66.00"),
                "BUY",
                "initial",
            ),
            FakeTrade(
                _et(sunday),
                "AOS",
                Decimal("0.5"),
                Decimal("66.88"),
                "DIVIDEND",
                "DRIP",
            ),
        ]
    )
    h["set_prices"]({"AOS": {d: 70.0 for d in trading_days}})

    result = rebuild_fund_from_date(FUND, RANGE_START)

    assert result["success"] is True, result.get("message")
    by_date = _positions_by_date(h["saved_snapshots"]())

    # Saturday-side (weekdays up through Friday before the Sunday): no DRIP yet
    for d in trading_days:
        if d <= friday:
            assert by_date[d]["AOS"] == Decimal("10"), (
                f"pre-Sunday {d} should be 10, got {by_date[d]['AOS']}"
            )
        else:
            assert by_date[d]["AOS"] == Decimal("10.5"), (
                f"from {next_monday} onward should include Sunday DRIP; "
                f"{d} has {by_date[d]['AOS']}"
            )
