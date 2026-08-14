"""
Social Sentiment Jobs
====================

Jobs for fetching and managing social sentiment data from StockTwits and Reddit.
"""

import logging
import time
import os
from datetime import UTC, datetime
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


def _format_ticker_sample(tickers: list[str], limit: int = 10) -> str:
    """Format a bounded ticker list for operator logs."""

    sample = ", ".join(tickers[:limit])
    if len(tickers) > limit:
        sample = f"{sample}..."
    return sample


def _sort_tickers_oldest_first(
    tickers: list[str],
    last_processed_at: dict[str, datetime | None],
) -> tuple[list[str], int, datetime | None]:
    """Sort tickers so never/oldest-processed symbols run first."""

    never = datetime.min.replace(tzinfo=UTC)

    def sort_value(ticker: str) -> datetime:
        value = last_processed_at.get(ticker)
        if value is None:
            return never
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value

    sorted_tickers = sorted(tickers, key=lambda ticker: (sort_value(ticker), ticker))
    never_count = sum(1 for ticker in tickers if last_processed_at.get(ticker) is None)
    known_dates = [sort_value(ticker) for ticker in tickers if last_processed_at.get(ticker) is not None]
    oldest_existing = min(known_dates) if known_dates else None
    return sorted_tickers, never_count, oldest_existing


