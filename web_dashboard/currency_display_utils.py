#!/usr/bin/env python3
"""Currency display helpers shared by Flask and Streamlit (no Streamlit dependency)."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from dashboard_data_clients import get_user_scoped_supabase_client
from flask_cache_utils import cache_data

logger = logging.getLogger(__name__)


def get_user_display_currency() -> str:
    """User's preferred display currency code (default CAD)."""
    try:
        from user_preferences import get_user_currency

        currency = get_user_currency()
        return currency if currency else "CAD"
    except ImportError:
        return "CAD"


def get_exchange_rate_for_display(
    from_currency: str,
    to_currency: str,
    date: Optional[datetime] = None,
) -> Optional[float]:
    """Exchange rate between two currencies (direct or inverse)."""
    if from_currency == to_currency:
        return 1.0

    client = get_user_scoped_supabase_client()
    if not client:
        return None

    try:
        if date is None:
            rate = client.get_latest_exchange_rate(from_currency, to_currency)
        else:
            rate = client.get_exchange_rate(date, from_currency, to_currency)

        if rate is not None:
            return float(rate)

        if date is None:
            inverse_rate = client.get_latest_exchange_rate(to_currency, from_currency)
        else:
            inverse_rate = client.get_exchange_rate(date, to_currency, from_currency)

        if inverse_rate is not None and inverse_rate != 0:
            return 1.0 / float(inverse_rate)

        return None
    except Exception as e:
        logger.warning("Error getting exchange rate %s→%s: %s", from_currency, to_currency, e)
        return None


def convert_to_display_currency(
    value: float,
    from_currency: str,
    date: Optional[datetime] = None,
    display_currency: Optional[str] = None,
) -> float:
    """Convert a value into the user's display currency."""
    if display_currency is None:
        display_currency = get_user_display_currency()

    if from_currency.upper() == display_currency.upper():
        return value

    rate = get_exchange_rate_for_display(from_currency, display_currency, date)

    if rate is None:
        if from_currency.upper() == "USD" and display_currency.upper() == "CAD":
            rate = 1.35
        elif from_currency.upper() == "CAD" and display_currency.upper() == "USD":
            rate = 1.0 / 1.35
        else:
            logger.warning(
                "No exchange rate for %s→%s, returning original value",
                from_currency,
                display_currency,
            )
            return value

    return value * float(rate)


@cache_data(ttl=3600)
def fetch_latest_rates_bulk(currencies: List[str], target_currency: str) -> Dict[str, float]:
    """Latest FX rates for many currencies → one target currency."""
    if not currencies:
        return {}

    unique_currencies = list(
        {
            str(c).upper()
            for c in currencies
            if c and str(c).upper() != target_currency.upper()
        }
    )

    if not unique_currencies:
        return {}

    client = get_user_scoped_supabase_client()
    if not client:
        return {c: 1.0 for c in unique_currencies}

    try:
        thirty_days_ago = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        relevant = list(set(unique_currencies + [target_currency.upper()]))

        response = (
            client.supabase.table("exchange_rates")
            .select("from_currency,to_currency,timestamp,rate")
            .gte("timestamp", thirty_days_ago)
            .in_("from_currency", relevant)
            .in_("to_currency", relevant)
            .execute()
        )

        if not response.data:
            return {}

        latest_rates: Dict[tuple[str, str], tuple[str, float]] = {}
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
    except Exception as e:
        logger.error("Error in fetch_latest_rates_bulk: %s", e)
        res: Dict[str, float] = {}
        for c in unique_currencies:
            if c == "USD" and target_currency == "CAD":
                res[c] = 1.35
            elif c == "CAD" and target_currency == "USD":
                res[c] = 1.0 / 1.35
            else:
                res[c] = 1.0
        return res
