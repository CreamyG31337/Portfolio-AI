#!/usr/bin/env python3
"""Do ARK's own trades beat simply holding the ARK fund? (roadmap Phase L, ETF copy-trading)

ARK publishes every trade its active ETFs make (the daily trade notification, sent after
the close). Those are decisions, not fund flows. arkfunds.io archives them from
2020-09-09, which covers the 2021 peak, the 2022 crash and the recovery.

Design, fixed BEFORE looking at results (2026-11-12):

* Event = one fund's trade in one ticker on one day (Buy or Sell).
* Entry = close of the first trading day AFTER the trade date (the notification arrives
  after the close, so that is the earliest a copier could act).
* Excess return = stock return - the trading fund's own ETF return over the same days
  ("would copying beat just holding the fund?"). QQQ is shown as a second yardstick.
* Horizons 21 / 63 / 126 trading days. Excess winsorised at 1/99 per horizon.
* Main test: mean excess after Buys, after Sells, and Buy - Sell, with a bootstrap that
  resamples calendar months of entry (trades cluster in time and move together).
* Cuts: large trades (top quartile of etf_percent within fund x year), and per year.
* Portfolio: hold, equal weight, every name the funds bought in the last 63 trading days,
  rebalanced daily from closes, no costs; versus ARKK and QQQ. Same for Sells.

Survivorship: names yfinance cannot price (mostly delisted) drop out; the run reports
how many events that removes. Prices are forward-filled, so a name that stops trading
keeps its last price (roughly right for take-overs, flattering for bankruptcies).

Usage (inside the container, cache in the host-mounted logs/study/):
    python web_dashboard/scripts/ark_history_study.py fetch
    python web_dashboard/scripts/ark_history_study.py prices [--fill]
    python web_dashboard/scripts/ark_history_study.py analyze
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_WEB_DASHBOARD = _SCRIPT_DIR.parent
for p in (str(_SCRIPT_DIR), str(_WEB_DASHBOARD), str(_WEB_DASHBOARD.parent)):
    if p not in sys.path:
        sys.path.insert(0, p)

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

DEFAULT_OUT = _WEB_DASHBOARD / "logs" / "study"
API = "https://arkfunds.io/api/v2/etf/trades"
FUNDS = ("ARKK", "ARKW", "ARKG", "ARKQ", "ARKF", "ARKX")
BENCH = ("QQQ", "SPY", "IWM")
FIRST_YEAR, PRICE_START = 2020, "2020-08-01"
HORIZONS = (21, 63, 126)
HOLD_DAYS = 63
BOOT = 1000
SEED = 20261112
TRADES_FILE, PRICES_FILE = "ark_trades.csv.gz", "ark_prices.csv.gz"


# --------------------------------------------------------------------------- fetch


def fetch_trades(out: Path) -> pd.DataFrame:
    import requests

    rows: list[dict] = []
    this_year = pd.Timestamp.today().year
    for fund in FUNDS:
        for y in range(FIRST_YEAR, this_year + 1):
            r = requests.get(
                API,
                params={"symbol": fund, "date_from": f"{y}-01-01", "date_to": f"{y}-12-31", "limit": 100000},
                headers={"User-Agent": "portfolio-research/1.0"},
                timeout=120,
            )
            r.raise_for_status()
            got = r.json().get("trades", [])
            rows.extend(got)
            print(f"  {fund} {y}: {len(got)} trades", flush=True)
            time.sleep(1.0)
    df = pd.DataFrame(rows)
    df["ticker"] = df["ticker"].astype(str).str.upper().str.strip()
    df.to_csv(out / TRADES_FILE, index=False)
    print(f"saved {len(df)} trades -> {out / TRADES_FILE}")
    return df


def priceable(t: str) -> bool:
    """US-style symbols only; foreign listings like '4689 JP' or numeric codes are skipped."""
    return bool(t) and " " not in t and not t[0].isdigit() and len(t) <= 6


def fetch_prices(out: Path, fill: bool) -> None:
    from winners_study import download_prices, empty_columns

    trades = pd.read_csv(out / TRADES_FILE)
    tickers = sorted({t for t in trades["ticker"].dropna() if priceable(t)} | set(FUNDS) | set(BENCH))
    path = out / PRICES_FILE
    if fill and path.exists():
        panel = pd.read_csv(path, index_col=0, parse_dates=True)
        todo = empty_columns(panel) + [t for t in tickers if t not in panel.columns]
        print(f"filling {len(todo)} empty/missing tickers")
        new = download_prices(todo, PRICE_START, batch=50, pause_s=5.0)
        for c in new.columns:
            if new[c].notna().any():
                panel[c] = new[c].reindex(panel.index.union(new.index))
        panel = panel.sort_index()
    else:
        panel = download_prices(tickers, PRICE_START, batch=100, pause_s=3.0)
    panel.to_csv(path)
    empty = empty_columns(panel)
    print(f"saved {panel.shape[1]} tickers x {panel.shape[0]} days; {len(empty)} with no data")


# --------------------------------------------------------------------------- analysis


def build_events(trades: pd.DataFrame, panel: pd.DataFrame) -> pd.DataFrame:
    t = trades.copy()
    t["date"] = pd.to_datetime(t["date"])
    t["dir"] = t["direction"].str.lower().map({"buy": 1, "sell": -1})
    t = t.dropna(subset=["dir"])
    # Same fund buying and selling a name on one day is a wash; drop it.
    both = t.groupby(["fund", "date", "ticker"])["dir"].transform("nunique") > 1
    t = t[~both]
    t = t.groupby(["fund", "date", "ticker", "dir"], as_index=False)["etf_percent"].sum()
    t["year"] = t["date"].dt.year
    q75 = t.groupby(["fund", "year"])["etf_percent"].transform(lambda s: s.quantile(0.75))
    t["big"] = t["etf_percent"] >= q75

    idx = panel.index
    t["entry_i"] = idx.searchsorted(t["date"], side="right")  # first trading day AFTER the trade
    t = t[t["entry_i"] < len(idx)].copy()
    t["entry_date"] = idx[t["entry_i"].to_numpy()]
    t["month"] = t["entry_date"].dt.to_period("M").astype(str)

    filled = panel.ffill()
    cols = {c: i for i, c in enumerate(filled.columns)}
    arr = filled.to_numpy()
    has_px = t["ticker"].map(cols).notna()
    print(f"events: {len(t)}; with prices: {has_px.sum()} ({100 * has_px.mean():.1f}%); "
          f"unpriced tickers: {t.loc[~has_px, 'ticker'].nunique()}")
    t = t[has_px].copy()
    ti = t["ticker"].map(cols).astype(int).to_numpy()
    fi = t["fund"].map(cols).astype(int).to_numpy()
    qi = cols["QQQ"]
    e = t["entry_i"].to_numpy()
    p0, f0, q0 = arr[e, ti], arr[e, fi], arr[e, qi]
    for h in HORIZONS:
        x = e + h
        ok = x < len(idx)
        xs = np.where(ok, x, 0)
        r = np.where(ok, arr[xs, ti] / p0 - 1, np.nan)
        rf = np.where(ok, arr[xs, fi] / f0 - 1, np.nan)
        rq = np.where(ok, arr[xs, qi] / q0 - 1, np.nan)
        t[f"ret_{h}"] = r * 100
        t[f"xf_{h}"] = (r - rf) * 100
        t[f"xq_{h}"] = (r - rq) * 100
    return t


def _winsor(s: pd.Series) -> pd.Series:
    return s.clip(s.quantile(0.01), s.quantile(0.99))


def boot_month(d: pd.DataFrame, col: str, rng: np.random.Generator) -> dict:
    """Mean excess for buys, sells and buy-sell, CIs from resampling entry months."""
    d = d.dropna(subset=[col])
    if d.empty:
        return {}
    v = _winsor(d[col])
    buy = (d["dir"] == 1).astype(float)
    per = pd.DataFrame({
        "sb": v * buy, "nb": buy, "ss": v * (1 - buy), "ns": 1 - buy,
    }).groupby(d["month"]).sum()
    k = len(per)
    counts = np.stack([np.bincount(rng.integers(0, k, k), minlength=k) for _ in range(BOOT)])
    nb, ns = counts @ per["nb"].to_numpy(), counts @ per["ns"].to_numpy()
    mb = np.divide(counts @ per["sb"].to_numpy(), nb, out=np.full(BOOT, np.nan), where=nb > 0)
    ms = np.divide(counts @ per["ss"].to_numpy(), ns, out=np.full(BOOT, np.nan), where=ns > 0)

    def ci(a: np.ndarray) -> str:
        a = a[~np.isnan(a)]
        lo, hi = np.percentile(a, [2.5, 97.5]) if len(a) else (np.nan, np.nan)
        return f"{lo:+.2f}..{hi:+.2f}"

    b, s = v[buy == 1], v[buy == 0]
    return {
        "n_buy": len(b), "n_sell": len(s), "months": k,
        "buy": round(b.mean(), 2), "buy_ci": ci(mb),
        "sell": round(s.mean(), 2), "sell_ci": ci(ms),
        "buy-sell": round(b.mean() - s.mean(), 2), "spread_ci": ci(mb - ms),
        "buy_med": round(d.loc[buy == 1, col].median(), 2),
        "sell_med": round(d.loc[buy == 0, col].median(), 2),
    }


def table(ev: pd.DataFrame, cols: list[str], by: str | None = None) -> pd.DataFrame:
    rng = np.random.default_rng(SEED)
    rows = []
    groups = [("all", ev)] if by is None else list(ev.groupby(by))
    for key, g in groups:
        for c in cols:
            r = boot_month(g, c, rng)
            if r:
                rows.append({"group": key, "measure": c, **r})
    return pd.DataFrame(rows).set_index(["group", "measure"])


def portfolio(ev: pd.DataFrame, panel: pd.DataFrame, direction: int) -> pd.Series:
    """Daily returns of: hold every name traded in `direction` in the last HOLD_DAYS days."""
    rets = panel.ffill().pct_change(fill_method=None).clip(-0.9, 3.0)
    n = len(panel.index)
    active = np.zeros((n, panel.shape[1]), dtype=bool)
    cols = {c: i for i, c in enumerate(panel.columns)}
    sub = ev[ev["dir"] == direction]
    for e, tk in zip(sub["entry_i"].to_numpy(), sub["ticker"].to_numpy()):
        # bought at close of day e -> earns returns on days e+1 .. e+HOLD_DAYS
        active[e + 1 : min(e + 1 + HOLD_DAYS, n), cols[tk]] = True
    r = rets.to_numpy()
    valid = active & ~np.isnan(r)
    cnt = valid.sum(axis=1)
    tot = np.where(valid, r, 0.0).sum(axis=1)
    out = pd.Series(np.where(cnt > 0, tot / np.maximum(cnt, 1), np.nan), index=panel.index)
    return out


def perf(r: pd.Series) -> dict:
    r = r.dropna()
    if r.empty:
        return {}
    eq = (1 + r).cumprod()
    yrs = len(r) / 252
    dd = (eq / eq.cummax() - 1).min()
    return {
        "total_%": round(100 * (eq.iloc[-1] - 1), 1),
        "cagr_%": round(100 * (eq.iloc[-1] ** (1 / yrs) - 1), 1) if yrs > 0 else np.nan,
        "vol_%": round(100 * r.std() * np.sqrt(252), 1),
        "max_dd_%": round(100 * dd, 1),
    }


def analyze(out: Path) -> None:
    trades = pd.read_csv(out / TRADES_FILE)
    panel = pd.read_csv(out / PRICES_FILE, index_col=0, parse_dates=True).sort_index()
    print(f"trades {len(trades)}  {trades['date'].min()} .. {trades['date'].max()}  "
          f"funds {sorted(trades['fund'].unique())}")
    ev = build_events(trades, panel)
    ev.to_csv(out / "ark_events.csv.gz", index=False)
    pd.set_option("display.width", 250)

    xf = [f"xf_{h}" for h in HORIZONS]
    print("\n=== ALL TRADES: excess return vs the trading fund's own ETF (%), months-bootstrap 95% CI")
    print(table(ev, xf + [f"xq_{h}" for h in HORIZONS]).to_string())
    print("\n=== LARGE TRADES (top quartile of etf_percent within fund x year)")
    print(table(ev[ev["big"]], xf).to_string())
    print("\n=== BY FUND (63d vs own fund)")
    print(table(ev, ["xf_63"], by="fund").to_string())
    print("\n=== BY YEAR OF ENTRY (63d vs own fund)")
    print(table(ev, ["xf_63"], by=ev["entry_date"].dt.year).to_string())

    rets = panel.ffill().pct_change(fill_method=None)
    start = ev["entry_date"].min() + pd.Timedelta(days=100)  # let the book fill up
    series = {
        "copy_buys": portfolio(ev, panel, 1),
        "copy_sells": portfolio(ev, panel, -1),
        "ARKK": rets["ARKK"],
        "QQQ": rets["QQQ"],
        "SPY": rets["SPY"],
    }
    df = pd.DataFrame(series).loc[start:]
    df["buys_minus_sells"] = df["copy_buys"] - df["copy_sells"]
    print(f"\n=== PORTFOLIO from {df.index[0].date()} to {df.index[-1].date()} "
          f"(hold names bought/sold in the last {HOLD_DAYS} trading days, equal weight, no costs)")
    print(pd.DataFrame({k: perf(df[k]) for k in df.columns}).T.to_string())
    print("\n=== PORTFOLIO by calendar year (total return %)")
    yearly = df.groupby(df.index.year).apply(lambda g: ((1 + g.fillna(0)).prod() - 1) * 100).round(1)
    print(yearly.to_string())
    df.to_csv(out / "ark_portfolio_daily.csv.gz")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=("fetch", "prices", "analyze"))
    ap.add_argument("--fill", action="store_true")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    if a.cmd == "fetch":
        fetch_trades(out)
    elif a.cmd == "prices":
        fetch_prices(out, a.fill)
    else:
        analyze(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
