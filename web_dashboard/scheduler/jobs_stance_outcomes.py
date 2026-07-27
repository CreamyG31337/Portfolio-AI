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
from typing import Any, NamedTuple
from collections.abc import Mapping, Sequence

current_dir = Path(__file__).resolve().parent
web_dashboard_path = str(current_dir.parent)
if web_dashboard_path not in sys.path:
    sys.path.insert(0, web_dashboard_path)

project_root = str(current_dir.parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from benchmarks import SCORING_VERSION, resolve_benchmark
from scheduler.scheduler_core import log_job_execution
from stance_history import DIRECTIONAL_STANCES, is_directional_stance

logger = logging.getLogger(__name__)

BENCHMARK_TICKER = "^RUT"
HORIZONS: tuple[int, ...] = (7, 30, 90)
JOB_ID = "stance_outcomes"

# After this many failed attempts a (stance, horizon) pair is dead-lettered out of
# the queue. Without it, rows that can never be priced (bad symbol, delisting) sit
# at the head of the `as_of ASC` window forever and starve every newer stance --
# the cause of the observed `scored=0 skipped=202` stall.
MAX_SCORING_ATTEMPTS = 5

# SCORING_VERSION is defined in benchmarks.py so the scoring job and the
# track-record aggregates cannot drift apart on which scheme they mean.

# Skip reasons. These exist so the job summary can distinguish a transient,
# system-wide fetch failure (provider rate-limiting -> no_ticker_price everywhere)
# from a permanently bad symbol (one ticker, every run). A single `skipped` counter
# made those two look identical, which is why the stall went unnoticed.
SKIP_NO_TICKER_PRICE = "no_ticker_price"
SKIP_NO_BENCHMARK_PRICE = "no_benchmark_price"
SKIP_NOT_MATURED = "not_matured"
SKIP_BAD_AS_OF = "bad_as_of"
SKIP_ZERO_BASELINE = "zero_baseline"

# Reasons that reflect "too early", not "broken". These must NOT burn attempts or a
# stance could be dead-lettered before it was ever eligible to score.
TRANSIENT_SKIP_REASONS = frozenset({SKIP_NOT_MATURED})


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
    symbol: str = BENCHMARK_TICKER,
) -> list[dict[str, Any]]:
    """Benchmark closes, cache-first with a provider fallback that backfills the cache.

    ``benchmark_data`` already holds ^GSPC / ^RUT / QQQ / VTI. ^GSPTSE (needed once
    per-ticker benchmarks landed) is not there, so a cache miss falls through to the
    price provider and writes the result back -- no separate backfill job, and any
    future benchmark self-populates the same way.
    """
    rows = supabase_client.get_benchmark_data(
        symbol,
        datetime.combine(start, datetime.min.time(), tzinfo=UTC),
        datetime.combine(end, datetime.max.time().replace(microsecond=0), tzinfo=UTC),
    )
    if rows:
        return rows

    logger.info("stance_outcomes_job: benchmark cache miss for %s; fetching", symbol)
    fetched = _fetch_ticker_closes_yfinance(symbol, start, end)
    if not fetched:
        logger.warning("stance_outcomes_job: no benchmark data available for %s", symbol)
        return []
    try:
        supabase_client.cache_benchmark_data(
            symbol,
            [{"Date": r["date"], "Close": r["close"]} for r in fetched],
        )
    except Exception as exc:
        logger.warning("stance_outcomes_job: could not cache %s: %s", symbol, exc)
    return fetched


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


def candidate_price_symbols(ticker: str) -> list[str]:
    """Provider symbol candidates to try for ``ticker``, best guess first.

    Stored tickers do not always match the price provider's spelling. Class shares
    use a dot here but a dash there (``BRK.B`` -> ``BRK-B``), and TSX listings need
    a ``.TO`` suffix (``TECK.B`` -> ``TECK-B.TO``). Rather than guess a single
    transformation, try a short ladder and cache whichever resolves.
    """
    base = (ticker or "").strip().upper()
    if not base:
        return []
    candidates = [base]
    if "." in base:
        head, _, tail = base.rpartition(".")
        # Only treat a short trailing segment as a share class; ".TO"/".V" are
        # already exchange suffixes and must not be rewritten into "-TO".
        if head and len(tail) == 1:
            candidates.append(f"{head}-{tail}")
            candidates.append(f"{head}-{tail}.TO")
    return list(dict.fromkeys(candidates))


