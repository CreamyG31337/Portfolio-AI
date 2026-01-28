"""
Social Sentiment Jobs
====================

Jobs for fetching and managing social sentiment data from StockTwits and Reddit.
"""

import logging
import time
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Add parent directory to path if needed (standard boilerplate for these jobs)
import sys

# Add project root to path for utils imports
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

def fetch_social_sentiment_job() -> None:
    """Fetch social sentiment data from StockTwits and Reddit for watched tickers.
    
    This job:
    1. Fetches tickers from both watched_tickers (Supabase) and latest_positions (Supabase)
    2. Combines and deduplicates the ticker lists
    3. For each ticker, fetches sentiment from StockTwits and Reddit
    4. Saves metrics to the social_metrics table (Postgres)
    
    Robots.txt enforcement: Controlled by ENABLE_ROBOTS_TXT_CHECKS environment variable.
    When enabled, checks robots.txt before accessing StockTwits and Reddit APIs.
    """
    job_id = 'social_sentiment'
    start_time = time.time()
    
    try:
        # Import job tracking
        from utils.job_tracking import mark_job_started, mark_job_completed, mark_job_failed
        
        logger.info("Starting social sentiment job...")
        
        # Mark job as started
        target_date = datetime.now(timezone.utc).date()
        mark_job_started('social_sentiment', target_date)
        
        # Import dependencies (lazy imports)
        try:
            from social_service import SocialSentimentService
            from supabase_client import SupabaseClient
        except ImportError as e:
            duration_ms = int((time.time() - start_time) * 1000)
            message = f"Missing dependency: {e}"
            try:
                log_job_execution(job_id, False, message, duration_ms)
            except Exception as log_error:
                logger.warning(f"Failed to log job execution: {log_error}")
            logger.error(f"❌ {message}")
            return
        
        # Initialize service
        service = SocialSentimentService()
        supabase_client = SupabaseClient(use_service_role=True)
        
        # Check FlareSolverr availability
        try:
            import requests
            flaresolverr_url = os.getenv("FLARESOLVERR_URL", "http://host.docker.internal:8191")
            requests.get(f"{flaresolverr_url}/health", timeout=5)
            logger.info("✅ FlareSolverr is available")
        except Exception:
            logger.warning("⚠️  FlareSolverr unavailable - will fallback to direct requests")
        
        # Check Ollama availability
        if not service.ollama:
            logger.warning("⚠️  Ollama unavailable - Reddit sentiment will be NEUTRAL only")
        
        # 1. Get tickers from watched_tickers table
        watched_tickers = service.get_watched_tickers()
        logger.info(f"Found {len(watched_tickers)} watched tickers")
        
        # 2. Get tickers from latest_positions (owned positions)
        try:
            positions_result = supabase_client.supabase.table("latest_positions")\
                .select("ticker")\
                .execute()
            
            owned_tickers = list(set([row['ticker'] for row in positions_result.data if row.get('ticker')]))
            logger.info(f"Found {len(owned_tickers)} tickers from latest positions")
        except Exception as e:
            logger.warning(f"Failed to fetch tickers from latest_positions: {e}")
            owned_tickers = []
        
        # 3. Combine and deduplicate
        all_tickers = list(set(watched_tickers + owned_tickers))
        logger.info(f"Processing {len(all_tickers)} unique tickers for social sentiment")
        
        if not all_tickers:
            duration_ms = int((time.time() - start_time) * 1000)
            message = "No tickers to process"
            log_job_execution(job_id, success=True, message=message, duration_ms=duration_ms)
            mark_job_completed('social_sentiment', target_date, None, [], duration_ms=duration_ms, message=message)
            logger.info(f"ℹ️ {message}")
            return
        
        # 4. Process each ticker with timeouts and progress logging
        success_count = 0
        error_count = 0
        failed_tickers = []
        timeout_tickers = []
        
        # Overall job timeout: 50 minutes (leave 10 min buffer before next run)
        MAX_JOB_DURATION = 50 * 60  # 50 minutes in seconds
        # Per-ticker timeout: 3 minutes max per ticker
        MAX_TICKER_DURATION = 3 * 60  # 3 minutes in seconds
        
        total_tickers = len(all_tickers)
        logger.info(f"📊 Processing {total_tickers} tickers (max {MAX_TICKER_DURATION}s per ticker, {MAX_JOB_DURATION}s total)")
        
        for idx, ticker in enumerate(all_tickers, 1):
            # Check overall job timeout
            elapsed = time.time() - start_time
            if elapsed > MAX_JOB_DURATION:
                remaining = total_tickers - idx + 1
                logger.warning(f"⏱️  Job timeout reached ({elapsed/60:.1f}m). Skipping {remaining} remaining tickers")
                timeout_tickers.extend(all_tickers[idx-1:])
                break
            
            ticker_start = time.time()
            logger.info(f"📈 Processing ticker {idx}/{total_tickers}: {ticker}")
            
            try:
                # Fetch StockTwits sentiment with timeout protection
                try:
                    stocktwits_data = service.fetch_stocktwits_sentiment(ticker)
                    if stocktwits_data:
                        service.save_metrics(
                            ticker=ticker,
                            platform='stocktwits',
                            metrics=stocktwits_data  # Pass the entire dict
                        )
                        logger.debug(f"✅ Saved StockTwits data for {ticker}")
                except Exception as e:
                    logger.warning(f"⚠️  StockTwits fetch failed for {ticker}: {e}")
                    stocktwits_data = None
                
                # Check per-ticker timeout before Reddit (which is slower)
                ticker_elapsed = time.time() - ticker_start
                if ticker_elapsed > MAX_TICKER_DURATION:
                    logger.warning(f"⏱️  Ticker {ticker} timeout ({ticker_elapsed:.1f}s) - skipping Reddit fetch")
                    timeout_tickers.append(ticker)
                    if stocktwits_data:
                        success_count += 1
                    else:
                        error_count += 1
                    continue
                
                # Fetch Reddit sentiment with timeout protection
                # Calculate remaining time for Reddit fetch (leave 10s buffer)
                remaining_time = MAX_TICKER_DURATION - (time.time() - ticker_start) - 10
                if remaining_time < 30:  # Need at least 30s for Reddit
                    logger.warning(f"⏱️  Not enough time for Reddit fetch for {ticker} (only {remaining_time:.1f}s remaining)")
                    reddit_data = None
                else:
                    try:
                        reddit_data = service.fetch_reddit_sentiment(ticker, max_duration=remaining_time)
                        if reddit_data:
                            service.save_metrics(
                                ticker=ticker,
                                platform='reddit',
                                metrics=reddit_data  # Pass the entire dict
                            )
                            logger.debug(f"✅ Saved Reddit data for {ticker}")
                    except Exception as e:
                        logger.warning(f"⚠️  Reddit fetch failed for {ticker}: {e}")
                        reddit_data = None
                
                ticker_duration = time.time() - ticker_start
                if stocktwits_data or reddit_data:
                    success_count += 1
                    logger.info(f"✅ Completed {ticker} in {ticker_duration:.1f}s")
                else:
                    error_count += 1
                    logger.warning(f"⚠️  No data saved for {ticker} (completed in {ticker_duration:.1f}s)")
                
            except Exception as e:
                error_count += 1
                failed_tickers.append(ticker)
                ticker_duration = time.time() - ticker_start
                logger.warning(f"❌ Failed to process {ticker} after {ticker_duration:.1f}s: {e}")
                continue
        
        # 5. Log completion
        duration_ms = int((time.time() - start_time) * 1000)
        duration_min = duration_ms / 60000
        
        # Build completion message
        parts = [f"{success_count} successful", f"{error_count} errors"]
        if timeout_tickers:
            parts.append(f"{len(timeout_tickers)} timeouts")
        message = f"Processed {success_count + error_count + len(timeout_tickers)}/{len(all_tickers)} tickers: {', '.join(parts)}"
        
        log_job_execution(job_id, success=True, message=message, duration_ms=duration_ms)
        mark_job_completed('social_sentiment', target_date, None, [], duration_ms=duration_ms, message=message)
        logger.info(f"✅ Social sentiment job completed: {message} in {duration_min:.1f} minutes")
        
        # Log failed tickers if any
        if failed_tickers:
            logger.warning(f"❌ Failed tickers ({len(failed_tickers)}): {', '.join(failed_tickers[:10])}{'...' if len(failed_tickers) > 10 else ''}")
        if timeout_tickers:
            logger.warning(f"⏱️  Timeout tickers ({len(timeout_tickers)}): {', '.join(timeout_tickers[:10])}{'...' if len(timeout_tickers) > 10 else ''}")
        
    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        message = f"Error: {str(e)}"
        log_job_execution(job_id, success=False, message=message, duration_ms=duration_ms)
        mark_job_failed('social_sentiment', target_date, None, str(e), duration_ms=duration_ms)
        logger.error(f"❌ Social sentiment job failed: {e}", exc_info=True)


