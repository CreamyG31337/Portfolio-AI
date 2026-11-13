"""Detect stock splits on held tickers and apply them without anyone stepping in.

The price job rebuilds every share count from ``trade_log``. When a split
happens, the price feed switches to the post-split price but ``trade_log`` still
holds pre-split shares, so the position silently loses ~(1 - 1/ratio) of its
value. ITA 3:1 (2026-11-05) and CRWD 4:1 (2026-07-02) both went unnoticed for
days or months that way.

How a split is applied:

1. Yahoo lists a split for a ticker the fund holds, dated after the fund's
   first trade in it, with a split-sized ratio (>= 1.5 or <= 1/1.5). Smaller
   ratios are stock dividends or spin-offs (SPGI 1.057, UL 0.888), which
   must never be applied.
2. **Our own stored prices** show the matching cliff within a couple of rows of
   the ex-date (CRWD's cliff landed one row *before* Yahoo's stamp). Confirming
   from ``portfolio_positions`` rather than Yahoo matters: once Yahoo
   back-adjusts its history, its own series no longer shows the cliff.
3. No trade sits between the ex-date and the cliff, where it would be unclear
   whether the trade was pre- or post-split.
4. ``apply_stock_split()`` (Postgres, one transaction) records the split in
   ``corporate_actions`` and adjusts ``trade_log`` rows dated before the cliff
   and ``portfolio_positions`` rows on or after it. The ledger's unique key
   makes a second application impossible.

If Yahoo lists a split but the cliff never shows up in our prices, nothing is
changed. Once the ex-date is older than ``UNCONFIRMED_AFTER_DAYS``, the split is
recorded as ``unconfirmed`` so it is logged once instead of on every run.

Runs at the start of every ``update_portfolio_prices_job``. On the ex-date the
first run may still write one row with the old share count (the cliff needs a
post-split row to be visible); the next run, 15 minutes later, repairs it.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Callable, Iterable, Optional, Sequence

import pytz

logger = logging.getLogger(__name__)

ET = pytz.timezone("America/New_York")

MIN_SPLIT_RATIO = 1.5
MAX_REVERSE_RATIO = 1.0 / MIN_SPLIT_RATIO
CLIFF_TOLERANCE = 0.15
# Stored rows before / after the first row on or after the ex-date that may
# carry the cliff. CRWD: one row before. Yahoo's documented lag: one row after.
CLIFF_ROWS_BEFORE = 1
CLIFF_ROWS_AFTER = 2
UNCONFIRMED_AFTER_DAYS = 10
DEFAULT_LOOKBACK_DAYS = 90
_SPLIT_CACHE_TTL_S = 2 * 60 * 60

_split_cache: dict[tuple[str, int], tuple[float, dict[date, float]]] = {}
_split_cache_lock = threading.Lock()


@dataclass
class SplitPlan:
    fund: str
    ticker: str
    ex_date: date
    ratio: float
    cliff_date: Optional[date] = None
    status: str = "pending"  # apply | wait | unconfirmed | ambiguous
    reason: str = ""
    trades_before_cliff: list[dict[str, Any]] = field(default_factory=list)
    positions_from_cliff: int = 0


# ---------------------------------------------------------------------------
# Pure helpers (unit-tested)
# ---------------------------------------------------------------------------


def is_split_sized(ratio: float) -> bool:
    """True for real splits / reverse splits; False for stock dividends and spin-offs."""
    if ratio is None or ratio <= 0:
        return False
    return ratio >= MIN_SPLIT_RATIO or ratio <= MAX_REVERSE_RATIO


def trade_et_date(value: Any) -> date:
    """Calendar date of a trade_log timestamp in America/New_York."""
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = pytz.UTC.localize(dt)
    return dt.astimezone(ET).date()


def held_tickers(trades: Iterable[dict[str, Any]], is_sell: Callable[[dict], bool]) -> dict[str, date]:
    """Ticker -> ET date of first trade, for tickers with a positive share balance.

    Mirrors the price job: anything that is not a sell (BUY, DRIP DIVIDEND) adds shares.
    """
    balance: dict[str, Decimal] = {}
    first: dict[str, date] = {}
    for t in trades:
        ticker = str(t.get("ticker") or "").strip().upper()
        if not ticker:
            continue
        shares = Decimal(str(t.get("shares") or 0))
        balance[ticker] = balance.get(ticker, Decimal("0")) + (-shares if is_sell(t) else shares)
        d = trade_et_date(t["date"])
        if ticker not in first or d < first[ticker]:
            first[ticker] = d
    return {tk: first[tk] for tk, bal in balance.items() if bal > 0}


def candidate_splits(
    splits: dict[date, float], first_trade: date, already_recorded: set[date]
) -> list[tuple[date, float]]:
    """Split-sized events after the first trade that the ledger has not seen."""
    out = []
    for ex_date, ratio in sorted(splits.items()):
        if ex_date <= first_trade or ex_date in already_recorded:
            continue
        if is_split_sized(float(ratio)):
            out.append((ex_date, float(ratio)))
    return out


def find_cliff(
    price_rows: Sequence[tuple[date, float]],
    ex_date: date,
    ratio: float,
    tolerance: float = CLIFF_TOLERANCE,
) -> Optional[date]:
    """First stored date whose price dropped (or rose) by the split ratio.

    ``price_rows`` is (date_only, price) for one fund+ticker, any order. Only
    rows next to the ex-date are searched, so an ordinary later move of similar
    size can never match.
    """
    rows = sorted((d, float(p)) for d, p in price_rows if p is not None and float(p) > 0)
    k = next((i for i, (d, _) in enumerate(rows) if d >= ex_date), None)
    if k is None:
        return None
    lo = max(1, k - CLIFF_ROWS_BEFORE)
    hi = min(len(rows) - 1, k + CLIFF_ROWS_AFTER)
    for i in range(lo, hi + 1):
        prev_price, price = rows[i - 1][1], rows[i][1]
        observed = prev_price / price
        if abs(observed - ratio) <= tolerance * ratio:
            return rows[i][0]
    return None


def ambiguous_trades(
    trades: Iterable[dict[str, Any]], ex_date: date, cliff_date: date
) -> list[dict[str, Any]]:
    """Trades between the provider's ex-date and our cliff, whose side of the split is unclear."""
    if ex_date == cliff_date:
        return []
    lo, hi = min(ex_date, cliff_date), max(ex_date, cliff_date)
    return [t for t in trades if lo <= trade_et_date(t["date"]) < hi]


