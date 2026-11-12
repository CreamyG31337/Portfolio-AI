#!/usr/bin/env python3
"""Winners-first study, step 1 (ROADMAP Phase L): peer-relative winners and losers.

Idea (cream, 2026-11-12): most stocks move with the market, and the market has been
volatile, so judge a stock against its *peers*, not the index. Find which stocks
beat their peer group, then (later steps) write hindsight theses, look for the
signals that preceded the move, and keep only signals that hold up out of sample.

This script is step 1 only: pure price math, no LLM.

PEER GROUP = sector x size band
-------------------------------
``securities.industry`` is empty for ~97% of the universe (2026-11-12), so peers
are the same sector within the same size band. Bands come from point-in-time ETF
membership at the start of the study (earliest ``etf_holdings_log`` date):
IVV -> ``large``, IWM not in IVV -> ``small``, IWC not in either -> ``micro``.
Using membership at the START (not today) keeps stocks that later collapsed or
delisted in the sample, so winners are not inflated by survivorship.

SUBCOMMANDS
-----------
  prices         download daily adjusted closes for the universe + alpha_idea tickers
                 (yfinance) and cache them to ``<out>/prices.csv.gz``
  label          rolling 63-trading-day windows starting on the first trading day of
                 each month; per window, return minus peer-group median; label the top
                 10% of each group ``winner``, bottom 10% ``loser``, rest ``control``.
                 Writes ``<out>/windows.csv.gz`` and prints a summary.
  rescore-ideas  re-score every ``alpha_idea`` stance against its peer group over the
                 exact dates ``stance_outcomes`` used, and compare with the original
                 index-benchmark excess.

Run inside the Flask container (DB credentials live there):
  docker exec -w /app trading-dashboard-flask python web_dashboard/scripts/winners_study.py prices
  ... winners_study.py label
  ... winners_study.py rescore-ideas
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

_SCRIPT_DIR = Path(__file__).resolve().parent
_WEB_DASHBOARD = _SCRIPT_DIR.parent
for p in (str(_WEB_DASHBOARD), str(_WEB_DASHBOARD.parent)):
    if p not in sys.path:
        sys.path.insert(0, p)

import pandas as pd  # noqa: E402

DEFAULT_OUT = _WEB_DASHBOARD / "logs" / "study"  # host-mounted in the container
PRICE_START = "2025-12-01"
WINDOW_DAYS = 63  # ~one quarter of trading days
MIN_PEERS = 8
TAIL = 0.10
MIN_START_PRICE = 1.0
BAND_ETFS = (("IVV", "large"), ("IWM", "small"), ("IWC", "micro"))


# --------------------------------------------------------------------------- universe


def load_universe(pg: Any) -> pd.DataFrame:
    """ticker -> size band from ETF membership on the earliest logged date."""
    first = pg.execute_query("SELECT MIN(date) AS d FROM etf_holdings_log")[0]["d"]
    band: dict[str, str] = {}
    for etf, name in BAND_ETFS:  # order matters: large wins over small wins over micro
        rows = pg.execute_query(
            """
            SELECT DISTINCT holding_ticker AS t FROM etf_holdings_log
            WHERE etf_ticker = %s
              AND date = (SELECT MIN(date) FROM etf_holdings_log WHERE etf_ticker = %s)
            """,
            (etf, etf),
        )
        for r in rows:
            t = (r["t"] or "").upper().strip()
            if t and t not in band:
                band[t] = name
    df = pd.DataFrame({"ticker": list(band), "band": list(band.values())})
    print(f"universe: {len(df)} tickers from ETF membership (earliest log {first})")
    return df


def load_sectors(tickers: list[str]) -> dict[str, str]:
    from supabase_client import SupabaseClient
    from supabase_pagination import fetch_all_rows

    sb = SupabaseClient(use_service_role=True)
    rows = fetch_all_rows(sb, "securities", select="ticker,sector", order="ticker")
    want = set(tickers)
    return {
        r["ticker"].upper(): r["sector"]
        for r in rows
        if r.get("ticker") and r.get("sector") and r["ticker"].upper() in want
    }


def alpha_idea_tickers(pg: Any) -> list[str]:
    rows = pg.execute_query(
        "SELECT DISTINCT ticker FROM stance_history WHERE source = 'alpha_idea'"
    )
    return [r["ticker"].upper() for r in rows if r.get("ticker")]


# --------------------------------------------------------------------------- prices


def download_prices(
    tickers: list[str], start: str, batch: int = 200, pause_s: float = 0.0
) -> pd.DataFrame:
    """Adjusted closes. ``pause_s`` paces batches (yfinance rate-limits ~3k symbols).

    A rate-limited batch comes back as all-NaN columns, not an exception; callers
    find those with ``empty_columns`` and retry them via ``prices --fill``.
    """
    import time

    import yfinance as yf

    frames: list[pd.DataFrame] = []
    for i in range(0, len(tickers), batch):
        if i and pause_s:
            time.sleep(pause_s)
        chunk = tickers[i : i + batch]
        # yfinance uses '-' for share classes (BRK-B); our tickers use '.'
        yf_syms = [t.replace(".", "-") if t.count(".") == 1 and len(t.split(".")[1]) == 1 else t
                   for t in chunk]
        data = yf.download(
            yf_syms, start=start, auto_adjust=True, progress=False, threads=True,
            group_by="column",
        )
        if data is None or data.empty:
            continue
        close = data["Close"] if "Close" in data else data
        if isinstance(close, pd.Series):
            close = close.to_frame(name=yf_syms[0])
        close = close.rename(columns=dict(zip(yf_syms, chunk)))
        frames.append(close)
        print(f"  prices {min(i + batch, len(tickers))}/{len(tickers)}", flush=True)
    if not frames:
        return pd.DataFrame()
    panel = pd.concat(frames, axis=1, sort=True)
    panel = panel.loc[:, ~panel.columns.duplicated()]
    panel.index = pd.to_datetime(panel.index).tz_localize(None).normalize()
    return panel.sort_index()


def empty_columns(panel: pd.DataFrame) -> list[str]:
    return [c for c in panel.columns if panel[c].notna().sum() == 0]


def load_prices(out: Path) -> pd.DataFrame:
    panel = pd.read_csv(out / "prices.csv.gz", index_col=0, parse_dates=True)
    return panel.sort_index()


# --------------------------------------------------------------------------- labelling


def month_start_indices(index: pd.DatetimeIndex) -> list[int]:
    seen: set[tuple[int, int]] = set()
    out: list[int] = []
    for i, d in enumerate(index):
        key = (d.year, d.month)
        if key not in seen:
            seen.add(key)
            out.append(i)
    return out


def label_windows(
    panel: pd.DataFrame, meta: pd.DataFrame, *, window: int = WINDOW_DAYS
) -> pd.DataFrame:
    """One row per (window, ticker) with peer-relative return and a tail label."""
    meta = meta.dropna(subset=["sector"]).set_index("ticker")
    cols = [t for t in panel.columns if t in meta.index]
    px = panel[cols]
    idx = px.index
    rows: list[pd.DataFrame] = []
    for s in month_start_indices(idx):
        e = s + window
        if e >= len(idx) or idx[s] < pd.Timestamp("2026-01-01"):
            continue
        start, end = px.iloc[s], px.iloc[e]
        ok = start.notna() & end.notna() & (start >= MIN_START_PRICE)
        ret = (end[ok] / start[ok] - 1.0).rename("ret")
        df = ret.to_frame().join(meta[["sector", "band"]])
        df["group"] = df["sector"] + " | " + df["band"]
        g = df.groupby("group")["ret"]
        df["group_n"] = g.transform("size")
        df = df[df["group_n"] >= MIN_PEERS].copy()
        g = df.groupby("group")["ret"]
        df["peer_median"] = g.transform("median")
        df["rel"] = df["ret"] - df["peer_median"]
        df["pct"] = df.groupby("group")["rel"].rank(pct=True)
        df["label"] = "control"
        df.loc[df["pct"] >= 1 - TAIL, "label"] = "winner"
        df.loc[df["pct"] <= TAIL, "label"] = "loser"
        df["window_start"] = idx[s].date()
        df["window_end"] = idx[e].date()
        rows.append(df.reset_index().rename(columns={"index": "ticker"}))
    return pd.concat(rows, ignore_index=True)


# --------------------------------------------------------------------------- re-score


def _close_on_or_before(series: pd.Series, d: date) -> float | None:
    s = series.loc[: pd.Timestamp(d)].dropna()
    return float(s.iloc[-1]) if len(s) else None


def rescore_ideas(pg: Any, panel: pd.DataFrame, meta: pd.DataFrame) -> pd.DataFrame:
    """Peer-relative signed excess for every scored alpha_idea outcome.

    Same dates as stance_outcomes: baseline = close on/before as_of date, end = close
    on/before as_of + horizon days. Peers = same sector+band (sector-only if the
    ticker is outside the index universe), excluding the ticker itself.
    """
    from stance_history import BEARISH_STANCES

    rows = pg.execute_query(
        """
        SELECT sh.ticker, upper(sh.stance) AS stance, sh.as_of, so.horizon_days AS h,
               so.excess_return AS index_excess,
               sh.metadata->'idea'->>'domain' AS domain
        FROM stance_outcomes so JOIN stance_history sh ON sh.id = so.stance_id
        WHERE sh.source = 'alpha_idea'
        """
    )
    m = meta.dropna(subset=["sector"]).set_index("ticker")
    sector_members = m.groupby("sector").groups
    group_members = m.groupby(["sector", "band"]).groups
    sectors = load_sectors([r["ticker"].upper() for r in rows])
    out: list[dict[str, Any]] = []
    for r in rows:
        t = r["ticker"].upper()
        if t not in panel.columns:
            continue
        as_of = r["as_of"]
        d0 = as_of.date() if isinstance(as_of, datetime) else as_of
        d1 = d0 + timedelta(days=int(r["h"]))
        p0, p1 = _close_on_or_before(panel[t], d0), _close_on_or_before(panel[t], d1)
        if not p0 or p1 is None:
            continue
        if t in m.index:
            peers = list(group_members[(m.at[t, "sector"], m.at[t, "band"])])
            peer_kind = "sector+band"
        elif sectors.get(t) in sector_members:
            peers = list(sector_members[sectors[t]])
            peer_kind = "sector"
        else:
            continue
        peers = [p for p in peers if p != t and p in panel.columns]
        sub = panel[peers]
        a = sub.loc[: pd.Timestamp(d0)].ffill().iloc[-1] if len(sub.loc[: pd.Timestamp(d0)]) else None
        b = sub.loc[: pd.Timestamp(d1)].ffill().iloc[-1] if len(sub.loc[: pd.Timestamp(d1)]) else None
        if a is None or b is None:
            continue
        rets = (b / a - 1.0)[(a >= MIN_START_PRICE)].dropna()
        if len(rets) < MIN_PEERS:
            continue
        ret = p1 / p0 - 1.0
        rel = (ret - float(rets.median())) * 100.0
        sign = -1.0 if r["stance"] in BEARISH_STANCES else 1.0
        idx_ex = float(r["index_excess"]) if r["index_excess"] is not None else None
        out.append({
            "ticker": t, "stance": r["stance"], "h": int(r["h"]), "domain": r["domain"],
            "peer_kind": peer_kind, "peer_n": len(rets),
            "signed_peer_excess": sign * rel,
            "signed_index_excess": sign * idx_ex if idx_ex is not None else None,
        })
    return pd.DataFrame(out)


def _summ(df: pd.DataFrame, col: str) -> pd.DataFrame:
    g = df.dropna(subset=[col]).groupby("h")[col]
    return pd.DataFrame({
        "n": g.size(),
        "hit_pct": g.apply(lambda s: round(100 * (s > 0).mean(), 1)),
        "mean_pct": g.mean().round(2),
        "median_pct": g.median().round(2),
    })


# --------------------------------------------------------------------------- main


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["prices", "label", "rescore-ideas"])
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--fill", action="store_true",
                    help="prices: re-download only tickers missing/empty in the cache")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    from postgres_client import PostgresClient

    pg = PostgresClient()
    uni = load_universe(pg)
    sectors = load_sectors(uni["ticker"].tolist())
    uni["sector"] = uni["ticker"].map(sectors)
    print(f"with sector: {uni['sector'].notna().sum()}  bands: {uni['band'].value_counts().to_dict()}")

    if args.cmd == "prices":
        tickers = sorted(set(uni["ticker"]) | set(alpha_idea_tickers(pg)))
        if args.fill and (out / "prices.csv.gz").exists():
            panel = load_prices(out)
            todo = sorted(set(empty_columns(panel)) | (set(tickers) - set(panel.columns)))
            print(f"fill: {len(todo)} missing/empty tickers")
            for attempt in range(3):
                if not todo:
                    break
                got = download_prices(todo, PRICE_START, batch=50, pause_s=20)
                got = got[[c for c in got.columns if got[c].notna().any()]] if not got.empty else got
                if not got.empty:
                    panel = panel.drop(columns=[c for c in got.columns if c in panel.columns])
                    panel = pd.concat([panel, got], axis=1, sort=True)
                todo = [t for t in todo if t not in got.columns]
                print(f"  attempt {attempt + 1}: filled {got.shape[1]}, still empty {len(todo)}")
            panel.to_csv(out / "prices.csv.gz")
            print(f"saved {panel.shape[1]} tickers; still empty (likely delisted): {len(todo)}")
            return 0
        panel = download_prices(tickers, PRICE_START, pause_s=10)
        panel.to_csv(out / "prices.csv.gz")
        print(f"saved {panel.shape[1]} tickers x {panel.shape[0]} days -> {out / 'prices.csv.gz'}")
        return 0

    panel = load_prices(out)

    if args.cmd == "label":
        w = label_windows(panel, uni)
        w.to_csv(out / "windows.csv.gz", index=False)
        print(f"windows: {w['window_start'].nunique()}  rows: {len(w)}  groups: {w['group'].nunique()}")
        print(w.groupby(["window_start", "label"]).size().unstack(fill_value=0))
        latest = w[w["window_start"] == w["window_start"].max()]
        top = latest.nlargest(15, "rel")[["ticker", "group", "ret", "peer_median", "rel"]]
        print(f"\nTop peer-relative winners, window starting {latest['window_start'].iloc[0]}:")
        print(top.round(3).to_string(index=False))
        repeat = w[w["label"] == "winner"].groupby("ticker").size().sort_values(ascending=False)
        print("\nMost frequent winners across windows:")
        print(repeat.head(15).to_string())
        return 0

    if args.cmd == "rescore-ideas":
        r = rescore_ideas(pg, panel, uni)
        r.to_csv(out / "alpha_idea_rescore.csv.gz", index=False)
        print(f"rescored {len(r)} outcome rows (peer kinds: {r['peer_kind'].value_counts().to_dict()})")
        print("\nvs PEERS (sector+band median):")
        print(_summ(r, "signed_peer_excess").to_string())
        print("\nvs INDEX benchmark (same rows, for comparison):")
        print(_summ(r, "signed_index_excess").to_string())
        print("\nvs PEERS by direction:")
        for st, sub in r.groupby("stance"):
            print(st)
            print(_summ(sub, "signed_peer_excess").to_string())
        d30 = r[r["h"] == 30].groupby("domain")["signed_peer_excess"]
        dom = pd.DataFrame({"n": d30.size(), "hit_pct": d30.apply(lambda s: round(100 * (s > 0).mean(), 1)),
                            "mean_pct": d30.mean().round(2)})
        print("\n30d vs PEERS by domain (n>=10):")
        print(dom[dom["n"] >= 10].sort_values("mean_pct", ascending=False).to_string())
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
