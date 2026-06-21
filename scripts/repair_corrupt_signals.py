"""Repair corrupt signal_analysis rows in place (no deletes).

Some scan runs ingested a zero/NaN price bar for the latest (incomplete)
trading day, which the old code coerced to Decimal('0'). That phantom -100%
crash poisoned the ENTIRE signal row (structure/timing/fear/momentum and the
derived overall_signal/confidence) for ~94 watchlist tickers.

This script recomputes each corrupt row through the (patched) SignalEngine on a
clean OHLCV window ending at that row's own analysis_date, then UPDATEs the
signal columns in place. Rows, dates, and explanations are preserved -- only the
wrong signal values are replaced. Nothing is deleted; failed fetches are skipped
and reported, never blanked.

Usage:
    # Dry run (default): recompute + print old->new, ZERO writes
    ./venv/Scripts/python.exe scripts/repair_corrupt_signals.py

    # Apply: write corrected rows to production
    ./venv/Scripts/python.exe scripts/repair_corrupt_signals.py --apply

    # Limit number of (ticker, run) groups (handy for a small test first)
    ./venv/Scripts/python.exe scripts/repair_corrupt_signals.py --limit 5
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

# --- path setup (project root + web_dashboard), mirroring the scheduler job ---
# CRITICAL: project root MUST come BEFORE web_dashboard in sys.path. Otherwise
# web_dashboard/utils (a package lacking ticker_utils) shadows the root `utils`
# package, and the Yahoo fetch path's `import utils.ticker_utils` fails -- which
# silently breaks EVERY price fetch ("all strategies failed"). Insert
# web_dashboard first, then project root, so root lands at index 0.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
WEB_DASHBOARD = PROJECT_ROOT / "web_dashboard"
if str(WEB_DASHBOARD) not in sys.path:
    sys.path.insert(0, str(WEB_DASHBOARD))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(WEB_DASHBOARD / ".env")

import pandas as pd  # noqa: E402
import psycopg2  # noqa: E402
import psycopg2.extras  # noqa: E402

from market_data.data_fetcher import MarketDataFetcher  # noqa: E402
from web_dashboard.signals.signal_engine import SignalEngine  # noqa: E402

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("repair_corrupt_signals")
logger.setLevel(logging.INFO)

# A row is corrupt if the fear sub-signal recorded a ~-100% drawdown or daily
# change -- a real value would mean the security went to zero (impossible for the
# blue chips / broad ETFs affected), so these are provably bogus.
CORRUPT_PREDICATE = """
    (fear_risk_signal->>'drawdown_pct') ~ '^-?[0-9.]+$'
    AND (
        (fear_risk_signal->>'drawdown_pct')::float <= -99
        OR (fear_risk_signal->>'daily_change_pct')::float <= -99
    )
