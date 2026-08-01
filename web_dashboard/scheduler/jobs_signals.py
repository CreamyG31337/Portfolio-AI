"""
Signals Jobs
============

Jobs for calculating and storing technical signals for watchlist tickers.
"""

import logging
import math
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
            mark_job_failed('signal_scan', target_date, None, message, duration_ms=duration_ms)
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
        signal_analyses_to_upsert = []
        ticker_states_to_upsert = []

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

                # Build cross-source ticker state (best-effort, only for AI candidates)
                ticker_state = None
                overall_signal = signals.get('overall_signal', 'HOLD')
                confidence = signals.get('confidence', 0.0)
                fear_level = signals.get('fear_risk', {}).get('fear_level', 'LOW')
                needs_ai = AI_EXPLANATION_ENABLED and ai_explanations < AI_EXPLANATION_MAX_PER_RUN and (
                    (overall_signal in AI_EXPLANATION_SIGNALS and confidence >= AI_EXPLANATION_MIN_CONFIDENCE)
                    or fear_level in AI_EXPLANATION_FEAR_LEVELS
                )
                if needs_ai:
                    try:
                        from web_dashboard.ticker_state import build_ticker_state, summarize_ticker_state
                        pg_client = None
                        try:
                            from postgres_client import PostgresClient
                            pg_client = PostgresClient()
                        except Exception:
                            pass
                        ticker_state = build_ticker_state(
                            ticker, supabase_client, postgres_client=pg_client
                        )
                    except Exception as state_err:
                        logger.debug(f"Could not build ticker state for {ticker}: {state_err}")

                # Optionally generate AI explanation (limited per run)
                explanation = None
                if needs_ai:
                    try:
                        from web_dashboard.signals.ai_explainer import generate_signal_explanation
                        explanation = generate_signal_explanation(
                            ticker, signals, ticker_state=ticker_state
                        )
                        if explanation:
                            ai_explanations += 1
                    except Exception as ai_error:
                        logger.warning(f"AI explanation failed for {ticker}: {ai_error}")
                
                # Accumulate for batched upsert
                signal_analyses_to_upsert.append({
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
                })

                if should_alert:
                    alerts_sent += 1
                    logger.info(f"⚠️  Alert: {ticker} - {signals.get('overall_signal')} signal (confidence: {signals.get('confidence', 0):.2f})")

                if ticker_state:
                    try:
                        from web_dashboard.ticker_state import summarize_ticker_state
                        summary = summarize_ticker_state(ticker_state)
                        ticker_states_to_upsert.append({
                            'ticker': ticker.upper(),
                            'snapshot_date': analysis_date.isoformat(),
                            'state': ticker_state,
                            'summary': summary,
                        })
                    except Exception as snap_err:
                        logger.debug(f"Failed to build state snapshot for {ticker}: {snap_err}")

                processed += 1

                # Small delay to avoid rate limiting data fetcher
                time.sleep(0.5)
                
            except Exception as e:
                logger.error(f"Error processing {ticker}: {e}", exc_info=True)
                errors += 1
                continue
        
        # ⚡ Bolt: Execute batched upserts to avoid per-row network roundtrips
        if signal_analyses_to_upsert:
            try:
                # Upsert in chunks to avoid URL size limits if list is huge
                chunk_size = 200
                for i in range(0, len(signal_analyses_to_upsert), chunk_size):
                    chunk = signal_analyses_to_upsert[i:i + chunk_size]
                    supabase_client.supabase.table("signal_analysis").upsert(
                        chunk, on_conflict='ticker,analysis_date'
                    ).execute()
            except Exception as e:
                logger.error(f"Failed to batch insert signal_analysis: {e}")
                errors += 1

        if ticker_states_to_upsert:
            try:
                chunk_size = 200
                for i in range(0, len(ticker_states_to_upsert), chunk_size):
                    chunk = ticker_states_to_upsert[i:i + chunk_size]
                    supabase_client.supabase.table("ticker_state_snapshots").upsert(
                        chunk, on_conflict='ticker,snapshot_date'
                    ).execute()
            except Exception as e:
                logger.error(f"Failed to batch insert ticker_state_snapshots: {e}")
                errors += 1

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


