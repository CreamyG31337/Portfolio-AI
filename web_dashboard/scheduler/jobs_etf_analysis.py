#!/usr/bin/env python3
"""
ETF Group Analysis Job
======================

Analyzes ETF holdings changes as groups using AI.
Runs daily at 9 PM EST after ETF Watchtower.
Resumable via ai_analysis_queue table.
"""

import logging
import time
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any

# Import log_job_execution if available (optional for standalone testing)
try:
    from scheduler.scheduler_core import log_job_execution
except ImportError:
    # Fallback for standalone testing
    def log_job_execution(job_id, success, message="", duration_ms=0):
        logger.info(f"Job {job_id}: {'SUCCESS' if success else 'FAILED'} - {message} ({duration_ms}ms)")
from supabase_client import SupabaseClient
from ollama_client import get_ollama_client
from postgres_client import PostgresClient
from research_repository import ResearchRepository
from etf_group_analysis import ETFGroupAnalysisService

logger = logging.getLogger(__name__)

def get_pending_etf_analysis() -> List[Dict]:
    """Get pending ETF group analysis items from queue.
    
    Returns:
        List of queue items
    """
    try:
        db = SupabaseClient(use_service_role=True)
        result = db.supabase.table('ai_analysis_queue') \
            .select('*') \
            .eq('analysis_type', 'etf_group') \
            .in_('status', ['pending', 'failed']) \
            .order('priority', desc=True) \
            .order('created_at', desc=False) \
            .limit(100) \
            .execute()
        return result.data or []
    except Exception as e:
        logger.error(f"Error fetching pending ETF analysis: {e}")
        return []

def queue_todays_etf_analysis():
    """Queue today's ETF analysis for all ETFs with changes."""
    try:
        db = SupabaseClient(use_service_role=True)
        today = datetime.now(timezone.utc).date()
        today_str = today.strftime('%Y-%m-%d')
        
        # Get all ETFs with changes today
        result = db.supabase.from_('etf_holdings_changes') \
            .select('etf_ticker') \
            .eq('date', today_str) \
            .execute()
        
        # Get distinct tickers
        etf_tickers = list(set([row['etf_ticker'] for row in result.data or []]))
        
        if not etf_tickers:
            logger.info("No ETF changes found for today")
            return
        
        # Queue each ETF
        queue_items = []
        for etf_ticker in etf_tickers:
            target_key = f"{etf_ticker}_{today_str}"
            queue_items.append({
                'analysis_type': 'etf_group',
                'target_key': target_key,
                'priority': 0,  # Default priority
                'status': 'pending'
            })
        
        # Insert in batch
        if queue_items:
            db.supabase.table('ai_analysis_queue') \
                .insert(queue_items) \
                .execute()
            logger.info(f"Queued {len(queue_items)} ETF groups for analysis")
        
    except Exception as e:
        logger.error(f"Error queueing ETF analysis: {e}", exc_info=True)

def mark_analysis_started(queue_id: str):
    """Mark analysis as started in queue."""
    try:
        db = SupabaseClient(use_service_role=True)
        db.supabase.table('ai_analysis_queue') \
            .update({
                'status': 'in_progress',
                'started_at': datetime.now(timezone.utc).isoformat()
            }) \
            .eq('id', queue_id) \
            .execute()
    except Exception as e:
        logger.warning(f"Error marking analysis started: {e}")

def mark_analysis_completed(queue_id: str):
    """Mark analysis as completed in queue."""
    try:
        db = SupabaseClient(use_service_role=True)
        db.supabase.table('ai_analysis_queue') \
            .update({
                'status': 'completed',
                'completed_at': datetime.now(timezone.utc).isoformat()
            }) \
            .eq('id', queue_id) \
            .execute()
    except Exception as e:
        logger.warning(f"Error marking analysis completed: {e}")

