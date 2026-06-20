"""Tests for stance_outcomes scoring helpers."""

from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

from web_dashboard.scheduler.jobs_stance_outcomes import (
    compute_excess_return,
    score_stance_row,
    select_unscored_stances,
    _nearest_close_on_or_before,
)


def test_compute_excess_return_math() -> None:
    result = compute_excess_return(
        Decimal("100"),
        Decimal("110"),
        Decimal("200"),
        Decimal("204"),
    )
    assert result["ticker_return"] == Decimal("10")
    assert result["benchmark_return"] == Decimal("2")
    assert result["excess_return"] == Decimal("8")


def test_nearest_close_on_or_before() -> None:
    rows = [
        {"date": date(2026, 1, 1), "close": 10.0},
        {"date": date(2026, 1, 5), "close": 12.0},
        {"date": date(2026, 1, 10), "close": 11.0},
    ]
    assert _nearest_close_on_or_before(rows, date(2026, 1, 4)) == Decimal("10.0")
    assert _nearest_close_on_or_before(rows, date(2026, 1, 7)) == Decimal("12.0")


def test_select_unscored_stances_filters_risk_watch() -> None:
    pg = MagicMock()
    pg.execute_query.return_value = [
        {"id": "1", "ticker": "AAA", "stance": "BUY", "as_of": datetime.now(timezone.utc)},
        {"id": "2", "ticker": "BBB", "stance": "RISK", "as_of": datetime.now(timezone.utc)},
    ]
    rows = select_unscored_stances(
        pg,
        horizon_days=7,
        as_of_cutoff=datetime.now(timezone.utc),
    )
    assert len(rows) == 1
    assert rows[0]["stance"] == "BUY"


def test_score_stance_row_returns_payload() -> None:
    as_of = datetime(2026, 1, 1, tzinfo=timezone.utc)
    now = datetime(2026, 2, 1, tzinfo=timezone.utc)
    ticker_rows = [
        {"date": date(2026, 1, 1), "close": 100.0},
        {"date": date(2026, 1, 8), "close": 110.0},
    ]
    bench_rows = [
        {"date": date(2026, 1, 1), "close": 200.0},
        {"date": date(2026, 1, 8), "close": 210.0},
    ]
    payload = score_stance_row(
        {"id": "uuid-1", "ticker": "AAA", "stance": "BUY", "as_of": as_of, "price_at_stance": None},
        horizon_days=7,
        now=now,
        benchmark_rows=bench_rows,
        ticker_rows=ticker_rows,
    )
    assert payload is not None
    assert payload["horizon_days"] == 7
    assert payload["excess_return"] == Decimal("5")


def test_score_stance_row_skips_nan_prices() -> None:
    as_of = datetime(2026, 1, 1, tzinfo=timezone.utc)
    now = datetime(2026, 2, 1, tzinfo=timezone.utc)
    ticker_rows = [
        {"date": date(2026, 1, 1), "close": float("nan")},
        {"date": date(2026, 1, 8), "close": float("nan")},
    ]
    bench_rows = [
        {"date": date(2026, 1, 1), "close": 200.0},
        {"date": date(2026, 1, 8), "close": 210.0},
    ]
    payload = score_stance_row(
        {"id": "uuid-1", "ticker": "BAD", "stance": "BUY", "as_of": as_of, "price_at_stance": None},
        horizon_days=7,
        now=now,
        benchmark_rows=bench_rows,
        ticker_rows=ticker_rows,
    )
    assert payload is None


@patch("web_dashboard.scheduler.jobs_stance_outcomes._fetch_benchmark_closes")
@patch("web_dashboard.scheduler.jobs_stance_outcomes._fetch_ticker_closes_yfinance")
def test_stance_outcomes_job_scores_row(mock_ticker_fetch, mock_bench_fetch) -> None:
    from web_dashboard.scheduler.jobs_stance_outcomes import _run_stance_outcomes_job

    mock_bench_fetch.return_value = [
        {"date": date(2026, 1, 1), "close": 200.0},
        {"date": date(2026, 1, 8), "close": 210.0},
    ]
    mock_ticker_fetch.return_value = [
        {"date": date(2026, 1, 1), "close": 100.0},
        {"date": date(2026, 1, 8), "close": 110.0},
    ]

    with patch("postgres_client.PostgresClient") as mock_pg_cls, patch(
        "supabase_client.SupabaseClient"
    ), patch("utils.job_tracking.mark_job_started"), patch(
        "utils.job_tracking.mark_job_completed"
    ), patch(
        "web_dashboard.scheduler.jobs_stance_outcomes.select_unscored_stances"
    ) as mock_select, patch(
        "web_dashboard.scheduler.jobs_stance_outcomes.log_job_execution"
    ):
        pg = MagicMock()
        mock_pg_cls.return_value = pg
        mock_select.side_effect = [
            [
                {
                    "id": "uuid-1",
                    "ticker": "AAA",
                    "stance": "BUY",
                    "as_of": datetime(2026, 1, 1, tzinfo=timezone.utc),
                    "price_at_stance": None,
                }
            ],
            [],
            [],
        ]
        _run_stance_outcomes_job()
        assert pg.execute_update.called