def cleanup_social_metrics_job() -> None:
    """Daily cleanup job for social metrics retention policy.
    
    Implements two-tier retention:
    - Removes raw_data JSON from records older than 7 days
    - Deletes entire rows older than 90 days
    """
    job_id = 'social_metrics_cleanup'
    start_time = time.time()
    
    try:
        # Import job tracking
        from utils.job_tracking import mark_job_started, mark_job_completed, mark_job_failed
        
        logger.info("Starting social metrics cleanup job...")
        
        # Mark job as started
        target_date = datetime.now(timezone.utc).date()
        mark_job_started('social_metrics_cleanup', target_date)
        
        # Import dependencies (lazy imports)
        try:
            from social_service import SocialSentimentService
        except ImportError as e:
            duration_ms = int((time.time() - start_time) * 1000)
            message = f"Missing dependency: {e}"
            try:
                log_job_execution(job_id, False, message, duration_ms)
            except Exception as log_error:
                logger.warning(f"Failed to log job execution: {log_error}")
            logger.error(f"❌ {message}")
            return
        
        # Initialize service
        service = SocialSentimentService()
        
        # Run cleanup
        results = service.run_daily_cleanup()
        
        # Log completion
        duration_ms = int((time.time() - start_time) * 1000)
        message = f"Updated {results['rows_updated']} records, deleted {results['rows_deleted']} records"
        try:
            log_job_execution(job_id, True, message, duration_ms)
        except Exception as log_error:
            logger.warning(f"Failed to log job execution: {log_error}")
        mark_job_completed('social_metrics_cleanup', target_date, None, [], duration_ms=duration_ms, message=message)
        logger.info(f"✅ Social metrics cleanup job completed: {message} in {duration_ms/1000:.2f}s")
        
    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        message = f"Error: {str(e)}"
        try:
            log_job_execution(job_id, False, message, duration_ms)
        except Exception as log_error:
            logger.warning(f"Failed to log job execution error: {log_error}")
        mark_job_failed('social_metrics_cleanup', target_date, None, str(e), duration_ms=duration_ms)
        logger.error(f"❌ Social metrics cleanup job failed: {e}", exc_info=True)


