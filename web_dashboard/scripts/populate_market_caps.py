#!/usr/bin/env python3
"""Populate securities.market_cap for tickers that carry stances (measurement rig M2a).

Market cap drives the US small/large benchmark split (< $2B -> ^RUT, else ^GSPC).
Without it every US ticker resolves to the broad index flagged as a fallback, which
is safe but blunt -- genuinely small names get measured against the S&P 500.

Creates a securities row when one is missing: 51 of the stance tickers have none.

Run from project root:
  python web_dashboard/scripts/populate_market_caps.py            # dry run
  python web_dashboard/scripts/populate_market_caps.py --execute
  python web_dashboard/scripts/populate_market_caps.py --execute --stale-days 30
"""

from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path
from typing import Any

_SCRIPT_DIR = Path(__file__).resolve().parent
_WEB_DASHBOARD = _SCRIPT_DIR.parent
_REPO_ROOT = _WEB_DASHBOARD.parent
for p in (str(_WEB_DASHBOARD), str(_REPO_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

warnings.filterwarnings("ignore")


def _safe(text: Any, width: int = 12) -> str:
    s = str(text if text is not None else "")[:width]
    try:
        s.encode(sys.stdout.encoding or "utf-8")
        return s
    except (UnicodeEncodeError, TypeError):
        return s.encode("ascii", "replace").decode("ascii")


def _fetch_market_cap(symbol: str) -> float | None:
    import yfinance as yf

    try:
        info = yf.Ticker(symbol).get_info()
    except Exception:
        return None
    for key in ("marketCap", "market_cap"):
        value = (info or {}).get(key)
        if value:
            try:
                out = float(value)
            except (TypeError, ValueError):
                continue
            if out > 0:
                return out
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true", help="write to the DB")
    parser.add_argument("--stale-days", type=int, default=30,
                        help="refresh caps older than this many days (default 30)")
    parser.add_argument("--limit", type=int, default=0, help="cap tickers processed (0 = all)")
    args = parser.parse_args()

    from benchmarks import resolve_benchmark
    from postgres_client import PostgresClient

    pg = PostgresClient()

    rows = pg.execute_query(
        """
        SELECT DISTINCT upper(sh.ticker) AS ticker,
               s.market_cap, s.market_cap_set_at, s.price_symbol, s.currency,
               s.benchmark_override
        FROM stance_history sh
        LEFT JOIN securities s ON upper(s.ticker) = upper(sh.ticker)
        WHERE (s.market_cap IS NULL
               OR s.market_cap_set_at IS NULL
               OR s.market_cap_set_at < NOW() - INTERVAL '1 day' * %s)
        ORDER BY 1
        """,
        (args.stale_days,),
    )
    if args.limit:
        rows = rows[: args.limit]

    print(f"{len(rows)} ticker(s) need a market cap "
          f"({'EXECUTE' if args.execute else 'DRY RUN'})\n")
    print(f"{'ticker':<12} {'market_cap':>18}  {'benchmark':<10} note")
    print("-" * 62)

    updated = 0
    unresolved: list[str] = []
    bench_tally: dict[str, int] = {}

    for row in rows:
        ticker = str(row["ticker"])
        # Prefer the alias the scoring job already resolved (e.g. TECK.B -> TECK-B.TO).
        symbol = str(row.get("price_symbol") or ticker)
        cap = _fetch_market_cap(symbol)

        bench, fallback = resolve_benchmark(
            ticker,
            market_cap=cap,
            price_symbol=row.get("price_symbol"),
            currency=row.get("currency"),
            override=row.get("benchmark_override"),
        )
        bench_tally[bench] = bench_tally.get(bench, 0) + 1

        note = ""
        if cap is None:
            unresolved.append(ticker)
            note = "no cap from provider" + (" (fallback benchmark)" if fallback else "")
        cap_s = f"{cap:,.0f}" if cap is not None else "-"
        print(f"{_safe(ticker):<12} {cap_s:>18}  {bench:<10} {note}")

        if args.execute and cap is not None:
            pg.execute_update(
                """
                INSERT INTO securities (ticker, market_cap, market_cap_set_at)
                VALUES (%s, %s, NOW())
                ON CONFLICT (ticker) DO UPDATE SET
                    market_cap = EXCLUDED.market_cap,
                    market_cap_set_at = NOW()
                """,
                (ticker, cap),
            )
            updated += 1

    print("\nbenchmark distribution:",
          " ".join(f"{k}={v}" for k, v in sorted(bench_tally.items())))
    if unresolved:
        print(f"no market cap for {len(unresolved)}: {', '.join(unresolved[:25])}")
        print("  (ETFs and indices legitimately have no market cap -- they resolve to the "
              "broad benchmark, which is correct for them)")
    if args.execute:
        print(f"\nupdated {updated} securities row(s)")
    else:
        print("\nDry run. Re-run with --execute to write.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
