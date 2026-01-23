#!/usr/bin/env python3
"""
Ticker Analysis Job
===================

Analyzes tickers with 3 months of multi-source data.
Runs daily at 10 PM EST.
Processes holdings first (priority=100), then watched tickers (priority=10).
Stops after 2 hours, resumes next day where it left off.
"""

import logging
import time
from datetime import datetime, timezone
from typing import List, Tuple

# Import log_job_execution if available (optional for standalone testing)
try:
    from scheduler.scheduler_core import log_job_execution
except ImportError:
    # Fallback for standalone testing
    def log_job_execution(job_id, success, message="", duration_ms=0):
        logger.info(f"Job {job_id}: {'SUCCESS' if success else 'FAILED'} - {message} ({duration_ms}ms)")
from supabase_client import SupabaseClient
from postgres_client import PostgresClient
from ollama_client import get_ollama_client
from ticker_analysis_service import TickerAnalysisService
from ai_skip_list_manager import AISkipListManager

logger = logging.getLogger(__name__)

def ticker_analysis_job() -> None:
    """Analyze tickers. Holdings first, then watched. 2-hour max. Resumable."""
    job_id = 'ticker_analysis'
    start_time = time.time()
    max_duration = 2 * 60 * 60  # 2 hours
    
    # Check if job is already running (prevents concurrent execution)
    try:
        supabase_check = SupabaseClient(use_service_role=True)
        running_check = supabase_check.supabase.table('job_executions') \
            .select('id') \
            .eq('job_name', job_id) \
            .eq('status', 'running') \
            .execute()
        
        if running_check.data:
            logger.info(f"⏸️  Job {job_id} is already running. Skipping to prevent concurrent execution.")
            return
    except Exception as e:
        logger.warning(f"Could not check if job is running: {e}")
        # Continue anyway - better to run twice than fail silently
    
    try:
        from utils.job_tracking import mark_job_started, mark_job_completed, mark_job_failed
        target_date = datetime.now(timezone.utc).date()
        mark_job_started(job_id, target_date)
    except Exception as e:
        logger.warning(f"Could not mark job started: {e}")
    
    logger.info("Starting Ticker Analysis Job...")
    
    # Initialize clients
    try:
        supabase = SupabaseClient(use_service_role=True)
        postgres = PostgresClient()
        ollama = get_ollama_client()
        
        if not ollama:
            duration_ms = int((time.time() - start_time) * 1000)
            message = "Ollama client not available"
            log_job_execution(job_id, success=False, message=message, duration_ms=duration_ms)
            logger.error(f"❌ {message}")
            return
        
        skip_list = AISkipListManager(supabase)
        service = TickerAnalysisService(ollama, supabase, postgres, skip_list)
    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        message = f"Failed to initialize clients: {e}"
        log_job_execution(job_id, success=False, message=message, duration_ms=duration_ms)
        logger.error(f"❌ {message}")
        return
    
    # Get priority-sorted tickers (holdings first, then watched)
    tickers = service.get_tickers_to_analyze()
    
    if not tickers:
        duration_ms = int((time.time() - start_time) * 1000)
        message = "No tickers to analyze"
        log_job_execution(job_id, success=True, message=message, duration_ms=duration_ms)
        logger.info(f"ℹ️ {message}")
        return
    
    logger.info(f"Found {len(tickers)} tickers to analyze (prioritized)")
    
    processed = 0
    failed = 0
    
    for ticker, priority in tickers::
        # Check time limit
        elapsed = time.time() - start_time
        if elapsed > max_duration:
            duration_ms = int((time.time() - start_time) * 1000)
            message = f"Stopped after 2 hours. Processed {processed}/{len(tickers)} tickers. {failed} failed."
            log_job_execution(job_id, success=True, message=message, duration_ms=duration_ms)
            logger.info(f"⏰ {message}")
            logger.info(f"   Remaining tickers will be processed in next run")
            break
        
        try:
            logger.info(f"Analyzing {ticker} (priority={priority})...")
            service.analyze_ticker(ticker)
            processed += 1
            
            # Log progress every 10 tickers
            if processed % 10 == 0:
                elapsed_min = elapsed / 60
                logger.info(f"Progress: {processed} processed, {elapsed_min:.1f} minutes elapsed")
            
        except Exception as e:
            logger.error(f"Failed to analyze {ticker}: {e}", exc_info=True)
            # Skip list manager handles repeated failures
            failed += 1
    
    duration_ms = int((time.time() - start_time) * 1000)
    message = f"Processed {processed}/{len(tickers)} tickers. {failed} failed."
    log_job_execution(job_id, success=True, message=message, duration_ms=duration_ms)
    logger.info(f"✅ Ticker Analysis complete: {message}")
