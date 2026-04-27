#!/usr/bin/env python3
"""
Inventory of tier-1 UI AI summary scopes (template / metric bundle mapping).

Phase 0: single pilot scope `dashboard.portfolio_overview`; expand in later phases.
"""

from __future__ import annotations

# scope -> metadata
SCOPE_REGISTRY: dict[str, dict[str, str]] = {
    "dashboard.portfolio_overview": {
        "content_class": "price_linked",
        "template": "dashboard.html",
        "description": "Fund totals, period change, top holdings, sector weights (ALL range pilot)",
    },
    "signals.overview": {
        "content_class": "price_linked",
        "template": "signals.html",
        "description": "Planned: watchlist signal aggregates",
    },
    "research.feed": {
        "content_class": "content_linked",
        "template": "research.html",
        "description": "Planned: recent article titles/conclusions digest",
    },
}


def scope_dashboard_portfolio() -> str:
    return "dashboard.portfolio_overview"


def make_portfolio_scope_key(fund: str, display_currency: str, time_range: str) -> str:
    """Stable key for dashboard portfolio tier-1 row (fund + currency + range)."""
    f = (fund or "").strip()
    c = (display_currency or "CAD").strip().upper()
    r = (time_range or "ALL").strip().upper()
    return f"{f}|{c}|{r}"
