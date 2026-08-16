#!/usr/bin/env python3
"""Adjust trade_log rows for a stock split. Does NOT rebuild positions.

Usage:
  python debug/apply_stock_split.py --fund "TEST MNST RRSP" --ticker MNST --ratio 2 --dry-run
  python debug/apply_stock_split.py --fund "TEST MNST RRSP" --ticker MNST --ratio 2 --apply

Cost basis is invariant. Pair with a targeted position repair, not a full rebuild,
until the data provider has back-adjusted its price series.
"""

from __future__ import annotations

import argparse
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "web_dashboard"))


class SplitApplyError(ValueError):
    """User-facing refusal (bad ratio, zero rows, prod without override)."""


def adjust_trade_for_split(
    shares: Decimal, price: Decimal, ratio: Decimal
) -> tuple[Decimal, Decimal]:
    """Return (new_shares, new_price). cost_basis is not an input — it is invariant."""
    if ratio < 1:
        raise SplitApplyError(
            f"ratio must be >= 1 (got {ratio}). Reverse splits are not supported."
        )
    new_shares = shares * ratio
    new_price = price / ratio
    return new_shares, new_price


def _dec(value: Any) -> Decimal:
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


def plan_split_updates(rows: list[dict[str, Any]], ratio: Decimal) -> list[dict[str, Any]]:
    """Build before/after records. Raises if there is nothing to adjust."""
    if not rows:
        raise SplitApplyError("zero rows matched — refusing to apply a no-op split")
    planned: list[dict[str, Any]] = []
    for row in rows:
        shares = _dec(row.get("shares"))
        price = _dec(row.get("price"))
        new_shares, new_price = adjust_trade_for_split(shares, price, ratio)
        planned.append(
            {
                "id": row["id"],
                "date": row.get("date"),
                "action": row.get("action") or "",
                "shares_before": shares,
                "price_before": price,
                "shares_after": new_shares,
                "price_after": new_price,
                "cost_basis": _dec(row.get("cost_basis")),
                "pnl": _dec(row.get("pnl")),
            }
        )
    return planned


def implied_open_shares(rows: list[dict[str, Any]], shares_key: str) -> Decimal:
    """Net shares after walking trades in date order (BUY +, SELL -)."""
    ordered = sorted(rows, key=lambda r: str(r.get("date") or ""))
    total = Decimal("0")
    for row in ordered:
        action = str(row.get("action") or "").upper()
        shares = _dec(row[shares_key])
        if action == "SELL":
            total -= shares
        elif action == "DIVIDEND":
            continue
        else:
            total += shares
    return total


def assert_fund_writable(is_production: bool, i_know_this_is_prod: bool) -> None:
    if is_production and not i_know_this_is_prod:
        raise SplitApplyError(
            "refusing to write a production fund without --i-know-this-is-prod"
        )


def _format_table(planned: list[dict[str, Any]]) -> str:
    headers = (
        "date",
        "action",
        "sh_before",
        "px_before",
        "sh_after",
        "px_after",
        "cost_basis",
        "pnl",
    )
    lines = ["  ".join(f"{h:>12}" for h in headers)]
    for row in planned:
        date_s = str(row["date"])[:10] if row["date"] else ""
        vals = (
            date_s,
            str(row["action"]),
            f"{row['shares_before']}",
            f"{row['price_before']}",
            f"{row['shares_after']}",
            f"{row['price_after']}",
            f"{row['cost_basis']}",
            f"{row['pnl']}",
        )
        lines.append("  ".join(f"{v:>12}" for v in vals))
    return "\n".join(lines)


def _follow_up_sql(fund: str, ticker: str, ratio: Decimal) -> str:
    return (
        f"update portfolio_positions\n"
        f"set shares           = shares * {ratio},\n"
        f"    pnl              = round(shares * {ratio} * price - cost_basis, 2),\n"
        f"    total_value_base = round(shares * {ratio} * price * exchange_rate, 2),\n"
        f"    pnl_base         = round((shares * {ratio} * price - cost_basis) * exchange_rate, 2)\n"
        f"where ticker = '{ticker}'\n"
        f"  and fund = '{fund}'\n"
        f"  and date_only >= '2026-08-10';"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fund", required=True, help="Fund name")
    parser.add_argument("--ticker", required=True, help="Ticker to adjust")
    parser.add_argument("--ratio", required=True, type=Decimal, help="Split ratio (e.g. 2)")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=None,
        help="Plan only (default if --apply not passed)",
    )
    parser.add_argument("--apply", action="store_true", help="Write trade_log updates")
    parser.add_argument(
        "--i-know-this-is-prod",
        action="store_true",
        help="Required to write a fund with is_production=true",
    )
    args = parser.parse_args(argv)

    if args.apply and args.dry_run:
        print("Error: pass only one of --dry-run / --apply")
        return 1

    dry_run = not args.apply
    ticker = args.ticker.strip().upper()
    ratio: Decimal = args.ratio

    from web_dashboard.supabase_client import SupabaseClient

    client = SupabaseClient(use_service_role=True)
    sb = client.supabase

    fund_res = (
        sb.table("funds").select("name, is_production").eq("name", args.fund).limit(1).execute()
    )
    if not fund_res.data:
        print(f"Error: fund not found: {args.fund}")
        return 1
    is_production = bool(fund_res.data[0].get("is_production"))

    if not dry_run:
        try:
            assert_fund_writable(is_production, args.i_know_this_is_prod)
        except SplitApplyError as e:
            print(f"Error: {e}")
            return 1

    trades_res = (
        sb.table("trade_log")
        .select("id, fund, date, ticker, action, shares, price, cost_basis, pnl")
        .eq("fund", args.fund)
        .eq("ticker", ticker)
        .order("date")
        .execute()
    )
    rows = list(trades_res.data or [])

    try:
        planned = plan_split_updates(rows, ratio)
    except SplitApplyError as e:
        print(f"Error: {e}")
        return 1

    open_before = implied_open_shares(
        [
            {
                "date": p["date"],
                "action": p["action"],
                "shares_before": p["shares_before"],
            }
            for p in planned
        ],
        "shares_before",
    )
    open_after = implied_open_shares(
        [
            {
                "date": p["date"],
                "action": p["action"],
                "shares_after": p["shares_after"],
            }
            for p in planned
        ],
        "shares_after",
    )

    mode = "DRY-RUN" if dry_run else "APPLY"
    print(f"Stock split ({mode})")
    print(f"  fund={args.fund}  ticker={ticker}  ratio={ratio}  production={is_production}")
    print(f"  matched {len(planned)} trade_log row(s)")
    print()
    print(_format_table(planned))
    print()
    print(f"Implied open position: {open_before} -> {open_after} shares (cost_basis unchanged)")
    print()
    print("Next: targeted position repair (do NOT full-rebuild until Yahoo back-adjusts):")
    print(_follow_up_sql(args.fund, ticker, ratio))

    if dry_run:
        print()
        print("DRY-RUN only — no trade_log writes.")
        return 0

    updated = 0
    for row in planned:
        sb.table("trade_log").update(
            {
                "shares": str(row["shares_after"]),
                "price": str(row["price_after"]),
            }
        ).eq("id", row["id"]).execute()
        updated += 1
    print()
    print(f"Updated {updated} trade_log row(s). Positions were NOT rebuilt.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
