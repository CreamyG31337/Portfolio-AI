#!/usr/bin/env python3
"""Insider buy-vs-sell event study — positive control for the measurement rig.

WHY THIS EXISTS
---------------
The stance track record shows no detectable edge. That result is only meaningful if
the measurement apparatus can detect an edge that genuinely exists -- otherwise
"no edge found" and "cannot find edges" are indistinguishable.

Insider trading is the natural control: it is well documented that insider PURCHASES
carry information while SALES mostly do not (insiders sell for liquidity,
diversification and tax reasons unrelated to their view). If this pipeline cannot
reproduce that asymmetry on 18k purchases across 3.7k tickers, the pipeline is broken
-- not the hypothesis.

Uses no LLM, no idea_triage clicks, and no stance ledger.

METHODOLOGY (the parts that matter)
-----------------------------------
1. EVENT DATE = ``disclosure_date``, never ``transaction_date``.
   Form 4 filings lag the trade: median 2 days here, 28% beyond 2 days, max 68.
   Measuring from transaction_date would capture price moves that occurred before
   anyone could have known -- manufacturing a large fake edge. This is the single
   easiest way to get a spuriously strong result, so it is the default and there is
   deliberately no flag to switch it off.

2. ENTRY = the first close STRICTLY AFTER the disclosure date.
   disclosure_date has no reliable intraday timestamp, so entering at that day's
   close could assume knowledge of a filing published after the bell. Entering the
   next session is unambiguously tradeable.

3. EVENTS ARE DEDUPED to (ticker, disclosure_date, type).
   A company-day where eight insiders all filed is ONE event, not eight. Without
   this, a handful of clustered filings dominate the average and the effective
   sample size is far smaller than the row count suggests.

4. HEADLINE = the PURCHASE - SALE spread.
   Absolute excess depends on benchmark choice; the spread does not, because both
   sides draw from the same universe and get the same benchmark treatment. Absolute
   numbers are reported too, but the spread is the robust statistic.

5. BASELINE = day-bucketed random relabelling, matching the stance track record's
   null model, so the two are read the same way.

Run from project root:
  python web_dashboard/scripts/insider_event_study.py
  python web_dashboard/scripts/insider_event_study.py --sample-tickers 800 --horizon 30
"""

from __future__ import annotations

import argparse
import random
import statistics
import sys
import warnings
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any

