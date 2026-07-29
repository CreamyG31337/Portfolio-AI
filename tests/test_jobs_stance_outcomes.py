"""Tests for stance_outcomes scoring helpers."""

from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

from web_dashboard.scheduler.jobs_stance_outcomes import (
    MAX_SCORING_ATTEMPTS,
    SKIP_NO_BENCHMARK_PRICE,
    SKIP_NO_TICKER_PRICE,
    SKIP_NOT_MATURED,
    candidate_price_symbols,
    compute_excess_return,
    record_scoring_attempt,
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
    result = score_stance_row(
        {"id": "uuid-1", "ticker": "AAA", "stance": "BUY", "as_of": as_of, "price_at_stance": None},
        horizon_days=7,
        now=now,
        benchmark_rows=bench_rows,
        ticker_rows=ticker_rows,
    )
    assert result.payload is not None
    assert result.skip_reason is None
    assert result.payload["horizon_days"] == 7
    assert result.payload["excess_return"] == Decimal("5")


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
    result = score_stance_row(
        {"id": "uuid-1", "ticker": "BAD", "stance": "BUY", "as_of": as_of, "price_at_stance": None},
        horizon_days=7,
        now=now,
        benchmark_rows=bench_rows,
        ticker_rows=ticker_rows,
    )
    assert result.payload is None
    assert result.skip_reason == SKIP_NO_TICKER_PRICE


def test_score_stance_row_distinguishes_benchmark_gap_from_ticker_gap() -> None:
    """The whole point of M1: a provider outage must not look like a bad symbol."""
    as_of = datetime(2026, 1, 1, tzinfo=timezone.utc)
    now = datetime(2026, 2, 1, tzinfo=timezone.utc)
    ticker_rows = [
        {"date": date(2026, 1, 1), "close": 100.0},
        {"date": date(2026, 1, 8), "close": 110.0},
    ]
    result = score_stance_row(
        {"id": "uuid-1", "ticker": "AAA", "stance": "BUY", "as_of": as_of, "price_at_stance": None},
        horizon_days=7,
        now=now,
        benchmark_rows=[],
        ticker_rows=ticker_rows,
    )
    assert result.payload is None
    assert result.skip_reason == SKIP_NO_BENCHMARK_PRICE


def test_score_stance_row_not_matured_is_its_own_reason() -> None:
    as_of = datetime(2026, 1, 1, tzinfo=timezone.utc)
    now = datetime(2026, 1, 3, tzinfo=timezone.utc)
    result = score_stance_row(
        {"id": "uuid-1", "ticker": "AAA", "stance": "BUY", "as_of": as_of, "price_at_stance": None},
        horizon_days=30,
        now=now,
        benchmark_rows=[],
        ticker_rows=[],
    )
    assert result.payload is None
    assert result.skip_reason == SKIP_NOT_MATURED


def test_not_matured_does_not_burn_a_scoring_attempt() -> None:
    """A stance must never be dead-lettered before it was eligible to score."""
    pg = MagicMock()
    record_scoring_attempt(pg, stance_id="uuid-1", horizon_days=30, reason=SKIP_NOT_MATURED)
    assert not pg.execute_update.called

    record_scoring_attempt(pg, stance_id="uuid-1", horizon_days=30, reason=SKIP_NO_TICKER_PRICE)
    assert pg.execute_update.called


def test_select_unscored_stances_excludes_dead_lettered_rows() -> None:
    pg = MagicMock()
    pg.execute_query.return_value = []
    select_unscored_stances(pg, horizon_days=7, as_of_cutoff=datetime.now(timezone.utc))
    sql, params = pg.execute_query.call_args[0]
    assert "stance_outcome_attempts" in sql
    assert "COALESCE(sa.attempts, 0) < %s" in sql
    assert MAX_SCORING_ATTEMPTS in params


def test_candidate_price_symbols_handles_class_shares_and_tsx() -> None:
    # The exact case that stalled the queue: TECK.B is unknown to the provider,
    # TECK-B.TO resolves.
    assert candidate_price_symbols("TECK.B") == ["TECK.B", "TECK-B", "TECK-B.TO"]
    assert candidate_price_symbols("BRK.B") == ["BRK.B", "BRK-B", "BRK-B.TO"]
    # Existing exchange suffixes must not be mangled into "-TO".
    assert candidate_price_symbols("GMIN.TO") == ["GMIN.TO"]
    assert candidate_price_symbols("MSFT") == ["MSFT"]
    assert candidate_price_symbols("") == []


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
        pg.execute_query.return_value = []  # no cached price_symbol alias
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