def plan_split(
    *,
    fund: str,
    ticker: str,
    ex_date: date,
    ratio: float,
    trades: list[dict[str, Any]],
    price_rows: Sequence[tuple[date, float]],
    today: date,
) -> SplitPlan:
    """Decide what to do about one provider-reported split. No I/O."""
    plan = SplitPlan(fund=fund, ticker=ticker, ex_date=ex_date, ratio=ratio)
    cliff = find_cliff(price_rows, ex_date, ratio)
    if cliff is None:
        if (today - ex_date).days > UNCONFIRMED_AFTER_DAYS:
            plan.status = "unconfirmed"
            plan.reason = "no matching price cliff in stored positions"
        else:
            plan.status = "wait"
            plan.reason = "no post-split row stored yet"
        return plan
    plan.cliff_date = cliff
    unclear = ambiguous_trades(trades, ex_date, cliff)
    if unclear:
        plan.status = "ambiguous"
        plan.reason = (
            f"{len(unclear)} trade(s) between ex-date {ex_date} and cliff {cliff}; "
            "cannot tell which side of the split they are on"
        )
        return plan
    plan.trades_before_cliff = [t for t in trades if trade_et_date(t["date"]) < cliff]
    if not plan.trades_before_cliff:
        plan.status = "ambiguous"
        plan.reason = "no trades before the cliff"
        return plan
    plan.positions_from_cliff = sum(1 for d, _ in price_rows if d >= cliff)
    plan.status = "apply"
    return plan


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------


