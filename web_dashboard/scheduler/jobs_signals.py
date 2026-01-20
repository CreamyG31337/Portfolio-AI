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

# Initialize logger
logger = logging.getLogger(__name__)


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
        
        # Get watchlist from watched_tickers table
        watchlist = []
        try:
            result = supabase_client.supabase.table("watched_tickers")\
                .select("ticker, priority_tier, is_active, source, created_at")\
                .eq("is_active", True)\
                .execute()
            
            if result.data:
                for item in result.data:
                    ticker = item.get('ticker', '').upper().strip()
                    if ticker:
                        watchlist.append({
                            'ticker': ticker,
                            'priority_tier': item.get('priority_tier', 'C'),
                            'created_at': item.get('created_at')
                        })
        except Exception as e:
            logger.warning(f"Error fetching watched_tickers: {e}")
        
        if not watchlist:
            logger.warning("No watchlist tickers found")
            duration_ms = int((time.time() - start_time) * 1000)
            message = "No watchlist tickers to process"
            try:
                log_job_execution(job_id, True, message, duration_ms)
                mark_job_completed('signal_scan', target_date)
            except Exception as log_error:
                logger.warning(f"Failed to log job execution: {log_error}")
            return
        
        logger.info(f"Processing {len(watchlist)} watchlist tickers...")
        
        processed = 0
        errors = 0
        alerts_sent = 0
        
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
                
                # Generate signals
                signals = signal_engine.evaluate(ticker, price_data.df)
                
                # Store in database
                analysis_date = datetime.now(timezone.utc)
                
                # Check if signal should trigger alert
                should_alert = _should_alert(signals)
                
                # Insert or update signal analysis
                try:
                    supabase_client.supabase.table("signal_analysis").upsert({
                        'ticker': ticker.upper(),
                        'analysis_date': analysis_date.isoformat(),
                        'structure_signal': signals.get('structure', {}),
                        'timing_signal': signals.get('timing', {}),
                        'fear_risk_signal': signals.get('fear_risk', {}),
                        'overall_signal': signals.get('overall_signal', 'HOLD'),
                        'confidence_score': signals.get('confidence', 0.0)
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
        message = f"Processed {processed} tickers, {errors} errors, {alerts_sent} alerts"
        
        try:
            log_job_execution(job_id, True, message, duration_ms)
            mark_job_completed('signal_scan', target_date)
        except Exception as log_error:
            logger.warning(f"Failed to log job execution: {log_error}")
        
        logger.info(f"✅ Signal scan complete: {message}")
        
    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        message = f"Job failed: {str(e)}"
        try:
            log_job_execution(job_id, False, message, duration_ms)
            mark_job_failed('signal_scan', target_date, str(e))
        except Exception as log_error:
            logger.warning(f"Failed to log job execution: {log_error}")
        logger.error(f"❌ {message}", exc_info=True)


def _should_alert(signals: dict) -> bool:
    """Determine if alert should be sent for this signal.
    
    Args:
        signals: Signal analysis dictionary
    
    Returns:
        True if alert should be sent
    """
    overall = signals.get('overall_signal', 'HOLD')
    confidence = signals.get('confidence', 0.0)
    fear_level = signals.get('fear_risk', {}).get('fear_level', 'LOW')
    
    # Alert on strong signals or high fear
    return (
        (overall in ['BUY', 'SELL'] and confidence > 0.7) or
        fear_level in ['HIGH', 'EXTREME']
    )
