"""Admin glance at every Project Chimera holder's stake.

Friends who never log in still ask how their money is doing. This page answers
that from the same NAV ledger as the dashboard "Your share" card, for Chimera only.
"""

from __future__ import annotations

import logging
import math
from typing import Any, Dict, Optional

from flask import Blueprint, jsonify, render_template

from auth import require_admin
from flask_data_utils import (
    fetch_latest_rates_bulk_flask as fetch_latest_rates_bulk,
    get_cash_balances_flask as get_cash_balances,
    get_current_positions_flask as get_current_positions,
)
from portfolio_metrics import get_user_investment_metrics
from portfolio_summary_math import compute_core_summary_metrics
from user_preferences import get_user_currency

logger = logging.getLogger(__name__)

holder_glance_bp = Blueprint("holder_glance", __name__)

CHIMERA_FUND = "Project Chimera"


def _finite(value: Any, default: Optional[float] = 0.0) -> Optional[float]:
    """JSON-safe float. ``default`` is used for missing or non-finite input."""
    if value is None:
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(number) or math.isinf(number):
        return default
    return number


def load_chimera_holder_glance() -> Dict[str, Any]:
    """Current value, return, and today's slice for each Chimera holder."""
    display_currency = get_user_currency() or "CAD"
    positions_df = get_current_positions(CHIMERA_FUND)
    cash_balances = get_cash_balances(CHIMERA_FUND) or {}

    currencies = set()
    if positions_df is not None and not positions_df.empty and "currency" in positions_df.columns:
        codes = positions_df["currency"].fillna("CAD").astype(str).str.upper().unique().tolist()
        currencies.update(codes)
    currencies.update(str(code).upper() for code in cash_balances.keys())
    rate_map = fetch_latest_rates_bulk(list(currencies), display_currency)

    core = compute_core_summary_metrics(positions_df, cash_balances, rate_map, display_currency)
    total_value = float(core["total_value"])
    total_cash = float(core["cash_balance"])
    day_change = _finite(core.get("day_change"), 0.0) or 0.0
    day_change_pct = _finite(core.get("day_change_pct"), None)
    portfolio_value_no_cash = total_value - total_cash

    raw = get_user_investment_metrics(
        CHIMERA_FUND,
        portfolio_value_no_cash,
        include_cash=True,
        session_id="chimera-holders",
        display_currency=display_currency,
        user_email="",
        user_id="",
        for_all_holders=True,
    )
    if not raw:
        return {
            "fund": CHIMERA_FUND,
            "display_currency": display_currency,
            "fund_value": 0.0,
            "unit_price": None,
            "day_change": day_change,
            "day_change_pct": day_change_pct,
            "holders": [],
        }

    holders = []
    for row in raw.get("holders") or []:
        ownership = _finite(row.get("ownership_pct"), 0.0) or 0.0
        holders.append(
            {
                "name": row.get("name") or "Unknown",
                "net_contribution": _finite(row.get("net_contribution"), 0.0),
                "current_value": _finite(row.get("current_value"), 0.0),
                "gain_loss": _finite(row.get("gain_loss"), 0.0),
                "gain_loss_pct": _finite(row.get("gain_loss_pct"), None),
                "ownership_pct": ownership,
                "day_change": day_change * (ownership / 100.0),
                "day_change_pct": day_change_pct,
            }
        )

    return {
        "fund": CHIMERA_FUND,
        "display_currency": raw.get("display_currency") or display_currency,
        "fund_value": _finite(raw.get("fund_value"), 0.0),
        "unit_price": _finite(raw.get("unit_price"), None),
        "day_change": day_change,
        "day_change_pct": day_change_pct,
        "holders": holders,
    }


@holder_glance_bp.route("/admin/chimera-holders")
@require_admin
def chimera_holders_page():
    """Glance page: each Chimera friend's stake."""
    from app import get_navigation_context

    nav_context = get_navigation_context(current_page="admin_chimera_holders")
    return render_template("chimera_holders.html", **nav_context)


@holder_glance_bp.route("/api/admin/chimera-holders")
@require_admin
def api_chimera_holders():
    """NAV-based stake for every Project Chimera holder."""
    try:
        return jsonify(load_chimera_holder_glance())
    except Exception as exc:
        logger.error("Chimera holder glance failed: %s", exc, exc_info=True)
        return jsonify({"error": "Could not load Chimera holder balances"}), 500
