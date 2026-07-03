from __future__ import annotations

import os
import sys
from datetime import date, timedelta
from unittest.mock import patch

import pandas as pd


sys.path.append(
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "web_dashboard"))
)

from flask_data_utils import calculate_portfolio_value_over_time_flask


def _recent_trading_triple() -> tuple[date, date, date]:
    """Three consecutive past trading days within the function's days=30 window.

    The test seeds metrics on the outer two days and expects the middle day to be
    gap-filled, so all three must be trading days. Dates are computed relative to
    today: hardcoded dates silently age out of the 30-day query window and the
    test starts failing a month after it was written.
    """
    try:
        from utils.market_holidays import MarketHolidays
        market_holidays = MarketHolidays()
        def is_trading(d: date) -> bool:
            return market_holidays.is_trading_day(d, market="any")
    except Exception:
        def is_trading(d: date) -> bool:
            return d.weekday() < 5

    # Most recent Wednesday that ended at least two days ago, then walk back
    # week by week if any of Tue/Wed/Thu falls on a holiday.
    anchor = date.today() - timedelta(days=2)
    while anchor.weekday() != 2:
        anchor -= timedelta(days=1)
    for _ in range(3):
        tue, wed, thu = anchor - timedelta(days=1), anchor, anchor + timedelta(days=1)
        if all(is_trading(d) for d in (tue, wed, thu)):
            return tue, wed, thu
        anchor -= timedelta(days=7)
    return tue, wed, thu


class _Query:
    def __init__(self, table_name: str, table_rows: dict[str, list[dict]]):
        self._table_name = table_name
        self._table_rows = table_rows
        self._filters: list[tuple[str, str, object]] = []

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, field, value):
        self._filters.append(("eq", field, value))
        return self

    def gte(self, field, value):
        self._filters.append(("gte", field, value))
        return self

    def lt(self, field, value):
        self._filters.append(("lt", field, value))
        return self

    def order(self, *_args, **_kwargs):
        return self

    def range(self, *_args, **_kwargs):
        return self

    def execute(self):
        rows = list(self._table_rows.get(self._table_name, []))
        for op, field, value in self._filters:
            if op == "eq":
                rows = [r for r in rows if r.get(field) == value]
            elif op == "gte":
                rows = [r for r in rows if str(r.get(field)) >= str(value)]
            elif op == "lt":
                rows = [r for r in rows if str(r.get(field)) < str(value)]
        return type("Result", (), {"data": rows})()


class _SupabaseFacade:
    def __init__(self, table_rows: dict[str, list[dict]]):
        self._table_rows = table_rows
        self.supabase = self

    def table(self, name: str):
        return _Query(name, self._table_rows)


def test_performance_metrics_gap_is_filled_from_positions():
    day_before, gap_day, day_after = _recent_trading_triple()
    table_rows = {
        "performance_metrics": [
            {
                "date": day_before.isoformat(),
                "total_value": 100.0,
                "cost_basis": 90.0,
                "unrealized_pnl": 10.0,
                "fund": "Project Chimera",
            },
            {
                "date": day_after.isoformat(),
                "total_value": 120.0,
                "cost_basis": 90.0,
                "unrealized_pnl": 30.0,
                "fund": "Project Chimera",
            },
        ],
        "portfolio_positions": [
            {
                "date": f"{gap_day.isoformat()}T20:05:00+00:00",
                "total_value": 0.0,
                "cost_basis": 0.0,
                "pnl": 0.0,
                "fund": "Project Chimera",
                "currency": "CAD",
                "total_value_base": 110.0,
                "cost_basis_base": 90.0,
                "pnl_base": 20.0,
                "base_currency": "CAD",
            },
            {
                "date": f"{gap_day.isoformat()}T20:05:00+00:00",
                "total_value": 0.0,
                "cost_basis": 0.0,
                "pnl": 0.0,
                "fund": "Project Chimera",
                "currency": "CAD",
                "total_value_base": 15.0,
                "cost_basis_base": 10.0,
                "pnl_base": 5.0,
                "base_currency": "CAD",
            },
        ],
    }

    with patch(
        "flask_data_utils.get_supabase_client_flask",
        return_value=_SupabaseFacade(table_rows),
    ), patch(
        "flask_data_utils.get_current_positions_flask",
        return_value=pd.DataFrame(),
    ), patch(
        "cache_version.get_cache_version",
        return_value="v-test-gap-fill",
    ):
        result = calculate_portfolio_value_over_time_flask(
            fund="Project Chimera",
            days=30,
            _cache_version="v-test-gap-fill",
        )

    assert not result.empty
    result_dates = [d.date().isoformat() for d in pd.to_datetime(result["date"])]
    assert day_before.isoformat() in result_dates
    assert gap_day.isoformat() in result_dates
    assert day_after.isoformat() in result_dates

    gap_day_value = float(result.loc[pd.to_datetime(result["date"]).dt.date == gap_day, "value"].iloc[0])
    assert gap_day_value == 125.0


def test_trailing_session_included_on_us_only_holiday():
    """When US markets are closed but TSX is open, include the session from positions."""
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo

    last_session = date(2026, 7, 2)
    canadian_session = date(2026, 7, 3)  # US Independence Day observed; TSX open

    table_rows = {
        "performance_metrics": [
            {
                "date": last_session.isoformat(),
                "total_value": 100.0,
                "cost_basis": 90.0,
                "unrealized_pnl": 10.0,
                "fund": "Project Chimera",
            },
        ],
        "portfolio_positions": [
            {
                "date": f"{canadian_session.isoformat()}T20:05:00+00:00",
                "total_value": 0.0,
                "cost_basis": 0.0,
                "pnl": 0.0,
                "fund": "Project Chimera",
                "currency": "CAD",
                "total_value_base": 105.0,
                "cost_basis_base": 90.0,
                "pnl_base": 15.0,
                "base_currency": "CAD",
            },
        ],
    }

    toronto_now = datetime(2026, 7, 3, 14, 0, tzinfo=ZoneInfo("America/Toronto"))

    def fake_now(tz=None):
        if tz is not None:
            tz_key = getattr(tz, "key", str(tz))
            if "Toronto" in tz_key:
                return toronto_now
        return datetime.now(timezone.utc)

    with patch(
        "flask_data_utils.get_supabase_client_flask",
        return_value=_SupabaseFacade(table_rows),
    ), patch(
        "flask_data_utils.get_current_positions_flask",
        return_value=pd.DataFrame(),
    ), patch(
        "cache_version.get_cache_version",
        return_value="v-test-trailing-holiday",
    ), patch(
        "flask_data_utils.datetime"
    ) as mock_datetime:
        mock_datetime.now = fake_now
        mock_datetime.combine = datetime.combine
        mock_datetime.side_effect = lambda *args, **kwargs: datetime(*args, **kwargs)
        result = calculate_portfolio_value_over_time_flask(
            fund="Project Chimera",
            days=30,
            _cache_version="v-test-trailing-holiday",
        )

    assert not result.empty
    result_dates = {d.date() for d in pd.to_datetime(result["date"])}
    assert last_session in result_dates
    assert canadian_session in result_dates
    jul3_value = float(
        result.loc[pd.to_datetime(result["date"]).dt.date == canadian_session, "value"].iloc[0]
    )
    assert jul3_value == 105.0
