from __future__ import annotations

import os
import sys
from unittest.mock import patch

import pandas as pd


sys.path.append(
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "web_dashboard"))
)

from flask_data_utils import calculate_portfolio_value_over_time_flask


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
    table_rows = {
        "performance_metrics": [
            {
                "date": "2026-05-05",
                "total_value": 100.0,
                "cost_basis": 90.0,
                "unrealized_pnl": 10.0,
                "fund": "Project Chimera",
            },
            {
                "date": "2026-05-07",
                "total_value": 120.0,
                "cost_basis": 90.0,
                "unrealized_pnl": 30.0,
                "fund": "Project Chimera",
            },
        ],
        "portfolio_positions": [
            {
                "date": "2026-05-06T20:05:00+00:00",
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
                "date": "2026-05-06T20:05:00+00:00",
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
    assert "2026-05-05" in result_dates
    assert "2026-05-06" in result_dates
    assert "2026-05-07" in result_dates

    may_6_value = float(result.loc[pd.to_datetime(result["date"]).dt.date == pd.Timestamp("2026-05-06").date(), "value"].iloc[0])
    assert may_6_value == 125.0