def fetch_yahoo_splits(ticker: str, lookback_days: int) -> dict[date, float]:
    """Yahoo split events within ``lookback_days``, cached for two hours."""
    key = (ticker, lookback_days)
    now = time.time()
    with _split_cache_lock:
        hit = _split_cache.get(key)
        if hit and now - hit[0] < _SPLIT_CACHE_TTL_S:
            return hit[1]
    import yfinance as yf

    start = (datetime.now(ET).date() - timedelta(days=lookback_days)).isoformat()
    out: dict[date, float] = {}
    try:
        hist = yf.Ticker(ticker).history(start=start, actions=True, auto_adjust=False)
        if hist is not None and not hist.empty and "Stock Splits" in hist.columns:
            for ts, ratio in hist["Stock Splits"].items():
                if ratio and float(ratio) > 0:
                    out[ts.date()] = float(ratio)
    except Exception as e:  # network/404: treat as no splits this run
        logger.debug("split_guard: Yahoo split fetch failed for %s: %s", ticker, e)
        return out
    with _split_cache_lock:
        _split_cache[key] = (now, out)
    return out


def _recorded_ex_dates(sb: Any, fund: str) -> dict[str, set[date]]:
    rows = (
        sb.table("corporate_actions")
        .select("ticker, ex_date")
        .eq("fund", fund)
        .eq("action_type", "split")
        .execute()
        .data
        or []
    )
    out: dict[str, set[date]] = {}
    for r in rows:
        out.setdefault(r["ticker"].upper(), set()).add(date.fromisoformat(str(r["ex_date"])[:10]))
    return out


def _price_rows(sb: Any, fund: str, ticker: str, ex_date: date) -> list[tuple[date, float]]:
    """Stored position prices from two weeks before the ex-date onward."""
    rows = (
        sb.table("portfolio_positions")
        .select("date_only, price")
        .eq("fund", fund)
        .eq("ticker", ticker)
        .gte("date_only", (ex_date - timedelta(days=14)).isoformat())
        .order("date_only")
        .limit(1000)
        .execute()
        .data
        or []
    )
    return [(date.fromisoformat(str(r["date_only"])[:10]), float(r["price"])) for r in rows if r.get("price") is not None]


def _record_unconfirmed(sb: Any, plan: SplitPlan) -> None:
    sb.table("corporate_actions").upsert(
        {
            "fund": plan.fund,
            "ticker": plan.ticker,
            "action_type": "split",
            "ex_date": plan.ex_date.isoformat(),
            "ratio": plan.ratio,
            "status": "unconfirmed",
            "source": "split_guard",
            "notes": plan.reason,
        },
        on_conflict="fund,ticker,action_type,ex_date",
        ignore_duplicates=True,
    ).execute()


def _refresh_performance_metrics(fund: str, from_date: date) -> None:
    try:
        from scheduler.jobs_metrics import populate_performance_metrics_job

        populate_performance_metrics_job(
            from_date=from_date, to_date=datetime.now(ET).date(), fund_filter=fund
        )
    except Exception as e:
        logger.warning("split_guard: performance_metrics refresh failed for %s: %s", fund, e)


