"""Tests for shares-outstanding dilution detection (ROADMAP G3)."""

from datetime import date
from unittest.mock import MagicMock

from web_dashboard.dilution_service import (
    compute_dilution_observations,
    fetch_recent_dilution_flags,
)

AS_OF = date(2026, 6, 14)


def _obs_by_window(observations):
    return {o["window_days"]: o for o in observations}


def test_dilution_flagged_above_threshold():
    # +60% YoY clears 365d (20%); the recent leg clears 90d (10%) too.
    history = {
        "GLO.TO": [("2025-07-01", 100.0), ("2026-03-20", 130.0), ("2026-05-01", 160.0)]
    }
    obs = _obs_by_window(compute_dilution_observations(history, as_of=AS_OF))

    assert obs[365]["pct_change"] == 60.0
    assert obs[365]["flagged"] is True
    assert obs[365]["shares_start"] == 100.0
    assert obs[365]["shares_end"] == 160.0
    assert obs[90]["flagged"] is True  # 130 -> 160 = +23%


def test_small_growth_not_flagged():
    history = {"DRX.TO": [("2026-03-20", 1000.0), ("2026-05-01", 1001.0)]}
    obs = _obs_by_window(compute_dilution_observations(history, as_of=AS_OF))

    assert obs[90]["pct_change"] == 0.1
    assert obs[90]["flagged"] is False


def test_buyback_negative_change_not_flagged():
    history = {"CCO.TO": [("2026-03-20", 1000.0), ("2026-05-01", 989.0)]}
    obs = _obs_by_window(compute_dilution_observations(history, as_of=AS_OF))

    assert obs[90]["pct_change"] == -1.1
    assert obs[90]["flagged"] is False


def test_window_with_too_few_points_is_skipped():
    # Only one reading falls inside either window -> nothing trustworthy to compute.
    history = {"X": [("2025-01-01", 100.0), ("2026-05-01", 150.0)]}
    assert compute_dilution_observations(history, as_of=AS_OF) == []


def test_baseline_is_earliest_point_in_window_not_oldest_overall():
    # A pre-window reading (2025-01-01, before the 365d cutoff) must NOT be the baseline.
    history = {
        "Y": [
            ("2025-01-01", 10.0),   # before both window cutoffs
            ("2026-03-20", 200.0),  # 90d baseline
            ("2026-05-01", 220.0),
        ]
    }
    obs = _obs_by_window(compute_dilution_observations(history, as_of=AS_OF))
    # 90d: baseline 200 -> 220 = +10% (not 2100% off the Jan-2025 reading)
    assert obs[90]["shares_start"] == 200.0
    assert obs[90]["pct_change"] == 10.0


def test_custom_thresholds_and_empty_history():
    history = {"Z": [("2026-03-20", 100.0), ("2026-05-01", 108.0)]}
    obs = _obs_by_window(
        compute_dilution_observations(history, as_of=AS_OF, thresholds={90: 5.0, 365: 5.0})
    )
    assert obs[90]["flagged"] is True  # +8% > 5%
    assert compute_dilution_observations({}, as_of=AS_OF) == []
    assert compute_dilution_observations({"E": []}, as_of=AS_OF) == []


def test_fetch_recent_dilution_flags_passes_ticker_filter():
    pg = MagicMock()
    pg.execute_query.return_value = [{"ticker": "GLO.TO", "pct_change": 48.9}]

    rows = fetch_recent_dilution_flags(pg, tickers=["glo.to", "ganx"], days=30, limit=10)

    assert rows[0]["ticker"] == "GLO.TO"
    sql, params = pg.execute_query.call_args[0]
    assert "ticker = ANY(%s)" in sql
    # params: (days, [UPPER tickers], limit)
    assert params[0] == 30
    assert params[1] == ["GLO.TO", "GANX"]
    assert params[2] == 10


def test_fetch_recent_dilution_flags_no_ticker_filter():
    pg = MagicMock()
    pg.execute_query.return_value = []

    fetch_recent_dilution_flags(pg, days=45, limit=20)

    sql, params = pg.execute_query.call_args[0]
    assert "ticker = ANY" not in sql
    assert params == (45, 20)


def test_fetch_recent_dilution_flags_swallows_missing_table():
    pg = MagicMock()
    pg.execute_query.side_effect = Exception('relation "dilution_observations" does not exist')
    assert fetch_recent_dilution_flags(pg) == []