def _build_social_sentiment_summary(
    *,
    total_tickers: int,
    attempted_count: int,
    success_count: int,
    error_count: int,
    no_data_count: int,
    per_ticker_timeout_count: int,
    skipped_count: int,
    reddit_429_count: int,
    reddit_auth_fail_count: int,
    duration_min: float,
) -> str:
    """Build a precise social sentiment completion message."""

    message = (
        f"Social sentiment: {attempted_count}/{total_tickers} attempted in {duration_min:.1f}m "
        f"({success_count} ok, {error_count} errors, {no_data_count} no-data, "
        f"{per_ticker_timeout_count} per-ticker-timeouts"
    )
    if reddit_429_count or reddit_auth_fail_count:
        message = (
            f"{message}; reddit 429={reddit_429_count}, reddit auth_fail={reddit_auth_fail_count}"
        )
    message = f"{message})"
    if skipped_count:
        message = f"{message}. Job cap reached - {skipped_count} tickers deferred to next run"
    return message

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
    job_started = False
    job_finalized = False
    target_date = datetime.now(UTC).date()

    def _finalize_success(message: str) -> None:
        nonlocal job_finalized
        if job_finalized:
            return
        duration_ms = int((time.time() - start_time) * 1000)
        log_job_execution(job_id, success=True, message=message, duration_ms=duration_ms)
        if job_started:
            try:
                from utils.job_tracking import mark_job_completed
                mark_job_completed(job_id, target_date, None, [], duration_ms=duration_ms, message=message)
            except Exception as e:
                logger.warning(f"Failed to finalize success for {job_id}: {e}")
        job_finalized = True

    def _finalize_failure(message: str) -> None:
        nonlocal job_finalized
        if job_finalized:
            return
        duration_ms = int((time.time() - start_time) * 1000)
        log_job_execution(job_id, success=False, message=message, duration_ms=duration_ms)
        if job_started:
            try:
                from utils.job_tracking import mark_job_failed
                mark_job_failed(job_id, target_date, None, message, duration_ms=duration_ms)
            except Exception as e:
                logger.warning(f"Failed to finalize failure for {job_id}: {e}")
        job_finalized = True

    # Global AI lock (prevent overlapping AI jobs)
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
        from utils.job_tracking import mark_job_started
        
        logger.info("Starting social sentiment job...")
        
        # Mark job as started
        mark_job_started('social_sentiment', target_date)
        job_started = True
        
        # Import dependencies (lazy imports)
        try:
            from social_service import SocialSentimentService
            from supabase_client import SupabaseClient
        except ImportError as e:
            message = f"Missing dependency: {e}"
            logger.error(f"❌ {message}")
            _finalize_failure(message)
            return
        
        # Initialize service
        service = SocialSentimentService()
        supabase_client = SupabaseClient(use_service_role=True)
        
        # Check FlareSolverr availability
        from web_fetch_client import get_web_fetch_client

        if get_web_fetch_client().check_health():
            logger.info("✅ FlareSolverr is available")
        else:
            logger.warning("⚠️  FlareSolverr unavailable - will fallback to direct requests")

        from reddit_client import check_reddit_connectivity

        reddit_status = check_reddit_connectivity()
        if reddit_status.ok:
            logger.info("✅ %s", reddit_status.message)
        else:
            logger.error(
                "❌ Reddit unavailable: %s (status=%s)",
                reddit_status.message,
                reddit_status.status_code,
            )

        if not service.reddit.oauth_enabled:
            warm_stats = service.reddit.warm_sentiment_feed_cache()
            logger.info(
                "Reddit RSS cache: %s/%s subs warmed, %s posts cached (%s rate-limited)",
                warm_stats.subs_fetched,
                warm_stats.subs_requested,
                warm_stats.posts_cached,
                warm_stats.subs_rate_limited,
            )
        
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
            message = "No tickers to process"
            logger.info(f"ℹ️ {message}")
            _finalize_success(message)
            return

        last_processed_at = service.get_last_processed_at(all_tickers)
        all_tickers, never_count, oldest_existing = _sort_tickers_oldest_first(
            all_tickers,
            last_processed_at,
        )
        oldest_label = oldest_existing.isoformat() if oldest_existing else "none"
        logger.info(
            "Sorted %s tickers oldest-first: %s never processed, oldest existing data = %s",
            len(all_tickers),
            never_count,
            oldest_label,
        )
        
        # 4. Process each ticker with timeouts and progress logging
        success_count = 0
        no_data_tickers: list[str] = []
        error_tickers: list[str] = []
        ticker_timeout_tickers: list[str] = []
        skipped_tickers: list[str] = []
        attempted_count = 0
        reddit_429_count = 0
        reddit_auth_fail_count = 0
        
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
                logger.warning(
                    f"⏱️  Job cap reached ({elapsed/60:.1f}m). "
                    f"Deferring {remaining} remaining tickers to the next run"
                )
                skipped_tickers.extend(all_tickers[idx-1:])
                break
            
            ticker_start = time.time()
            attempted_count += 1
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
                    ticker_timeout_tickers.append(ticker)
                    if stocktwits_data:
                        success_count += 1
                    else:
                        no_data_tickers.append(ticker)
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
                            error_codes = reddit_data.get("reddit_error_codes") or []
                            if "429" in error_codes:
                                reddit_429_count += 1
                            if "auth_failed" in error_codes:
                                reddit_auth_fail_count += 1
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
                    no_data_tickers.append(ticker)
                    logger.warning(f"⚠️  No data saved for {ticker} (completed in {ticker_duration:.1f}s)")
                
            except Exception as e:
                error_tickers.append(ticker)
                ticker_duration = time.time() - ticker_start
                logger.warning(f"❌ Failed to process {ticker} after {ticker_duration:.1f}s: {e}")
                continue
        
        # 5. Log completion
        duration_ms = int((time.time() - start_time) * 1000)
        duration_min = duration_ms / 60000
        
        error_count = len(error_tickers)
        no_data_count = len(no_data_tickers)
        per_ticker_timeout_count = len(ticker_timeout_tickers)
        skipped_count = len(skipped_tickers)
        message = _build_social_sentiment_summary(
            total_tickers=len(all_tickers),
            attempted_count=attempted_count,
            success_count=success_count,
            error_count=error_count,
            no_data_count=no_data_count,
            per_ticker_timeout_count=per_ticker_timeout_count,
            skipped_count=skipped_count,
            reddit_429_count=reddit_429_count,
            reddit_auth_fail_count=reddit_auth_fail_count,
            duration_min=duration_min,
        )

        if success_count == 0 and (error_count > 0 or per_ticker_timeout_count > 0):
            _finalize_failure(message)
            logger.warning(f"⚠️ Social sentiment timed out with no successful ticker processing in {duration_min:.1f} minutes")
        else:
            _finalize_success(message)
            logger.info(f"✅ Social sentiment job completed: {message} in {duration_min:.1f} minutes")
        
        # Log ticker buckets if any so operator-visible issues are easy to grep.
        if error_tickers:
            logger.warning("❌ Error tickers (%s): %s", len(error_tickers), _format_ticker_sample(error_tickers))
        if no_data_tickers:
            logger.warning("⚠️  No-data tickers (%s): %s", len(no_data_tickers), _format_ticker_sample(no_data_tickers))
        if ticker_timeout_tickers:
            logger.warning(
                "⏱️  Per-ticker timeout tickers (%s): %s",
                len(ticker_timeout_tickers),
                _format_ticker_sample(ticker_timeout_tickers),
            )
        if skipped_tickers:
            logger.info(
                "Deferred to next social sentiment run (%s): %s",
                len(skipped_tickers),
                _format_ticker_sample(skipped_tickers),
            )
        
    except Exception as e:
        message = f"Error: {str(e)}"
        logger.error(f"❌ Social sentiment job failed: {e}", exc_info=True)
        _finalize_failure(message)
    finally:
        if job_started and not job_finalized:
            _finalize_failure("Job exited without terminal status")


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
        target_date = datetime.now(UTC).date()
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
            mark_job_failed('social_metrics_cleanup', target_date, None, message, duration_ms=duration_ms)
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

    # Global AI lock (prevent overlapping AI jobs)
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

        logger.info("🤖 Starting Social Sentiment AI Analysis job...")

        # Mark job as started
        target_date = datetime.now(UTC).date()
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
            mark_job_failed('social_sentiment_ai', target_date, None, message, duration_ms=duration_ms)
            return

        # Initialize service
        service = SocialSentimentService()

        # Queue mode fans sessions out to the GLM + Ollama worker pool, so a
        # local Ollama client is only required for the inline fallback path.
        from scheduler.ai_task_workers import (
            QUEUE_JOB_SOCIAL_SENTIMENT_ANALYSIS,
            is_ai_queue_job_enabled,
        )

        try:
            queue_mode = is_ai_queue_job_enabled(QUEUE_JOB_SOCIAL_SENTIMENT_ANALYSIS)
        except Exception as e:
            logger.warning("AI queue mode check failed (using inline path): %s", e)
            queue_mode = False

        # Check Ollama availability
        if not queue_mode and not service.ollama:
            duration_ms = int((time.time() - start_time) * 1000)
            message = "Ollama client unavailable - cannot perform AI analysis"
            log_job_execution(job_id, success=False, message=message, duration_ms=duration_ms)
            logger.error(f"❌ {message}")
            mark_job_failed('social_sentiment_ai', target_date, None, message, duration_ms=duration_ms)
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

        from postgres_client import PostgresClient
        pc = PostgresClient()

        if queue_mode:
            from scheduler.ai_task_workers import (
                AIQueueConfig,
                enqueue_social_sentiment_analysis_tasks,
            )
            from supabase_client import SupabaseClient

            # Newest first: the dashboard only renders the last 7 days, so
            # recent sessions are the ones that make the page non-empty.
            pending_sessions = pc.execute_query("""
                SELECT id FROM sentiment_sessions
                WHERE needs_ai_analysis = TRUE
                ORDER BY session_start DESC
                LIMIT 200
            """)
            session_ids = [int(s['id']) for s in pending_sessions]

            if not session_ids:
                message = (
                    f"Extracted {extraction_result['posts_created']} posts, "
                    f"created {session_result['sessions_created']} sessions, "
                    "no sessions pending analysis"
                )
            else:
                config = AIQueueConfig.from_env()
                enqueued_by = os.getenv("AI_QUEUE_ENQUEUED_BY", "cron").strip() or "cron"
                # Above backfill bulk (priority 0) so cron work leases first.
                stats = enqueue_social_sentiment_analysis_tasks(
                    SupabaseClient(use_service_role=True),
                    session_ids,
                    priority=10,
                    enqueued_by=enqueued_by,
                    max_attempts=config.max_attempts,
                )
                message = (
                    f"Extracted {extraction_result['posts_created']} posts, "
                    f"created {session_result['sessions_created']} sessions, "
                    f"enqueued {stats['enqueued']}/{stats['attempted']} analysis "
                    f"task(s) (failed={stats['failed']})"
                )

            duration_ms = int((time.time() - start_time) * 1000)
            log_job_execution(job_id, success=True, message=message, duration_ms=duration_ms)
            mark_job_completed(
                'social_sentiment_ai', target_date, None, [],
                duration_ms=duration_ms, message=message,
            )
            logger.info(f"✅ Social Sentiment AI Analysis job completed: {message} in {duration_ms/1000:.2f}s")
            return

        # Inline fallback: process a small batch so the job cannot overrun.
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
