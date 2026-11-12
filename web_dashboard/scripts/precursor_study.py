#!/usr/bin/env python3
"""Winners-first study, step 3 (ROADMAP Phase L3): which signals came BEFORE the move?

Input: ``logs/study/windows.csv.gz`` from ``winners_study.py label`` (one row per
(window, ticker) with peer-relative return ``rel`` and a winner/loser/control label)
and ``logs/study/prices.csv.gz``.

For every (window, ticker) we record which signals fired in the PRE-PERIOD, the
``PRE_DAYS`` calendar days before the window started, using only point-in-time dates
(insider/congress ``disclosure_date``, article ``fetched_at``, ETF log ``date``,
stance ``as_of``). Then, per signal: does the window's peer-relative return differ
between stocks WITH the signal and stocks WITHOUT it?

PRE-REGISTERED TEST (fixed in code before looking at the holdout)
-----------------------------------------------------------------
* Discovery = windows starting Jan-Apr 2026. Holdout = windows starting Jun-Aug 2026.
  May is skipped: its window overlaps both.
* A signal PASSES discovery when it fires on >= MIN_WITH stock-windows and the
  bootstrap CI of (mean rel WITH - mean rel WITHOUT) excludes zero. The bootstrap
  resamples whole tickers, because one stock appears in several overlapping windows.
* ``rel`` is winsorised at the 1st/99th percentile for means. A +290% squeeze must not
  decide the result on its own. Medians are reported too.
* Each signal is only evaluated on windows where its source covers the whole
  pre-period (``coverage_start``). A signal with no data looks like "absent",
  which would bias the comparison.
* The holdout is reported for every signal, with discovery passers flagged. Only a
  signal that passes discovery AND keeps its sign with a CI excluding zero on the
  holdout is a candidate rule for L4.

Run inside the Flask container after ``winners_study.py label``:
  docker exec -w /app trading-dashboard-flask python web_dashboard/scripts/precursor_study.py
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable

_SCRIPT_DIR = Path(__file__).resolve().parent
_WEB_DASHBOARD = _SCRIPT_DIR.parent
for p in (str(_WEB_DASHBOARD), str(_WEB_DASHBOARD.parent), str(_SCRIPT_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

DEFAULT_OUT = _WEB_DASHBOARD / "logs" / "study"
PRE_DAYS = 60
MIN_WITH = 30
BOOT = 1000
SEED = 20261112
DISCOVERY_MONTHS = (1, 2, 3, 4)
HOLDOUT_MONTHS = (6, 7, 8)
ACTIVE_ETFS = ("ARKK", "ARKW", "ARKF", "ARKG", "ARKQ", "ARKX")
# Source coverage starts (first date the source has data). A window is eligible for a
# signal only when its whole pre-period lies after this date (a few days' slack).
COVERAGE = {
    "insider": date(2020, 1, 1),
    "congress": date(2020, 1, 1),
    "articles": date(2025, 12, 25),
    "etf": date(2026, 1, 3),
    "momentum": date(2025, 12, 1),  # needs ~63 trading days of prices before the window
    "alpha_idea": date(2025, 12, 25),  # ideas exist as far back as the articles
}
SLACK_DAYS = 5


# --------------------------------------------------------------------------- loading


def _ticker_set(series: pd.Series) -> set[str]:
    return {str(t).upper().strip() for t in series.dropna()}


def load_insiders(universe: set[str], since: date) -> pd.DataFrame:
    from supabase_client import SupabaseClient
    from supabase_pagination import fetch_all_rows

    sb = SupabaseClient(use_service_role=True)
    rows = fetch_all_rows(
        sb, "insider_trades", select="ticker,insider_name,type,disclosure_date",
        apply_query=lambda q: q.gte("disclosure_date", since.isoformat()), order="id",
    )
    df = pd.DataFrame(rows)
    df["ticker"] = df["ticker"].str.upper().str.strip()
    df = df[df["ticker"].isin(universe)].copy()
    df["d"] = pd.to_datetime(df["disclosure_date"]).dt.date
    return df


def load_congress(universe: set[str], since: date) -> pd.DataFrame:
    from supabase_client import SupabaseClient
    from supabase_pagination import fetch_all_rows

    sb = SupabaseClient(use_service_role=True)
    rows = fetch_all_rows(
        sb, "congress_trades", select="ticker,type,disclosure_date",
        apply_query=lambda q: q.gte("disclosure_date", since.isoformat()), order="id",
    )
    df = pd.DataFrame(rows)
    df["ticker"] = df["ticker"].fillna("").str.upper().str.strip()
    df = df[df["ticker"].isin(universe)].copy()
    df["d"] = pd.to_datetime(df["disclosure_date"]).dt.date
    return df


def load_articles(pg: Any, universe: set[str], since: date) -> pd.DataFrame:
    rows = pg.execute_query(
        """
        SELECT upper(t) AS ticker, ra.fetched_at::date AS d, upper(COALESCE(ra.sentiment,'')) AS s
        FROM research_articles ra,
             unnest(COALESCE(NULLIF(ra.tickers, '{}'), ARRAY[ra.ticker])) AS t
        WHERE ra.fetched_at >= %s AND t IS NOT NULL
        """,
        (since,),
    )
    df = pd.DataFrame(rows)
    return df[df["ticker"].isin(universe)].copy()


def load_etf_buys(pg: Any, universe: set[str], since: date) -> pd.DataFrame:
    rows = pg.execute_query(
        """
        SELECT upper(holding_ticker) AS ticker, date AS d
        FROM etf_holdings_changes
        WHERE action = 'BUY' AND etf_ticker = ANY(%s) AND date >= %s
        """,
        (list(ACTIVE_ETFS), since),
    )
    df = pd.DataFrame(rows)
    return df[df["ticker"].isin(universe)].copy() if len(df) else df


def load_alpha_ideas(pg: Any, universe: set[str]) -> pd.DataFrame:
    """Bullish ideas by the date the article was FETCHED (when we could have known)."""
    rows = pg.execute_query(
        """
        SELECT upper(ticker) AS ticker,
               (metadata->'idea'->>'fetched_at')::timestamptz::date AS d
        FROM stance_history
        WHERE source = 'alpha_idea' AND upper(stance) = 'BULLISH'
        """
    )
    df = pd.DataFrame(rows)
    return df[df["ticker"].isin(universe)].copy() if len(df) else df


# --------------------------------------------------------------------------- features


def _count_in(df: pd.DataFrame, lo: date, hi: date, mask: pd.Series | None = None) -> pd.Series:
    sub = df if mask is None else df[mask]
    sub = sub[(sub["d"] >= lo) & (sub["d"] < hi)]
    return sub.groupby("ticker").size()


def build_features(
    windows: pd.DataFrame,
    panel: pd.DataFrame,
    *,
    insiders: pd.DataFrame,
    congress: pd.DataFrame,
    articles: pd.DataFrame,
    etf: pd.DataFrame,
    ideas: pd.DataFrame,
) -> pd.DataFrame:
    """Add one boolean column per signal (NaN where the source does not cover the window)."""
    out: list[pd.DataFrame] = []
    trading_days = panel.index
    for ws, g in windows.groupby("window_start"):
        s = pd.Timestamp(ws).date()
        lo, hi = s - timedelta(days=PRE_DAYS), s
        g = g.copy()
        t = g["ticker"]

        def covered(src: str) -> bool:
            return COVERAGE[src] <= lo + timedelta(days=SLACK_DAYS)

        def put(name: str, src: str, values: pd.Series) -> None:
            g[name] = values.astype(float) if covered(src) else np.nan

        buy_mask = insiders["type"].str.lower().str.startswith("purchase")
        sell_mask = insiders["type"].str.lower().str.startswith("sale")
        ib = _count_in(insiders, lo, hi, buy_mask)
        isell = _count_in(insiders, lo, hi, sell_mask)
        buyers = (
            insiders[buy_mask & (insiders["d"] >= lo) & (insiders["d"] < hi)]
            .groupby("ticker")["insider_name"].nunique()
        )
        put("insider_buy", "insider", t.map(ib).fillna(0) >= 1)
        put("insider_buy_cluster", "insider", t.map(buyers).fillna(0) >= 2)
        put("insider_sell_heavy", "insider", t.map(isell).fillna(0) >= 3)

        cb = _count_in(congress, lo, hi, congress["type"].str.lower().str.startswith("purchase"))
        put("congress_buy", "congress", t.map(cb).fillna(0) >= 1)

        a_all = _count_in(articles, lo, hi)
        a_bull = _count_in(articles, lo, hi, articles["s"] == "BULLISH")
        a_bear = _count_in(articles, lo, hi, articles["s"] == "BEARISH")
        put("article_any", "articles", t.map(a_all).fillna(0) >= 1)
        put("article_burst", "articles", t.map(a_all).fillna(0) >= 5)
        put("article_bullish", "articles", t.map(a_bull).fillna(0) >= 1)
        put("article_bearish", "articles", t.map(a_bear).fillna(0) >= 1)

        if len(etf):
            eb = _count_in(etf, lo, hi)
            put("ark_buy", "etf", t.map(eb).fillna(0) >= 1)
        if len(ideas):
            ib2 = _count_in(ideas, lo, hi)
            put("alpha_idea_bullish", "alpha_idea", t.map(ib2).fillna(0) >= 1)

        # Prior-quarter peer-relative momentum, ranked within the same peer group.
        s_idx = trading_days.searchsorted(pd.Timestamp(s))
        if s_idx >= 63:
            p0, p1 = panel.iloc[s_idx - 63], panel.iloc[s_idx - 1]
            prior = (p1 / p0 - 1.0).reindex(t.values).values
            g["prior_ret"] = prior
            g["prior_rel"] = g["prior_ret"] - g.groupby("group")["prior_ret"].transform("median")
            pct = g.groupby("group")["prior_rel"].rank(pct=True)
            g["momentum_top"] = np.where(pct.notna(), (pct >= 0.9).astype(float), np.nan)
            g["momentum_bottom"] = np.where(pct.notna(), (pct <= 0.1).astype(float), np.nan)
        else:
            g["momentum_top"] = np.nan
            g["momentum_bottom"] = np.nan
        out.append(g)
    return pd.concat(out, ignore_index=True)


# --------------------------------------------------------------------------- stats


def _winsor(x: pd.Series) -> pd.Series:
    lo, hi = x.quantile(0.01), x.quantile(0.99)
    return x.clip(lo, hi)


def evaluate(df: pd.DataFrame, signal: str, rng: np.random.Generator) -> dict[str, Any] | None:
    d = df.dropna(subset=[signal, "rel"])
    if d.empty:
        return None
    d = d.assign(relw=_winsor(d["rel"]) * 100.0, rel100=d["rel"] * 100.0)
    w = d[d[signal] == 1.0]
    wo = d[d[signal] == 0.0]
    if len(w) == 0 or len(wo) == 0:
        return {"signal": signal, "n_with": len(w), "n_without": len(wo)}
    diff = float(w["relw"].mean() - wo["relw"].mean())

    # Cluster bootstrap over tickers, vectorised: resampling tickers with
    # replacement == drawing a multiplicity count per ticker, so each replicate's
    # group means are (counts @ per-ticker sums) / (counts @ per-ticker n).
    is_w = (d[signal] == 1.0).astype(float)
    per_t = pd.DataFrame({
        "sw": d["relw"] * is_w, "nw": is_w,
        "so": d["relw"] * (1 - is_w), "no": 1 - is_w,
    }).groupby(d["ticker"]).sum()
    k = len(per_t)
    counts = np.stack([np.bincount(rng.integers(0, k, k), minlength=k) for _ in range(BOOT)])
    nw, no = counts @ per_t["nw"].to_numpy(), counts @ per_t["no"].to_numpy()
    ok = (nw > 0) & (no > 0)
    diffs = (counts @ per_t["sw"].to_numpy())[ok] / nw[ok] - (counts @ per_t["so"].to_numpy())[ok] / no[ok]
    lo, hi = (np.percentile(diffs, [2.5, 97.5]) if len(diffs) else (np.nan, np.nan))
    return {
        "signal": signal,
        "n_with": len(w),
        "n_without": len(wo),
        "tickers_with": w["ticker"].nunique(),
        "mean_with": round(float(w["relw"].mean()), 2),
        "mean_without": round(float(wo["relw"].mean()), 2),
        "diff": round(diff, 2),
        "ci_lo": round(float(lo), 2),
        "ci_hi": round(float(hi), 2),
        "median_with": round(float(w["rel100"].median()), 2),
        "median_without": round(float(wo["rel100"].median()), 2),
        "p_winner_with": round(100 * float((w["label"] == "winner").mean()), 1),
        "p_loser_with": round(100 * float((w["label"] == "loser").mean()), 1),
        "p_winner_without": round(100 * float((wo["label"] == "winner").mean()), 1),
    }


def run_split(df: pd.DataFrame, signals: list[str], months: tuple[int, ...]) -> pd.DataFrame:
    rng = np.random.default_rng(SEED)
    sub = df[pd.to_datetime(df["window_start"]).dt.month.isin(months)]
    rows = [r for s in signals if (r := evaluate(sub, s, rng))]
    return pd.DataFrame(rows).set_index("signal")


# --------------------------------------------------------------------------- main


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args()
    out = Path(args.out)

    from postgres_client import PostgresClient

    windows = pd.read_csv(out / "windows.csv.gz")
    panel = pd.read_csv(out / "prices.csv.gz", index_col=0, parse_dates=True).sort_index()
    universe = _ticker_set(windows["ticker"])
    earliest = pd.to_datetime(windows["window_start"]).min().date() - timedelta(days=PRE_DAYS + 5)

    pg = PostgresClient()
    print("loading sources...", flush=True)
    insiders = load_insiders(universe, earliest)
    congress = load_congress(universe, earliest)
    articles = load_articles(pg, universe, earliest)
    etf = load_etf_buys(pg, universe, earliest)
    ideas = load_alpha_ideas(pg, universe)
    print(f"  insiders {len(insiders)}  congress {len(congress)}  article-mentions {len(articles)}"
          f"  ark buys {len(etf)}  bullish ideas {len(ideas)}")

    feats = build_features(windows, panel, insiders=insiders, congress=congress,
                           articles=articles, etf=etf, ideas=ideas)
    feats.to_csv(out / "precursor_features.csv.gz", index=False)
    signals = [c for c in (
        "insider_buy", "insider_buy_cluster", "insider_sell_heavy", "congress_buy",
        "article_any", "article_burst", "article_bullish", "article_bearish",
        "ark_buy", "alpha_idea_bullish", "momentum_top", "momentum_bottom",
    ) if c in feats.columns]

    cols = ["n_with", "tickers_with", "mean_with", "mean_without", "diff", "ci_lo", "ci_hi",
            "median_with", "median_without", "p_winner_with", "p_loser_with"]
    disc = run_split(feats, signals, DISCOVERY_MONTHS)
    disc["passes"] = (disc["n_with"] >= MIN_WITH) & ((disc["ci_lo"] > 0) | (disc["ci_hi"] < 0))
    print(f"\n=== DISCOVERY (windows starting months {DISCOVERY_MONTHS}) — rel in % vs peers, winsorised means")
    print(disc[[c for c in cols if c in disc.columns] + ["passes"]].to_string())

    hold = run_split(feats, signals, HOLDOUT_MONTHS)
    hold["passed_discovery"] = hold.index.map(lambda s: bool(disc["passes"].get(s, False)))
    same_sign = np.sign(hold["diff"]) == np.sign(disc["diff"].reindex(hold.index))
    hold["confirmed"] = (
        hold["passed_discovery"] & same_sign
        & ((hold["ci_lo"] > 0) | (hold["ci_hi"] < 0))
    )
    print(f"\n=== HOLDOUT (windows starting months {HOLDOUT_MONTHS})")
    print(hold[[c for c in cols if c in hold.columns] + ["passed_discovery", "confirmed"]].to_string())

    disc.to_csv(out / "precursor_discovery.csv")
    hold.to_csv(out / "precursor_holdout.csv")
    confirmed = list(hold.index[hold["confirmed"]])
    print(f"\nCONFIRMED (passed discovery and holdout): {confirmed or 'none'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
