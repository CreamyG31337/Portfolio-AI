
from flask import Blueprint, jsonify, request, render_template, redirect, url_for, Response
import logging
import math
import time
import pandas as pd
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
import json

from auth import require_auth
from flask_auth_utils import get_effective_user_email_flask, get_effective_user_id_flask
from user_preferences import get_user_theme, get_user_currency, get_user_selected_fund

from market_regime_normalization import normalize_market_regime

from flask_data_utils import (
    fetch_dividend_log_flask, 
    get_supabase_client_flask,
    get_current_positions_flask as get_current_positions,
    get_trade_log_flask as get_trade_log,
    get_cash_balances_flask as get_cash_balances,
    get_fund_thesis_data_flask as get_fund_thesis_data,
    fetch_latest_rates_bulk_flask as fetch_latest_rates_bulk,
    get_investor_count_flask as get_investor_count,
    get_first_trade_dates_flask as get_first_trade_dates,
    calculate_portfolio_value_over_time_flask as calculate_portfolio_value_over_time,
    get_biggest_movers_flask as get_biggest_movers,
    get_portfolio_start_date_flask as get_portfolio_start_date,
    get_individual_holdings_performance_flask,
    get_positions_as_of_date_flask
)
from web_dashboard.utils.logo_utils import get_ticker_logo_urls
from web_dashboard.watchlist_access import get_active_watchlist_rows
from utils.trade_reason import infer_trade_action

from action_queue_service import (
    attach_ai_reviews,
    attach_research_context,
    build_action_queue_items,
)

logger = logging.getLogger(__name__)


def _json_safe_number(value: Any, default: float = 0.0) -> float:
    """Return a JSON-serializable number; NaN/Inf become default (avoids invalid JSON)."""
    if value is None:
        return default
    try:
        x = float(value)
        return x if math.isfinite(x) else default
    except (TypeError, ValueError):
        return default


def _json_safe_optional_number(value: Any) -> float | None:
    """Return a finite float or None. Use for optional P&L (e.g. new position = no data).
    None serializes as JSON null so the UI can show '—' instead of misleading $0."""
    if value is None:
        return None
    try:
        x = float(value)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


dashboard_bp = Blueprint('dashboard', __name__)

@dashboard_bp.route('/dashboard')
@require_auth
def dashboard_page():
    """Render the main dashboard page"""
    try:
        # Lazy import to avoid circular dependency
        from app import get_navigation_context
        
        # V2 preference check removed - Flask is now the primary UI
        # Users who prefer Streamlit can access it directly at /streamlit/
        # but Flask handles all authentication
            
        user_email = get_effective_user_email_flask()
        
        # Navigation context
        nav_context = get_navigation_context(current_page='dashboard')

        # Dashboard should start on a concrete fund to avoid misleading aggregate "all funds"
        # metrics in sections that are fundamentally per-fund/per-user.
        selected_fund = get_user_selected_fund()
        if not selected_fund or str(selected_fund).lower() == "all":
            available = nav_context.get("available_funds") or []
            if available:
                selected_fund = available[0]

        # Keep sidebar selector and dashboard JS initial state in sync.
        nav_context["selected_fund"] = selected_fund
        
        return render_template('dashboard.html',
                             user_email=user_email,
                             initial_fund=selected_fund,
                             **nav_context)
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        logger.error(f"Error rendering dashboard: {e}\n{tb}")
        
        # Show full stack trace in debug mode (like AI Assistant does)
        from flask import current_app
        if current_app.debug:
            return f'''<!DOCTYPE html>
<html>
<head><title>Error - Dashboard</title></head>
<body style="background:#1a1a2e;color:#eee;font-family:monospace;padding:20px;">
<h1 style="color:#ff6b6b;">❌ Failed to load Dashboard</h1>
<h2 style="color:#feca57;">Exception: {type(e).__name__}</h2>
<pre style="background:#16213e;padding:20px;border-radius:8px;overflow-x:auto;white-space:pre-wrap;word-wrap:break-word;">{e}</pre>
<h3 style="color:#54a0ff;">Stack Trace:</h3>
<pre style="background:#16213e;padding:20px;border-radius:8px;overflow-x:auto;white-space:pre-wrap;word-wrap:break-word;">{tb}</pre>
<p><a href="/" style="color:#5f27cd;">← Back to Home</a></p>
</body>
</html>''', 500
        
        # Fallback with minimal context in production
        try:
            from app import get_navigation_context
            nav_context = get_navigation_context(current_page='dashboard')
        except Exception:
            # If navigation context also fails, use minimal fallback
            nav_context = {}
        return render_template('dashboard.html', 
                             user_email='User',
                             initial_fund=None,
                             **nav_context)

