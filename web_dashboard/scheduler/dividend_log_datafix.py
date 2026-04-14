"""
Helpers for one-off dividend_log eligibility corrections.

See web_dashboard/scripts/fix_dividend_log_eligibility.py for the CLI entrypoint.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, time as dt_time
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from scheduler.jobs_dividends import (
    DividendEvent,
    calculate_withholding_tax,
)

logger = logging.getLogger(__name__)

# Match dividend_log numeric(15,6) for money fields
QUANT_6 = Decimal("0.000001")
QUANT_SHARES = Decimal("0.000001")


def parse_ex_date(value: Any) -> date:
    """Parse ex_date from Supabase (date or ISO string)."""
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    s = str(value).strip()
    if "T" in s:
        s = s.split("T", 1)[0]
    y, m, d = (int(x) for x in s.split("-", 2))
    return date(y, m, d)


def legacy_sum_shares_before_ex(fund: str, ticker: str, ex_date: date, client: Any) -> Decimal:
    """
    Sum of trade_log.shares before ex_date (all trades additive).

    Matches the pre-fix bug in calculate_eligible_shares (sells were added, not subtracted).
    Used only as fallback divisor for implied per-share when API data is missing.
    """
    ex_datetime = datetime.combine(ex_date, dt_time(0, 0, 0))
    ex_datetime_str = ex_datetime.isoformat()

    trades_result = (
        client.supabase.table("trade_log")
        .select("shares")
        .eq("fund", fund)
        .eq("ticker", ticker)
        .lt("date", ex_datetime_str)
        .order("date")
        .execute()
    )

    total = Decimal("0")
    for trade in trades_result.data or []:
        total += Decimal(str(trade.get("shares", 0) or 0))
    return total


def per_share_from_events(events: list[DividendEvent], ex_date: date) -> Decimal | None:
    """Return dividend amount per share for ex_date from API-merged events, if present."""
    for evt in events:
        if evt.ex_date == ex_date:
            return Decimal(str(evt.amount))
    return None


def resolve_per_share(
    ticker: str,
    ex_date: date,
    gross_stored: Decimal,
    legacy_sum: Decimal,
    events: list[DividendEvent],
) -> tuple[Decimal, str]:
    """
    Prefer per-share from fetch_dividend_data events; fallback to gross/legacy_sum.

    Returns (per_share, source) where source is 'api' or 'fallback_gross_over_legacy'.
    """
    from_api = per_share_from_events(events, ex_date)
    if from_api is not None and from_api > 0:
        return from_api, "api"

    if legacy_sum > 0:
        implied = (gross_stored / legacy_sum).quantize(QUANT_6, rounding=ROUND_HALF_UP)
        logger.warning(
            "%s ex=%s: no API ex-date match; per_share=%s from gross/legacy_sum=%s",
            ticker,
            ex_date,
            implied,
            legacy_sum,
        )
        return implied, "fallback_gross_over_legacy"

    raise ValueError(
        f"Cannot derive per_share for {ticker} ex={ex_date}: legacy_sum=0 and no API match"
    )


def recalc_amounts(
    eligible: Decimal,
    per_share: Decimal,
    fund_type: str,
    ticker: str,
) -> tuple[Decimal, Decimal, Decimal]:
    """Recompute gross, withholding tax, and net from eligible shares and per-share dividend."""
    gross = (eligible * per_share).quantize(QUANT_6, rounding=ROUND_HALF_UP)
    tax = calculate_withholding_tax(gross, fund_type, ticker).quantize(
        QUANT_6, rounding=ROUND_HALF_UP
    )
    net = (gross - tax).quantize(QUANT_6, rounding=ROUND_HALF_UP)
    return gross, tax, net


def quantize_reinvested_shares(net: Decimal, drip_price: Decimal) -> Decimal:
    """Shares from net / drip_price for DRIP rows."""
    if drip_price <= 0:
        return Decimal("0")
    return (net / drip_price).quantize(QUANT_SHARES, rounding=ROUND_HALF_UP)


def materially_different(a: Decimal, b: Decimal, epsilon: Decimal = QUANT_6) -> bool:
    """True if financial amounts differ beyond trivial rounding."""
    return abs(a - b) > epsilon


def row_amounts_need_update(
    old_gross: Decimal,
    old_tax: Decimal,
    old_net: Decimal,
    old_reinvested: Decimal,
    new_gross: Decimal,
    new_tax: Decimal,
    new_net: Decimal,
    new_reinvested: Decimal,
    epsilon: Decimal = QUANT_6,
) -> bool:
    """Whether any stored dividend_log (and reinvested) field should be rewritten."""
    return (
        materially_different(old_gross, new_gross, epsilon)
        or materially_different(old_tax, new_tax, epsilon)
        or materially_different(old_net, new_net, epsilon)
        or materially_different(old_reinvested, new_reinvested, QUANT_SHARES)
    )
