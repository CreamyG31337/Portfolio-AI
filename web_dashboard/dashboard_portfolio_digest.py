#!/usr/bin/env python3
"""Compact numeric + structural digest for dashboard portfolio AI (tier-1)."""

from __future__ import annotations

import json
import logging
from typing import Any

import pandas as pd

from flask_data_utils import (
    calculate_portfolio_value_over_time_flask,
    fetch_latest_rates_bulk_flask,
    get_cash_balances_flask,
    get_current_positions_flask,
)
from portfolio_summary_math import compute_core_summary_metrics

logger = logging.getLogger(__name__)

_DAYS_MAP = {"1M": 30, "3M": 90, "6M": 180, "1Y": 365, "ALL": None}


def build_dashboard_portfolio_digest(
    fund: str | None,
    display_currency: str,
    time_range: str = "ALL",
) -> dict[str, Any]:
    """
    Build a JSON-serializable digest for LLM input (no OHLCV dumps).

    ``fund`` None or 'all' is normalized to cross-fund aggregate where supported.
    """
    raw_fund = fund
    if not fund or str(fund).lower() == "all":
        fund = None

    tr = (time_range or "ALL").upper()
    days = _DAYS_MAP.get(tr)

    positions_df = get_current_positions_flask(fund)
    cash_balances = get_cash_balances_flask(fund)

    all_currencies: set[str] = set()
    if not positions_df.empty and "currency" in positions_df.columns:
        all_currencies.update(
            positions_df["currency"].fillna("CAD").astype(str).str.upper().unique().tolist()
        )
    all_currencies.update(str(c).upper() for c in cash_balances.keys())
    dc = (display_currency or "CAD").upper()
    rate_map = fetch_latest_rates_bulk_flask(list(all_currencies), dc)

    core = compute_core_summary_metrics(positions_df, cash_balances, rate_map, dc)

    period: dict[str, Any] = {}
    if days is not None:
        try:
            range_df = calculate_portfolio_value_over_time_flask(
                fund, days=days, display_currency=dc
            )
            if not range_df.empty:
                period = {
                    "range": tr,
                    "start_value": float(range_df["value"].iloc[0]),
                    "end_value": float(range_df["value"].iloc[-1]),
                    "change": float(range_df["value"].iloc[-1] - range_df["value"].iloc[0]),
                }
                if period["start_value"]:
                    period["change_pct"] = period["change"] / period["start_value"] * 100.0
        except Exception as exc:
            logger.warning("Period stats for digest failed: %s", exc)

    top_holdings: list[dict[str, Any]] = []
    sector_weights: dict[str, float] = {}
    if not positions_df.empty and "market_value" in positions_df.columns and "ticker" in positions_df.columns:
        mv = pd.to_numeric(positions_df["market_value"], errors="coerce").fillna(0.0)
        total_mv = float(mv.sum()) or 1.0
        tmp = positions_df.assign(_mv=mv)
        tmp = tmp.sort_values("_mv", ascending=False)
        for _, row in tmp.head(8).iterrows():
            t = str(row.get("ticker") or "").upper()
            w = float(row["_mv"]) / total_mv * 100.0
            sec = row.get("sector") or row.get("Sector")
            if hasattr(sec, "item"):
                sec = sec.item() if pd.notna(sec) else None
            top_holdings.append(
                {
                    "ticker": t,
                    "weight_pct": round(w, 2),
                    "sector": (str(sec) if sec is not None and str(sec) != "nan" else None),
                }
            )
        if "sector" in tmp.columns:
            for sec, grp in tmp.groupby(tmp["sector"].fillna("Unknown")):
                sector_weights[str(sec)] = round(float(grp["_mv"].sum()) / total_mv * 100.0, 2)

    return {
        "fund": raw_fund,
        "normalized_fund": fund,
        "display_currency": dc,
        "time_range": tr,
        "totals": {
            "total_value": float(core["total_value"]),
            "cash": float(core["cash_balance"]),
            "day_change_pct": float(core["day_change_pct"] or 0),
            "unrealized_pnl_pct": float(core["unrealized_pnl_pct"] or 0),
            "holdings_count": int(len(positions_df)) if not positions_df.empty else 0,
        },
        "period": period,
        "top_holdings": top_holdings,
        "sector_weights_pct": sector_weights,
    }


def digest_fingerprint(digest: dict[str, Any]) -> str:
    """Stable JSON for hashing (sorted keys)."""
    return json.dumps(digest, sort_keys=True, default=str)
