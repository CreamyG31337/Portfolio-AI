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
# Discovery is frozen; the holdout grows as new windows complete (monthly re-run job).
DISCOVERY_BEFORE = date(2026, 5, 1)   # windows starting before this
HOLDOUT_FROM = date(2026, 6, 1)       # windows starting on/after this (May = gap)
MAX_SNAPSHOT_GAP_DAYS = 7  # a holdings change vs a snapshot older than this is not a daily change
ACTIVE_ETFS = ("ARKK", "ARKW", "ARKF", "ARKG", "ARKQ", "ARKX")
# ETF families. A share-count change is mostly fund flow (creations/redemptions move every
# holding by the same %), so the signals below use only the part of a change that differs
# from the fund's own median change that day, plus new positions and exits.
# Coverage = (first usable day, last day) of each family's feed; the iShares feeds stop
# 2026-05-15 so they can only be judged on discovery windows.
ETF_FAMILIES: dict[str, tuple[str, ...]] = {
    "ark": ACTIVE_ETFS,
    "ark_indexed": ("PRNT", "IZRL"),
    "theme": ("XBI", "SMH", "BUZZ", "OIH", "PPH", "BUG", "IBOT", "SMOT", "DAPP", "BOTZ",
              "SMHX", "MOAT", "LIT", "BBH", "FINX", "RTH"),
    "ishares": ("IVV", "IWM", "IWC", "IWO", "IBB", "ICLN", "SOXX"),
}
# Coverage is derived from etf_holdings_log: a family covers the stretches between
# feed outages (gaps > MAX_SNAPSHOT_GAP_DAYS), e.g. the iShares outage 2026-05-15..11-12.
ETF_PRE_DAYS = 30  # fund decisions are near-term; 60 would leave almost no covered windows
OVERWEIGHT_PP = 2.0  # holding's % change beats the fund's median % change that day by this
# Source coverage starts (first date the source has data). A window is eligible for a
# signal only when its whole pre-period lies after this date (a few days' slack).
COVERAGE = {
    "insider": date(2020, 1, 1),
    "congress": date(2020, 1, 1),
    "articles": date(2025, 12, 25),
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


def load_etf_events(pg: Any, universe: set[str]) -> pd.DataFrame:
    """Deliberate ETF decisions: new positions, exits, and flow-adjusted over/underweights.

    Returns ticker, d, family, kind in {new, exit, over, under}. Each fund's first logged
    day is dropped (the initial snapshot shows up as a wall of changes).
    """
    fam_of = {e: f for f, etfs in ETF_FAMILIES.items() for e in etfs}
    rows = pg.execute_query(
        """
        SELECT upper(etf_ticker) AS etf, upper(holding_ticker) AS ticker, date AS d,
               shares_before::float AS sb, shares_after::float AS sa, percent_change::float AS pc
        FROM etf_holdings_changes
        WHERE upper(etf_ticker) = ANY(%s)
        """,
        (list(fam_of),),
    )
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=["ticker", "d", "family", "kind"])
    # Keep only true day-over-day changes: drop each fund's first snapshot and any day
    # compared against a snapshot more than MAX_SNAPSHOT_GAP_DAYS old (feed outages).
    log_dates = pd.DataFrame(pg.execute_query(
        "SELECT DISTINCT upper(etf_ticker) AS etf, date AS d FROM etf_holdings_log "
        "WHERE upper(etf_ticker) = ANY(%s)",
        (list(fam_of),),
    )).sort_values(["etf", "d"])
    prev = log_dates.groupby("etf")["d"].shift()
    log_dates["gap"] = (pd.to_datetime(log_dates["d"]) - pd.to_datetime(prev)).dt.days
    df = df.merge(log_dates, on=["etf", "d"], how="left")
    df = df[df["gap"].notna() & (df["gap"] <= MAX_SNAPSHOT_GAP_DAYS)]
    sb, sa = df["sb"].fillna(0), df["sa"].fillna(0)
    new, exit_ = (sb <= 0) & (sa > 0), (sa <= 0) & (sb > 0)
    cont = ~new & ~exit_ & df["pc"].notna()
    med = df[cont].groupby(["etf", "d"])["pc"].transform("median")
    excess = (df.loc[cont, "pc"] - med).reindex(df.index)
    kind = pd.Series(pd.NA, index=df.index, dtype="object")
    kind[excess >= OVERWEIGHT_PP] = "over"
    kind[excess <= -OVERWEIGHT_PP] = "under"
    kind[new] = "new"
    kind[exit_] = "exit"
    out = df.assign(kind=kind, family=df["etf"].map(fam_of)).dropna(subset=["kind"])
    out = out[out["ticker"].isin(universe)]
    return out[["ticker", "d", "family", "kind"]].reset_index(drop=True)