def load_securities_meta(postgres: Any, tickers: Sequence[str]) -> dict[str, dict[str, Any]]:
    """Fetch benchmark inputs for a batch of tickers, keyed by UPPER(ticker).

    Missing rows are normal, not exceptional: 51 of the stance tickers have no
    ``securities`` row at all. Callers must treat an absent entry as "unknown", which
    resolves to the default benchmark flagged as a fallback.
    """
    wanted = sorted({(t or "").strip().upper() for t in tickers if t})
    if not wanted:
        return {}
    try:
        rows = postgres.execute_query(
            """
            SELECT upper(ticker) AS ticker, market_cap, price_symbol, currency, benchmark_override
            FROM securities
            WHERE upper(ticker) = ANY(%s)
            """,
            (wanted,),
        )
    except Exception as exc:
        logger.warning("stance_outcomes_job: securities lookup failed (%s); using defaults", exc)
        return {}
    return {str(r["ticker"]): dict(r) for r in rows}


def _load_cached_price_symbol(postgres: Any, ticker: str) -> str | None:
    try:
        rows = postgres.execute_query(
            "SELECT price_symbol FROM securities WHERE upper(ticker) = %s AND price_symbol IS NOT NULL",
            (ticker.upper(),),
        )
        if not rows:
            return None
        value = rows[0].get("price_symbol")
        return str(value) if value else None
    except Exception:
        # Column may not exist yet on an un-migrated DB; fall back to the ladder.
        return None


def _save_price_symbol(postgres: Any, ticker: str, price_symbol: str) -> None:
    """Remember a resolved alias so the candidate ladder runs once, not every night."""
    if price_symbol.upper() == ticker.upper():
        return
    try:
        postgres.execute_update(
            """
            INSERT INTO securities (ticker, price_symbol, price_symbol_set_at)
            VALUES (%s, %s, NOW())
            ON CONFLICT (ticker) DO UPDATE SET
                price_symbol = EXCLUDED.price_symbol,
                price_symbol_set_at = NOW()
            """,
            (ticker.upper(), price_symbol),
        )
    except Exception as exc:
        logger.debug("could not cache price_symbol for %s: %s", ticker, exc)


def _fetch_ticker_closes_resolved(
    postgres: Any,
    ticker: str,
    start: date,
    end: date,
    resolved_symbols: dict[str, str],
) -> list[dict[str, Any]]:
    """Fetch closes for ``ticker``, trying provider symbol aliases before giving up.

    Returns an empty list only when every candidate fails, which the caller reports
    as an unpriced ticker rather than silently folding into a skip count.
    """
    cached = _load_cached_price_symbol(postgres, ticker)
    candidates = ([cached] if cached else []) + candidate_price_symbols(ticker)
    for symbol in dict.fromkeys(c for c in candidates if c):
        rows = _fetch_ticker_closes_yfinance(symbol, start, end)
        if rows:
            resolved_symbols[ticker] = symbol
            if symbol.upper() != ticker.upper():
                logger.info("stance_outcomes_job: resolved %s -> %s", ticker, symbol)
                _save_price_symbol(postgres, ticker, symbol)
            return rows
    return []


def select_unscored_stances(
    postgres: Any,
    *,
    horizon_days: int,
    as_of_cutoff: datetime,
    limit: int = 200,
    max_attempts: int = MAX_SCORING_ATTEMPTS,
) -> list[dict[str, Any]]:
    """Return stance rows eligible for scoring at the given horizon.

    The directional filter MUST live in SQL: non-directional rows
    (INSUFFICIENT_DATA, NEUTRAL, RISK, WATCH, ...) are never scored, so
    filtering after LIMIT would let them permanently occupy the oldest-first
    window and starve the queue.

    Dead-lettering is the same class of guard: rows that have failed
    ``max_attempts`` times are excluded in SQL for exactly the same reason. Before
    this existed, a handful of unpriceable symbols pinned the head of the
    ``as_of ASC`` window and scoring stalled completely.
    """
    rows = postgres.execute_query(
        """
        SELECT sh.id, sh.ticker, sh.stance, sh.as_of, sh.price_at_stance
        FROM stance_history sh
        LEFT JOIN stance_outcomes so
          ON so.stance_id = sh.id AND so.horizon_days = %s
        LEFT JOIN stance_outcome_attempts sa
          ON sa.stance_id = sh.id AND sa.horizon_days = %s
        WHERE sh.as_of <= %s
          AND so.id IS NULL
          AND COALESCE(sa.attempts, 0) < %s
          AND UPPER(sh.stance) = ANY(%s)
        ORDER BY sh.as_of ASC
        LIMIT %s
        """,
        (
            horizon_days,
            horizon_days,
            as_of_cutoff,
            max_attempts,
            sorted(DIRECTIONAL_STANCES),
            limit,
        ),
    )
    return [r for r in rows if is_directional_stance(r.get("stance"))]


