"""
Securities Metadata Refresh Job
=================================
Periodically refreshes company names and metadata for tickers with stale or missing data.

This job:
1. Finds tickers where company_name IS NULL or company_name = 'Unknown'
2. Finds tickers with stale metadata (last_updated > 90 days ago)
3. Fetches fresh data from yfinance using ensure_ticker_in_securities
4. Processes in small batches to avoid rate limits
"""

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional

# Add project root to path for utils imports
import sys
from pathlib import Path

# Get current directory
current_dir = Path(__file__).resolve().parent

# Logic to find project root
if current_dir.name == 'scheduler':
    project_root = current_dir.parent.parent
elif current_dir.parent.name == 'web_dashboard':
    project_root = current_dir.parent.parent
else:
    project_root = current_dir.parent.parent

# Also ensure web_dashboard is in path for supabase_client imports
web_dashboard_path = str(project_root / 'web_dashboard')
if web_dashboard_path not in sys.path:
    sys.path.insert(0, web_dashboard_path)

# CRITICAL: Project root must be inserted LAST (at index 0) to ensure it comes
# BEFORE web_dashboard in sys.path. This prevents web_dashboard/utils from
# shadowing the project root's utils package.
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from web_dashboard.supabase_client import SupabaseClient
from scheduler.scheduler_core import log_job_execution

logger = logging.getLogger(__name__)


def get_tickers_needing_refresh(client: SupabaseClient, max_tickers: int = 10) -> List[Dict]:
    """Get tickers that need metadata refresh.
    
    Returns tickers where:
    - company_name IS NULL or company_name = 'Unknown', OR
    - last_updated is older than 90 days
    
    Args:
        client: SupabaseClient instance
        max_tickers: Maximum number of tickers to return (to limit processing per run)
    
    Returns:
        List of ticker dictionaries with ticker and currency
    """
    try:
        # Calculate cutoff date (90 days ago)
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=90)
        cutoff_iso = cutoff_date.isoformat()
        
        # Query for tickers with missing company names or stale data
        # We use OR condition to get both cases
        result = client.supabase.table("securities")\
            .select("ticker, currency, company_name, last_updated")\
            .or_(f"company_name.is.null,company_name.eq.Unknown,last_updated.lt.{cutoff_iso}")\
            .limit(max_tickers)\
            .execute()
        
        tickers = []
        if result.data:
            for row in result.data:
                ticker = row.get('ticker')
                currency = row.get('currency', 'USD')
                company_name = row.get('company_name')
                last_updated = row.get('last_updated')
                
                # Additional filtering to ensure we only get ones that need refresh
                needs_refresh = False
                if not company_name or company_name == 'Unknown':
                    needs_refresh = True
                elif last_updated:
                    try:
                        # Parse last_updated if it's a string
                        if isinstance(last_updated, str):
                            updated_dt = datetime.fromisoformat(last_updated.replace('Z', '+00:00'))
                        else:
                            updated_dt = last_updated
                        
                        if updated_dt < cutoff_date:
                            needs_refresh = True
                    except Exception as e:
                        logger.warning(f"Error parsing last_updated for {ticker}: {e}")
                        # If we can't parse, assume it needs refresh
                        needs_refresh = True
                else:
                    # No last_updated timestamp, assume stale
                    needs_refresh = True
                
                if needs_refresh and ticker:
                    tickers.append({
                        'ticker': ticker,
                        'currency': currency
                    })
        
        return tickers
        
    except Exception as e:
        logger.error(f"Error querying securities table for refresh: {e}")
        return []


def refresh_securities_metadata_job() -> None:
    """Scheduled job to refresh stale or missing securities metadata.
    
    Processes a small batch of tickers per run to avoid rate limits.
    Uses ensure_ticker_in_securities which fetches from yfinance.
    """
    job_name = "refresh_securities_metadata"
    start_time = datetime.now(timezone.utc)
    
    try:
        logger.info(f"🔄 Starting {job_name} job")
        
        client = SupabaseClient(use_service_role=True)
        
        # Get tickers that need refresh (limit to 10 per run to avoid rate limits)
        tickers_to_refresh = get_tickers_needing_refresh(client, max_tickers=10)
        
        if not tickers_to_refresh:
            logger.info(f"✅ No tickers need metadata refresh")
            duration_ms = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)
            try:
                log_job_execution(
                    job_name,
                    True,
                    "No tickers needed refresh",
                    duration_ms
                )
            except Exception as log_error:
                logger.warning(f"Failed to log job execution: {log_error}")
            return
        
        logger.info(f"📊 Found {len(tickers_to_refresh)} tickers needing metadata refresh")
        
        success_count = 0
        error_count = 0
        
        # Process each ticker
        for ticker_info in tickers_to_refresh:
            ticker = ticker_info.get('ticker')
            currency = ticker_info.get('currency', 'USD')
            
            if not ticker:
                continue
            
            try:
                # Use ensure_ticker_in_securities which will fetch from yfinance
                success = client.ensure_ticker_in_securities(ticker, currency)
                
                if success:
                    success_count += 1
                    logger.debug(f"✅ Refreshed metadata for {ticker}")
                else:
                    error_count += 1
                    logger.warning(f"⚠️ Failed to refresh metadata for {ticker}")
                
                # Small delay to avoid rate limits (0.5 seconds between calls)
                time.sleep(0.5)
                
            except Exception as e:
                error_count += 1
                logger.error(f"❌ Error refreshing metadata for {ticker}: {e}")
                # Continue with next ticker even if one fails
        
        duration_ms = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)
        
        message = f"Processed {len(tickers_to_refresh)} tickers: {success_count} succeeded, {error_count} errors"
        logger.info(f"✅ {job_name} job completed: {message}")
        
        # Consider it successful even if some tickers had errors (partial success)
        try:
            log_job_execution(
                job_name,
                True,
                message,
                duration_ms
            )
        except Exception as log_error:
            logger.warning(f"Failed to log job execution: {log_error}")
        
    except Exception as e:
        duration_ms = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)
        error_msg = f"Error in {job_name} job: {str(e)}"
        logger.error(f"❌ {error_msg}")
        
        try:
            log_job_execution(
                job_name,
                False,
                error_msg,
                duration_ms
            )
        except Exception as log_error:
            logger.warning(f"Failed to log job execution error: {log_error}")
        raise


if __name__ == "__main__":
    # Allow running directly for testing
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    refresh_securities_metadata_job()
