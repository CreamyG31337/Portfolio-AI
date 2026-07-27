#!/usr/bin/env python3
"""Re-score existing stance_outcomes under per-ticker benchmarks (measurement rig M2b).

Every row scored before M2a used a single hardcoded ^RUT, so excess_return measured
the large/small-cap and US/Canada spreads rather than whether the call was right.
This recomputes benchmark_return / excess_return against the benchmark each ticker
should have been scored against, and stamps scoring_version = 2.

Run ONCE, deliberately. After this, a scored row's benchmark is immutable: any future
benchmark change bumps SCORING_VERSION and applies to new rows only, so the track
record can never be quietly re-cut.

Note the nightly job inserts with ON CONFLICT DO NOTHING, so it cannot perform this
update -- that is why re-scoring is an explicit UPDATE here rather than a re-run.

Run from project root:
  python web_dashboard/scripts/rescore_stance_outcomes.py                # dry run
  python web_dashboard/scripts/rescore_stance_outcomes.py --execute
"""

from __future__ import annotations

import argparse
import sys
import warnings
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

_SCRIPT_DIR = Path(__file__).resolve().parent
_WEB_DASHBOARD = _SCRIPT_DIR.parent
_REPO_ROOT = _WEB_DASHBOARD.parent
for p in (str(_WEB_DASHBOARD), str(_REPO_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

warnings.filterwarnings("ignore")

TARGET_VERSION = 2


def _hit(stance: str, excess: Any) -> bool | None:
    """Mirror of track_record_service._hit_from_row, kept local to avoid a UI import."""
    if excess is None:
        return None
    s = (stance or "").upper()
    ex = float(excess)
    if s in {"BUY", "BULLISH", "VERY_BULLISH"}:
        return ex > 0
    if s in {"SELL", "BEARISH", "VERY_BEARISH", "AVOID"}:
        return ex < 0
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true", help="write the new scores")
    parser.add_argument("--limit", type=int, default=0, help="cap rows processed (0 = all)")
    args = parser.parse_args()

    from benchmarks import resolve_benchmark
    from postgres_client import PostgresClient
    from scheduler.jobs_stance_outcomes import (
        _fetch_benchmark_closes,
        _fetch_ticker_closes_resolved,
        compute_excess_return,
        _nearest_close_on_or_before,
        _to_decimal,
    )
    from supabase_client import SupabaseClient

    pg = PostgresClient()
    supabase = SupabaseClient(use_service_role=True)
    now = datetime.now(UTC)

    rows = pg.execute_query(
        """
        SELECT so.stance_id, so.horizon_days, so.excess_return AS old_excess,
               so.benchmark_symbol AS old_benchmark, so.scoring_version,
               sh.ticker, sh.stance, sh.as_of, sh.price_at_stance,
               s.market_cap, s.price_symbol, s.currency, s.benchmark_override
        FROM stance_outcomes so
        JOIN stance_history sh ON sh.id = so.stance_id
        LEFT JOIN securities s ON upper(s.ticker) = upper(sh.ticker)
        WHERE COALESCE(so.scoring_version, 1) < %s
        ORDER BY sh.as_of ASC
        """,
        (TARGET_VERSION,),
    )
    if args.limit:
        rows = rows[: args.limit]

    if not rows:
        print(f"Nothing to do: all rows already at scoring_version >= {TARGET_VERSION}.")
        return 0

    min_date = min(r["as_of"].date() for r in rows) - timedelta(days=7)
    max_date = now.date()
    print(f"{len(rows)} outcome row(s) to re-score; price window {min_date} .. {max_date}")
    print(f"mode: {'EXECUTE' if args.execute else 'DRY RUN'}\n")

    ticker_cache: dict[str, list[dict[str, Any]]] = {}
    bench_cache: dict[str, list[dict[str, Any]]] = {}
    resolved: dict[str, str] = {}

    changed_hit = 0
    changed_miss = 0
    unchanged = 0
    unscoreable = 0
    updated = 0
    bench_tally: dict[str, int] = defaultdict(int)

    for row in rows:
        ticker = str(row["ticker"] or "").upper()
        bench_symbol, _fallback = resolve_benchmark(
            ticker,
            market_cap=row.get("market_cap"),
            price_symbol=row.get("price_symbol"),
            currency=row.get("currency"),
            override=row.get("benchmark_override"),
        )
        bench_tally[bench_symbol] += 1

        if ticker not in ticker_cache:
            ticker_cache[ticker] = _fetch_ticker_closes_resolved(
                pg, ticker, min_date, max_date, resolved
            )
        if bench_symbol not in bench_cache:
            bench_cache[bench_symbol] = _fetch_benchmark_closes(
                supabase, min_date, max_date, bench_symbol
            )

        as_of = row["as_of"]
        baseline_date = as_of.date()
        end_date = (as_of + timedelta(days=int(row["horizon_days"]))).date()

        baseline_price = _to_decimal(row.get("price_at_stance")) or _nearest_close_on_or_before(
            ticker_cache[ticker], baseline_date
        )
        end_price = _nearest_close_on_or_before(ticker_cache[ticker], end_date)
        bench_baseline = _nearest_close_on_or_before(bench_cache[bench_symbol], baseline_date)
        bench_end = _nearest_close_on_or_before(bench_cache[bench_symbol], end_date)

        if None in (baseline_price, end_price, bench_baseline, bench_end):
            unscoreable += 1
            continue

        returns = compute_excess_return(baseline_price, end_price, bench_baseline, bench_end)
        new_excess = returns["excess_return"]
        if new_excess is None:
            unscoreable += 1
            continue

        old_hit = _hit(row["stance"], row.get("old_excess"))
        new_hit = _hit(row["stance"], new_excess)
        if old_hit != new_hit:
            if new_hit:
                changed_hit += 1
            else:
                changed_miss += 1
        else:
            unchanged += 1

        if args.execute:
            pg.execute_update(
                """
                UPDATE stance_outcomes
                SET ticker_return = %s,
                    benchmark_return = %s,
                    excess_return = %s,
                    benchmark_symbol = %s,
                    scoring_version = %s,
                    scored_at = NOW()
                WHERE stance_id = %s::uuid AND horizon_days = %s
                """,
                (
                    returns["ticker_return"],
                    returns["benchmark_return"],
                    new_excess,
                    bench_symbol,
                    TARGET_VERSION,
                    str(row["stance_id"]),
                    int(row["horizon_days"]),
                ),
            )
            updated += 1

    total_comparable = changed_hit + changed_miss + unchanged
    churn = (100.0 * (changed_hit + changed_miss) / total_comparable) if total_comparable else 0.0

    print("benchmark distribution:",
          " ".join(f"{k}={v}" for k, v in sorted(bench_tally.items())))
    print(f"\nverdict changes (old benchmark -> per-ticker benchmark):")
    print(f"  miss -> hit : {changed_hit}")
    print(f"  hit  -> miss: {changed_miss}")
    print(f"  unchanged   : {unchanged}")
    print(f"  churn       : {churn:.1f}% of comparable rows")
    print(f"  unscoreable : {unscoreable} (missing price on either side)")

    if args.execute:
        print(f"\nupdated {updated} row(s) to scoring_version={TARGET_VERSION}")
    else:
        print("\nDry run. Re-run with --execute to write.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