"""

SIGNAL_COLUMNS = (
    "structure_signal",
    "timing_signal",
    "fear_risk_signal",
    "momentum_signal",
    "fundamental_signal",
)


def _is_corrupt(fear: dict[str, Any]) -> bool:
    """Python-side mirror of CORRUPT_PREDICATE (defensive re-check)."""
    if not isinstance(fear, dict):
        return False
    for key in ("drawdown_pct", "daily_change_pct"):
        try:
            if float(fear.get(key)) <= -99:
                return True
        except (TypeError, ValueError):
            continue
    return False


def fetch_corrupt_rows(conn) -> list[dict[str, Any]]:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            f"""
            SELECT id, ticker, analysis_date,
                   fear_risk_signal->>'fear_level'  AS old_fear,
                   overall_signal                   AS old_overall,
                   (explanation IS NOT NULL)        AS has_explanation
            FROM signal_analysis
            WHERE {CORRUPT_PREDICATE}
            ORDER BY ticker, analysis_date
            """
        )
        return [dict(r) for r in cur.fetchall()]


def load_fundamentals(conn, tickers: list[str]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    if not tickers:
        return out
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT * FROM securities WHERE upper(ticker) = ANY(%s)",
            ([t.upper() for t in tickers],),
        )
        for row in cur.fetchall():
            tk = (row.get("ticker") or "").upper()
            if tk:
                out[tk] = dict(row)
    return out


def group_rows(rows: list[dict[str, Any]]) -> dict[tuple[str, Any], list[dict[str, Any]]]:
    """Group corrupt rows by (ticker, scan-run hour) so we recompute once per run."""
    groups: dict[tuple[str, Any], list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        bucket = r["analysis_date"].replace(minute=0, second=0, microsecond=0)
        groups[(r["ticker"].upper(), bucket)].append(r)
    return groups


def fetch_ticker_window(
    fetcher: MarketDataFetcher,
    ticker: str,
    period: str,
    attempts: int,
    backoff: float,
) -> pd.DataFrame | None:
    """Fetch ONE window per ticker (covering every corrupt run, sliced later).

    Uses the period-only call -- the same pattern the production scan uses and
    proven reliable here -- instead of start/end, which is flakier and triggers
    Yahoo's throttle far more readily. `period='1y'` gives enough history to
    slice back to the oldest corrupt run (~2 weeks ago) with margin."""
    for attempt in range(1, attempts + 1):
        try:
            df = fetcher.fetch_price_data(ticker, period=period).df
            if df is not None and not df.empty:
                return df
        except Exception as e:  # noqa: BLE001
            logger.debug("  %s fetch attempt %d/%d failed: %s", ticker, attempt, attempts, e)
        if attempt < attempts:
            wait = backoff * attempt  # long, to let any throttle clear
            logger.info("  %s fetch attempt %d/%d empty; backing off %.0fs",
                        ticker, attempt, attempts, wait)
            time.sleep(wait)
    return None


def slice_as_of(df: pd.DataFrame, as_of: Any) -> pd.DataFrame:
    """Return the rows of df dated on or before `as_of` (faithful as-of-date)."""
    idx = df.index
    try:
        idx_naive = idx.tz_localize(None) if getattr(idx, "tz", None) is not None else idx
    except (TypeError, AttributeError):
        idx_naive = idx
    cutoff = pd.Timestamp(as_of.date())
    return df[idx_naive <= cutoff]


def recompute_as_of(
    engine: SignalEngine,
    ticker: str,
    df_full: pd.DataFrame,
    as_of: Any,
    fundamentals: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Recompute the full signal set for `ticker` as of `as_of`, from a
    pre-fetched window sliced to that date."""
    df = slice_as_of(df_full, as_of)
    if df is None or df.empty or len(df) < 60:
        logger.warning("  %s @ %s: insufficient sliced data (rows=%s) -- skipping",
                       ticker, as_of.date(), 0 if df is None else len(df))
        return None
    signals = engine.evaluate(ticker, df, fundamentals=fundamentals)
    if signals.get("error") or _is_corrupt(signals.get("fear_risk", {})):
        logger.warning("  %s @ %s: recompute still bad -- skipping (no overwrite)",
                       ticker, as_of.date())
        return None
    return signals


