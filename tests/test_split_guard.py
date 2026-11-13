"""Unit tests for web_dashboard/split_guard.py planning logic. No DB or network."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "web_dashboard"))

from split_guard import (  # noqa: E402
    ambiguous_trades,
    candidate_splits,
    find_cliff,
    held_tickers,
    is_split_sized,
    plan_split,
    trade_et_date,
)
from utils.trade_reason import is_trade_sell  # noqa: E402

D = date.fromisoformat

# Stored portfolio_positions prices, as they were in prod.
ITA_ROWS = [
    (D("2026-10-30"), 209.74),
    (D("2026-11-02"), 214.68),
    (D("2026-11-03"), 216.17),
    (D("2026-11-04"), 212.84),
    (D("2026-11-05"), 68.11),
    (D("2026-11-06"), 68.98),
    (D("2026-11-09"), 71.67),
]
# CRWD: Yahoo stamps 2026-07-02, but our stored cliff is on 07-01.
CRWD_ROWS = [
    (D("2026-06-29"), 747.51),
    (D("2026-06-30"), 763.14),
    (D("2026-07-01"), 193.18),
    (D("2026-07-02"), 193.98),
    (D("2026-07-06"), 199.38),
]
ITA_TRADES = [
    {"ticker": "ITA", "date": "2025-09-02T22:26:57+00:00", "action": "BUY", "shares": 0.451633, "price": 198.58},
    {"ticker": "ITA", "date": "2025-09-16T20:00:00+00:00", "action": "DIVIDEND", "reason": "DRIP", "shares": 0.001678, "price": 201.89},
    {"ticker": "ITA", "date": "2026-09-15T20:00:00+00:00", "action": "DIVIDEND", "reason": "DRIP", "shares": 0.000452, "price": 214.0},
]


def test_split_sized_rejects_spinoffs_and_stock_dividends() -> None:
    assert is_split_sized(3.0) and is_split_sized(4.0) and is_split_sized(1.5)
    assert is_split_sized(0.1)  # 1:10 reverse split
    assert not is_split_sized(1.057)  # SPGI spin-off
    assert not is_split_sized(0.888)  # UL spin-off
    assert not is_split_sized(1.05)  # stock dividend
    assert not is_split_sized(0)


def test_trade_et_date_uses_new_york_calendar() -> None:
    # 02:00 UTC on the 3rd is still the 2nd in New York.
    assert trade_et_date("2025-09-03T02:00:00+00:00") == D("2025-09-02")
    assert trade_et_date("2025-09-02T22:26:57+00:00") == D("2025-09-02")


def test_find_cliff_ita_on_ex_date() -> None:
    assert find_cliff(ITA_ROWS, D("2026-11-05"), 3.0) == D("2026-11-05")


def test_find_cliff_crwd_one_row_before_yahoo_stamp() -> None:
    assert find_cliff(CRWD_ROWS, D("2026-07-02"), 4.0) == D("2026-07-01")


def test_find_cliff_wrong_ratio_does_not_match() -> None:
    assert find_cliff(ITA_ROWS, D("2026-11-05"), 2.0) is None


def test_find_cliff_none_before_post_split_row_exists() -> None:
    pre_only = [r for r in ITA_ROWS if r[0] < D("2026-11-05")]
    assert find_cliff(pre_only, D("2026-11-05"), 3.0) is None


def test_find_cliff_ignores_later_moves_of_split_size() -> None:
    # Back-adjusted history (no cliff at the ex-date), then an unrelated crash much later.
    rows = [(D(f"2026-11-{d:02d}"), 70.0) for d in range(2, 13)]
    rows.append((D("2026-11-20"), 23.0))
    assert find_cliff(rows, D("2026-11-05"), 3.0) is None


def test_find_cliff_reverse_split() -> None:
    rows = [(D("2026-03-02"), 1.0), (D("2026-03-03"), 1.02), (D("2026-03-04"), 10.3)]
    assert find_cliff(rows, D("2026-03-04"), 0.1) == D("2026-03-04")


def test_held_tickers_counts_drip_and_drops_closed() -> None:
    trades = ITA_TRADES + [
        {"ticker": "XYZ", "date": "2025-01-02T15:00:00+00:00", "action": "BUY", "shares": 5, "price": 10},
        {"ticker": "XYZ", "date": "2025-02-02T15:00:00+00:00", "action": "SELL", "shares": 5, "price": 12},
    ]
    assert held_tickers(trades, is_trade_sell) == {"ITA": D("2025-09-02")}


def test_candidate_splits_filters_ledger_and_pre_ownership() -> None:
    splits = {D("2020-12-07"): 2.0, D("2026-07-01"): 1.057, D("2026-08-11"): 2.0, D("2026-11-05"): 3.0}
    got = candidate_splits(splits, D("2025-09-02"), already_recorded={D("2026-08-11")})
    assert got == [(D("2026-11-05"), 3.0)]


def test_plan_ita_applies_to_all_three_trades() -> None:
    plan = plan_split(
        fund="TFSA", ticker="ITA", ex_date=D("2026-11-05"), ratio=3.0,
        trades=ITA_TRADES, price_rows=ITA_ROWS, today=D("2026-11-13"),
    )
    assert plan.status == "apply"
    assert plan.cliff_date == D("2026-11-05")
    assert len(plan.trades_before_cliff) == 3
    assert plan.positions_from_cliff == 3


def test_plan_waits_on_ex_date_before_post_split_row() -> None:
    plan = plan_split(
        fund="TFSA", ticker="ITA", ex_date=D("2026-11-05"), ratio=3.0, trades=ITA_TRADES,
        price_rows=[r for r in ITA_ROWS if r[0] < D("2026-11-05")], today=D("2026-11-05"),
    )
    assert plan.status == "wait"


def test_plan_unconfirmed_when_old_and_no_cliff() -> None:
    flat = [(D(f"2026-11-{d:02d}"), 70.0) for d in range(2, 13)]
    plan = plan_split(
        fund="TFSA", ticker="ITA", ex_date=D("2026-11-05"), ratio=3.0,
        trades=ITA_TRADES, price_rows=flat, today=D("2026-11-20"),
    )
    assert plan.status == "unconfirmed"


def test_plan_refuses_trade_between_cliff_and_ex_date() -> None:
    trades = [
        {"ticker": "CRWD", "date": "2025-09-10T13:30:00+00:00", "action": "BUY", "shares": 0.7261, "price": 427.93},
        {"ticker": "CRWD", "date": "2026-07-01T15:00:00+00:00", "action": "BUY", "shares": 1, "price": 193.0},
    ]
    assert len(ambiguous_trades(trades, D("2026-07-02"), D("2026-07-01"))) == 1
    plan = plan_split(
        fund="Project Chimera", ticker="CRWD", ex_date=D("2026-07-02"), ratio=4.0,
        trades=trades, price_rows=CRWD_ROWS, today=D("2026-11-13"),
    )
    assert plan.status == "ambiguous"


def test_plan_trade_on_cliff_day_is_post_split_when_dates_agree() -> None:
    trades = ITA_TRADES + [
        {"ticker": "ITA", "date": "2026-11-05T18:00:00+00:00", "action": "BUY", "shares": 3, "price": 68.5},
    ]
    plan = plan_split(
        fund="TFSA", ticker="ITA", ex_date=D("2026-11-05"), ratio=3.0,
        trades=trades, price_rows=ITA_ROWS, today=D("2026-11-13"),
    )
    assert plan.status == "apply"
    assert len(plan.trades_before_cliff) == 3  # the 11-05 buy is left alone