_SCRIPT_DIR = Path(__file__).resolve().parent
_WEB_DASHBOARD = _SCRIPT_DIR.parent
_REPO_ROOT = _WEB_DASHBOARD.parent
for p in (str(_WEB_DASHBOARD), str(_REPO_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

warnings.filterwarnings("ignore")

PURCHASE = "Purchase"
SALE = "Sale"
PRICE_BATCH = 100


def _fetch_events(sb: Any, since: str) -> list[dict[str, Any]]:
    """Page through insider_trades (PostgREST caps a single response at 1000 rows)."""
    out: list[dict[str, Any]] = []
    step = 1000
    off = 0
    while True:
        resp = (
            sb.supabase.table("insider_trades")
            .select("ticker,type,transaction_date,disclosure_date,value,shares")
            .gte("disclosure_date", since)
            .in_("type", [PURCHASE, SALE])
            .order("disclosure_date")
            .range(off, off + step - 1)
            .execute()
        )
        data = resp.data or []
        out.extend(data)
        if len(data) < step:
            return out
        off += step


def _dedupe_to_company_day(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse to one event per (ticker, disclosure day, direction)."""
    grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
    for r in rows:
        ticker = str(r.get("ticker") or "").strip().upper()
        disclosed = str(r.get("disclosure_date") or "")[:10]
        kind = str(r.get("type") or "")
        if not ticker or not disclosed or kind not in (PURCHASE, SALE):
            continue
        key = (ticker, disclosed, kind)
        slot = grouped.setdefault(
            key, {"ticker": ticker, "date": disclosed, "type": kind, "value": 0.0, "filings": 0}
        )
        try:
            slot["value"] += float(r.get("value") or 0)
        except (TypeError, ValueError):
            pass
        slot["filings"] += 1
    return list(grouped.values())


def _download_closes(tickers: list[str], start: date, end: date) -> dict[str, list[dict[str, Any]]]:
    """Batch-download closes. One call per PRICE_BATCH tickers, not one per ticker."""
    import pandas as pd
    import yfinance as yf

    out: dict[str, list[dict[str, Any]]] = {}
    for i in range(0, len(tickers), PRICE_BATCH):
        batch = tickers[i : i + PRICE_BATCH]
        print(f"  prices {i + 1}-{i + len(batch)} of {len(tickers)}...", flush=True)
        try:
            data = yf.download(
                batch,
                start=start.isoformat(),
                end=(end + timedelta(days=1)).isoformat(),
                progress=False,
                auto_adjust=True,
                group_by="ticker",
                threads=True,
            )
        except Exception as exc:
            print(f"    batch failed: {exc}")
            continue
        if data is None or data.empty:
            continue

        # yfinance returns MultiIndex columns for a multi-ticker request but FLAT
        # columns for a single ticker. Benchmarks are fetched one symbol at a time,
        # so mishandling the flat case silently yields no benchmark data -- and then
        # every event is unpriceable, which looks like a data problem rather than a
        # bug. Handle both shapes explicitly.
        multi = isinstance(data.columns, pd.MultiIndex)
        available = set(data.columns.get_level_values(0)) if multi else set()

        for symbol in batch:
            try:
                if multi:
                    if symbol not in available:
                        continue
                    closes = data[symbol]["Close"].dropna()
                else:
                    closes = data["Close"].dropna()
            except Exception:
                continue
            series = [
                {"date": idx.date(), "close": float(val)}
                for idx, val in closes.items()
                if val == val
            ]
            if series:
                out[symbol] = sorted(series, key=lambda r: r["date"])
    return out


def _close_after(series: list[dict[str, Any]], target: date) -> tuple[date, float] | None:
    """First close STRICTLY after target (entry must be tradeable, never same-session)."""
    for row in series:
        if row["date"] > target:
            return row["date"], row["close"]
    return None


def _close_on_or_before(series: list[dict[str, Any]], target: date) -> float | None:
    best = None
    for row in series:
        if row["date"] <= target:
            best = row["close"]
        else:
            break
    return best


def _pct(a: float, b: float) -> float | None:
    if a is None or b is None or a == 0:
        return None
    return (b - a) / a * 100.0


def _summarise(label: str, excesses: list[float]) -> dict[str, Any]:
    if not excesses:
        return {"label": label, "n": 0}
    return {
        "label": label,
        "n": len(excesses),
        "mean": statistics.mean(excesses),
        "median": statistics.median(excesses),
        "hit_rate": sum(1 for e in excesses if e > 0) / len(excesses),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--since", default="2025-01-01", help="earliest disclosure_date")
    parser.add_argument("--horizon", type=int, default=30, help="holding period in calendar days")
    parser.add_argument("--sample-tickers", type=int, default=600,
                        help="random ticker sample for price fetching (0 = all)")
    parser.add_argument("--seed", type=int, default=17)
    args = parser.parse_args()

    from benchmarks import resolve_benchmark
    from postgres_client import PostgresClient
    from supabase_client import SupabaseClient

    sb = SupabaseClient(use_service_role=True)
    pg = PostgresClient()

    print(f"Fetching insider events disclosed since {args.since}...")
    raw = _fetch_events(sb, args.since)
    events = _dedupe_to_company_day(raw)
    print(f"  {len(raw)} filings -> {len(events)} company-day events "
          f"({sum(1 for e in events if e['type'] == PURCHASE)} purchase / "
          f"{sum(1 for e in events if e['type'] == SALE)} sale)")

    all_tickers = sorted({e["ticker"] for e in events})
    if args.sample_tickers and len(all_tickers) > args.sample_tickers:
        rng = random.Random(args.seed)
        # Random, not top-N: sampling the most-traded names would bias toward large
        # caps and heavy filers, which is exactly where insider signal differs.
        tickers = sorted(rng.sample(all_tickers, args.sample_tickers))
        print(f"  sampling {len(tickers)} of {len(all_tickers)} tickers (seed {args.seed})")
    else:
        tickers = all_tickers
    keep = set(tickers)
    events = [e for e in events if e["ticker"] in keep]

    # Benchmark per ticker, reusing the M2a rules so this study and the stance track
    # record are measured the same way.
    meta_rows = pg.execute_query(
        "SELECT upper(ticker) AS ticker, market_cap, price_symbol, currency, benchmark_override "
        "FROM securities WHERE upper(ticker) = ANY(%s)",
        (tickers,),
    )
    meta = {str(r["ticker"]): dict(r) for r in meta_rows}
    bench_of: dict[str, str] = {}
    for t in tickers:
        m = meta.get(t, {})
        symbol, _fallback = resolve_benchmark(
            t,
            market_cap=m.get("market_cap"),
            price_symbol=m.get("price_symbol"),
            currency=m.get("currency"),
            override=m.get("benchmark_override"),
        )
        bench_of[t] = symbol

    dates = [date.fromisoformat(e["date"]) for e in events]
    start = min(dates) - timedelta(days=10)
    end = min(date.today(), max(dates) + timedelta(days=args.horizon + 10))

    print(f"Downloading prices {start} .. {end}")
    closes = _download_closes(tickers, start, end)
    bench_symbols = sorted(set(bench_of.values()))
    bench_closes = _download_closes(bench_symbols, start, end)
    print(f"  prices for {len(closes)}/{len(tickers)} tickers, "
          f"{len(bench_closes)}/{len(bench_symbols)} benchmarks")

    by_type: dict[str, list[float]] = defaultdict(list)
    per_day: dict[str, list[tuple[str, float]]] = defaultdict(list)
    by_ticker: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    skipped = 0

    for ev in events:
        series = closes.get(ev["ticker"])
        bseries = bench_closes.get(bench_of.get(ev["ticker"], ""))
        if not series or not bseries:
            skipped += 1
            continue
        event_date = date.fromisoformat(ev["date"])
        entry = _close_after(series, event_date)
        bentry = _close_after(bseries, event_date)
        if not entry or not bentry:
            skipped += 1
            continue
        exit_date = entry[0] + timedelta(days=args.horizon)
        if exit_date > end:
            skipped += 1
            continue
        exit_px = _close_on_or_before(series, exit_date)
        bexit = _close_on_or_before(bseries, exit_date)
        if exit_px is None or bexit is None:
            skipped += 1
            continue
        r = _pct(entry[1], exit_px)
        br = _pct(bentry[1], bexit)
        if r is None or br is None:
            skipped += 1
            continue
        excess = r - br
        by_type[ev["type"]].append(excess)
        per_day[ev["date"]].append((ev["type"], excess))
        # Raw return (not excess) for the within-ticker paired test below: that design
        # needs no benchmark at all, so keeping the unadjusted number avoids importing
        # benchmark error into the one statistic built to be free of it.
        by_ticker[ev["ticker"]][ev["type"]].append(r)

    buys = _summarise("PURCHASE", by_type[PURCHASE])
    sells = _summarise("SALE", by_type[SALE])

    print(f"\n{'=' * 66}")
    print(f"INSIDER EVENT STUDY — {args.horizon}d excess return vs per-ticker benchmark")
    print(f"entry = first close after disclosure_date | {skipped} events unpriceable")
    print("=" * 66)
    print(f"{'':<10} {'n':>7} {'mean':>9} {'median':>9} {'hit rate':>10}")
    for s in (buys, sells):
        if not s["n"]:
            print(f"{s['label']:<10} {0:>7}")
            continue
        print(f"{s['label']:<10} {s['n']:>7} {s['mean']:>+8.2f}% {s['median']:>+8.2f}% "
              f"{s['hit_rate']:>9.1%}")

    if buys["n"] and sells["n"]:
        spread = buys["mean"] - sells["mean"]
        hit_spread = buys["hit_rate"] - sells["hit_rate"]
        print("-" * 66)
        print(f"{'SPREAD':<10} {'':>7} {spread:>+8.2f}% {'':>9} {hit_spread:>+9.1%}")
        print("\n(the spread is the robust statistic: benchmark misspecification affects")
        print(" both sides equally and cancels)")

        # Day-bucketed null, same construction as the stance track record: hold the
        # day's outcomes fixed and deal the buy/sell labels at random.
        exp_buy_hits = 0.0
        n_buy = 0
        for day_rows in per_day.values():
            total = len(day_rows)
            if not total:
                continue
            pos = sum(1 for _t, e in day_rows if e > 0)
            b = sum(1 for t, _e in day_rows if t == PURCHASE)
            exp_buy_hits += b * pos / total
            n_buy += b
        if n_buy:
            print(f"\nno-skill baseline for purchases: {exp_buy_hits / n_buy:.1%} "
                  f"(actual {buys['hit_rate']:.1%}, "
                  f"edge {buys['hit_rate'] - exp_buy_hits / n_buy:+.1%})")

    # ------------------------------------------------------------------
    # Within-ticker paired test: the design that removes benchmark risk.
    #
    # The cross-sectional spread above is confounded whenever the purchase and sale
    # baskets differ systematically -- and they do: insider purchases concentrate in
    # small caps, sales in large caps (executives disposing of vested equity). With
    # an unknown market cap both legs fall back to the broad index, which penalises
    # the smaller-cap purchase basket and does NOT cancel in the spread.
    #
    # Comparing purchases against sales IN THE SAME TICKER makes every stock its own
    # control: size, sector, benchmark and market regime are identical on both legs,
    # so they cancel exactly. Each ticker contributes one paired observation and is
    # weighted equally, so a single heavily-traded name cannot dominate.
    # ------------------------------------------------------------------
    paired: list[float] = []
    for _t, sides in by_ticker.items():
        if sides.get(PURCHASE) and sides.get(SALE):
            paired.append(statistics.mean(sides[PURCHASE]) - statistics.mean(sides[SALE]))

    print("\n" + "=" * 66)
    print("WITHIN-TICKER PAIRED TEST (each stock is its own control)")
    print("=" * 66)
    if len(paired) < 2:
        print(f"only {len(paired)} ticker(s) have both a purchase and a sale event —")
        print("not enough for the paired test; widen --sample-tickers.")
    else:
        mean_p = statistics.mean(paired)
        med_p = statistics.median(paired)
        sd = statistics.stdev(paired)
        se = sd / (len(paired) ** 0.5)
        share_pos = sum(1 for p in paired if p > 0) / len(paired)
        print(f"tickers with both legs : {len(paired)}")
        print(f"mean purchase - sale   : {mean_p:+.2f}%  (se {se:.2f}, t {mean_p / se:+.2f})")
        print(f"median                 : {med_p:+.2f}%")
        print(f"tickers where buys won : {share_pos:.1%}")
        if abs(mean_p / se) < 2:
            print("\n-> within ~2 standard errors of zero: NO significant asymmetry detected.")
        elif mean_p > 0:
            print("\n-> purchases significantly outperform sales: the expected asymmetry IS")
            print("   reproduced, so the pipeline can detect a real effect.")
        else:
            print("\n-> purchases significantly UNDERperform sales: contrary to the prior.")
            print("   Suspect the pipeline before believing this.")

    print("\nVERDICT GUIDE: purchases should beat sales. Read the PAIRED test, not the")
    print("cross-sectional spread — the latter is confounded by size differences")
    print("between the purchase and sale baskets whenever market caps are unknown.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