@dashboard_bp.route('/api/dashboard/latest-timestamp', methods=['GET'])
@require_auth
def get_latest_timestamp():
    """Get the latest timestamp from portfolio_positions (same as Streamlit)"""
    fund = request.args.get('fund')
    if not fund or fund.lower() == 'all':
        fund = None
    
    try:
        from flask_data_utils import get_supabase_client_flask
        client = get_supabase_client_flask()
        if not client:
            return jsonify({"error": "Database client unavailable"}), 500
        
        # Query latest date from portfolio_positions (same as Streamlit)
        query = client.supabase.table("portfolio_positions").select("date")
        if fund:
            query = query.eq("fund", fund)
        
        result = query.order("date", desc=True).limit(1).execute()
        
        if result.data and result.data[0].get('date'):
            from dateutil import parser
            max_date = result.data[0]['date']
            
            # Parse and convert to datetime (same logic as Streamlit)
            if isinstance(max_date, str):
                latest_timestamp = parser.parse(max_date)
            elif hasattr(max_date, 'to_pydatetime'):
                latest_timestamp = max_date.to_pydatetime()
            elif isinstance(max_date, pd.Timestamp):
                latest_timestamp = max_date.to_pydatetime()
            else:
                latest_timestamp = max_date
            
            # Ensure timezone-aware (UTC)
            if latest_timestamp.tzinfo is None:
                latest_timestamp = latest_timestamp.replace(tzinfo=timezone.utc)
            
            return jsonify({
                "timestamp": latest_timestamp.isoformat(),
                "formatted": latest_timestamp.strftime("%Y-%m-%d %I:%M:%S %p")
            })
        else:
            return jsonify({"error": "No data found"}), 404
    except Exception as e:
        logger.error(f"Error fetching latest timestamp: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

@dashboard_bp.route('/api/dashboard/summary', methods=['GET'])
@require_auth
def get_dashboard_summary():
    """Get top-level dashboard metrics"""
    fund = request.args.get('fund')
    raw_fund = fund
    # Convert 'all' or empty string to None for aggregate view
    if not fund or fund.lower() == 'all':
        fund = None
        
    display_currency = get_user_currency() or 'CAD'
    time_range = (request.args.get('range', 'ALL') or 'ALL').upper()
    days_map = {
        '1M': 30,
        '3M': 90,
        '6M': 180,
        '1Y': 365,
        'ALL': None
    }
    days = days_map.get(time_range, None)
    
    logger.info(f"[Dashboard API] /api/dashboard/summary called - fund={fund}, range={time_range}, currency={display_currency}")
    start_time = time.time()
    
    try:
        # Fetch Data
        logger.debug(f"[Dashboard API] Fetching positions for fund={fund}")
        positions_df = get_current_positions(fund)
        logger.debug(f"[Dashboard API] Positions fetched: {len(positions_df)} rows")
        
        logger.debug(f"[Dashboard API] Fetching cash balances for fund={fund}")
        cash_balances = get_cash_balances(fund)
        logger.debug(f"[Dashboard API] Cash balances: {cash_balances}")
        
        # Calculate Rates
        all_currencies = set()
        if not positions_df.empty:
            all_currencies.update(positions_df['currency'].fillna('CAD').astype(str).str.upper().unique().tolist())
        all_currencies.update([str(c).upper() for c in cash_balances.keys()])
        
        logger.debug(f"[Dashboard API] Currencies found: {all_currencies}")
        rate_map = fetch_latest_rates_bulk(list(all_currencies), display_currency)
        logger.debug(f"[Dashboard API] Exchange rates fetched: {len(rate_map)} rates")

        from portfolio_summary_math import compute_core_summary_metrics

        core = compute_core_summary_metrics(positions_df, cash_balances, rate_map, display_currency)
        total_value = core["total_value"]
        total_cash = core["cash_balance"]
        day_pnl = core["day_change"]
        day_pnl_pct = core["day_change_pct"]
        total_pnl = core["unrealized_pnl"]
        unrealized_pnl_pct = core["unrealized_pnl_pct"]
        portfolio_value_no_cash = total_value - total_cash

        # Thesis Data
        logger.debug(f"[Dashboard API] Fetching thesis data for fund={fund}")
        thesis = get_fund_thesis_data(fund) if fund else None
        logger.debug(f"[Dashboard API] Thesis data: {'found' if thesis else 'not found'}")
        
        # Investor & Holdings Count
        investor_count = get_investor_count(fund)
        holdings_count = len(positions_df) if not positions_df.empty else 0
        
        # Get First Trade Date
        first_trade_date = None
        try:
            logger.debug(f"[Dashboard API] Fetching first trade date for fund={fund}")
            # Use optimized query to get start date without fetching entire trade log
            first_trade_date = get_portfolio_start_date(fund)

            # Ensure proper formatting (YYYY-MM-DD)
            if first_trade_date:
                 if 'T' in first_trade_date:
                     first_trade_date = first_trade_date.split('T')[0]
                 # Ensure it's a string
                 first_trade_date = str(first_trade_date)

            logger.debug(f"[Dashboard API] First trade date: {first_trade_date}")
        except Exception as e:
            logger.warning(f"[Dashboard API] Could not get first trade date: {e}")

        # Period change (range-aware)
        period_start_value = None
        period_end_value = None
        period_change = None
        period_change_pct = None
        if days is not None:
            try:
                logger.debug(f"[Dashboard API] Fetching portfolio value over time for range={time_range}")
                range_df = calculate_portfolio_value_over_time(fund, days=days, display_currency=display_currency)
                if not range_df.empty:
                    period_start_value = float(range_df['value'].iloc[0])
                    period_end_value = float(range_df['value'].iloc[-1])
                    period_change = period_end_value - period_start_value
                    period_change_pct = (period_change / period_start_value * 100) if period_start_value > 0 else 0.0
            except Exception as e:
                logger.warning(f"[Dashboard API] Could not calculate period change for range={time_range}: {e}")
        
        user_investment_payload: Optional[Dict[str, Any]] = None
        if fund is not None and investor_count > 1:
            try:
                from portfolio_metrics import get_user_investment_metrics

                uid = (get_effective_user_email_flask() or "").strip()
                eff_user_id = (get_effective_user_id_flask() or "").strip()
                raw_ui = get_user_investment_metrics(
                    fund,
                    float(portfolio_value_no_cash),
                    include_cash=True,
                    session_id="flask-dashboard-summary",
                    display_currency=display_currency,
                    user_email=uid,
                    user_id=eff_user_id,
                )
                if raw_ui:
                    ownership_ratio = float(raw_ui["ownership_pct"]) / 100.0
                    if days is not None and period_change is not None:
                        user_change_dollars = float(period_change) * ownership_ratio
                        user_change_pct = period_change_pct
                    else:
                        user_change_dollars = float(day_pnl) * ownership_ratio
                        user_change_pct = day_pnl_pct
                    user_investment_payload = {
                        "net_contribution": _json_safe_number(raw_ui.get("net_contribution")),
                        "current_value": _json_safe_number(raw_ui.get("current_value")),
                        "gain_loss": _json_safe_number(raw_ui.get("gain_loss")),
                        "gain_loss_pct": _json_safe_optional_number(raw_ui.get("gain_loss_pct")),
                        "ownership_pct": _json_safe_number(raw_ui.get("ownership_pct")),
                        "contributor_name": raw_ui.get("contributor_name"),
                        "units": _json_safe_number(raw_ui.get("units")),
                        "unit_price": _json_safe_number(raw_ui.get("unit_price")),
                        "user_day_change": _json_safe_number(user_change_dollars),
                        "user_day_change_pct": _json_safe_optional_number(user_change_pct),
                    }
            except Exception as uie:
                logger.warning(
                    "[Dashboard API] Could not attach user_investment to summary: %s",
                    uie,
                    exc_info=True,
                )

        processing_time = time.time() - start_time
        response = {
            "total_value": total_value,
            "cash_balance": total_cash,
            "day_change": day_pnl,
            "day_change_pct": day_pnl_pct,
            "unrealized_pnl": total_pnl,
            "unrealized_pnl_pct": unrealized_pnl_pct,
            "display_currency": display_currency,
            "thesis": thesis,
            "investor_count": investor_count,
            "holdings_count": holdings_count,
            "first_trade_date": first_trade_date,
            "period_start_value": period_start_value,
            "period_end_value": period_end_value,
            "period_change": period_change,
            "period_change_pct": period_change_pct,
            "range": time_range,
            "from_cache": False,
            "processing_time": processing_time,
            "user_investment": user_investment_payload,
        }
        
        logger.info(f"[Dashboard API] Summary calculated successfully - total_value={total_value:.2f} {display_currency}, processing_time={processing_time:.3f}s")
        return jsonify(response)
        
    except Exception as e:
        processing_time = time.time() - start_time
        logger.error(f"[Dashboard API] Error calculating dashboard summary (took {processing_time:.3f}s): {e}", exc_info=True)
        return jsonify({"error": str(e), "processing_time": processing_time}), 500

@dashboard_bp.route('/api/dashboard/action-queue', methods=['GET'])
@require_auth
def get_action_queue():
    """Get top priority actions for the dashboard.

    Returns a ranked list of actionable items from the fund's watchlist,
    filtered by the selected fund so that every item is relevant to it.

    Fund-scoped action rules
    ~~~~~~~~~~~~~~~~~~~~~~~~
    Each action type is gated on whether the ticker is currently held in the
    selected fund so the queue changes meaningfully when the user switches
    funds:

    * **SELL** – signal says SELL *and* the fund holds the position.
    * **BUY**  – signal says BUY *and* the fund does **not** hold it.
    * **RISK** – fear level is elevated *and* the fund holds the position
      (no point warning about risk on something the fund doesn't own).
    * **WATCH** – signal says WATCH *and* the fund does **not** hold it
      (potential buy candidates the user is monitoring).

    Query params:
        fund  – fund name, or "all" / empty for cross-fund view.
        limit – max items to return (1-25, default 10).
        enrich – if "0", skip research Postgres joins (default: enrich on).
    """
    fund = request.args.get('fund')
    if not fund or fund.lower() == 'all':
        fund = None

    limit = int(request.args.get('limit', 10))
    limit = max(1, min(limit, 25))
    enrich = request.args.get('enrich', '1').lower() not in ('0', 'false', 'no')

    start_time = time.time()

    try:
        supabase_client = get_supabase_client_flask()
        if not supabase_client:
            return jsonify({"error": "Database client unavailable"}), 500

        actions = build_action_queue_items(supabase_client, fund, limit)

        if enrich:
            try:
                from postgres_client import PostgresClient

                pg = PostgresClient()
                attach_research_context(pg, actions)
                attach_ai_reviews(pg, fund or "", actions)
            except Exception as e:
                logger.warning("[Dashboard API] Action queue enrich skipped: %s", e)

        for row in actions:
            ar = row.get("ai_review")
            if ar and ar.get("updated_at") is not None:
                u = ar["updated_at"]
                if hasattr(u, "isoformat"):
                    ar["updated_at"] = u.isoformat()

        return jsonify({
            "data": actions,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "processing_time": time.time() - start_time
        })
    except Exception as e:
        logger.error(f"[Dashboard API] Error building action queue: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


def _serialize_brief_row(row: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k, v in row.items():
        if v is None:
            out[k] = None
        elif hasattr(v, "isoformat") and callable(getattr(v, "isoformat")):
            out[k] = v.isoformat()
        else:
            out[k] = v
    return out


def _serialize_market_brief_response(row: Dict[str, Any]) -> Dict[str, Any]:
    """JSON for market-brief API: row fields plus ``regime_canonical`` for stable clients."""
    out = _serialize_brief_row(row)
    rj = out.get("regime_json")
    if isinstance(rj, str):
        try:
            loaded = json.loads(rj)
            parsed: Dict[str, Any] = loaded if isinstance(loaded, dict) else {}
        except (json.JSONDecodeError, TypeError):
            parsed = {}
    elif isinstance(rj, dict):
        parsed = rj
    else:
        parsed = {}
    out["regime_canonical"] = normalize_market_regime(
        parsed,
        brief_date=out.get("brief_date"),
        updated_at=out.get("updated_at"),
    )
    return out


@dashboard_bp.route('/api/dashboard/market-brief', methods=['GET'])
@require_auth
def get_market_brief():
    """Latest cached daily market brief from research Postgres (404 if none)."""
    try:
        from market_brief_service import fetch_latest_brief
        from postgres_client import PostgresClient

        pg = PostgresClient()
        row = fetch_latest_brief(pg)
        if not row:
            return jsonify({"error": "No brief generated yet"}), 404
        return jsonify(_serialize_market_brief_response(dict(row)))
    except Exception as e:
        logger.error("[Dashboard API] market-brief: %s", e, exc_info=True)
        return jsonify({"error": str(e)}), 500


@dashboard_bp.route('/api/dashboard/stance-flips', methods=['GET'])
@require_auth
def get_stance_flips():
    """Recent stance changes per (ticker, source, fund_key) from stance_history."""
    start_time = time.time()
    try:
        from postgres_client import PostgresClient
        from today_briefing_service import fetch_stance_flips

        days = request.args.get('days', default=30, type=int)
        limit = request.args.get('limit', default=50, type=int)
        days = max(1, min(days, 365))
        limit = max(1, min(limit, 200))

        pg = PostgresClient()
        rows = fetch_stance_flips(pg, days=days, limit=limit)

        data = []
        for row in rows:
            item = dict(row)
            flipped = item.get("flipped_at")
            if flipped is not None and hasattr(flipped, "isoformat"):
                item["flipped_at"] = flipped.isoformat()
            conf = item.get("confidence")
            if conf is not None:
                item["confidence"] = float(conf)
            meta = item.get("metadata")
            if isinstance(meta, str):
                try:
                    item["metadata"] = json.loads(meta)
                except json.JSONDecodeError:
                    item["metadata"] = {}
            data.append(item)

        return jsonify({
            "data": data,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "processing_time": time.time() - start_time,
        })
    except Exception as e:
        logger.error("[Dashboard API] stance-flips: %s", e, exc_info=True)
        return jsonify({"error": str(e)}), 500


def _serialize_ui_ai_summary_row(row: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k, v in row.items():
        if k == "summary_json" and v is not None:
            if isinstance(v, str):
                try:
                    out[k] = json.loads(v)
                except json.JSONDecodeError:
                    out[k] = {}
            else:
                out[k] = v
        elif v is None:
            out[k] = None
        elif hasattr(v, "isoformat") and callable(getattr(v, "isoformat")):
            out[k] = v.isoformat()
        else:
            out[k] = v
    sj = out.get("summary_json") or {}
    if isinstance(sj, dict):
        out["headline"] = sj.get("headline")
        out["narrative"] = sj.get("narrative")
        out["bullets"] = sj.get("bullets")
    return out


@dashboard_bp.route('/api/dashboard/ai-summary', methods=['GET'])
@require_auth
def get_dashboard_ai_summary():
    """Cached tier-1 AI read for dashboard portfolio metrics (research DB)."""
    scope = (request.args.get("scope") or "").strip().lower()
    if scope in {"commodities", "currency"}:
        return _get_dashboard_scope_summary(scope)

    fund = request.args.get('fund')
    if not fund or str(fund).lower() == 'all':
        return jsonify({"error": "fund query parameter is required", "summary": None}), 400
    tr = (request.args.get('range', 'ALL') or 'ALL').upper()
    dc = get_user_currency() or 'CAD'
    try:
        from postgres_client import PostgresClient
        from ui_ai_summary_scopes import make_portfolio_scope_key, scope_dashboard_portfolio
        from ui_ai_summary_service import fetch_ui_summary_row

        pg = PostgresClient()
        sk = make_portfolio_scope_key(fund, dc, tr)
        row = fetch_ui_summary_row(pg, scope_dashboard_portfolio(), sk)
        fallback_note = None
        if not row and dc.upper() != 'CAD':
            sk_cad = make_portfolio_scope_key(fund, 'CAD', tr)
            row = fetch_ui_summary_row(pg, scope_dashboard_portfolio(), sk_cad)
            if row:
                fallback_note = "Showing CAD-generated summary; switch currency preference or wait for a refresh."

        if not row:
            return jsonify(
                {
                    "summary": None,
                    "scope": scope_dashboard_portfolio(),
                    "scope_key": sk,
                    "hint": "No summary yet. Ensure ui_ai_summary exists and scheduler job ui_ai_summaries has run.",
                }
            )

        payload = _serialize_ui_ai_summary_row(dict(row))
        if fallback_note:
            payload["currency_fallback_note"] = fallback_note
        return jsonify({"summary": payload})
    except Exception as e:
        err = str(e).lower()
        if "ui_ai_summary" in err or "does not exist" in err:
            logger.warning("[Dashboard API] ai-summary table missing: %s", e)
            return jsonify(
                {
                    "error": "ui_ai_summary not installed",
                    "summary": None,
                    "hint": "Apply database/schema/research/tables/ui_ai_summary.sql",
                }
            ), 503
        logger.error("[Dashboard API] ai-summary: %s", e, exc_info=True)
        return jsonify({"error": str(e), "summary": None}), 500


def _get_dashboard_scope_summary(scope: str):
    """Fetch dashboard scope-level summary for commodities/currency."""
    try:
        from postgres_client import PostgresClient
        from ui_ai_summary_scopes import make_global_scope_key
        from ui_ai_summary_service import fetch_ui_summary_row

        pg = PostgresClient()
        if scope == "commodities":
            row = fetch_ui_summary_row(pg, "dashboard.commodities", make_global_scope_key("90D"))
        else:
            fund = request.args.get("fund")
            if not fund or str(fund).lower() == "all":
                return jsonify({"error": "fund query parameter is required for currency scope", "summary": None}), 400
            row = fetch_ui_summary_row(pg, "dashboard.currency", f"{fund}|FX|30D")

        if not row:
            return jsonify({"summary": None, "scope": scope, "hint": "No cached summary yet. Run ui_ai_summaries job."})
        return jsonify({"summary": _serialize_ui_ai_summary_row(dict(row)), "scope": scope})
    except Exception as e:
        logger.error("[Dashboard API] scope ai-summary (%s): %s", scope, e, exc_info=True)
        return jsonify({"summary": None, "scope": scope, "error": str(e)}), 500


def _serialize_fund_digest_row(row: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k, v in row.items():
        if k == "sources_used" and v is not None:
            if isinstance(v, str):
                try:
                    out[k] = json.loads(v)
                except json.JSONDecodeError:
                    out[k] = {}
            else:
                out[k] = v
        elif v is None:
            out[k] = None
        elif hasattr(v, "isoformat") and callable(getattr(v, "isoformat")):
            out[k] = v.isoformat()
        else:
            out[k] = v
    return out


@dashboard_bp.route('/api/dashboard/fund-digest', methods=['GET'])
@require_auth
def get_dashboard_fund_digest():
    """Tier-2 per-fund cross-screen digest (market brief + portfolio summary)."""
    fund = request.args.get('fund')
    if not fund or str(fund).lower() == 'all':
        return jsonify({"error": "fund query parameter is required", "digest": None}), 400
    try:
        from postgres_client import PostgresClient
        from ui_ai_summary_service import fetch_rollup_row

        pg = PostgresClient()
        row = fetch_rollup_row(pg, fund)
        if not row:
            return jsonify(
                {
                    "digest": None,
                    "hint": "No rollup yet. Run scheduler job ui_ai_summaries after tier-1 summaries exist.",
                }
            )
        return jsonify({"digest": _serialize_fund_digest_row(dict(row))})
    except Exception as e:
        err = str(e).lower()
        if "ui_ai_rollup_fund" in err or "does not exist" in err:
            logger.warning("[Dashboard API] fund-digest table missing: %s", e)
            return jsonify(
                {
                    "error": "ui_ai_rollup_fund not installed",
                    "digest": None,
                }
            ), 503
        logger.error("[Dashboard API] fund-digest: %s", e, exc_info=True)
        return jsonify({"error": str(e), "digest": None}), 500


@dashboard_bp.route('/api/dashboard/charts/performance', methods=['GET'])
@require_auth
def get_performance_chart():
    """Get portfolio performance chart as Plotly JSON.
    
    GET /api/dashboard/charts/performance
    
    Query Parameters:
        fund (str): Fund name (optional)
        range (str): Time range - '1M', '3M', '6M', '1Y', or 'ALL' (default: 'ALL')
        use_solid (str): 'true' to use solid lines for benchmarks (default: 'false')
        theme (str): Chart theme - 'dark', 'light', 'midnight-tokyo', 'abyss' (optional)
        
    Returns:
        JSON response with Plotly chart data:
            - data: Array of trace objects
            - layout: Layout configuration
            
    Error Responses:
        500: Server error during data fetch
    """
    import plotly.utils
    from chart_utils import create_portfolio_value_chart
    
    fund = request.args.get('fund') or None
    # Convert empty string to None
    if fund == '':
        fund = None
    time_range = request.args.get('range', 'ALL') # '1M', '3M', '6M', '1Y', 'ALL'
    use_solid = request.args.get('use_solid', 'false').lower() == 'true'
    display_currency = get_user_currency() or 'CAD'
    
    logger.info(f"[Dashboard API] /api/dashboard/charts/performance called - fund={fund}, range={time_range}, currency={display_currency}")
    start_time = time.time()
    
    try:
        # Translate 'All' or empty to None for the backend
        if not fund or fund.lower() == 'all':
            fund = None
            
        from flask_data_utils import calculate_portfolio_value_over_time_flask as calculate_portfolio_value_over_time
        
        days_map = {
            '1M': 30,
            '3M': 90,
            '6M': 180,
            '1Y': 365,
            'ALL': None
        }
        days = days_map.get(time_range)
        logger.debug(f"[Dashboard API] Calculating portfolio value over time - days={days}, fund={fund}")
        
        df = calculate_portfolio_value_over_time(fund, days=days, display_currency=display_currency)
        logger.debug(f"[Dashboard API] Portfolio value data fetched: {len(df)} rows")
        
        # DEBUG: Log performance_index values to diagnose the 0,1,2,3... issue
        if not df.empty and 'performance_index' in df.columns:
            first_10_idx = df['performance_index'].head(10).tolist()
            last_10_idx = df['performance_index'].tail(10).tolist()
            logger.info(f"[DEBUG] Performance Index BEFORE chart creation - First 10: {first_10_idx}, Last 10: {last_10_idx}, Min: {df['performance_index'].min():.2f}, Max: {df['performance_index'].max():.2f}")
            if 'cost_basis' in df.columns:
                first_investment = df[df['cost_basis'] > 0]
                if not first_investment.empty:
                    logger.info(f"[DEBUG] First investment day: {first_investment.iloc[0]['date']}, cost_basis: {first_investment.iloc[0]['cost_basis']}, performance_index: {first_investment.iloc[0]['performance_index']}")
        
        if df.empty:
            from flask_auth_utils import resolve_supabase_access_token_for_rls

            had_supabase_jwt = bool(resolve_supabase_access_token_for_rls())
            logger.warning(
                "[Dashboard API] Performance chart empty - fund=%s range=%s "
                "had_supabase_jwt=%s user_id=%s",
                fund,
                time_range,
                had_supabase_jwt,
                getattr(request, "user_id", None),
            )
            import plotly.graph_objs as go
            fig = go.Figure()
            fig.add_annotation(
                text="No data available",
                xref="paper", yref="paper",
                x=0.5, y=0.5, showarrow=False
            )
            from plotly_utils import serialize_plotly_figure
            payload = json.loads(serialize_plotly_figure(fig))
            payload["meta"] = {
                "reason": "no_portfolio_rows",
                "had_supabase_jwt": had_supabase_jwt,
                "fund": fund,
                "range": time_range,
            }
            return Response(
                json.dumps(payload),
                mimetype='application/json'
            )
        
        # All benchmarks are now passed to the chart (S&P 500 visible, others in legend)
        all_benchmarks = ['sp500', 'qqq', 'russell2000', 'vti']
        
        # Create Plotly chart using shared function (same as Streamlit)
        fig = create_portfolio_value_chart(
            df,
            fund_name=fund,
            show_normalized=True,  # Show percentage change from baseline
            show_benchmarks=all_benchmarks,  # All benchmarks (S&P 500 visible, others in legend)
            show_weekend_shading=True,
            use_solid_lines=use_solid,
            display_currency=display_currency
        )
        
        # DEBUG: Log the actual y-values being sent to the chart
        if fig.data and len(fig.data) > 0:
            portfolio_trace = fig.data[0]  # First trace is usually the portfolio
            if hasattr(portfolio_trace, 'y') and portfolio_trace.y is not None:
                y_values = list(portfolio_trace.y)[:20] if len(portfolio_trace.y) > 20 else list(portfolio_trace.y)
                logger.info(f"[DEBUG] Chart y-values (first 20): {y_values}, Total points: {len(portfolio_trace.y)}")
        
        # Apply theme to chart (similar to ticker chart)
        client_theme = request.args.get('theme', '').strip().lower()
        if not client_theme or client_theme not in ['dark', 'light', 'midnight-tokyo', 'abyss']:
            # Get user theme preference from backend
            user_theme = get_user_theme() or 'system'
            theme = user_theme if user_theme in ['dark', 'light', 'midnight-tokyo', 'abyss'] else 'light'
        else:
            theme = client_theme
        
        # Apply theme to chart data (convert to dict, apply theme, return as JSON)
        from chart_utils import get_chart_theme_config
        from plotly_utils import serialize_plotly_figure
        
        # Serialize figure with numpy array conversion
        chart_json = serialize_plotly_figure(fig)
        chart_data = json.loads(chart_json)
        
        # DEBUG: Log the y-values in the JSON being sent to frontend
        if 'data' in chart_data and len(chart_data['data']) > 0:
            portfolio_data = chart_data['data'][0]
            if 'y' in portfolio_data:
                y_values_json = portfolio_data['y'][:20] if len(portfolio_data['y']) > 20 else portfolio_data['y']
                logger.info(f"[DEBUG] JSON y-values being sent to frontend (first 20): {y_values_json}")
        
        theme_config = get_chart_theme_config(theme)
        
        # Update layout for theme
        if 'layout' in chart_data:
            chart_data['layout']['template'] = theme_config['template']
            chart_data['layout']['paper_bgcolor'] = theme_config['paper_bgcolor']
            chart_data['layout']['plot_bgcolor'] = theme_config['plot_bgcolor']
            chart_data['layout']['font'] = {'color': theme_config['font_color']}
            
            # Update grid colors for both axes if they exist
            if 'xaxis' in chart_data['layout']:
                chart_data['layout']['xaxis']['gridcolor'] = theme_config['grid_color']
                chart_data['layout']['xaxis']['zerolinecolor'] = theme_config['grid_color']
            if 'yaxis' in chart_data['layout']:
                chart_data['layout']['yaxis']['gridcolor'] = theme_config['grid_color']
                chart_data['layout']['yaxis']['zerolinecolor'] = theme_config['grid_color']
            
            # Update legend background if it exists
            if 'legend' in chart_data['layout']:
                chart_data['layout']['legend']['bgcolor'] = theme_config['legend_bg_color']
            
            # Update shapes (baseline line and weekend shading)
            if 'shapes' in chart_data['layout']:
                for shape in chart_data['layout']['shapes']:
                    if shape.get('type') == 'line' and shape.get('y0') == shape.get('y1'):
                        # This is the baseline hline
                        if 'line' in shape:
                            shape['line']['color'] = theme_config['baseline_line_color']
                    elif shape.get('type') == 'rect' and 'fillcolor' in shape:
                        # This is weekend shading
                        shape['fillcolor'] = theme_config['weekend_shading_color']
        
        processing_time = time.time() - start_time
        logger.info(f"[Dashboard API] Performance chart created - {len(df)} data points, use_solid={use_solid}, theme={theme}, processing_time={processing_time:.3f}s")
        
        # Return Plotly JSON with theme applied
        return Response(
            json.dumps(chart_data),
            mimetype='application/json'
        )
        
    except Exception as e:
        processing_time = time.time() - start_time
        logger.error(f"[Dashboard API] Error fetching performance chart (took {processing_time:.3f}s): {e}", exc_info=True)
        return jsonify({"error": str(e), "processing_time": processing_time}), 500


@dashboard_bp.route('/api/dashboard/charts/individual-holdings', methods=['GET'])
@require_auth
def get_individual_holdings_chart():
    """Get individual stock performance chart as Plotly JSON.
    
    GET /api/dashboard/charts/individual-holdings
    
    Query Parameters:
        fund (str): Fund name (required)
        days (int): Number of days - 7, 30, or 0 for all (default: 7)
        filter (str): Stock filter - 'all', 'winners', 'losers', 'top5', 'bottom5', 'cad', 'usd' (default: 'all')
        use_solid (str): 'true' to use solid lines for benchmarks (default: 'false')
        theme (str): Chart theme - 'dark', 'light', 'midnight-tokyo', 'abyss' (optional)
        
    Returns:
        JSON response with Plotly chart data and metadata
            
    Error Responses:
        400: Fund is required
        500: Server error during data fetch
    """
    import plotly.utils
    from chart_utils import create_individual_holdings_chart, get_chart_theme_config
    from flask_data_utils import get_individual_holdings_performance_flask
    from plotly_utils import serialize_plotly_figure
    
    fund = request.args.get('fund')
    if not fund or fund.lower() == 'all':
        return jsonify({"error": "Fund name is required for individual holdings chart"}), 400
    
    days = int(request.args.get('days', '7'))
    stock_filter = request.args.get('filter', 'all')
    use_solid = request.args.get('use_solid', 'false').lower() == 'true'
    client_theme = request.args.get('theme', '').strip().lower()
    
    logger.info(f"[Dashboard API] /api/dashboard/charts/individual-holdings called - fund={fund}, days={days}, filter={stock_filter}")
    start_time = time.time()
    
    try:
        # Get holdings data
        holdings_df = get_individual_holdings_performance_flask(fund, days=days)
        
        if holdings_df.empty:
            logger.warning(f"[Dashboard API] No individual holdings data found for fund={fund}, days={days}")
            import plotly.graph_objs as go
            fig = go.Figure()
            fig.add_annotation(
                text="No holdings data available",
                xref="paper", yref="paper",
                x=0.5, y=0.5, showarrow=False
            )
            return Response(
                serialize_plotly_figure(fig),
                mimetype='application/json'
            )
        
        # Apply stock filter
        if stock_filter != 'all' and not holdings_df.empty:
            latest_per_ticker = holdings_df.sort_values('date').groupby('ticker').last().reset_index()
            tickers_to_show = latest_per_ticker['ticker'].tolist()
            
            if stock_filter == 'winners':
                if 'return_pct' in latest_per_ticker.columns:
                    tickers_to_show = latest_per_ticker[latest_per_ticker['return_pct'].fillna(0) > 0]['ticker'].tolist()
            elif stock_filter == 'losers':
                if 'return_pct' in latest_per_ticker.columns:
                    tickers_to_show = latest_per_ticker[latest_per_ticker['return_pct'].fillna(0) < 0]['ticker'].tolist()
            elif stock_filter == 'daily_winners':
                if 'daily_pnl_pct' in latest_per_ticker.columns:
                    tickers_to_show = latest_per_ticker[latest_per_ticker['daily_pnl_pct'].fillna(0) > 0]['ticker'].tolist()
            elif stock_filter == 'daily_losers':
                if 'daily_pnl_pct' in latest_per_ticker.columns:
                    tickers_to_show = latest_per_ticker[latest_per_ticker['daily_pnl_pct'].fillna(0) < 0]['ticker'].tolist()
            elif stock_filter == 'top5':
                if 'return_pct' in latest_per_ticker.columns:
                    top_5 = latest_per_ticker.nlargest(5, 'return_pct')
                    tickers_to_show = top_5['ticker'].tolist()
            elif stock_filter == 'bottom5':
                if 'return_pct' in latest_per_ticker.columns:
                    bottom_5 = latest_per_ticker.nsmallest(5, 'return_pct')
                    tickers_to_show = bottom_5['ticker'].tolist()
            elif stock_filter == 'cad':
                if 'currency' in latest_per_ticker.columns:
                    tickers_to_show = latest_per_ticker[latest_per_ticker['currency'] == 'CAD']['ticker'].tolist()
            elif stock_filter == 'usd':
                if 'currency' in latest_per_ticker.columns:
                    tickers_to_show = latest_per_ticker[latest_per_ticker['currency'] == 'USD']['ticker'].tolist()
            elif stock_filter.startswith('sector:'):
                sector_name = stock_filter.replace('sector:', '')
                if 'sector' in latest_per_ticker.columns:
                    tickers_to_show = latest_per_ticker[latest_per_ticker['sector'] == sector_name]['ticker'].tolist()
            elif stock_filter.startswith('industry:'):
                industry_name = stock_filter.replace('industry:', '')
                if 'industry' in latest_per_ticker.columns:
                    tickers_to_show = latest_per_ticker[latest_per_ticker['industry'] == industry_name]['ticker'].tolist()
            
            holdings_df = holdings_df[holdings_df['ticker'].isin(tickers_to_show)].copy()
        
        # All benchmarks (S&P 500 visible, others in legend)
        all_benchmarks = ['sp500', 'qqq', 'russell2000', 'vti']
        
        # Create chart
        fig = create_individual_holdings_chart(
            holdings_df,
            fund_name=fund,
            show_benchmarks=all_benchmarks,
            show_weekend_shading=True,
            use_solid_lines=use_solid
        )
        
        # Apply theme
        if not client_theme or client_theme not in ['dark', 'light', 'midnight-tokyo', 'abyss']:
            user_theme = get_user_theme() or 'system'
            theme = user_theme if user_theme in ['dark', 'light', 'midnight-tokyo', 'abyss'] else 'light'
        else:
            theme = client_theme
        
        chart_json = serialize_plotly_figure(fig)
        chart_data = json.loads(chart_json)
        
        theme_config = get_chart_theme_config(theme)
        
        # Update layout for theme
        if 'layout' in chart_data:
            chart_data['layout']['template'] = theme_config['template']
            chart_data['layout']['paper_bgcolor'] = theme_config['paper_bgcolor']
            chart_data['layout']['plot_bgcolor'] = theme_config['plot_bgcolor']
            chart_data['layout']['font'] = {'color': theme_config['font_color']}
            
            if 'xaxis' in chart_data['layout']:
                chart_data['layout']['xaxis']['gridcolor'] = theme_config['grid_color']
            if 'yaxis' in chart_data['layout']:
                chart_data['layout']['yaxis']['gridcolor'] = theme_config['grid_color']
            if 'legend' in chart_data['layout']:
                chart_data['layout']['legend']['bgcolor'] = theme_config['legend_bg_color']
        
        # Get metadata for filter dropdowns
        sectors = sorted([s for s in holdings_df['sector'].dropna().unique() if s]) if 'sector' in holdings_df.columns else []
        industries = sorted([i for i in holdings_df['industry'].dropna().unique() if i]) if 'industry' in holdings_df.columns else []
        num_stocks = holdings_df['ticker'].nunique()
        
        processing_time = time.time() - start_time
        logger.info(f"[Dashboard API] Individual holdings chart created - {num_stocks} stocks, processing_time={processing_time:.3f}s")
        
        # Return chart data with metadata
        response_data = {
            **chart_data,
            'metadata': {
                'num_stocks': num_stocks,
                'sectors': sectors,
                'industries': industries,
                'days': days,
                'filter': stock_filter
            }
        }
        
        return Response(
            json.dumps(response_data),
            mimetype='application/json'
        )
        
    except Exception as e:
        processing_time = time.time() - start_time
        logger.error(f"[Dashboard API] Error fetching individual holdings chart (took {processing_time:.3f}s): {e}", exc_info=True)
        return jsonify({"error": str(e), "processing_time": processing_time}), 500


@dashboard_bp.route('/api/dashboard/charts/allocation', methods=['GET'])
@require_auth
def get_allocation_charts():
    """Get allocation chart as Plotly JSON (Sector pie chart).
    
    GET /api/dashboard/charts/allocation
    
    Query Parameters:
        fund (str): Fund name (optional)
        theme (str): Chart theme - 'dark', 'light', 'midnight-tokyo', 'abyss' (optional)
        view (str): Chart view - 'top_bottom', 'winners', 'losers' (optional)
        
    Returns:
        JSON response with Plotly chart data:
            - data: Array of trace objects (pie chart)
            - layout: Layout configuration
            
    Error Responses:
        500: Server error during data fetch
    """
    import plotly.utils
    from chart_utils import create_sector_allocation_chart
    from user_preferences import get_user_theme
    
    fund = request.args.get('fund')
    # Convert 'all' or empty string to None for aggregate view
    if not fund or fund.lower() == 'all':
        fund = None
    
    client_theme = request.args.get('theme', '').strip().lower()
    chart_view = request.args.get('view', 'top_bottom').strip().lower()
    if chart_view not in {'top_bottom', 'winners', 'losers'}:
        chart_view = 'top_bottom'
    time_range = (request.args.get('range', 'ALL') or 'ALL').upper()
    days_map = {
        '1M': 30,
        '3M': 90,
        '6M': 180,
        '1Y': 365,
        'ALL': None
    }
    days = days_map.get(time_range, None)
    display_currency = get_user_currency() or 'CAD'
    
    logger.info(f"[Dashboard API] /api/dashboard/charts/allocation called - fund={fund}, range={time_range}, currency={display_currency}")
    start_time = time.time()
    
    try:
        logger.debug(f"[Dashboard API] Fetching positions for allocation chart")
        if days is None:
            positions_df = get_current_positions(fund)
        else:
            as_of_date = datetime.now(timezone.utc) - timedelta(days=days)
            positions_df = get_positions_as_of_date_flask(fund, as_of_date)
        logger.debug(f"[Dashboard API] Positions fetched: {len(positions_df)} rows")
        
        # Debug: Log sample of market_value data
        if not positions_df.empty and 'market_value' in positions_df.columns:
            sample_values = positions_df['market_value'].head(10).tolist()
            total_market_value = positions_df['market_value'].sum()
            logger.info(f"[Dashboard API] Sample market_value values: {sample_values}")
            logger.info(f"[Dashboard API] Total market_value: {total_market_value}")
            logger.info(f"[Dashboard API] Market_value column type: {positions_df['market_value'].dtype}")
            logger.info(f"[Dashboard API] Market_value null count: {positions_df['market_value'].isna().sum()}")
        
        if positions_df.empty:
            logger.warning(f"[Dashboard API] No positions found for allocation chart - fund={fund}")
            # Return empty Plotly chart
            import plotly.graph_objs as go
            fig = go.Figure()
            fig.add_annotation(
                text="No data available",
                xref="paper", yref="paper",
                x=0.5, y=0.5, showarrow=False
            )
            from plotly_utils import serialize_plotly_figure
            return Response(
                serialize_plotly_figure(fig),
                mimetype='application/json'
            )
        
        # Create Plotly pie chart using shared function (same as Streamlit)
        # Pass display_currency to ensure all values are converted before aggregation
        fig = create_sector_allocation_chart(positions_df, fund_name=fund, display_currency=display_currency)
        
        # Update height to match container (700px) and increase bottom margin for legend
        fig.update_layout(
            height=700,
            margin=dict(l=20, r=20, t=50, b=100)  # Increased bottom margin for legend
        )
        
        # Apply theme to chart (similar to ticker chart)
        if not client_theme or client_theme not in ['dark', 'light', 'midnight-tokyo', 'abyss']:
            # Get user theme preference from backend
            from user_preferences import get_user_theme
            user_theme = get_user_theme() or 'system'
            theme = user_theme if user_theme in ['dark', 'light', 'midnight-tokyo', 'abyss'] else 'light'
        else:
            theme = client_theme
        
        # Apply theme to chart data (convert to dict, apply theme, return as JSON)
        from chart_utils import get_chart_theme_config
        from plotly_utils import serialize_plotly_figure
        
        # Serialize figure with numpy array conversion
        chart_json = serialize_plotly_figure(fig)
        chart_data = json.loads(chart_json)
        theme_config = get_chart_theme_config(theme)
        
        # Update layout for theme
        if 'layout' in chart_data:
            chart_data['layout']['template'] = theme_config['template']
            chart_data['layout']['paper_bgcolor'] = theme_config['paper_bgcolor']
            chart_data['layout']['plot_bgcolor'] = theme_config['plot_bgcolor']
            chart_data['layout']['font'] = {'color': theme_config['font_color']}
            
            # Update legend background if it exists
            if 'legend' in chart_data['layout']:
                chart_data['layout']['legend']['bgcolor'] = theme_config['legend_bg_color']
        
        processing_time = time.time() - start_time
        logger.info(f"[Dashboard API] Sector allocation chart created - theme={theme}, processing_time={processing_time:.3f}s")
        
        # Return Plotly JSON with theme applied
        return Response(
            json.dumps(chart_data),
            mimetype='application/json'
        )
        
    except Exception as e:
        processing_time = time.time() - start_time
        logger.error(f"[Dashboard API] Error fetching allocation charts (took {processing_time:.3f}s): {e}", exc_info=True)
        return jsonify({"error": str(e), "processing_time": processing_time}), 500

@dashboard_bp.route('/api/dashboard/charts/pnl', methods=['GET'])
@require_auth
def get_pnl_chart():
    """Get P&L by Position chart as Plotly JSON.
    
    GET /api/dashboard/charts/pnl
    
    Query Parameters:
        fund (str): Fund name (optional)
        theme (str): Chart theme - 'dark', 'light', 'midnight-tokyo', 'abyss' (optional)
        view (str): Chart view - 'top_bottom', 'winners', or 'losers' (default: 'top_bottom')
        
    Returns:
        JSON response with Plotly chart data:
            - data: Array of trace objects (bar chart)
            - layout: Layout configuration
            
    Error Responses:
        500: Server error during data fetch
    """
    from chart_utils import create_pnl_chart, get_chart_theme_config
    from plotly_utils import serialize_plotly_figure
    from flask_data_utils import fetch_dividend_log_flask
    
    fund = request.args.get('fund')
    # Convert 'all' or empty string to None for aggregate view
    if not fund or fund.lower() == 'all':
        fund = None
    
    client_theme = request.args.get('theme', '').strip().lower()
    chart_view = request.args.get('view', 'top_bottom').strip().lower()
    if chart_view not in {'top_bottom', 'winners', 'losers'}:
        chart_view = 'top_bottom'
    time_range = (request.args.get('range', 'ALL') or 'ALL').upper()
    days_map = {
        '1M': 30,
        '3M': 90,
        '6M': 180,
        '1Y': 365,
        'ALL': None
    }
    days = days_map.get(time_range, None)
    display_currency = get_user_currency() or 'CAD'
    
    logger.info(f"[Dashboard API] /api/dashboard/charts/pnl called - fund={fund}, range={time_range}, currency={display_currency}")
    start_time = time.time()
    
    try:
        if days is None:
            logger.debug(f"[Dashboard API] Fetching positions for P&L chart")
            positions_df = get_current_positions(fund)
            logger.debug(f"[Dashboard API] Positions fetched: {len(positions_df)} rows")
        else:
            logger.debug(f"[Dashboard API] Fetching trade log for realized P&L chart")
            trades_df = get_trade_log(limit=1000, fund=fund)
            logger.debug(f"[Dashboard API] Trade log fetched: {len(trades_df)} rows")

            if trades_df.empty:
                positions_df = pd.DataFrame()
            else:
                cutoff = pd.Timestamp.now(tz='UTC') - pd.Timedelta(days=days)
                if 'date' in trades_df.columns:
                    dates = pd.to_datetime(trades_df['date'], utc=True, errors='coerce')
                    trades_df = trades_df.loc[dates >= cutoff]

                def infer_action_from_row(row):
                    for col in ['side', 'action', 'type']:
                        if col in row and row.get(col):
                            value = str(row.get(col)).lower()
                            if 'sell' in value:
                                return 'SELL'
                            if 'buy' in value:
                                return 'BUY'
                    return infer_trade_action(row.get('reason'), default='BUY')

                sells_df = trades_df.copy()
                if not sells_df.empty:
                    sells_df['action'] = sells_df.apply(infer_action_from_row, axis=1)
                    sells_df = sells_df[sells_df['action'] == 'SELL']

                if sells_df.empty or 'pnl' not in sells_df.columns:
                    positions_df = pd.DataFrame()
                else:
                    sells_df = sells_df[pd.notna(sells_df['pnl'])]
                    ticker_pnl = sells_df.groupby('ticker', as_index=False)['pnl'].sum()
                    positions_df = ticker_pnl.rename(columns={'pnl': 'pnl'})
        
        if positions_df.empty:
            logger.warning(f"[Dashboard API] No positions found for P&L chart - fund={fund}")
            # Return empty Plotly chart
            import plotly.graph_objs as go
            fig = go.Figure()
            fig.add_annotation(
                text="No P&L data available",
                xref="paper", yref="paper",
                x=0.5, y=0.5, showarrow=False
            )
            return Response(
                serialize_plotly_figure(fig),
                mimetype='application/json'
            )
        
        # Check for P&L columns
        if 'pnl' not in positions_df.columns and 'unrealized_pnl' not in positions_df.columns:
            logger.warning(f"[Dashboard API] No P&L columns found in positions data")
            import plotly.graph_objs as go
            fig = go.Figure()
            fig.add_annotation(
                text="No P&L data available",
                xref="paper", yref="paper",
                x=0.5, y=0.5, showarrow=False
            )
            return Response(
                serialize_plotly_figure(fig),
                mimetype='application/json'
            )
        
        # Fetch dividend data (only for current/unrealized mode)
        dividend_data = []
        if days is None:
            try:
                dividend_data = fetch_dividend_log_flask(days_lookback=365, fund=fund)
                logger.debug(f"[Dashboard API] Dividend data fetched: {len(dividend_data)} records")
            except Exception as e:
                logger.warning(f"[Dashboard API] Could not fetch dividend data: {e}")
        
        # Create P&L chart using shared function (same as Streamlit)
        fig = create_pnl_chart(
            positions_df,
            fund_name=fund,
            display_currency=display_currency,
            dividend_data=dividend_data,
            view=chart_view
        )
        
        # Update height to match container (500px)
        fig.update_layout(
            height=500,
            margin=dict(l=20, r=20, t=50, b=100)
        )
        
        # Apply theme to chart
        if not client_theme or client_theme not in ['dark', 'light', 'midnight-tokyo', 'abyss']:
            # Get user theme preference from backend
            user_theme = get_user_theme() or 'system'
            theme = user_theme if user_theme in ['dark', 'light', 'midnight-tokyo', 'abyss'] else 'light'
        else:
            theme = client_theme
        
        # Serialize figure with numpy array conversion
        chart_json = serialize_plotly_figure(fig)
        chart_data = json.loads(chart_json)
        theme_config = get_chart_theme_config(theme)
        
        # Update layout for theme
        if 'layout' in chart_data:
            chart_data['layout']['template'] = theme_config['template']
            chart_data['layout']['paper_bgcolor'] = theme_config['paper_bgcolor']
            chart_data['layout']['plot_bgcolor'] = theme_config['plot_bgcolor']
            chart_data['layout']['font'] = {'color': theme_config['font_color']}
            
            # Update legend background if it exists
            if 'legend' in chart_data['layout']:
                chart_data['layout']['legend']['bgcolor'] = theme_config['legend_bg_color']
        
        processing_time = time.time() - start_time
        logger.info(f"[Dashboard API] P&L chart created - theme={theme}, processing_time={processing_time:.3f}s")
        
        # Return Plotly JSON with theme applied
        return Response(
            json.dumps(chart_data),
            mimetype='application/json'
        )
        
    except Exception as e:
        processing_time = time.time() - start_time
        logger.error(f"[Dashboard API] Error fetching P&L chart (took {processing_time:.3f}s): {e}", exc_info=True)
        return jsonify({"error": str(e), "processing_time": processing_time}), 500

@dashboard_bp.route('/api/dashboard/holdings', methods=['GET'])
def get_holdings_data():
    """Get content for holdings table"""
    fund = request.args.get('fund')
    # Convert 'all' or empty string to None for aggregate view
    if not fund or fund.lower() == 'all':
        fund = None
        
    time_range = (request.args.get('range', 'ALL') or 'ALL').upper()
    days_map = {
        '1M': 30,
        '3M': 90,
        '6M': 180,
        '1Y': 365,
        'ALL': None
    }
    days = days_map.get(time_range, None)
    display_currency = get_user_currency() or 'CAD'
    
    logger.info(f"[Dashboard API] /api/dashboard/holdings called - fund={fund}, range={time_range}, currency={display_currency}")
    start_time = time.time()
    
    try:
        logger.debug(f"[Dashboard API] Fetching positions for holdings table")
        if days is None:
            positions_df = get_current_positions(fund)
        else:
            as_of_date = datetime.now(timezone.utc) - timedelta(days=days)
            positions_df = get_positions_as_of_date_flask(fund, as_of_date)
        logger.debug(f"[Dashboard API] Positions fetched: {len(positions_df)} rows")
        
        if positions_df.empty:
            logger.warning(f"[Dashboard API] No positions found for holdings - fund={fund}")
            return jsonify({"data": []})
        
        # Get first trade dates for "Opened" column
        first_trade_dates = get_first_trade_dates(fund)
            
        # Get rates
        all_currencies = positions_df['currency'].fillna('CAD').astype(str).str.upper().unique().tolist()
        rate_map = fetch_latest_rates_bulk(all_currencies, display_currency)
        def get_rate(curr): return rate_map.get(str(curr).upper(), 1.0)
        
        # Optimize: Vectorized calculation for total portfolio value
        # map() returns a Series aligned with positions_df index
        rates = positions_df['currency'].fillna('CAD').astype(str).str.upper().map(get_rate)
        
        # Safe access to market_value column
        if 'market_value' in positions_df.columns:
            market_values = positions_df['market_value'].fillna(0)
        else:
            market_values = pd.Series([0] * len(positions_df), index=positions_df.index)

        # Vectorized market value in display currency
        market_vals_display = (market_values * rates)
        total_portfolio_value = market_vals_display.sum()
        
        # Batch fetch logo URLs for all tickers (caching-friendly pattern)
        unique_tickers = positions_df['ticker'].dropna().unique().tolist()
        logo_urls_map = {}
        if unique_tickers:
            try:
                logo_urls_map = get_ticker_logo_urls(unique_tickers)
            except Exception as e:
                logger.warning(f"Error fetching logo URLs: {e}")
        
        # Optimize: Pre-calculate commonly used columns/values to avoid repeated lookups inside loop
        # Use itertuples() instead of iterrows() for significantly better performance (10-100x faster)
        data = []

        # Note: itertuples yields named tuples. Access via dot notation (row.ticker) or index.
        # However, accessing dict columns like 'securities' via dot notation works fine.
        for row in positions_df.itertuples(index=False):
            # Access attributes via dot notation (faster) or getattr for safety if column might be missing
            ticker = getattr(row, 'ticker', None)
            if not ticker:
                continue

            # Handle nested securities data
            company_name = ticker # Default
            sector = ""
            securities_data = getattr(row, 'securities', None)
            if isinstance(securities_data, dict):
                company_name = securities_data.get('company_name') or ticker
                sector = securities_data.get('sector') or ""
            
            # Use 'shares' from latest_positions view
            shares = getattr(row, 'shares', 0) or 0
            cost_basis = getattr(row, 'cost_basis', 0) or 0
            current_price = getattr(row, 'current_price', 0) or 0
            
            # Calculate average price (sanitize for JSON)
            avg_price = _json_safe_number((cost_basis / shares) if shares > 0 else 0)

            # Currency conversion
            curr_code = getattr(row, 'currency', 'CAD')
            rate = rate_map.get(str(curr_code).upper(), 1.0)
            
            rate_safe = _json_safe_number(rate, 1.0)
            market_val = _json_safe_number((getattr(row, 'market_value', 0) or 0) * rate_safe)
            pnl = _json_safe_number((getattr(row, 'unrealized_pnl', 0) or 0) * rate_safe)

            # Optional P&L: null when no prior snapshot (e.g. new position) so UI shows "—" not "$0"
            raw_day = _json_safe_optional_number(getattr(row, 'daily_pnl', None))
            day_pnl = (raw_day * rate_safe) if raw_day is not None else None
            day_pnl = _json_safe_optional_number(day_pnl) if day_pnl is not None else None
            day_pnl_pct = _json_safe_optional_number(getattr(row, 'daily_pnl_pct', None))
            raw_five = _json_safe_optional_number(getattr(row, 'five_day_pnl', None))
            five_day_pnl = (raw_five * rate_safe) if raw_five is not None else None
            five_day_pnl = _json_safe_optional_number(five_day_pnl) if five_day_pnl is not None else None
            five_day_pnl_pct = _json_safe_optional_number(getattr(row, 'five_day_pnl_pct', None))

            # Required numbers (never null)
            pnl_pct = _json_safe_number(getattr(row, 'return_pct', 0) or 0)

            # Calculate weight
            weight = _json_safe_number(
                (market_val / total_portfolio_value * 100) if total_portfolio_value > 0 else 0
            )
            
            # Get opened date
            opened_date = None
            if ticker in first_trade_dates:
                try:
                    opened_date = first_trade_dates[ticker].strftime('%m-%d-%y')
                except:
                    opened_date = None
            
            # Get stop loss if available
            stop_loss = getattr(row, 'stop_loss', None)
            
            # Get logo URL
            logo_url = logo_urls_map.get(ticker)
                
            data.append({
                "ticker": ticker,
                "name": company_name,
                "sector": sector,
                "shares": int(_json_safe_number(shares, 0)),
                "opened": opened_date,
                "avg_price": _json_safe_number(avg_price * rate_safe),
                "price": _json_safe_number((current_price or 0) * rate_safe),
                "value": market_val,
                "day_change": day_pnl,
                "day_change_pct": day_pnl_pct,
                "total_return": pnl,
                "total_return_pct": pnl_pct,
                "five_day_pnl": five_day_pnl,
                "five_day_pnl_pct": five_day_pnl_pct,
                "weight": weight,
                "stop_loss": stop_loss,
                "currency": curr_code,
                "_logo_url": logo_url
            })
            
        # Sort by weight desc (matching console app default)
        data.sort(key=lambda x: x.get('weight', 0), reverse=True)
        
        processing_time = time.time() - start_time
        logger.info(f"[Dashboard API] Holdings data prepared - {len(data)} holdings, processing_time={processing_time:.3f}s")
        
        return jsonify({"data": data})
        
    except Exception as e:
        processing_time = time.time() - start_time
        logger.error(f"[Dashboard API] Error fetching holdings (took {processing_time:.3f}s): {e}", exc_info=True)
        return jsonify({"error": str(e), "processing_time": processing_time}), 500

@dashboard_bp.route('/api/dashboard/activity', methods=['GET'])
def get_recent_activity():
    """Get recent transactions, optionally filtered by time range (1M, 3M, ALL)."""
    fund = request.args.get('fund')
    # Convert 'all' or empty string to None for aggregate view
    if not fund or fund.lower() == 'all':
        fund = None
        
    limit = int(request.args.get('limit', 10))
    time_range = request.args.get('range', 'ALL')
    display_currency = get_user_currency() or 'CAD'
    
    days_map = {'1M': 30, '3M': 90, '6M': 180, '1Y': 365, 'ALL': None}
    days = days_map.get(time_range.upper() if time_range else 'ALL')
    
    logger.info(f"[Dashboard API] /api/dashboard/activity called - fund={fund}, limit={limit}, range={time_range}, currency={display_currency}")
    start_time = time.time()
    
    try:
        logger.debug(f"[Dashboard API] Fetching trade log for activity")
        trades_df = get_trade_log(limit=500, fund=fund)
        logger.debug(f"[Dashboard API] Trade log fetched: {len(trades_df)} rows")
        
        if days is not None and 'date' in trades_df.columns and not trades_df.empty:
            cutoff = pd.Timestamp.now(tz='UTC') - pd.Timedelta(days=days)
            dates = pd.to_datetime(trades_df['date'], utc=True)
            trades_df = trades_df.loc[dates >= cutoff].head(limit)
        else:
            trades_df = trades_df.head(limit)
        
        if trades_df.empty:
            logger.warning(f"[Dashboard API] No trades found for activity - fund={fund}, range={time_range}")
            return jsonify({"data": []})
            
        # Batch fetch logo URLs
        unique_tickers = trades_df['ticker'].dropna().unique().tolist()
        logo_urls_map = {}
        if unique_tickers:
            try:
                logo_urls_map = get_ticker_logo_urls(unique_tickers)
            except Exception as e:
                logger.warning(f"Error fetching logo URLs: {e}")
        
        def infer_action(reason):
            """Infer activity action label from reason field for dashboard UI."""
            action = infer_trade_action(reason, default='BUY')
            # The dashboard activity table renders dividend reinvestment entries as DRIP.
            if action == "DIVIDEND":
                return "DRIP"
            return action
        
        def calculate_display_amount(row, action):
            """Calculate display amount: P&L for sells, purchase amount for buys/drips"""
            if action == 'SELL':
                pnl = getattr(row, 'pnl', 0)
                if pnl is not None and not pd.isna(pnl):
                    return float(pnl)
                # Fallback: calculate from amount if pnl not available
                amount = getattr(row, 'amount', 0)
                return abs(float(amount if not pd.isna(amount) else 0))
            else:
                # For BUYs/DRIPs: show purchase amount
                shares_val = getattr(row, 'shares', 0)
                shares = abs(float(shares_val if not pd.isna(shares_val) else 0))
                price_val = getattr(row, 'price', 0)
                price = float(price_val if not pd.isna(price_val) else 0)
                return shares * price
        
        data = []
        for row in trades_df.itertuples(index=False):
            # Format date as MM-DD-YY (matching Streamlit)
            row_date = getattr(row, 'date', None)
            if hasattr(row_date, 'strftime'):
                date_str = row_date.strftime('%m-%d-%y')
            else:
                # Try to parse and format if it's a string
                try:
                    from datetime import datetime
                    date_obj = datetime.strptime(str(row_date), '%Y-%m-%d')
                    date_str = date_obj.strftime('%m-%d-%y')
                except:
                    date_str = str(row_date)
            
            ticker = getattr(row, 'ticker', None)
            reason = getattr(row, 'reason', None)
            action = infer_action(reason)
            
            shares_val = getattr(row, 'shares', 0)
            shares = abs(float(shares_val if not pd.isna(shares_val) else 0))
            price_val = getattr(row, 'price', 0)
            price = float(price_val if not pd.isna(price_val) else 0)
            pnl = getattr(row, 'pnl', None)
            company_name = getattr(row, 'company_name', None)
            
            display_amount = calculate_display_amount(row, action)
            
            # Get logo URL from map
            logo_url = logo_urls_map.get(ticker)
            
            data.append({
                "date": date_str,
                "ticker": ticker,
                "company_name": company_name if company_name and not pd.isna(company_name) else None,
                "action": action,
                "reason": str(reason) if reason and not pd.isna(reason) else None,
                "shares": shares,
                "price": price,
                "pnl": float(pnl) if pnl is not None and not pd.isna(pnl) else None,
                "amount": abs(
                    float(
                        getattr(row, "amount", 0)
                        if not pd.isna(getattr(row, "amount", 0))
                        else 0
                    )
                ),
                "display_amount": display_amount,
                "_logo_url": logo_url
            })
            
        processing_time = time.time() - start_time
        logger.info(f"[Dashboard API] Activity data prepared - {len(data)} activities, processing_time={processing_time:.3f}s")
        
        return jsonify({"data": data})
        
    except Exception as e:
        processing_time = time.time() - start_time
        logger.error(f"[Dashboard API] Error fetching activity (took {processing_time:.3f}s): {e}", exc_info=True)
        return jsonify({"error": str(e), "processing_time": processing_time}), 500

@dashboard_bp.route('/api/dashboard/dividends', methods=['GET'])
@require_auth
def get_dividend_data():
    """Get dividend metrics and log, optionally scoped by time range (1M, 3M, ALL).
    
    Returns:
        JSON with metrics (total LTM, tax, etc.) and list of dividend events.
    """
    fund = request.args.get('fund')
    if not fund or fund.lower() == 'all':
        fund = None
    
    time_range = request.args.get('range', 'ALL')
    days_map = {'1M': 30, '3M': 90, '6M': 180, '1Y': 365, 'ALL': 365}
    days_lookback = days_map.get(time_range.upper() if time_range else 'ALL', 365)
    
    try:
        display_currency = get_user_currency() or 'CAD'
        logger.info(f"[Dividend API] Request received - fund={fund}, range={time_range}, currency={display_currency}")
        
        # Fetch dividend data using cached function
        # This function is now optimized to include securities(company_name) and is cached for 300s
        # The cache key includes user_id to prevent cross-user data leakage (security fix)
        logger.debug(f"[Dividend API] Querying dividends via cached function")
        
        dividend_list = fetch_dividend_log_flask(days_lookback=days_lookback, fund=fund)
        
        logger.info(f"[Dividend API] Fetched {len(dividend_list)} dividend records")

        # Batch fetch logo URLs
        unique_tickers = list(set(row.get('ticker') for row in dividend_list if row.get('ticker')))
        logo_urls_map = {}
        if unique_tickers:
            try:
                logo_urls_map = get_ticker_logo_urls(unique_tickers)
            except Exception as e:
                logger.warning(f"Error fetching logo URLs: {e}")

        
        # Prepare Log (for table) - already sorted by pay_date desc from query
        # Extract company_name from nested securities object (same as get_trade_log does)
        logger.debug("[Dividend API] Processing dividend records into log_data")
        log_data = []
        for row in dividend_list:
            pay_date = row.get('pay_date', '')
            ticker = row.get('ticker', '')
            net_amt = float(row.get('net_amount', 0) or 0)
            gross_amt = float(row.get('gross_amount', 0) or 0)
            reinvested = float(row.get('reinvested_shares', 0) or 0)
            drip_price = float(row.get('drip_price', 0) or 0)
            
            # Extract company_name from nested securities object (same pattern as get_trade_log)
            company_name = None
            if 'securities' in row and row['securities']:
                company_name = row['securities'].get('company_name')

            # Get logo URL from map
            logo_url = logo_urls_map.get(ticker)
            
            log_data.append({
                "date": pay_date if isinstance(pay_date, str) else str(pay_date),
                "ticker": ticker,
                "company_name": company_name if company_name else None,
                "amount": net_amt,
                "gross": gross_amt,
                "tax": gross_amt - net_amt,
                "shares": reinvested,
                "drip_price": drip_price,
                "type": "DRIP" if reinvested > 0 else "CASH",
                "_logo_url": logo_url
            })
        
        logger.debug(f"[Dividend API] Processed {len(log_data)} records into log_data")
            
        # Calculate Metrics from collected log data
        logger.debug("[Dividend API] Calculating metrics")
        total_dividends = sum(item['amount'] for item in log_data)
        total_us_tax = sum(item['tax'] for item in log_data)
        total_reinvested = sum(item['shares'] for item in log_data)
        payout_events = len(log_data)
        
        logger.debug(f"[Dividend API] Metrics calculated - total: {total_dividends}, tax: {total_us_tax}, events: {payout_events}")
        
        # Find largest dividend
        largest_dividend = 0.0
        largest_ticker = ''
        if log_data:
            largest_item = max(log_data, key=lambda x: x.get('amount', 0))
            largest_dividend = largest_item.get('amount', 0)
            largest_ticker = largest_item.get('ticker', '')
        
        logger.debug(f"[Dividend API] Largest dividend: {largest_dividend} ({largest_ticker})")
        logger.info(f"[Dividend API] Successfully prepared response with {payout_events} events")
            
        return jsonify({
            "metrics": {
                "total_dividends": total_dividends,
                "total_us_tax": total_us_tax,
                "largest_dividend": largest_dividend,
                "largest_ticker": largest_ticker,
                "reinvested_shares": total_reinvested,
                "payout_events": payout_events
            },
            "log": log_data,
            "currency": display_currency
        })
        
    except Exception as e:
        logger.error(f"Error fetching dividend data: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

@dashboard_bp.route('/api/dashboard/charts/currency', methods=['GET'])
@require_auth
def get_currency_chart():
    """Get currency exposure chart as Plotly JSON."""
    fund = request.args.get('fund')
    if not fund or fund.lower() == 'all':
        fund = None
        
    theme = request.args.get('theme', 'light')
    time_range = (request.args.get('range', 'ALL') or 'ALL').upper()
    days_map = {
        '1M': 30,
        '3M': 90,
        '6M': 180,
        '1Y': 365,
        'ALL': None
    }
    days = days_map.get(time_range, None)
    
    try:
        if days is None:
            positions_df = get_current_positions(fund)
        else:
            as_of_date = datetime.now(timezone.utc) - timedelta(days=days)
            positions_df = get_positions_as_of_date_flask(fund, as_of_date)
        cash_balances = get_cash_balances(fund)
        
        # Create chart using shared utility
        # Note: create_currency_exposure_chart takes positions_df and fund_name
        # We pass fund as fund_name since the function signature expects fund_name, not cash_balances
        from chart_utils import create_currency_exposure_chart, get_chart_theme_config
        from plotly_utils import serialize_plotly_figure

        fig = create_currency_exposure_chart(positions_df, fund_name=fund)
        
        if not fig:
             return jsonify({"error": "Could not create chart"}), 500
             
        # Update height and ensure it doesn't overflow
        fig.update_layout(
            height=350, 
            margin=dict(l=20, r=20, t=30, b=20),
            autosize=True
        )
        
        # Apply theme
        chart_json = serialize_plotly_figure(fig)
        chart_data = json.loads(chart_json)
        theme_config = get_chart_theme_config(theme)
        
        if 'layout' in chart_data:
            chart_data['layout']['template'] = theme_config['template']
            chart_data['layout']['paper_bgcolor'] = theme_config['paper_bgcolor']
            chart_data['layout']['plot_bgcolor'] = theme_config['plot_bgcolor']
            chart_data['layout']['font'] = {'color': theme_config['font_color']}
            
        return Response(json.dumps(chart_data), mimetype='application/json')
        
    except Exception as e:
        logger.error(f"Error creating currency chart: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

@dashboard_bp.route('/api/dashboard/exchange-rate', methods=['GET'])
def get_exchange_rate_data():
    """Get current exchange rate and 90-day historical data.
    
    GET /api/dashboard/exchange-rate
    
    Query Parameters:
        inverse (bool): If true, show CAD/USD instead of USD/CAD (default: false)
        
    Returns:
        JSON response with current rate and historical data for chart
    """
    from datetime import timedelta
    from exchange_rates_utils import get_supabase_client
    
    inverse = request.args.get('inverse', 'false').lower() == 'true'
    theme = request.args.get('theme', 'light')
    
    try:
        client = get_supabase_client()
        if not client:
            return jsonify({"error": "Could not connect to database"}), 500
        
        # Get latest rate
        latest_rate = client.get_latest_exchange_rate('USD', 'CAD')
        
        # Get 90-day historical rates
        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(days=90)
        historical_rates = client.get_exchange_rates(start_date, end_date, 'USD', 'CAD')
        
        # Prepare response
        current_rate = float(latest_rate) if latest_rate else None
        if inverse and current_rate:
            current_rate = 1.0 / current_rate
        
        # Prepare chart data
        chart_data = None
        if historical_rates:
            import plotly.graph_objects as go
            from chart_utils import get_chart_theme_config
            from plotly_utils import serialize_plotly_figure
            
            dates = []
            rates = []
            for r in historical_rates:
                timestamp = r.get('timestamp')
                rate = r.get('rate')
                if timestamp and rate:
                    if isinstance(timestamp, str):
                        dates.append(timestamp)
                    else:
                        dates.append(timestamp.isoformat())
                    rate_val = float(rate)
                    rates.append(1.0 / rate_val if inverse else rate_val)
            
            if dates and rates:
                y_label = 'CAD/USD' if inverse else 'USD/CAD'
                chart_title = f'{y_label} Rate (90 Days)'
                
                fig = go.Figure()
                fig.add_trace(go.Scatter(
                    x=dates,
                    y=rates,
                    mode='lines',
                    name=y_label,
                    line=dict(color='#3b82f6', width=2),
                    hovertemplate='%{x|%b %d}<br>%{y:.4f}<extra></extra>'
                ))
                
                fig.update_layout(
                    title=chart_title,
                    xaxis_title='Date',
                    yaxis_title='Rate',
                    template='plotly_white',
                    height=250,
                    margin=dict(l=40, r=20, t=40, b=30),
                    showlegend=False
                )
                
                # Apply theme
                chart_json = serialize_plotly_figure(fig)
                chart_data = json.loads(chart_json)
                theme_config = get_chart_theme_config(theme)
                
                if 'layout' in chart_data:
                    chart_data['layout']['template'] = theme_config['template']
                    chart_data['layout']['paper_bgcolor'] = theme_config['paper_bgcolor']
                    chart_data['layout']['plot_bgcolor'] = theme_config['plot_bgcolor']
                    chart_data['layout']['font'] = {'color': theme_config['font_color']}
        
        return jsonify({
            "current_rate": current_rate,
            "rate_label": "CAD/USD" if inverse else "USD/CAD",
            "rate_help": "1 CAD = X USD" if inverse else "1 USD = X CAD",
            "inverse": inverse,
            "chart": chart_data
        })
        
    except Exception as e:
        logger.error(f"Error fetching exchange rate data: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@dashboard_bp.route('/api/dashboard/movers', methods=['GET'])
@require_auth
def get_movers_data():
    """Get top gainers and losers for the day.
    
    GET /api/dashboard/movers
    
    Query Parameters:
        fund (str): Fund name (optional)
        limit (int): Number of movers to return per category (default: 10)
        
    Returns:
        JSON response with gainers and losers arrays
    """
    fund = request.args.get('fund')
    if not fund or fund.lower() == 'all':
        fund = None
        
    limit = int(request.args.get('limit', 10))
    time_range = (request.args.get('range', 'ALL') or 'ALL').upper()
    days_map = {
        '1M': 30,
        '3M': 90,
        '6M': 180,
        '1Y': 365,
        'ALL': None
    }
    days = days_map.get(time_range, None)
    display_currency = get_user_currency() or 'CAD'
    
    logger.info(f"[Dashboard API] /api/dashboard/movers called - fund={fund}, range={time_range}, limit={limit}, currency={display_currency}")
    start_time = time.time()
    
    try:
        movers = None
        if days is not None and fund:
            logger.debug(f"[Dashboard API] Fetching holdings performance for movers - range={time_range}")
            perf_df = get_individual_holdings_performance_flask(fund, days=days)

            if perf_df.empty:
                logger.warning(f"[Dashboard API] No performance data found for movers - fund={fund}, range={time_range}")
                return jsonify({"gainers": [], "losers": [], "display_currency": display_currency, "processing_time": 0.0})

            # Take the last row per ticker (latest date)
            perf_df = perf_df.sort_values(['ticker', 'date'])
            perf_latest = perf_df.groupby('ticker').tail(1).reset_index(drop=True)

            # Build gainers/losers by return_pct
            perf_latest = perf_latest[pd.notna(perf_latest['return_pct'])]
            if perf_latest.empty:
                return jsonify({"gainers": [], "losers": [], "display_currency": display_currency, "processing_time": 0.0})

            gainers_df = perf_latest.sort_values('return_pct', ascending=False).head(limit)
            losers_df = perf_latest.sort_values('return_pct', ascending=True).head(limit)

            movers = {
                "gainers": gainers_df,
                "losers": losers_df
            }
        else:
            positions_df = get_current_positions(fund)
            
            if positions_df.empty:
                logger.warning(f"[Dashboard API] No positions found for movers - fund={fund}")
                return jsonify({"gainers": [], "losers": []})
            
            movers = get_biggest_movers(positions_df, display_currency, limit=limit)
        
        def df_to_list(df, logo_map=None, company_map=None):
            if df.empty:
                return []
            result = []
            columns = set(df.columns)
            for row in df.itertuples(index=False):
                ticker = getattr(row, 'ticker', '')
                company_name = getattr(row, 'company_name', None)
                item = {
                    "ticker": ticker,
                    "company_name": company_name or (company_map.get(ticker, ticker) if company_map else ticker),
                }
                if logo_map:
                    item["_logo_url"] = logo_map.get(item["ticker"])

                if 'daily_pnl_pct' in columns:
                    val = getattr(row, 'daily_pnl_pct', None)
                    item["daily_pnl_pct"] = float(val) if pd.notna(val) else None
                elif 'return_pct' in columns:
                    val = getattr(row, 'return_pct', None)
                    item["daily_pnl_pct"] = float(val) if pd.notna(val) else None
                if 'pnl_display' in columns:
                    val = getattr(row, 'pnl_display', None)
                    item["daily_pnl"] = float(val) if pd.notna(val) else None
                if 'five_day_pnl_pct' in columns:
                    val = getattr(row, 'five_day_pnl_pct', None)
                    item["five_day_pnl_pct"] = float(val) if pd.notna(val) else None
                if 'five_day_pnl_display' in columns:
                    val = getattr(row, 'five_day_pnl_display', None)
                    item["five_day_pnl"] = float(val) if pd.notna(val) else None
                if 'return_pct' in columns and 'daily_pnl_pct' in columns:
                    val = getattr(row, 'return_pct', None)
                    item["total_return_pct"] = float(val) if pd.notna(val) else None
                if 'total_pnl_display' in columns:
                    val = getattr(row, 'total_pnl_display', None)
                    item["total_pnl"] = float(val) if pd.notna(val) else None
                if 'current_price' in columns:
                    val = getattr(row, 'current_price', None)
                    item["current_price"] = float(val) if pd.notna(val) else None
                if 'market_value' in columns:
                    val = getattr(row, 'market_value', None)
                    item["market_value"] = float(val) if pd.notna(val) else None
                result.append(item)
            return result

        # Company name lookup for period movers
        company_name_map = {}
        if movers and days is not None and fund:
            all_tickers = []
            if not movers['gainers'].empty:
                all_tickers.extend(movers['gainers']['ticker'].dropna().unique().tolist())
            if not movers['losers'].empty:
                all_tickers.extend(movers['losers']['ticker'].dropna().unique().tolist())
            unique_tickers = list(set(all_tickers))

            if unique_tickers:
                try:
                    client = get_supabase_client_flask()
                    if client:
                        for i in range(0, len(unique_tickers), 100):
                            batch = unique_tickers[i:i + 100]
                            result = client.supabase.table("securities") \
                                .select("ticker, company_name") \
                                .in_("ticker", batch) \
                                .execute()
                            if result.data:
                                for row in result.data:
                                    ticker = row.get('ticker')
                                    if ticker:
                                        company_name_map[ticker] = row.get('company_name') or ticker
                except Exception as e:
                    logger.warning(f"[Dashboard API] Could not fetch company names for movers: {e}")
        
        # Collect all tickers for logo fetching
        all_tickers = []
        if not movers['gainers'].empty:
            all_tickers.extend(movers['gainers']['ticker'].dropna().unique().tolist())
        if not movers['losers'].empty:
            all_tickers.extend(movers['losers']['ticker'].dropna().unique().tolist())
        
        # Batch fetch logo URLs
        logo_urls_map = {}
        unique_tickers = list(set(all_tickers))
        if unique_tickers:
            try:
                logo_urls_map = get_ticker_logo_urls(unique_tickers)
            except Exception as e:
                logger.warning(f"Error fetching logo URLs: {e}")

        gainers = df_to_list(movers['gainers'], logo_urls_map, company_name_map)
        losers = df_to_list(movers['losers'], logo_urls_map, company_name_map)

        
        processing_time = time.time() - start_time
        logger.info(f"[Dashboard API] Movers data prepared - {len(gainers)} gainers, {len(losers)} losers, processing_time={processing_time:.3f}s")
        
        return jsonify({
            "gainers": gainers,
            "losers": losers,
            "display_currency": display_currency,
            "range": time_range,
            "processing_time": processing_time
        })
        
    except Exception as e:
        processing_time = time.time() - start_time
        logger.error(f"[Dashboard API] Error fetching movers (took {processing_time:.3f}s): {e}", exc_info=True)
        return jsonify({"error": str(e), "processing_time": processing_time}), 500


@dashboard_bp.route('/api/dashboard/charts/commodities', methods=['GET'])
@require_auth
def get_commodities_chart():
    """Get commodity prices chart as Plotly JSON.
    
    GET /api/dashboard/charts/commodities
    
    Query Parameters:
        commodities (str): Comma-separated list of commodity symbols to show
                          Options: 'gold', 'silver', 'oil', 'uranium', 'lithium'
                          Default: 'gold,silver'
        days (int): Number of days of historical data (default: 365)
        theme (str): Chart theme - 'dark', 'light', 'midnight-tokyo', 'abyss'
        
    Returns:
        JSON response with Plotly chart data (multi-line chart, normalized %)
    """
    try:
        # Parse query parameters
        commodities_str = request.args.get('commodities', 'gold,silver')
        commodities = [c.strip().lower() for c in commodities_str.split(',') if c.strip()]
        days = int(request.args.get('days', 365))
        theme = request.args.get('theme', 'light')
        
        logger.info(f"[Dashboard API] /api/dashboard/charts/commodities called - commodities={commodities}, days={days}, theme={theme}")
        start_time = time.time()
        
        if not commodities:
            return jsonify({"error": "No commodities specified"}), 400
        
        # Create chart using utility function
        from chart_utils import create_commodity_chart
        from plotly_utils import serialize_plotly_figure
        
        fig = create_commodity_chart(
            commodities=commodities,
            days=days,
            theme=theme,
            show_weekend_shading=True
        )
        
        # Serialize figure
        chart_json = serialize_plotly_figure(fig)
        
        processing_time = time.time() - start_time
        logger.info(f"[Dashboard API] Commodity chart created - {len(commodities)} commodities, processing_time={processing_time:.3f}s")
        
        return Response(chart_json, mimetype='application/json')
        
    except ValueError as ve:
        logger.error(f"Error parsing commodity chart parameters: {ve}")
        return jsonify({"error": f"Invalid parameter: {str(ve)}"}), 400
    except Exception as e:
        logger.error(f"Error creating commodity chart: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500
