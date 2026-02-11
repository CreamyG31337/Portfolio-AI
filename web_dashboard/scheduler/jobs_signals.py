"""
Signals Jobs
============

Jobs for calculating and storing technical signals for watchlist tickers.
"""

import logging
import time
from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Any, Optional

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

# CRITICAL: Project root must be inserted LAST (at index 0) to ensure it comes
# BEFORE web_dashboard in sys.path. This prevents web_dashboard/utils from
# shadowing the project root's utils package.
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))
elif sys.path[0] != str(project_root):
    # If it is in path but not first, move it to front
    sys.path.remove(str(project_root))
    sys.path.insert(0, str(project_root))

from scheduler.scheduler_core import log_job_execution
from settings import get_signal_alert_policy, normalize_fund_type
from watchlist_access import get_active_watchlist_rows

# Initialize logger
logger = logging.getLogger(__name__)

# AI explanation settings (keep conservative to avoid long job times)
AI_EXPLANATION_ENABLED = True
AI_EXPLANATION_MIN_CONFIDENCE = 0.7
AI_EXPLANATION_SIGNALS = {"BUY", "SELL"}
AI_EXPLANATION_FEAR_LEVELS = {"HIGH", "EXTREME"}
AI_EXPLANATION_MAX_PER_RUN = 10


def _build_global_alert_policy(policies: list[dict[str, Any]]) -> dict[str, Any]:
    """Build conservative global alert policy when watchlist lacks fund scope."""
    if not policies:
        return get_signal_alert_policy(None)

    min_confidence = max(float(policy.get("min_confidence", 0.72)) for policy in policies)
    cooldown_minutes = max(int(policy.get("cooldown_minutes", 240)) for policy in policies)

    fear_sets: list[set[str]] = []
    for policy in policies:
        raw = policy.get("fear_levels", [])
        if isinstance(raw, list):
            fear_sets.append({str(level).strip().upper() for level in raw if str(level).strip()})

    if fear_sets:
        common_fear_levels = set.intersection(*fear_sets) if len(fear_sets) > 1 else fear_sets[0]
        if not common_fear_levels:
            common_fear_levels = set.union(*fear_sets)
    else:
        common_fear_levels = {"HIGH", "EXTREME"}

    return {
        "profile_key": "GLOBAL_STRICT",
        "min_confidence": min_confidence,
        "fear_levels": sorted(common_fear_levels),
        "cooldown_minutes": cooldown_minutes,
    }


def _resolve_global_alert_policy(supabase_client: Any) -> dict[str, Any]:
    """Resolve active profile policies and collapse to a conservative global gate."""
    try:
        result = supabase_client.supabase.table("funds").select(
            "fund_type, is_production"
        ).execute()
        rows = result.data or []

        production_rows = [row for row in rows if row.get("is_production") is True]
        scoped_rows = production_rows if production_rows else rows

        profile_keys = {
            normalize_fund_type(row.get("fund_type"))
            for row in scoped_rows
            if row.get("fund_type")
        }
        if profile_keys:
            policies = [get_signal_alert_policy(profile_key) for profile_key in sorted(profile_keys)]
            return _build_global_alert_policy(policies)
    except Exception as e:
        logger.warning(f"Failed to load fund profile alert policy: {e}")

    return get_signal_alert_policy(None)


