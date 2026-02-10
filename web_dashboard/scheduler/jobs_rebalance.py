"""
Portfolio Rebalance Recommendation Jobs
=======================================

Advisory-only rebalance scans by fund profile.
No trades are executed; the job writes summary outcomes to job tracking.
"""

import logging
import time
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
import sys

# Add parent directory to path if needed
current_dir = Path(__file__).resolve().parent
if current_dir.name == "scheduler":
    project_root = current_dir.parent.parent
else:
    project_root = current_dir.parent.parent

# Also ensure web_dashboard is in path for supabase_client imports
web_dashboard_path = str(Path(__file__).resolve().parent.parent)
if web_dashboard_path not in sys.path:
    sys.path.insert(0, web_dashboard_path)

# Keep project root before web_dashboard to avoid utils shadowing
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))
elif sys.path[0] != str(project_root):
    sys.path.remove(str(project_root))
    sys.path.insert(0, str(project_root))

from scheduler.scheduler_core import log_job_execution
from settings import get_rebalance_policy, normalize_fund_type

logger = logging.getLogger(__name__)


def _to_decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value or 0))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")


def _analyze_fund_rebalance(
    positions: list[dict[str, Any]],
    cash_rows: list[dict[str, Any]],
    policy: dict[str, Any],
) -> dict[str, Any]:
    """Return concentration and cash-drift recommendations for one fund."""
    max_position_pct = _to_decimal(policy.get("max_position_pct", 15.0))
    max_top3_pct = _to_decimal(policy.get("max_top3_pct", 50.0))
    min_positions = int(policy.get("min_positions", 3))
    min_cash_pct = _to_decimal(policy.get("min_cash_pct", 5.0))
    max_cash_pct = _to_decimal(policy.get("max_cash_pct", 35.0))

    cleaned_positions: list[tuple[str, Decimal]] = []
    for row in positions:
        ticker = str(row.get("ticker", "")).upper().strip()
        market_value = _to_decimal(row.get("market_value"))
        if ticker and market_value > 0:
            cleaned_positions.append((ticker, market_value))

    if not cleaned_positions:
        return {
            "actionable": False,
            "recommendations": ["No active positions found"],
            "position_count": 0,
            "top3_pct": Decimal("0"),
            "cash_pct": Decimal("0"),
        }

    sorted_positions = sorted(cleaned_positions, key=lambda item: item[1], reverse=True)
    total_equity = sum((item[1] for item in sorted_positions), Decimal("0"))
    total_cash = sum((_to_decimal(row.get("amount")) for row in cash_rows), Decimal("0"))
    total_portfolio = total_equity + total_cash

    recommendations: list[str] = []
    overweight: list[tuple[str, Decimal]] = []

    for ticker, market_value in sorted_positions:
        weight_pct = (market_value / total_equity) * Decimal("100")
        if weight_pct > max_position_pct:
            overweight.append((ticker, weight_pct))

    top3_value = sum((item[1] for item in sorted_positions[:3]), Decimal("0"))
    top3_pct = (top3_value / total_equity) * Decimal("100")
    cash_pct = (
        (total_cash / total_portfolio) * Decimal("100")
        if total_portfolio > 0
        else Decimal("0")
    )

    for ticker, weight_pct in overweight[:3]:
        recommendations.append(
            f"Trim {ticker} ({weight_pct:.1f}% > {max_position_pct:.1f}% max position)."
        )

    if top3_pct > max_top3_pct:
        recommendations.append(
            f"Reduce concentration (top 3 = {top3_pct:.1f}% > {max_top3_pct:.1f}% limit)."
        )

    if len(sorted_positions) < min_positions:
        recommendations.append(
            f"Increase diversification ({len(sorted_positions)} positions < {min_positions} minimum)."
        )

    if total_portfolio > 0 and cash_pct < min_cash_pct:
        recommendations.append(
            f"Raise cash buffer ({cash_pct:.1f}% < {min_cash_pct:.1f}% minimum)."
        )
    if total_portfolio > 0 and cash_pct > max_cash_pct:
        recommendations.append(
            f"Deploy excess cash ({cash_pct:.1f}% > {max_cash_pct:.1f}% maximum)."
        )

    return {
        "actionable": bool(recommendations),
        "recommendations": recommendations or ["Portfolio concentration is within profile limits."],
        "position_count": len(sorted_positions),
        "top3_pct": top3_pct,
        "cash_pct": cash_pct,
    }