def record_scoring_attempt(
    postgres: Any,
    *,
    stance_id: str,
    horizon_days: int,
    reason: str,
) -> None:
    """Increment the failed-attempt counter for a (stance, horizon) pair.

    Transient reasons ("not matured yet") must not burn attempts, or a stance could
    be dead-lettered before it was ever eligible to score.
    """
    if reason in TRANSIENT_SKIP_REASONS:
        return
    postgres.execute_update(
        """
        INSERT INTO stance_outcome_attempts (stance_id, horizon_days, attempts, last_reason, last_attempt_at)
        VALUES (%s::uuid, %s, 1, %s, NOW())
        ON CONFLICT (stance_id, horizon_days) DO UPDATE SET
            attempts = stance_outcome_attempts.attempts + 1,
            last_reason = EXCLUDED.last_reason,
            last_attempt_at = NOW()
        """,
        (str(stance_id), horizon_days, reason),
    )


class ScoreResult(NamedTuple):
    """Outcome of scoring one stance row.

    Exactly one of ``payload`` / ``skip_reason`` is set. The reason is what lets the
    caller record a dead-letter attempt and report a per-reason breakdown instead of
    an undiagnosable ``skipped`` count.
    """

    payload: dict[str, Any] | None
    skip_reason: str | None


def score_stance_row(
    row: Mapping[str, Any],
    *,
    horizon_days: int,
    now: datetime,
    benchmark_rows: Sequence[Mapping[str, Any]],
    ticker_rows: Sequence[Mapping[str, Any]],
    benchmark_symbol: str = BENCHMARK_TICKER,
) -> ScoreResult:
    """Score one stance row.

    Returns a :class:`ScoreResult` carrying either the insert payload or the reason
    scoring was not possible.
    """
    as_of = row.get("as_of")
    if isinstance(as_of, str):
        as_of = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
    if not isinstance(as_of, datetime):
        return ScoreResult(None, SKIP_BAD_AS_OF)
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=UTC)

    baseline_date = as_of.date()
    end_date = (as_of + timedelta(days=horizon_days)).date()
    if end_date > now.date():
        return ScoreResult(None, SKIP_NOT_MATURED)

    baseline_price = _to_decimal(row.get("price_at_stance"))
    if baseline_price is None:
        baseline_price = _nearest_close_on_or_before(ticker_rows, baseline_date)
    end_price = _nearest_close_on_or_before(ticker_rows, end_date)
    bench_baseline = _nearest_close_on_or_before(benchmark_rows, baseline_date)
    bench_end = _nearest_close_on_or_before(benchmark_rows, end_date)

    if baseline_price is None or end_price is None:
        return ScoreResult(None, SKIP_NO_TICKER_PRICE)
    if bench_baseline is None or bench_end is None:
        return ScoreResult(None, SKIP_NO_BENCHMARK_PRICE)
    if baseline_price == 0 or bench_baseline == 0:
        # _pct_return would return None and write a NULL excess_return that the
        # nightly NaN purge does not catch; reject it here with a nameable reason.
        return ScoreResult(None, SKIP_ZERO_BASELINE)

    returns = compute_excess_return(baseline_price, end_price, bench_baseline, bench_end)
    return ScoreResult(
        {
            "stance_id": row["id"],
            "horizon_days": horizon_days,
            "baseline_price": baseline_price,
            "end_price": end_price,
            "ticker_return": returns["ticker_return"],
            "benchmark_return": returns["benchmark_return"],
            "excess_return": returns["excess_return"],
            "benchmark_symbol": benchmark_symbol,
        },
        None,
    )


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
        min_date = now.date()
        max_date = now.date()
        if all_candidates:
            min_date = min(
                (c["as_of"].date() if isinstance(c["as_of"], datetime) else date.today())
                for c in all_candidates
            )

        # Benchmark inputs for every candidate ticker, fetched once.
        sec_meta = load_securities_meta(postgres, [c.get("ticker") or "" for c in all_candidates])
        # Benchmark closes are cached per symbol per run: a handful of symbols across
        # hundreds of stances, so this is 2-3 fetches, not one per row.
        bench_cache: dict[str, list[dict[str, Any]]] = {}
        benchmark_counts: dict[str, int] = {}
        fallback_benchmarks = 0

        def _benchmark_for(ticker: str) -> tuple[str, list[dict[str, Any]]]:
            meta = sec_meta.get(ticker.upper()) or {}
            symbol, is_fallback = resolve_benchmark(
                ticker,
                market_cap=meta.get("market_cap"),
                price_symbol=meta.get("price_symbol"),
                currency=meta.get("currency"),
                override=meta.get("benchmark_override"),
            )
            if is_fallback:
                nonlocal fallback_benchmarks
                fallback_benchmarks += 1
            if symbol not in bench_cache:
                bench_cache[symbol] = _fetch_benchmark_closes(
                    supabase, min_date - timedelta(days=7), max_date, symbol
                )
            benchmark_counts[symbol] = benchmark_counts.get(symbol, 0) + 1
            return symbol, bench_cache[symbol]

        # Pass 2: score. One price fetch per ticker per run, shared across horizons.
        ticker_cache: dict[str, list[dict[str, Any]]] = {}
        resolved_symbols: dict[str, str] = {}
        skip_reasons: dict[str, int] = {}
        for horizon, candidates in candidates_by_horizon.items():
            for row in candidates:
                ticker = (row.get("ticker") or "").upper()
                try:
                    if ticker not in ticker_cache:
                        ticker_cache[ticker] = _fetch_ticker_closes_resolved(
                            postgres,
                            ticker,
                            min_date - timedelta(days=7),
                            max_date,
                            resolved_symbols,
                        )
                    bench_symbol, bench_rows = _benchmark_for(ticker)
                    result = score_stance_row(
                        row,
                        horizon_days=horizon,
                        now=now,
                        benchmark_rows=bench_rows,
                        ticker_rows=ticker_cache[ticker],
                        benchmark_symbol=bench_symbol,
                    )
                    if result.payload is None:
                        reason = result.skip_reason or "unknown"
                        skip_reasons[reason] = skip_reasons.get(reason, 0) + 1
                        skipped += 1
                        record_scoring_attempt(
                            postgres,
                            stance_id=row["id"],
                            horizon_days=horizon,
                            reason=reason,
                        )
                        continue
                    payload = result.payload
                    postgres.execute_update(
                        """
                        INSERT INTO stance_outcomes (
                            stance_id, horizon_days, baseline_price, end_price,
                            ticker_return, benchmark_return, excess_return,
                            benchmark_symbol, scoring_version
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                            payload["benchmark_symbol"],
                            SCORING_VERSION,
                        ),
                    )
                    scored += 1
                except Exception as row_exc:
                    errors += 1
                    logger.warning("Failed scoring %s horizon=%s: %s", ticker, horizon, row_exc)

        # A ticker that resolved to nothing is either a bad symbol or a provider
        # outage. Name them so the two are separable from the job log alone.
        unpriced = sorted(t for t, rows in ticker_cache.items() if not rows)
        if unpriced:
            logger.warning(
                "stance_outcomes_job: no prices for %s ticker(s): %s",
                len(unpriced),
                ", ".join(unpriced[:20]),
            )

        duration_ms = int((time.time() - start_time) * 1000)
        reason_summary = " ".join(f"{k}={v}" for k, v in sorted(skip_reasons.items()))
        summary = f"scored={scored} skipped={skipped} errors={errors}"
        if reason_summary:
            summary += f" [{reason_summary}]"
        if unpriced:
            summary += f" unpriced_tickers={len(unpriced)}"
        if benchmark_counts:
            bench_summary = " ".join(f"{k}={v}" for k, v in sorted(benchmark_counts.items()))
            summary += f" bench[{bench_summary}]"
        if fallback_benchmarks:
            # Unknown market cap -> defaulted to the broad index. Visible so a large
            # share of guessed benchmarks cannot quietly inflate confidence.
            summary += f" bench_fallback={fallback_benchmarks}"
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