def update_rows(conn, ids: list[int], signals: dict[str, Any]) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE signal_analysis
            SET structure_signal   = %s::jsonb,
                timing_signal      = %s::jsonb,
                fear_risk_signal   = %s::jsonb,
                momentum_signal    = %s::jsonb,
                fundamental_signal = %s::jsonb,
                overall_signal     = %s,
                confidence_score   = %s
            WHERE id = ANY(%s)
            """,
            (
                json.dumps(signals.get("structure", {})),
                json.dumps(signals.get("timing", {})),
                json.dumps(signals.get("fear_risk", {})),
                json.dumps(signals.get("momentum", {})),
                json.dumps(signals.get("fundamental", {})),
                signals.get("overall_signal", "HOLD"),
                float(signals.get("confidence", 0.0)),
                ids,
            ),
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="Write corrected rows to production (default: dry run)")
    parser.add_argument("--limit", type=int, default=0,
                        help="Process at most N tickers (one fetch each)")
    parser.add_argument("--sleep", type=float, default=3.0,
                        help="Seconds to sleep between tickers (rate limit)")
    parser.add_argument("--attempts", type=int, default=3,
                        help="Fetch attempts per ticker before skipping")
    parser.add_argument("--backoff", type=float, default=20.0,
                        help="Base seconds to back off after an empty fetch (x attempt)")
    parser.add_argument("--period", type=str, default="1y",
                        help="yfinance period to fetch per ticker (sliced per run)")
    args = parser.parse_args()

    if os.environ.get("REPAIR_DEBUG"):
        logging.getLogger("market_data.data_fetcher").setLevel(logging.DEBUG)

    db_url = os.environ.get("SUPABASE_DATABASE_URL")
    if not db_url:
        logger.error("SUPABASE_DATABASE_URL not set in web_dashboard/.env")
        return 2

    conn = psycopg2.connect(db_url)
    conn.autocommit = False
    try:
        rows = fetch_corrupt_rows(conn)
        if not rows:
            logger.info("No corrupt rows found. Nothing to do.")
            return 0

        groups = group_rows(rows)
        # Regroup by ticker so we fetch ONE window per ticker (bursting many
        # date-bounded fetches is what trips Yahoo's rate limiter).
        by_ticker: dict[str, list[tuple[Any, list[dict[str, Any]]]]] = defaultdict(list)
        for (ticker, bucket), grp in groups.items():
            by_ticker[ticker].append((bucket, grp))
        tickers = sorted(by_ticker)
        if args.limit:
            tickers = tickers[: args.limit]

        with_expl = sum(1 for r in rows if r["has_explanation"])
        mode = "APPLY (writing to production)" if args.apply else "DRY RUN (no writes)"
        logger.info("=" * 72)
        logger.info("Repair corrupt signals -- %s", mode)
        logger.info("Corrupt rows total: %d across %d (ticker, run) groups, %d tickers",
                    len(rows), len(groups), len(by_ticker))
        logger.info("Processing %d tickers this run (one fetch each, sleep=%.1fs)",
                    len(tickers), args.sleep)
        if with_expl:
            logger.info("Note: %d corrupt rows have a non-null explanation (left untouched).",
                        with_expl)
        logger.info("=" * 72)

        fetcher = MarketDataFetcher()
        engine = SignalEngine()
        fundamentals_map = load_fundamentals(conn, list(by_ticker))

        fixed_rows = 0
        fixed_groups = 0
        skipped_groups = 0
        skipped_tickers = 0
        total_t = len(tickers)
        for ti, ticker in enumerate(tickers, start=1):
            buckets = sorted(by_ticker[ticker], key=lambda x: x[0])
            df_full = fetch_ticker_window(
                fetcher, ticker, args.period, args.attempts, args.backoff
            )
            if df_full is None or df_full.empty:
                n_grp = len(buckets)
                logger.warning("[%d/%d] %-9s: fetch failed after %d attempts -- "
                               "skipping %d run(s) (re-run later)",
                               ti, total_t, ticker, args.attempts, n_grp)
                skipped_groups += n_grp
                skipped_tickers += 1
                time.sleep(args.sleep)
                continue

            for bucket, grp in buckets:
                ids = [r["id"] for r in grp]
                old_fear = grp[0]["old_fear"]
                old_overall = grp[0]["old_overall"]
                try:
                    signals = recompute_as_of(
                        engine, ticker, df_full, bucket, fundamentals_map.get(ticker)
                    )
                except Exception as e:  # noqa: BLE001 - report and continue, never blank
                    logger.warning("[%d/%d] %s @ %s: recompute error: %s -- skipping",
                                   ti, total_t, ticker, bucket.date(), e)
                    signals = None

                if signals is None:
                    skipped_groups += 1
                    continue

                new_fear = signals.get("fear_risk", {}).get("fear_level")
                new_overall = signals.get("overall_signal")
                new_dd = signals.get("fear_risk", {}).get("drawdown_pct")
                logger.info("[%d/%d] %-9s @ %s  %sx  %s/%s -> %s/%s (dd=%.1f%%)",
                            ti, total_t, ticker, bucket.date(), len(ids),
                            old_fear, old_overall, new_fear, new_overall, float(new_dd))

                if args.apply:
                    update_rows(conn, ids, signals)
                    conn.commit()  # commit per run so slow-run progress persists
                fixed_rows += len(ids)
                fixed_groups += 1

            time.sleep(args.sleep)  # one pace step per ticker (after its single fetch)

        logger.info("-" * 72)
        if args.apply:
            logger.info("DONE. Fixed %d rows in %d runs; %d runs skipped "
                        "(%d tickers unfetched). Committed per run; re-run to retry skips.",
                        fixed_rows, fixed_groups, skipped_groups, skipped_tickers)
        else:
            conn.rollback()
            logger.info("DRY RUN complete. Would fix %d rows in %d runs; %d runs skipped "
                        "(%d tickers unfetched). Re-run with --apply to write.",
                        fixed_rows, fixed_groups, skipped_groups, skipped_tickers)
        return 0
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