def _run_rebalance_recommendation_job(job_id: str, target_profile: str) -> None:
    start_time = time.time()
    target_date = datetime.now(timezone.utc).date()

    try:
        from utils.job_tracking import mark_job_started, mark_job_completed
        from supabase_client import SupabaseClient

        mark_job_started(job_id, target_date)
        client = SupabaseClient(use_service_role=True)
        policy = get_rebalance_policy(target_profile)

        funds_result = client.supabase.table("funds").select(
            "name, fund_type, is_production"
        ).execute()
        fund_rows = funds_result.data or []
        production_rows = [row for row in fund_rows if row.get("is_production") is True]
        scoped_rows = production_rows if production_rows else fund_rows

        target_funds = [
            row for row in scoped_rows
            if normalize_fund_type(row.get("fund_type")) == target_profile
        ]
        if not target_funds:
            duration_ms = int((time.time() - start_time) * 1000)
            message = f"No {target_profile} funds found for rebalance review."
            log_job_execution(job_id, True, message, duration_ms)
            mark_job_completed(
                job_id,
                target_date,
                None,
                [],
                duration_ms=duration_ms,
                message=message,
            )
            return

        reviewed_funds: list[str] = []
        actionable_funds: list[str] = []
        sample_recommendations: list[str] = []

        for fund_row in target_funds:
            fund_name = str(fund_row.get("name", "")).strip()
            if not fund_name:
                continue

            positions_result = client.supabase.table("latest_positions").select(
                "ticker, market_value"
            ).eq("fund", fund_name).execute()
            cash_result = client.supabase.table("cash_balances").select(
                "amount"
            ).eq("fund", fund_name).execute()

            analysis = _analyze_fund_rebalance(
                positions=positions_result.data or [],
                cash_rows=cash_result.data or [],
                policy=policy,
            )

            reviewed_funds.append(fund_name)
            if analysis["actionable"]:
                actionable_funds.append(fund_name)
                first_note = str(analysis["recommendations"][0])
                sample_recommendations.append(f"{fund_name}: {first_note}")

            logger.info(
                "Rebalance review (%s) %s: positions=%s top3=%.1f%% cash=%.1f%% actionable=%s",
                target_profile,
                fund_name,
                analysis["position_count"],
                float(analysis["top3_pct"]),
                float(analysis["cash_pct"]),
                analysis["actionable"],
            )

        duration_ms = int((time.time() - start_time) * 1000)
        summary = (
            f"Reviewed {len(reviewed_funds)} {target_profile} fund(s); "
            f"{len(actionable_funds)} with rebalance recommendations."
        )
        if sample_recommendations:
            summary = f"{summary} Example: {sample_recommendations[0]}"

        log_job_execution(job_id, True, summary, duration_ms)
        mark_job_completed(
            job_id,
            target_date,
            None,
            reviewed_funds,
            duration_ms=duration_ms,
            message=summary,
        )
    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        message = f"Job failed: {str(e)}"
        log_job_execution(job_id, False, message, duration_ms)
        try:
            from utils.job_tracking import mark_job_failed
            mark_job_failed(job_id, target_date, None, str(e), duration_ms=duration_ms)
        except Exception:
            pass
        logger.error("Rebalance recommendation job failed", exc_info=True)


def rebalance_recommendation_tfsa_job() -> None:
    """Weekly advisory rebalance scan for TFSA profile funds."""
    _run_rebalance_recommendation_job(
        job_id="rebalance_recommendation_tfsa",
        target_profile="TFSA",
    )


def rebalance_recommendation_rrsp_job() -> None:
    """Monthly advisory rebalance scan for RRSP profile funds."""
    _run_rebalance_recommendation_job(
        job_id="rebalance_recommendation_rrsp",
        target_profile="RRSP",
    )