def run_split_guard(
    client: Any,
    funds: Sequence[str],
    *,
    apply: bool = True,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    refresh_metrics: bool = True,
) -> list[SplitPlan]:
    """Check every held ticker in ``funds`` for unapplied splits; apply the confirmed ones.

    ``client`` is a SupabaseClient (service role). Returns every plan considered,
    so callers and the CLI can print them. Never raises for a single ticker.
    """
    from supabase_pagination import fetch_all_rows
    from utils.trade_reason import is_trade_sell

    sb = client.supabase
    today = datetime.now(ET).date()
    plans: list[SplitPlan] = []

    for fund in funds:
        try:
            trades = fetch_all_rows(
                client,
                "trade_log",
                select="id, fund, ticker, date, action, reason, shares, price",
                filters=[("fund", "eq", fund)],
                order="date",
                order_secondary="id",
            )
            recorded = _recorded_ex_dates(sb, fund)
        except Exception as e:
            logger.warning("split_guard: could not load %s: %s", fund, e)
            continue

        for ticker, first_trade in sorted(held_tickers(trades, is_trade_sell).items()):
            splits = fetch_yahoo_splits(ticker, lookback_days)
            for ex_date, ratio in candidate_splits(splits, first_trade, recorded.get(ticker, set())):
                ticker_trades = [t for t in trades if str(t.get("ticker") or "").upper() == ticker]
                try:
                    plan = plan_split(
                        fund=fund,
                        ticker=ticker,
                        ex_date=ex_date,
                        ratio=ratio,
                        trades=ticker_trades,
                        price_rows=_price_rows(sb, fund, ticker, ex_date),
                        today=today,
                    )
                except Exception as e:
                    logger.warning("split_guard: planning %s/%s failed: %s", fund, ticker, e)
                    continue
                plans.append(plan)

                if plan.status == "wait":
                    logger.info("split_guard: %s %s %s:1 on %s — %s", fund, ticker, ratio, ex_date, plan.reason)
                    continue
                if plan.status in ("unconfirmed", "ambiguous"):
                    logger.error(
                        "split_guard: NOT applying %s %s %s:1 on %s — %s", fund, ticker, ratio, ex_date, plan.reason
                    )
                    if apply and plan.status == "unconfirmed":
                        try:
                            _record_unconfirmed(sb, plan)
                        except Exception as e:
                            logger.warning("split_guard: could not record unconfirmed split: %s", e)
                    continue
                if not apply:
                    continue

                try:
                    res = sb.rpc(
                        "apply_stock_split",
                        {
                            "p_fund": fund,
                            "p_ticker": ticker,
                            "p_ex_date": ex_date.isoformat(),
                            "p_ratio": ratio,
                            "p_cliff_date": plan.cliff_date.isoformat(),
                            "p_source": "split_guard",
                            "p_notes": f"auto: Yahoo {ratio}:1, price cliff on {plan.cliff_date}",
                        },
                    ).execute()
                except Exception as e:
                    # Unique-key violation means another run got there first.
                    logger.error("split_guard: apply_stock_split failed for %s %s: %s", fund, ticker, e)
                    continue
                logger.warning(
                    "split_guard: applied %s %s %s:1 (ex %s, cliff %s): %s",
                    fund, ticker, ratio, ex_date, plan.cliff_date, res.data,
                )
                if refresh_metrics:
                    _refresh_performance_metrics(fund, plan.cliff_date)
    return plans


def main(argv: Optional[list[str]] = None) -> int:
    """CLI: dry-run by default. ``--apply`` writes. ``--lookback-days`` scans further back."""
    import argparse
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    for p in (str(root), str(root / "web_dashboard")):
        if p not in sys.path:
            sys.path.insert(0, p)

    parser = argparse.ArgumentParser(description=main.__doc__)
    parser.add_argument("--fund", action="append", help="Fund name (repeatable; default: all)")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--lookback-days", type=int, default=DEFAULT_LOOKBACK_DAYS)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    from supabase_client import SupabaseClient

    client = SupabaseClient(use_service_role=True)
    funds = args.fund or [r["name"] for r in client.supabase.table("funds").select("name").execute().data]
    plans = run_split_guard(client, funds, apply=args.apply, lookback_days=args.lookback_days)
    print(f"\n{'APPLY' if args.apply else 'DRY-RUN'}: {len(plans)} split(s) considered")
    for p in plans:
        print(
            f"  {p.fund:20} {p.ticker:8} {p.ratio:g}:1 ex {p.ex_date} cliff {p.cliff_date} "
            f"-> {p.status}  trades={len(p.trades_before_cliff)} positions={p.positions_from_cliff} {p.reason}"
        )
        for t in p.trades_before_cliff:
            print(f"      {str(t['date'])[:10]} {t.get('action') or '':8} {t['shares']} @ {t['price']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
