"""
Stance Outcomes Scoring Job
===========================

Nightly, no-LLM job that scores directional stance_history rows at 7/30/90-day
horizons vs ^RUT benchmark. V1 excludes RISK/WATCH from scoring.
"""

from __future__ import annotations

import logging
import sys
import time
from datetime import date, datetime, timedelta, UTC
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from collections.abc import Mapping, Sequence

current_dir = Path(__file__).resolve().parent
web_dashboard_path = str(current_dir.parent)
if web_dashboard_path not in sys.path:
    sys.path.insert(0, web_dashboard_path)

project_root = str(current_dir.parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from scheduler.scheduler_core import log_job_execution
from stance_history import DIRECTIONAL_STANCES, is_directional_stance

logger = logging.getLogger(__name__)

BENCHMARK_TICKER = "^RUT"
HORIZONS: tuple[int, ...] = (7, 30, 90)
JOB_ID = "stance_outcomes"


def _to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    if not d.is_finite():
        return None
    return d


def _pct_return(baseline: Decimal, end: Decimal) -> Decimal | None:
    if baseline is None or end is None or baseline == 0:
        return None
    return ((end - baseline) / baseline) * Decimal("100")


def compute_excess_return(
    baseline_price: Decimal,
    end_price: Decimal,
    bench_baseline: Decimal,
    bench_end: Decimal,
) -> dict[str, Decimal | None]:
    """Compute ticker return, benchmark return, and excess return (percentage points)."""
    ticker_return = _pct_return(baseline_price, end_price)
    benchmark_return = _pct_return(bench_baseline, bench_end)
    excess_return: Decimal | None = None
    if ticker_return is not None and benchmark_return is not None:
        excess_return = ticker_return - benchmark_return
    return {
        "ticker_return": ticker_return,
        "benchmark_return": benchmark_return,
        "excess_return": excess_return,
    }


def _nearest_close_on_or_before(
    price_rows: Sequence[Mapping[str, Any]],
    target: date,
) -> Decimal | None:
    """Pick the latest close on or before target from rows sorted by date ascending."""
    best: Decimal | None = None
    for row in price_rows:
        row_date = row.get("date")
        if isinstance(row_date, str):
            row_date = date.fromisoformat(row_date[:10])
        elif isinstance(row_date, datetime):
            row_date = row_date.date()
        if not isinstance(row_date, date):
            continue
        if row_date <= target:
            best = _to_decimal(row.get("close"))
        else:
            break
    return best


def _fetch_benchmark_closes(
    supabase_client: Any,
    start: date,
    end: date,
) -> list[dict[str, Any]]:
    rows = supabase_client.get_benchmark_data(
        BENCHMARK_TICKER,
        datetime.combine(start, datetime.min.time(), tzinfo=UTC),
        datetime.combine(end, datetime.max.time().replace(microsecond=0), tzinfo=UTC),
    )
    return rows or []


def _fetch_ticker_closes_yfinance(
    ticker: str,
    start: date,
    end: date,
) -> list[dict[str, Any]]:
    import yfinance as yf

    # auto_adjust=True: micro-caps reverse-split often; unadjusted closes would
    # turn a 1:10 split into a fake +900% "return" and corrupt hit rates.
    data = yf.download(
        ticker,
        start=start.isoformat(),
        end=(end + timedelta(days=1)).isoformat(),
        progress=False,
        auto_adjust=True,
    )
    if data is None or data.empty:
        return []

    data = data.reset_index()
    if hasattr(data.columns, "levels"):
        data.columns = data.columns.get_level_values(0)

    out: list[dict[str, Any]] = []
    # to_dict("records") preserves per-column dtypes (Timestamp keeps .date(),
    # Close stays float) and avoids the Series instantiation overhead of iterrows().
    for record in data.to_dict("records"):
        row_date = record.get("Date")
        if hasattr(row_date, "date"):
            row_date = row_date.date()
        close_val = record.get("Close")
        if row_date and close_val is not None:
            out.append({"date": row_date, "close": float(close_val)})
    out.sort(key=lambda r: r["date"])
    return out


def select_unscored_stances(
    postgres: Any,
    *,
    horizon_days: int,
    as_of_cutoff: datetime,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Return stance rows eligible for scoring at the given horizon.

    The directional filter MUST live in SQL: non-directional rows
    (INSUFFICIENT_DATA, NEUTRAL, RISK, WATCH, ...) are never scored, so
    filtering after LIMIT would let them permanently occupy the oldest-first
    window and starve the queue.
    """
    rows = postgres.execute_query(
        """
        SELECT sh.id, sh.ticker, sh.stance, sh.as_of, sh.price_at_stance
        FROM stance_history sh
        LEFT JOIN stance_outcomes so
          ON so.stance_id = sh.id AND so.horizon_days = %s
        WHERE sh.as_of <= %s
          AND so.id IS NULL
          AND UPPER(sh.stance) = ANY(%s)
        ORDER BY sh.as_of ASC
        LIMIT %s
        """,
        (horizon_days, as_of_cutoff, sorted(DIRECTIONAL_STANCES), limit),
    )
    return [r for r in rows if is_directional_stance(r.get("stance"))]


def score_stance_row(
    row: Mapping[str, Any],
    *,
    horizon_days: int,
    now: datetime,
    benchmark_rows: Sequence[Mapping[str, Any]],
    ticker_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any] | None:
    """Score one stance row; returns insert payload or None if prices unavailable."""
    as_of = row.get("as_of")
    if isinstance(as_of, str):
        as_of = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
    if not isinstance(as_of, datetime):
        return None
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=UTC)

    baseline_date = as_of.date()
    end_date = (as_of + timedelta(days=horizon_days)).date()
    if end_date > now.date():
        return None

    baseline_price = _to_decimal(row.get("price_at_stance"))
    if baseline_price is None:
        baseline_price = _nearest_close_on_or_before(ticker_rows, baseline_date)
    end_price = _nearest_close_on_or_before(ticker_rows, end_date)
    bench_baseline = _nearest_close_on_or_before(benchmark_rows, baseline_date)
    bench_end = _nearest_close_on_or_before(benchmark_rows, end_date)

    if baseline_price is None or end_price is None or bench_baseline is None or bench_end is None:
        return None

    returns = compute_excess_return(baseline_price, end_price, bench_baseline, bench_end)
    return {
        "stance_id": row["id"],
        "horizon_days": horizon_days,
        "baseline_price": baseline_price,
        "end_price": end_price,
        "ticker_return": returns["ticker_return"],
        "benchmark_return": returns["benchmark_return"],
        "excess_return": returns["excess_return"],
    }


def _run_stance_outcomes_job() -> None:
    start_time = time.time()
    target_date = datetime.now(UTC).date()
    scored = 0
    skipped = 0
    errors = 0

    try:
        from postgres_client import PostgresClient
        from supabase_client import SupabaseClient
        from utils.job_tracking import mark_job_completed, mark_job_started

        mark_job_started(JOB_ID, target_date)
        postgres = PostgresClient()
        supabase = SupabaseClient(use_service_role=True)
        now = datetime.now(UTC)

        # yfinance gaps can produce Decimal('NaN') rows that break track-record;
        # delete them so the next run can retry once prices exist.
        deleted = postgres.execute_update(
            """
            DELETE FROM stance_outcomes
            WHERE excess_return != excess_return
               OR ticker_return != ticker_return
               OR benchmark_return != benchmark_return
            """
        )
        if deleted:
            logger.info("stance_outcomes_job: purged %s NaN outcome row(s)", deleted)

        # Pass 1: collect candidates for every horizon so price windows can be
        # fetched once with the widest needed date range (a per-horizon cache
        # could reuse a too-narrow window and permanently skip older rows).
        candidates_by_horizon: dict[int, list[dict[str, Any]]] = {}
        for horizon in HORIZONS:
            cutoff = now - timedelta(days=horizon)
            candidates_by_horizon[horizon] = select_unscored_stances(
                postgres, horizon_days=horizon, as_of_cutoff=cutoff
            )

        all_candidates = [c for rows in candidates_by_horizon.values() for c in rows]
        bench_rows: list[dict[str, Any]] = []
        min_date = now.date()
        max_date = now.date()
        if all_candidates:
            min_date = min(
                (c["as_of"].date() if isinstance(c["as_of"], datetime) else date.today())
                for c in all_candidates
            )
            bench_rows = _fetch_benchmark_closes(supabase, min_date - timedelta(days=7), max_date)

        # Pass 2: score. One yfinance fetch per ticker per run, shared across horizons.
        ticker_cache: dict[str, list[dict[str, Any]]] = {}
        for horizon, candidates in candidates_by_horizon.items():
            for row in candidates:
                ticker = (row.get("ticker") or "").upper()
                try:
                    if ticker not in ticker_cache:
                        ticker_cache[ticker] = _fetch_ticker_closes_yfinance(
                            ticker,
                            min_date - timedelta(days=7),
                            max_date,
                        )
                    payload = score_stance_row(
                        row,
                        horizon_days=horizon,
                        now=now,
                        benchmark_rows=bench_rows,
                        ticker_rows=ticker_cache[ticker],
                    )
                    if not payload:
                        skipped += 1
                        continue
                    postgres.execute_update(
                        """
                        INSERT INTO stance_outcomes (
                            stance_id, horizon_days, baseline_price, end_price,
                            ticker_return, benchmark_return, excess_return
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (stance_id, horizon_days) DO NOTHING
                        """,
                        (
                            str(payload["stance_id"]),
                            payload["horizon_days"],
                            payload["baseline_price"],
                            payload["end_price"],
                            payload["ticker_return"],
                            payload["benchmark_return"],
                            payload["excess_return"],
                        ),
                    )
                    scored += 1
                except Exception as row_exc:
                    errors += 1
                    logger.warning("Failed scoring %s horizon=%s: %s", ticker, horizon, row_exc)

        duration_ms = int((time.time() - start_time) * 1000)
        summary = f"scored={scored} skipped={skipped} errors={errors}"
        log_job_execution(JOB_ID, True, summary, duration_ms)
        mark_job_completed(
            JOB_ID,
            target_date,
            None,
            [],
            duration_ms=duration_ms,
            message=summary,
        )
        logger.info("stance_outcomes_job: %s", summary)
    except Exception as exc:
        duration_ms = int((time.time() - start_time) * 1000)
        err = str(exc)
        log_job_execution(JOB_ID, False, err, duration_ms)
        try:
            from utils.job_tracking import mark_job_failed

            mark_job_failed(JOB_ID, target_date, None, err, duration_ms=duration_ms)
        except Exception:
            pass
        logger.error("stance_outcomes_job failed: %s", exc, exc_info=True)


def stance_outcomes_job() -> None:
    """Nightly job: score matured stance_history rows vs ^RUT."""
    _run_stance_outcomes_job()