def etf_coverage(pg: Any) -> dict[str, list[tuple[date, date]]]:
    """Per family, the (first usable day, last day) stretches between feed outages."""
    out: dict[str, list[tuple[date, date]]] = {}
    for fam, etfs in ETF_FAMILIES.items():
        rows = pg.execute_query(
            "SELECT DISTINCT date AS d FROM etf_holdings_log WHERE upper(etf_ticker) = ANY(%s) ORDER BY 1",
            (list(etfs),),
        )
        days = [r["d"] for r in rows]
        spans: list[tuple[date, date]] = []
        seg_start = None
        for i, d in enumerate(days):
            if i == 0 or (d - days[i - 1]).days > MAX_SNAPSHOT_GAP_DAYS:
                if seg_start is not None:
                    spans.append((seg_start, days[i - 1]))
                seg_start = d + timedelta(days=1)  # first change day compares to a stale snapshot
        if seg_start is not None and days:
            spans.append((seg_start, days[-1]))
        out[fam] = [(x, y) for x, y in spans if y >= x]
    return out


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
    etf_cov: dict[str, list[tuple[date, date]]] | None = None,
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

        elo = s - timedelta(days=ETF_PRE_DAYS)
        for fam in ETF_FAMILIES:
            ok = any(
                x <= elo + timedelta(days=SLACK_DAYS) and hi <= y + timedelta(days=1)
                for x, y in (etf_cov or {}).get(fam, [])
            )
            fe = etf[etf["family"] == fam] if len(etf) else etf
            for kinds, label in ((("new", "over"), "add"), (("new",), "new"), (("exit", "under"), "cut")):
                name = f"etf_{fam}_{label}"
                if not ok or fe.empty:
                    g[name] = np.nan
                    continue
                c = _count_in(fe, elo, hi, fe["kind"].isin(kinds))
                g[name] = (t.map(c).fillna(0) >= 1).astype(float)
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


def run_split(df: pd.DataFrame, signals: list[str], lo: date | None, hi: date | None) -> pd.DataFrame:
    rng = np.random.default_rng(SEED)
    ws = pd.to_datetime(df["window_start"]).dt.date
    keep = pd.Series(True, index=df.index)
    if lo:
        keep &= ws >= lo
    if hi:
        keep &= ws < hi
    sub = df[keep]
    rows = [r for s in signals if (r := evaluate(sub, s, rng))]
    return pd.DataFrame(rows).set_index("signal")


# --------------------------------------------------------------------------- summary


