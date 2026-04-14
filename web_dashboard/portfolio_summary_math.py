"""Shared portfolio KPI math for dashboard API and outbound digest (single source of truth)."""

from __future__ import annotations

from typing import Any, Dict, Optional

import pandas as pd


def compute_core_summary_metrics(
    positions_df: pd.DataFrame,
    cash_balances: Dict[str, float],
    rate_map: Dict[str, float],
    display_currency: str,
) -> Dict[str, Any]:
    """Compute totals, day change, unrealized P&L, and optional 5-day position P&L (FX to display_currency).

    Mirrors the numeric core of ``get_dashboard_summary`` in dashboard_routes (period change excluded).
    """
    target = str(display_currency or "CAD").upper()

    def get_rate(curr: str) -> float:
        c = str(curr or "CAD").upper()
        if c == target:
            return 1.0
        return float(rate_map.get(c, 1.0))

    portfolio_value_no_cash = 0.0
    total_pnl = 0.0
    day_pnl = 0.0
    five_day_pnl = 0.0

    if not positions_df.empty:
        rates = positions_df["currency"].fillna("CAD").astype(str).str.upper().map(get_rate)
        portfolio_value_no_cash = float((positions_df["market_value"].fillna(0) * rates).sum())
        total_pnl = float((positions_df["unrealized_pnl"].fillna(0) * rates).sum())
        if "daily_pnl" in positions_df.columns:
            day_pnl = float((positions_df["daily_pnl"].fillna(0) * rates).sum())
        if "five_day_pnl" in positions_df.columns:
            five_day_pnl = float((positions_df["five_day_pnl"].fillna(0) * rates).sum())

    total_cash = 0.0
    for curr, amount in (cash_balances or {}).items():
        if amount and amount > 0:
            total_cash += float(amount) * get_rate(str(curr))

    total_value = portfolio_value_no_cash + total_cash

    day_pnl_pct = 0.0
    if (total_value - day_pnl) > 0:
        day_pnl_pct = (day_pnl / (total_value - day_pnl)) * 100

    unrealized_pnl_pct = 0.0
    cost_basis = portfolio_value_no_cash - total_pnl
    if cost_basis > 0:
        unrealized_pnl_pct = (total_pnl / cost_basis) * 100

    five_day_pnl_pct = 0.0
    denom = total_value - five_day_pnl
    if denom > 0:
        five_day_pnl_pct = (five_day_pnl / denom) * 100

    return {
        "total_value": total_value,
        "cash_balance": total_cash,
        "day_change": day_pnl,
        "day_change_pct": day_pnl_pct,
        "unrealized_pnl": total_pnl,
        "unrealized_pnl_pct": unrealized_pnl_pct,
        "five_day_change": five_day_pnl,
        "five_day_change_pct": five_day_pnl_pct,
        "display_currency": target,
        "holdings_count": len(positions_df) if not positions_df.empty else 0,
    }


def fetch_latest_rates_bulk_with_client(
    client: Any,
    currencies: list[str],
    target_currency: str,
) -> Dict[str, float]:
    """Same logic as ``fetch_latest_rates_bulk_flask`` but accepts any Supabase client wrapper."""
    if not currencies:
        return {}

    unique_currencies = list(
        set([str(c).upper() for c in currencies if c and str(c).upper() != target_currency.upper()])
    )
    if not unique_currencies:
        return {}

    try:
        from datetime import datetime, timedelta

        thirty_days_ago = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        relevant_currencies = list(set(unique_currencies + [target_currency.upper()]))

        response = (
            client.supabase.table("exchange_rates")
            .select("from_currency,to_currency,timestamp,rate")
            .gte("timestamp", thirty_days_ago)
            .in_("from_currency", relevant_currencies)
            .in_("to_currency", relevant_currencies)
            .execute()
        )

        if not response.data:
            return {}

        latest_rates: Dict[tuple[str, str], tuple[Any, float]] = {}
        for row in response.data:
            fc = row["from_currency"].upper()
            tc = row["to_currency"].upper()
            ts = row["timestamp"]
            r = float(row["rate"])
            key = (fc, tc)
            if key not in latest_rates or ts > latest_rates[key][0]:
                latest_rates[key] = (ts, r)

        result: Dict[str, float] = {}
        target = target_currency.upper()

        for curr in unique_currencies:
            curr = curr.upper()
            rate: Optional[float] = None
            if (curr, target) in latest_rates:
                rate = latest_rates[(curr, target)][1]
            elif (target, curr) in latest_rates:
                inv_rate = latest_rates[(target, curr)][1]
                if inv_rate != 0:
                    rate = 1.0 / inv_rate

            if rate is None:
                if curr == "USD" and target == "CAD":
                    result[curr] = 1.35
                elif curr == "CAD" and target == "USD":
                    result[curr] = 1.0 / 1.35
                else:
                    result[curr] = 1.0
            else:
                result[curr] = rate

        return result
    except Exception:
        return {c: 1.0 for c in unique_currencies}