def social_sentiment_ai_job() -> None:
    """AI analysis job for social sentiment data.

    This job:
    1. Extracts posts from raw_data into structured social_posts table
    2. Creates sentiment analysis sessions by grouping related posts
    3. Performs AI analysis on sessions using Ollama Granite model
    4. Stores detailed analysis results in research database
    """
    job_id = 'social_sentiment_ai'
    start_time = time.time()

    try:
        # Import job tracking
        from utils.job_tracking import mark_job_started, mark_job_completed, mark_job_failed

        logger.info("🤖 Starting Social Sentiment AI Analysis job...")

        # Mark job as started
        target_date = datetime.now(timezone.utc).date()
        mark_job_started('social_sentiment_ai', target_date)

        # Import dependencies (lazy imports)
        try:
            from social_service import SocialSentimentService
        except ImportError as e:
            duration_ms = int((time.time() - start_time) * 1000)
            message = f"Missing dependency: {e}"
            try:
                log_job_execution(job_id, False, message, duration_ms)
            except Exception as log_error:
                logger.warning(f"Failed to log job execution: {log_error}")
            logger.error(f"❌ {message}")
            return

        # Initialize service
        service = SocialSentimentService()

        # Check Ollama availability
        if not service.ollama:
            duration_ms = int((time.time() - start_time) * 1000)
            message = "Ollama client unavailable - cannot perform AI analysis"
            log_job_execution(job_id, success=False, message=message, duration_ms=duration_ms)
            logger.error(f"❌ {message}")
            return

        # Step 1: Extract posts from raw_data
        logger.info("📝 Step 1: Extracting posts from raw_data...")
        extraction_result = service.extract_posts_from_raw_data()

        # Step 2: Create sentiment sessions
        logger.info("🎯 Step 2: Creating sentiment analysis sessions...")
        session_result = service.create_sentiment_sessions()

        # Step 3: Perform AI analysis on pending sessions
        logger.info("🧠 Step 3: Performing AI analysis...")
        analyses_completed = 0

        # Get sessions that need analysis (limit to avoid timeouts)
        from postgres_client import PostgresClient
        pc = PostgresClient()
        pending_sessions = pc.execute_query("""
            SELECT id, ticker, platform FROM sentiment_sessions
            WHERE needs_ai_analysis = TRUE
            ORDER BY created_at ASC
            LIMIT 10  -- Process in batches to avoid timeouts
        """)

        for session in pending_sessions:
            session_id = session['id']
            ticker = session['ticker']
            platform = session['platform']

            logger.info(f"Analyzing session {session_id} for {ticker} ({platform})...")
            result = service.analyze_sentiment_session(session_id)

            if result:
                analyses_completed += 1
                logger.info(f"✅ Completed AI analysis for {ticker}")
            else:
                logger.warning(f"❌ Failed AI analysis for session {session_id}")

        # Log completion
        duration_ms = int((time.time() - start_time) * 1000)
        message = f"Extracted {extraction_result['posts_created']} posts, created {session_result['sessions_created']} sessions, completed {analyses_completed} AI analyses"
        log_job_execution(job_id, success=True, message=message, duration_ms=duration_ms)
        mark_job_completed('social_sentiment_ai', target_date, None, [], duration_ms=duration_ms, message=message)
        logger.info(f"✅ Social Sentiment AI Analysis job completed: {message} in {duration_ms/1000:.2f}s")

    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        message = f"Error: {str(e)}"
        log_job_execution(job_id, success=False, message=message, duration_ms=duration_ms)
        mark_job_failed('social_sentiment_ai', target_date, None, str(e), duration_ms=duration_ms)
        logger.error(f"❌ Social Sentiment AI Analysis job failed: {e}", exc_info=True)
