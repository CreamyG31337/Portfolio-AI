#!/usr/bin/env python3
"""Trace net shares in trade_log vs latest_positions for dust tickers."""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "web_dashboard"))

from dotenv import load_dotenv

load_dotenv(project_root / "web_dashboard" / ".env")

from supabase_client import SupabaseClient  # noqa: E402

from utils.trade_reason import is_trade_sell  # noqa: E402


def net_shares_from_trades(trades: list[dict]) -> Decimal:
    net = Decimal("0")
    for t in trades:
        sh = Decimal(str(t.get("shares") or 0))
        is_sell = is_trade_sell(t)
        if is_sell:
            net -= sh
        else:
            net += sh
    return net


def main() -> None:
    parser = argparse.ArgumentParser(description="Trace dust positions from trade_log")
    parser.add_argument("--fund", default="RRSP Lance Webull")
    parser.add_argument("--tickers", nargs="+", default=["BUG", "PAYX", "EXPD"])
    args = parser.parse_args()

    client = SupabaseClient(use_service_role=True)
    fund = args.fund

    print(f"Fund: {fund}\n")

    for ticker in args.tickers:
        res = (
            client.supabase.table("trade_log")
            .select("date,ticker,shares,price,reason,action,cost_basis,pnl")
            .eq("fund", fund)
            .eq("ticker", ticker)
            .order("date")
            .execute()
        )
        rows = res.data or []
        print(f"=== {ticker} ({len(rows)} trades) ===")
        net = Decimal("0")
        for t in rows:
            sh = Decimal(str(t.get("shares") or 0))
            reason = str(t.get("reason") or "")
            action = str(t.get("action") or "")
            is_sell = is_trade_sell(t)
            if is_sell:
                net -= sh
                sign = "SELL"
            else:
                net += sh
                sign = action or "BUY+"
            date_str = str(t.get("date") or "")[:10]
            print(f"  {date_str} | {sign:8} | {sh:>12} @ {t.get('price')} | {reason[:60]}")
        print(f"  NET (is_trade_sell): {net}")

        # Simulate jobs_portfolio.py rebuild (same is_trade_sell classification)
        running = {"shares": Decimal("0"), "cost": Decimal("0")}
        for t in rows:
            sh = Decimal(str(t.get("shares") or 0))
            pr = Decimal(str(t.get("price") or 0))
            if is_trade_sell(t):
                if running["shares"] > 0:
                    cps = running["cost"] / running["shares"]
                    running["shares"] -= sh
                    running["cost"] -= sh * cps
                    if running["shares"] < 0:
                        running["shares"] = Decimal("0")
                    if running["cost"] < 0:
                        running["cost"] = Decimal("0")
            else:
                running["shares"] += sh
                running["cost"] += sh * pr
        print(f"  NET (portfolio job logic): {running['shares']}")

        pos = (
            client.supabase.table("latest_positions")
            .select("ticker,shares,current_price,market_value")
            .eq("fund", fund)
            .eq("ticker", ticker)
            .execute()
        )
        if pos.data:
            p = pos.data[0]
            print(
                f"  latest_positions: shares={p.get('shares')} "
                f"price={p.get('current_price')} mv={p.get('market_value')}"
            )
        else:
            print("  latest_positions: (none)")
        print()

    # All dust: positions with market_value < $5
    dust = (
        client.supabase.table("latest_positions")
        .select("ticker,shares,current_price,market_value")
        .eq("fund", fund)
        .lt("market_value", 5)
        .order("market_value")
        .execute()
    )
    print(f"=== All positions with market_value < $5 ({len(dust.data or [])}) ===")
    for p in dust.data or []:
        print(
            f"  {p['ticker']:6} shares={p.get('shares')} "
            f"price={p.get('current_price')} mv={p.get('market_value')}"
        )


if __name__ == "__main__":
    main()