# =============================================================================
# Fundamentals Backfill Job
# =============================================================================

# yfinance key -> securities DB column
_YFINANCE_FUNDAMENTAL_MAP: dict[str, str] = {
    'trailingPE': 'trailing_pe',
    'dividendYield': 'dividend_yield',
    'fiftyTwoWeekHigh': 'fifty_two_week_high',
    'fiftyTwoWeekLow': 'fifty_two_week_low',
    'forwardPE': 'forward_pe',
    'priceToBook': 'price_to_book',
    'priceToSalesTrailing12Months': 'price_to_sales',
    'pegRatio': 'peg_ratio',
    'returnOnEquity': 'return_on_equity',
    'profitMargins': 'net_margin',
    'operatingMargins': 'operating_margin',
    'grossMargins': 'gross_margin',
    'revenueGrowth': 'revenue_growth',
    'earningsGrowth': 'earnings_growth',
    'currentRatio': 'current_ratio',
    'debtToEquity': 'debt_to_equity',
    'freeCashflow': 'free_cash_flow',
    'shortRatio': 'short_ratio',
    'shortPercentOfFloat': 'short_percent_of_float',
    'ebitda': 'ebitda',
    'trailingEps': 'trailing_eps',
    'forwardEps': 'forward_eps',
}

# Columns that indicate "real" fundamental data (not just trailing_pe which can
# come from basic metadata).  If none of these are populated we consider the
# ticker as needing a fundamentals refresh.
_FUNDAMENTAL_INDICATOR_COLS = [
    'forward_pe', 'price_to_book', 'return_on_equity', 'net_margin',
    'revenue_growth', 'current_ratio', 'debt_to_equity',
]