def write_summary(out: Path, disc: pd.DataFrame, hold: pd.DataFrame,
                  hold_windows: list[str], confirmed: list[str]) -> None:
    """precursor_latest.json: what the weekly retro shows (no human has to read the CSVs)."""
    import json
    from datetime import UTC, datetime

    def num(v: Any) -> float | None:
        try:
            f = float(v)
        except (TypeError, ValueError):
            return None
        return None if np.isnan(f) else round(f, 2)

    def part(df: pd.DataFrame, sig: str) -> dict[str, Any]:
        if sig not in df.index:
            return {"n": 0, "diff": None, "ci": None}
        r = df.loc[sig]
        return {"n": int(r.get("n_with") or 0), "diff": num(r.get("diff")),
                "ci": [num(r.get("ci_lo")), num(r.get("ci_hi"))]}

    rows = []
    for sig in disc.index.union(hold.index):
        d, h = part(disc, sig), part(hold, sig)
        rows.append({
            "signal": sig,
            "disc_n": d["n"], "disc_diff": d["diff"], "disc_ci": d["ci"],
            "passed_discovery": bool(disc["passes"].get(sig, False)),
            "hold_n": h["n"], "hold_diff": h["diff"], "hold_ci": h["ci"],
            "confirmed": sig in confirmed,
        })
    payload = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "discovery_before": DISCOVERY_BEFORE.isoformat(),
        "holdout_from": HOLDOUT_FROM.isoformat(),
        "holdout_windows": hold_windows,
        "confirmed": confirmed,
        "signals": rows,
    }
    (out / "precursor_latest.json").write_text(json.dumps(payload, indent=1), encoding="utf-8")


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
    etf = load_etf_events(pg, universe)
    etf_cov = etf_coverage(pg)
    ideas = load_alpha_ideas(pg, universe)
    print(f"  insiders {len(insiders)}  congress {len(congress)}  article-mentions {len(articles)}"
          f"  bullish ideas {len(ideas)}")
    if len(etf):
        print("  ETF decision events (family x kind):")
        print(etf.groupby(["family", "kind"]).size().unstack(fill_value=0).to_string())

    feats = build_features(windows, panel, insiders=insiders, congress=congress,
                           articles=articles, etf=etf, ideas=ideas, etf_cov=etf_cov)
    feats.to_csv(out / "precursor_features.csv.gz", index=False)
    signals = [c for c in (
        "insider_buy", "insider_buy_cluster", "insider_sell_heavy", "congress_buy",
        "article_any", "article_burst", "article_bullish", "article_bearish",
        "alpha_idea_bullish", "momentum_top", "momentum_bottom",
        *[f"etf_{f}_{k}" for f in ETF_FAMILIES for k in ("add", "new", "cut")],
    ) if c in feats.columns]

    cols = ["n_with", "tickers_with", "mean_with", "mean_without", "diff", "ci_lo", "ci_hi",
            "median_with", "median_without", "p_winner_with", "p_loser_with"]
    hold_windows = sorted({str(w) for w in feats["window_start"]
                           if pd.Timestamp(w).date() >= HOLDOUT_FROM})
    disc = run_split(feats, signals, None, DISCOVERY_BEFORE)
    disc["passes"] = (disc["n_with"] >= MIN_WITH) & ((disc["ci_lo"] > 0) | (disc["ci_hi"] < 0))
    print(f"\n=== DISCOVERY (windows starting before {DISCOVERY_BEFORE}) — rel in % vs peers, winsorised means")
    print(disc[[c for c in cols if c in disc.columns] + ["passes"]].to_string())

    hold = run_split(feats, signals, HOLDOUT_FROM, None)
    hold["passed_discovery"] = hold.index.map(lambda s: bool(disc["passes"].get(s, False)))
    same_sign = np.sign(hold["diff"]) == np.sign(disc["diff"].reindex(hold.index))
    hold["confirmed"] = (
        hold["passed_discovery"] & same_sign
        & ((hold["ci_lo"] > 0) | (hold["ci_hi"] < 0))
    )
    print(f"\n=== HOLDOUT (windows starting {HOLDOUT_FROM} on: {len(hold_windows)} windows)")
    print(hold[[c for c in cols if c in hold.columns] + ["passed_discovery", "confirmed"]].to_string())

    disc.to_csv(out / "precursor_discovery.csv")
    hold.to_csv(out / "precursor_holdout.csv")
    confirmed = list(hold.index[hold["confirmed"]])
    write_summary(out, disc, hold, hold_windows, confirmed)
    print(f"\nCONFIRMED (passed discovery and holdout): {confirmed or 'none'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