def signal_scan_job() -> None:
    """Scan watchlist tickers and generate technical signals.
    
    This job:
    1. Gets watchlist from dynamic watchlist function
    2. For each ticker, fetches price data
    3. Calculates structure, timing, and fear/risk signals
    4. Stores results in signal_analysis table
    5. Optionally sends alerts for significant signals
    """
    job_id = 'signal_scan'
    start_time = time.time()

    # Global AI lock (signal job can generate AI explanations)
    try:
        from utils.job_tracking import get_running_ai_job
        running_ai = get_running_ai_job(exclude_job_name=job_id)
        if running_ai:
            logger.info(f"⏸️  AI lock active: {running_ai} is running. Skipping {job_id}.")
            return
    except Exception as e:
        logger.warning(f"AI lock check failed (continuing): {e}")
    
    try:
        # Import job tracking
        from utils.job_tracking import mark_job_started, mark_job_completed, mark_job_failed
        
        logger.info("Starting signal scan job...")
        
        # Mark job as started
        target_date = datetime.now(timezone.utc).date()
        mark_job_started('signal_scan', target_date)
        
        # Import dependencies (lazy imports)
        try:
            from supabase_client import SupabaseClient
            from market_data.data_fetcher import MarketDataFetcher
            from web_dashboard.signals.signal_engine import SignalEngine
        except ImportError as e:
            duration_ms = int((time.time() - start_time) * 1000)
            message = f"Missing dependency: {e}"
            try:
                log_job_execution(job_id, False, message, duration_ms)
            except Exception as log_error:
                logger.warning(f"Failed to log job execution: {log_error}")
            logger.error(f"❌ {message}")
            return
        
        # Initialize clients
        supabase_client = SupabaseClient(use_service_role=True)
        data_fetcher = MarketDataFetcher()
        signal_engine = SignalEngine()
        
        watchlist = get_active_watchlist_rows(supabase_client)
        
        if not watchlist:
            logger.warning("No watchlist tickers found")
            duration_ms = int((time.time() - start_time) * 1000)
            message = "No watchlist tickers to process"
            try:
                log_job_execution(job_id, True, message, duration_ms)
                mark_job_completed(
                    'signal_scan',
                    target_date,
                    None,
                    [],
                    duration_ms=duration_ms,
                    message=message,
                )
            except Exception as log_error:
                logger.warning(f"Failed to log job execution: {log_error}")
            return
        
        logger.info(f"Processing {len(watchlist)} watchlist tickers...")
        
        processed = 0
        errors = 0
        alerts_sent = 0
        ai_explanations = 0
        global_alert_policy = _resolve_global_alert_policy(supabase_client)
        logger.info(
            "Signal alert policy: profile=%s min_confidence=%.2f fear_levels=%s",
            global_alert_policy.get("profile_key", "DEFAULT"),
            float(global_alert_policy.get("min_confidence", 0.72)),
            ",".join(global_alert_policy.get("fear_levels", [])),
        )
        
        # Pre-fetch fundamentals for all tickers to avoid N+1 queries
        fundamentals_map = {}
        all_tickers = sorted({t.get('ticker').upper() for t in watchlist if t.get('ticker')})
        if all_tickers:
            try:
                # Fetch in chunks to avoid URL length limits
                chunk_size = 50
                for i in range(0, len(all_tickers), chunk_size):
                    chunk = all_tickers[i:i + chunk_size]
                    sec_result = supabase_client.supabase.table("securities") \
                        .select("*") \
                        .in_("ticker", chunk) \
                        .execute()
                    if sec_result.data:
                        for row in sec_result.data:
                            if row.get('ticker'):
                                fundamentals_map[row['ticker'].upper()] = row
            except Exception as batch_err:
                logger.error(f"Failed to batch fetch fundamentals: {batch_err}")

        # Process each ticker
        for ticker_data in watchlist:
            ticker = ticker_data.get('ticker')
            if not ticker:
                continue
            
            try:
                # Fetch price data (need 6 months for indicators)
                price_data = data_fetcher.fetch_price_data(ticker, period="6mo")
                
                if price_data.df.empty:
                    logger.warning(f"No price data for {ticker}")
                    errors += 1
                    continue

                # Get fundamentals from pre-fetched map
                fundamentals = fundamentals_map.get(ticker.upper())
                
                # Generate signals (pass fundamentals if available)
                signals = signal_engine.evaluate(
                    ticker, price_data.df, fundamentals=fundamentals
                )
                
                # Store in database
                analysis_date = datetime.now(timezone.utc)
                
                # Check if signal should trigger alert
                should_alert = _should_alert(signals, policy=global_alert_policy)

                # Optionally generate AI explanation (limited per run)
                explanation = None
                if AI_EXPLANATION_ENABLED and ai_explanations < AI_EXPLANATION_MAX_PER_RUN:
                    overall_signal = signals.get('overall_signal', 'HOLD')
                    confidence = signals.get('confidence', 0.0)
                    fear_level = signals.get('fear_risk', {}).get('fear_level', 'LOW')
                    if (
                        overall_signal in AI_EXPLANATION_SIGNALS
                        and confidence >= AI_EXPLANATION_MIN_CONFIDENCE
                    ) or fear_level in AI_EXPLANATION_FEAR_LEVELS:
                        try:
                            from web_dashboard.signals.ai_explainer import generate_signal_explanation
                            explanation = generate_signal_explanation(ticker, signals)
                            if explanation:
                                ai_explanations += 1
                        except Exception as ai_error:
                            logger.warning(f"AI explanation failed for {ticker}: {ai_error}")
                
                # Insert or update signal analysis
                try:
                    supabase_client.supabase.table("signal_analysis").upsert({
                        'ticker': ticker.upper(),
                        'analysis_date': analysis_date.isoformat(),
                        'structure_signal': signals.get('structure', {}),
                        'timing_signal': signals.get('timing', {}),
                        'fear_risk_signal': signals.get('fear_risk', {}),
                        'momentum_signal': signals.get('momentum', {}),
                        'fundamental_signal': signals.get('fundamental', {}),
                        'overall_signal': signals.get('overall_signal', 'HOLD'),
                        'confidence_score': signals.get('confidence', 0.0),
                        'explanation': explanation
                    }, on_conflict='ticker,analysis_date').execute()
                    
                    processed += 1
                    
                    if should_alert:
                        alerts_sent += 1
                        logger.info(f"⚠️  Alert: {ticker} - {signals.get('overall_signal')} signal (confidence: {signals.get('confidence', 0):.2f})")
                    
                    # Small delay to avoid rate limiting
                    time.sleep(0.5)
                    
                except Exception as db_error:
                    logger.error(f"Error storing signals for {ticker}: {db_error}")
                    errors += 1
                    continue
                
            except Exception as e:
                logger.error(f"Error processing {ticker}: {e}", exc_info=True)
                errors += 1
                continue
        
        duration_ms = int((time.time() - start_time) * 1000)
        message = f"Processed {processed} tickers, {errors} errors, {alerts_sent} alerts, {ai_explanations} AI notes"
        
        try:
            log_job_execution(job_id, True, message, duration_ms)
            mark_job_completed(
                'signal_scan',
                target_date,
                None,
                [],
                duration_ms=duration_ms,
                message=message,
            )
        except Exception as log_error:
            logger.warning(f"Failed to log job execution: {log_error}")
        
        logger.info(f"✅ Signal scan complete: {message}")
        
    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        message = f"Job failed: {str(e)}"
        try:
            log_job_execution(job_id, False, message, duration_ms)
            mark_job_failed('signal_scan', target_date, None, str(e), duration_ms=duration_ms)
        except Exception as log_error:
            logger.warning(f"Failed to log job execution: {log_error}")
        logger.error(f"❌ {message}", exc_info=True)


def _should_alert(signals: dict[str, Any], policy: Optional[dict[str, Any]] = None) -> bool:
    """Determine if alert should be sent for this signal.
    
    Args:
        signals: Signal analysis dictionary
        policy: Optional alert policy thresholds
    
    Returns:
        True if alert should be sent
    """
    if policy is None:
        policy = get_signal_alert_policy(None)

    overall = signals.get('overall_signal', 'HOLD')
    confidence = signals.get('confidence', 0.0)
    fear_level = str(signals.get('fear_risk', {}).get('fear_level', 'LOW')).upper()
    min_confidence = float(policy.get("min_confidence", 0.72))
    fear_levels = {
        str(level).strip().upper()
        for level in policy.get("fear_levels", ["HIGH", "EXTREME"])
    }
    
    # Alert on strong signals or high fear
    return (
        (overall in ['BUY', 'SELL'] and confidence >= min_confidence) or
        fear_level in fear_levels
    )