def fundamentals_refresh_job() -> None:
    """Backfill / refresh fundamental columns in the securities table.

    This job:
    1. Gets watchlist tickers from the shared watchlist function
    2. Identifies tickers that are missing key fundamental columns
    3. Fetches fresh data from yfinance and updates the securities table
    4. Processes in batches with rate-limiting to stay under yfinance limits

    Designed to run once daily.  Fundamentals change at most quarterly, so
    we skip tickers whose fundamentals were refreshed within the last 7 days.
    """
    job_id = 'fundamentals_refresh'
    start_time = time.time()

    try:
        from utils.job_tracking import mark_job_started, mark_job_completed, mark_job_failed

        logger.info("Starting fundamentals refresh job...")
        target_date = datetime.now(timezone.utc).date()
        mark_job_started(job_id, target_date)

        # Lazy imports
        try:
            from supabase_client import SupabaseClient
            import yfinance as yf
        except ImportError as e:
            duration_ms = int((time.time() - start_time) * 1000)
            msg = f"Missing dependency: {e}"
            try:
                log_job_execution(job_id, False, msg, duration_ms)
            except Exception:
                pass
            logger.error(f"❌ {msg}")
            try:
                mark_job_failed(job_id, target_date, None, msg, duration_ms=duration_ms)
            except Exception:
                pass
            return

        supabase_client = SupabaseClient(use_service_role=True)
        watchlist = get_active_watchlist_rows(supabase_client)

        if not watchlist:
            duration_ms = int((time.time() - start_time) * 1000)
            msg = "No watchlist tickers to process"
            try:
                log_job_execution(job_id, True, msg, duration_ms)
                mark_job_completed(job_id, target_date, None, [], duration_ms=duration_ms, message=msg)
            except Exception:
                pass
            logger.info(f"✅ {msg}")
            return

        tickers = sorted({t.get('ticker', '').upper() for t in watchlist if t.get('ticker')})
        logger.info(f"Checking fundamentals for {len(tickers)} watchlist tickers...")

        # Batch-fetch current securities data to find gaps
        needs_refresh: list[str] = []
        chunk_size = 50
        for i in range(0, len(tickers), chunk_size):
            chunk = tickers[i:i + chunk_size]
            try:
                # Only select the columns we need to check
                select_cols = "ticker," + ",".join(_FUNDAMENTAL_INDICATOR_COLS)
                result = supabase_client.supabase.table("securities") \
                    .select(select_cols) \
                    .in_("ticker", chunk) \
                    .execute()

                existing_map = {}
                if result.data:
                    for row in result.data:
                        existing_map[row.get('ticker', '').upper()] = row

                for t in chunk:
                    row = existing_map.get(t)
                    if not row:
                        # Ticker not in securities table at all -- skip, the
                        # metadata refresh job or ensure_ticker will create it
                        continue

                    # Check if any indicator column is populated
                    has_fundamentals = any(
                        row.get(col) is not None
                        for col in _FUNDAMENTAL_INDICATOR_COLS
                    )
                    if not has_fundamentals:
                        needs_refresh.append(t)
            except Exception as e:
                logger.warning(f"Error checking fundamental gaps for chunk: {e}")
                # If we can't check, add the whole chunk to be safe
                needs_refresh.extend(chunk)

        if not needs_refresh:
            duration_ms = int((time.time() - start_time) * 1000)
            msg = f"All {len(tickers)} tickers have fundamental data"
            try:
                log_job_execution(job_id, True, msg, duration_ms)
                mark_job_completed(job_id, target_date, None, [], duration_ms=duration_ms, message=msg)
            except Exception:
                pass
            logger.info(f"✅ {msg}")
            return

        logger.info(f"📊 {len(needs_refresh)} tickers need fundamental data (out of {len(tickers)} watchlist)")

        updated = 0
        skipped = 0
        errors = 0

        for ticker in needs_refresh:
            try:
                ticker_obj = yf.Ticker(ticker)
                info = ticker_obj.info or {}

                if not info or info.get('quoteType') is None:
                    logger.debug(f"No yfinance info for {ticker}, skipping")
                    skipped += 1
                    time.sleep(0.3)
                    continue

                updates: dict[str, float] = {}
                for yf_key, db_col in _YFINANCE_FUNDAMENTAL_MAP.items():
                    raw = info.get(yf_key)
                    if raw is not None:
                        try:
                            val = float(raw)
                            # Skip inf/nan -- yfinance sometimes returns these
                            if math.isfinite(val):
                                updates[db_col] = val
                        except (TypeError, ValueError):
                            pass

                if updates:
                    supabase_client.supabase.table("securities") \
                        .update(updates) \
                        .eq("ticker", ticker) \
                        .execute()
                    updated += 1
                    logger.debug(f"✅ Updated {len(updates)} fundamental fields for {ticker}")
                else:
                    skipped += 1
                    logger.debug(f"No fundamental data available from yfinance for {ticker}")

                # Rate-limit: ~1 second between yfinance calls
                time.sleep(1.0)

            except Exception as e:
                errors += 1
                logger.warning(f"Error fetching fundamentals for {ticker}: {e}")
                time.sleep(0.5)

        duration_ms = int((time.time() - start_time) * 1000)
        msg = (
            f"Fundamentals refresh: {updated} updated, {skipped} skipped "
            f"(no data), {errors} errors, out of {len(needs_refresh)} candidates"
        )
        try:
            log_job_execution(job_id, True, msg, duration_ms)
            mark_job_completed(job_id, target_date, None, [], duration_ms=duration_ms, message=msg)
        except Exception:
            pass
        logger.info(f"✅ {msg}")

    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        msg = f"Fundamentals refresh failed: {e}"
        try:
            log_job_execution(job_id, False, msg, duration_ms)
            mark_job_failed(job_id, target_date, None, str(e), duration_ms=duration_ms)
        except Exception:
            pass
        logger.error(f"❌ {msg}", exc_info=True)


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