def mark_analysis_failed(queue_id: str, error: str):
    """Mark analysis as failed in queue."""
    try:
        db = SupabaseClient(use_service_role=True)
        db.supabase.table('ai_analysis_queue') \
            .update({
                'status': 'failed',
                'error_message': error[:500],  # Truncate long errors
                'retry_count': db.supabase.table('ai_analysis_queue')
                    .select('retry_count')
                    .eq('id', queue_id)
                    .execute()
                    .data[0].get('retry_count', 0) + 1 if db.supabase.table('ai_analysis_queue')
                    .select('retry_count')
                    .eq('id', queue_id)
                    .execute().data else 1
            }) \
            .eq('id', queue_id) \
            .execute()
    except Exception as e:
        logger.warning(f"Error marking analysis failed: {e}")

def etf_group_analysis_job() -> None:
    """Analyze ETF changes as groups. Resumable via queue."""
    job_id = 'etf_group_analysis'
    start_time = time.time()
    
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
    
    logger.info("Starting ETF Group Analysis Job...")
    
    # Initialize clients
    try:
        supabase = SupabaseClient(use_service_role=True)
        postgres = PostgresClient()
        ollama = get_ollama_client()
        repo = ResearchRepository(postgres_client=postgres)
        
        if not ollama:
            duration_ms = int((time.time() - start_time) * 1000)
            message = "Ollama client not available"
            log_job_execution(job_id, success=False, message=message, duration_ms=duration_ms)
            logger.error(f"❌ {message}")
            return
        
        service = ETFGroupAnalysisService(ollama, supabase, repo)
    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        message = f"Failed to initialize clients: {e}"
        log_job_execution(job_id, success=False, message=message, duration_ms=duration_ms)
        logger.error(f"❌ {message}")
        return
    
    # Check queue for pending work
    pending = get_pending_etf_analysis()
    
    if not pending:
        # Queue today's analysis
        queue_todays_etf_analysis()
        pending = get_pending_etf_analysis()
    
    if not pending:
        duration_ms = int((time.time() - start_time) * 1000)
        message = "No ETF groups to analyze"
        log_job_execution(job_id, success=True, message=message, duration_ms=duration_ms)
        logger.info(f"ℹ️ {message}")
        return
    
    logger.info(f"Processing {len(pending)} ETF groups...")
    
    processed = 0
    failed = 0
    
    for item in pending:
        try:
            queue_id = item['id']
            target_key = item['target_key']
            
            # Parse ETF ticker and date from target_key (format: "IWC_2026-01-15")
            parts = target_key.split('_')
            if len(parts) < 2:
                logger.warning(f"Invalid target_key format: {target_key}")
                mark_analysis_failed(queue_id, f"Invalid target_key format: {target_key}")
                failed += 1
                continue
            
            etf_ticker = parts[0]
            date_str = '_'.join(parts[1:])  # Handle dates with underscores if needed
            try:
                analysis_date = datetime.strptime(date_str, '%Y-%m-%d').replace(tzinfo=timezone.utc)
            except ValueError:
                logger.warning(f"Invalid date format in target_key: {target_key}")
                mark_analysis_failed(queue_id, f"Invalid date format: {date_str}")
                failed += 1
                continue
            
            # Mark as started
            mark_analysis_started(queue_id)
            
            # Analyze
            logger.info(f"Analyzing {etf_ticker} on {date_str}...")
            result = service.analyze_group(etf_ticker, analysis_date)
            
            if result:
                mark_analysis_completed(queue_id)
                processed += 1
                logger.info(f"✅ Analyzed {etf_ticker} on {date_str}")
            else:
                mark_analysis_failed(queue_id, "No changes found or analysis returned None")
                failed += 1
                logger.warning(f"⚠️ No analysis result for {etf_ticker} on {date_str}")
                
        except Exception as e:
            logger.error(f"Error analyzing {item.get('target_key', 'unknown')}: {e}", exc_info=True)
            mark_analysis_failed(item['id'], str(e))
            failed += 1
    
    duration_ms = int((time.time() - start_time) * 1000)
    message = f"Processed {processed} ETF groups, {failed} failed"
    log_job_execution(job_id, success=True, message=message, duration_ms=duration_ms)
    logger.info(f"✅ ETF Group Analysis complete: {message}")
