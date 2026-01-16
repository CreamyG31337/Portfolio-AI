"""
Scheduled Jobs Definitions
==========================

Define all background jobs here. Each job should:
1. Be a function that takes no arguments
2. Handle its own error logging
3. Call log_job_execution() to record results
"""

import logging
from datetime import datetime, timezone
from typing import Dict, Any

from scheduler.scheduler_core import log_job_execution


logger = logging.getLogger(__name__)

# Add project root to path for utils imports if running from web_dashboard
import sys
import os
from pathlib import Path

# If running from web_dashboard/scheduler, go up two levels
current_dir = Path(__file__).resolve().parent
if current_dir.name == 'scheduler':
    project_root = current_dir.parent.parent
else:
    project_root = current_dir.parent.parent

# CRITICAL: Project root must be FIRST in sys.path to ensure utils.job_tracking
# is found from the project root, not from web_dashboard/utils
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))
elif sys.path[0] != str(project_root):
    # If it is in path but not first, move it to front
    if str(project_root) in sys.path:
        sys.path.remove(str(project_root))
    sys.path.insert(0, str(project_root))

# Also ensure web_dashboard is in path for supabase_client imports
# (but AFTER project root so it doesn't shadow utils)
web_dashboard_path = str(current_dir.parent)
if web_dashboard_path not in sys.path:
    sys.path.insert(1, web_dashboard_path)  # Insert at index 1, after project_root



# Job definitions with metadata
AVAILABLE_JOBS: Dict[str, Dict[str, Any]] = {
    'exchange_rates': {
        'name': 'Exchange Rate Refresh',
        'description': 'Fetch latest USD/CAD exchange rate and store in database',
        'default_interval_minutes': 120,  # Every 2 hours
        'enabled_by_default': True,
        'icon': '💰'
    },
    'performance_metrics': {
        'name': 'Performance Metrics Population',
        'description': 'Aggregate daily portfolio performance into metrics table',
        'default_interval_minutes': 1440,  # Once per day
        'enabled_by_default': True,
        'icon': '📊',
        'parameters': {
            'target_date': {
                'type': 'date',
                'default': None,
                'optional': True,
                'description': 'Single date to recalculate (defaults to yesterday if not specified)'
            },
            'use_date_range': {
                'type': 'boolean',
                'default': False,
                'optional': True,
                'description': 'Process a date range instead of single date'
            },
            'from_date': {
                'type': 'date',
                'default': None,
                'optional': True,
                'description': 'Start date for range (only used if use_date_range is True)'
            },
            'to_date': {
                'type': 'date',
                'default': None,
                'optional': True,
                'description': 'End date for range (only used if use_date_range is True)'
            },
            'fund_filter': {
                'type': 'text',
                'default': None,
                'optional': True,
                'description': 'Filter by specific fund name (optional)'
            },
            'skip_existing': {
                'type': 'boolean',
                'default': False,
                'optional': True,
                'description': 'Skip dates where metrics already exist'
            }
        }
    },
    'update_portfolio_prices': {
        'name': 'Portfolio Price Update',
        'description': 'Fetch current stock prices and update portfolio positions for today',
        'default_interval_minutes': 15,  # Every 15 minutes during market hours
        'enabled_by_default': True,
        'icon': '📈',
        'parameters': {
            'target_date': {
                'type': 'date',
                'default': None,  # None means use today
                'optional': True,
                'description': 'Single date to update (defaults to today if not specified)'
            },
            'use_date_range': {
                'type': 'boolean',
                'default': False,
                'optional': True,
                'description': 'Process a date range instead of single date'
            },
            'from_date': {
                'type': 'date',
                'default': None,
                'optional': True,
                'description': 'Start date for range (only used if use_date_range is True)'
            },
            'to_date': {
                'type': 'date',
                'default': None,
                'optional': True,
                'description': 'End date for range (only used if use_date_range is True)'
            }
        }
    },
    'market_research': {
        'name': 'Market Research Collection',
        'description': 'Scrape and store general market news articles',
        'default_interval_minutes': 360,  # Every 6 hours (but uses cron triggers instead)
        'enabled_by_default': True,
        'icon': '📰'
    },
    'ticker_research': {
        'name': 'Ticker Research Collection',
        'description': 'Fetch news for specific companies in the portfolio',
        'default_interval_minutes': 360,  # Every 6 hours
        'enabled_by_default': True,
        'icon': '🔍'
    },
    'process_research_reports': {
        'name': 'Research Report Processing',
        'description': 'Process PDF research reports from Research/ folders, extract text, generate embeddings, and store in database',
        'default_interval_minutes': 60,  # Every hour
        'enabled_by_default': True,
        'icon': '📄'
    },
    'opportunity_discovery': {
        'name': 'Opportunity Discovery',
        'description': 'Hunt for new investment opportunities using targeted search queries',
        'default_interval_minutes': 720,  # Every 12 hours
        'enabled_by_default': True,
        'icon': '🔍'
    },
    'benchmark_refresh': {
        'name': 'Benchmark Data Refresh',
        'description': 'Fetch and cache benchmark data (S&P 500, QQQ, Russell 2000, VTI) for chart performance',
        'default_interval_minutes': 30,  # Every 30 minutes during market hours
        'enabled_by_default': True,
        'icon': '📊'
    },
    'social_sentiment': {
        'name': 'Social Sentiment Tracking',
        'description': 'Fetch retail hype and sentiment from StockTwits and Reddit',
        'default_interval_minutes': 60,  # Every 60 minutes (1 hour) - job takes 11-24 min, needs buffer
        'enabled_by_default': True,
        'icon': '💬'
    },
    'social_metrics_cleanup': {
        'name': 'Social Metrics Cleanup',
        'description': 'Daily cleanup: remove raw_data JSON after 14 days, delete rows after 60 days',
        'default_interval_minutes': 1440,  # Once per day
        'enabled_by_default': True,
        'icon': '🧹'
    },
    'social_sentiment_ai': {
        'name': 'Social Sentiment AI Analysis',
        'description': 'Extract posts, create sessions, and perform AI analysis on social sentiment data',
        'default_interval_minutes': 60,  # Every hour
        'enabled_by_default': True,
        'icon': '🤖'
    },
    'congress_trades': {
        'name': 'Congress Trade Fetch',
        'description': 'Fetch and analyze congressional stock trades from FMP API',
        'default_interval_minutes': 360,  # 6 hours (but uses cron triggers)
        'enabled_by_default': True,
        'icon': '🏛️'
    },
    'analyze_congress_trades': {
        'name': 'Congress Trade Analysis',
        'description': 'Calculate conflict scores for unscored congress trades using committee data',
        'default_interval_minutes': 30,  # Every 30 minutes
        'enabled_by_default': False,  # DISABLED during session backfill - re-enable after
        'icon': '🔍'
    },
    'archive_retry': {
        'name': 'Archive Retry',
        'description': 'Check for archived versions of paywalled articles and process them',
        'default_interval_minutes': 45,  # Every 45 minutes
        'enabled_by_default': True,
        'icon': '📦'
    },
    'rss_feed_ingest': {
        'name': 'RSS Feed Ingestion',
        'description': 'Fetch articles from validated RSS feeds (Push strategy)',
        'default_interval_minutes': 180,  # Every 3 hours
        'enabled_by_default': True,
        'icon': '📡'
    },
    'alpha_research': {
        'name': 'Alpha Hunter',
        'description': 'Targeted research on high-value alpha domains',
        'default_interval_minutes': 360,  # Every 6 hours
        'enabled_by_default': True,
        'icon': '🦊'
    },
    'seeking_alpha_symbol': {
        'name': 'Seeking Alpha Symbol Scraper',
        'description': 'Scrape Seeking Alpha symbol pages for portfolio tickers to extract news articles',
        'default_interval_minutes': 1440,  # Every 24 hours (daily)
        'enabled_by_default': True,
        'icon': '📑'
    },
    'dividend_processing': {
        'name': 'Dividend Reinvestment Processing',
        'description': 'Detect dividends and create DRIP transactions',
        'default_interval_minutes': 1440,  # Daily
        'enabled_by_default': True,
        'icon': '💰',
        'parameters': {
            'lookback_days': {
                'type': 'number',
                'default': 7,
                'optional': True,
                'description': 'Number of days to look back for dividend detection (default: 7)'
            }
        }
    },
    'subreddit_scanner': {
        'name': 'Subreddit Discovery Scanner',
        'description': 'Scans investment subreddits (pennystocks, microcap) for DD opportunities',
        'default_interval_minutes': 240,  # Every 4 hours
        'enabled_by_default': True,
        'icon': '👽'
    },
    'watchdog': {
        'name': 'Watchdog',
        'description': 'Automatically retry failed calculation jobs and detect stale/interrupted jobs',
        'default_interval_minutes': 30,  # Every 30 minutes
        'enabled_by_default': True,
        'icon': '🔄'
    },
    'process_retry_queue': {
        'name': 'Retry Queue Processing',
        'description': 'Automatically retry failed jobs from the retry queue',
        'default_interval_minutes': 15,  # Every 15 minutes
        'enabled_by_default': True,
        'icon': '♻️'
    },
    'log_cleanup': {
        'name': 'Log File Cleanup',
        'description': 'Delete log files older than 30 days to prevent unbounded disk usage',
        'default_interval_minutes': 1440,  # Once per day
        'enabled_by_default': True,
        'icon': '🧹'
    },
    'rescore_congress_sessions': {
        'name': 'Rescore Congress Sessions (Manual)',
        'description': 'One-time backfill: Rescore 1000 sessions with new AI logic',
        'default_interval_minutes': 0,  # Manual only, no schedule
        'enabled_by_default': False,  # Manual execution only
        'icon': '🔄',
        'parameters': {
            'limit': {
                'type': 'number', 
                'default': 1000, 
                'description': 'Number of sessions to process'
            },
            'batch_size': {
                'type': 'number', 
                'default': 10, 
                'description': 'Sessions to process per batch'
            },
            'model': {
                'type': 'text', 
                'default': 'granite3.3:8b', 
                'description': 'Ollama model name (defaults to get_summarizing_model() from settings if not provided)'
            }
        }
    },
    'etf_watchtower': {
        'name': 'ETF Watchtower',
        'description': 'Track daily ETF holdings changes (ARK, iShares) to detect institutional accumulation/distribution',
        'default_interval_minutes': 1440,  # Once per day
        'enabled_by_default': True,
        'icon': '🏛️',
        'cron_triggers': [
            {'hour': 20, 'minute': 0, 'timezone': 'America/New_York'}  # 20:00 EST - after ARK publishes
        ]
    },
    'refresh_securities_metadata': {
        'name': 'Securities Metadata Refresh',
        'description': 'Refresh company names and metadata for tickers with stale or missing data',
        'default_interval_minutes': 1440,  # Once per day
        'enabled_by_default': True,
        'icon': '📋'
    }
}


def get_job_icon(job_id: str) -> str:
    """Get the icon emoji for a job ID.
    
    Handles special cases for job variants:
    - update_portfolio_prices_close uses same icon as update_portfolio_prices
    - market_research_* variants use same icon as market_research
    - ticker_research_collect uses icon from ticker_research
    - opportunity_discovery_scan uses icon from opportunity_discovery
    
    Args:
        job_id: The job identifier
        
    Returns:
        Icon emoji string, or empty string if not found
    """
    # Handle special cases for job variants
    if job_id == 'update_portfolio_prices_close':
        job_id = 'update_portfolio_prices'
    elif job_id.startswith('market_research_collect_'):
        job_id = 'market_research'
    elif job_id == 'ticker_research_collect':
        job_id = 'ticker_research'
    elif job_id == 'opportunity_discovery_scan':
        job_id = 'opportunity_discovery'
    # Remove verb suffixes to get base job name for icon lookup
    elif job_id.endswith('_refresh'):
        job_id = job_id[:-8]  # Remove '_refresh'
    elif job_id.endswith('_populate'):
        job_id = job_id[:-9]  # Remove '_populate'
    elif job_id.endswith('_collect'):
        job_id = job_id[:-8]  # Remove '_collect'
    elif job_id.endswith('_scan'):
        job_id = job_id[:-5]  # Remove '_scan'
    elif job_id.endswith('_fetch'):
        job_id = job_id[:-6]  # Remove '_fetch'
    elif job_id.endswith('_cleanup'):
        job_id = job_id[:-8]  # Remove '_cleanup'
    
    # Look up icon from AVAILABLE_JOBS
    if job_id in AVAILABLE_JOBS:
        return AVAILABLE_JOBS[job_id].get('icon', '')
    
    return ''

# ============================================================================
# Import all job functions from separate modules
# ============================================================================

# Import metrics jobs
from scheduler.jobs_metrics import (
    benchmark_refresh_job,
    refresh_exchange_rates_job,
    populate_performance_metrics_job
)

# Import research jobs
from scheduler.jobs_research import (
    market_research_job,
    rss_feed_ingest_job,
    ticker_research_job,
    archive_retry_job,
    process_research_reports_job
)

# Import portfolio jobs
from scheduler.jobs_portfolio import (
    update_portfolio_prices_job,
    backfill_portfolio_prices_range
)

# Import social sentiment jobs
from scheduler.jobs_social import (
    fetch_social_sentiment_job,
    cleanup_social_metrics_job,
    social_sentiment_ai_job
)

# Import congress jobs
from scheduler.jobs_congress import (
    fetch_congress_trades_job,
    analyze_congress_trades_job,
    rescore_congress_sessions_job
)

# Import opportunity discovery job
from scheduler.jobs_opportunity import opportunity_discovery_job

# Import symbol article scraper job
from scheduler.jobs_symbol_articles import seeking_alpha_symbol_job

# Import dividend processing job
from scheduler.jobs_dividends import process_dividends_job

# Import watchdog job
from scheduler.jobs_watchdog import watchdog_job

# Import retry queue processor job
from scheduler.jobs_retry import process_retry_queue_job

# Import subreddit scanner job
from scheduler.jobs_reddit_discovery import subreddit_scanner_job

# Import securities refresh job
from scheduler.jobs_securities import refresh_securities_metadata_job

# Import shared utilities
from scheduler.jobs_common import calculate_relevance_score

# ============================================================================
# Re-export all job functions for backward compatibility
# ============================================================================
__all__ = [
    # Metrics jobs
    'benchmark_refresh_job',
    'refresh_exchange_rates_job',
    'populate_performance_metrics_job',
    # Research jobs
    'market_research_job',
    'rss_feed_ingest_job',
    'ticker_research_job',
    'archive_retry_job',
    # Portfolio jobs
    'update_portfolio_prices_job',
    'backfill_portfolio_prices_range',
    # Social sentiment jobs
    'fetch_social_sentiment_job',
    'cleanup_social_metrics_job',
    'social_sentiment_ai_job',
    # Congress jobs
    'fetch_congress_trades_job',
    'analyze_congress_trades_job',
    'rescore_congress_sessions_job',
    # Opportunity discovery
    'opportunity_discovery_job',
    # Seeking Alpha scraper
    'seeking_alpha_symbol_job',
    # Dividend processing
    'process_dividends_job',
    # Watchdog
    'watchdog_job',
    # Retry queue processor
    'process_retry_queue_job',
    # Subreddit scanner
    'subreddit_scanner_job',
    # Securities refresh
    'refresh_securities_metadata_job',
    # Shared utilities
    'calculate_relevance_score',
    # Registry functions (defined in this file)
    'AVAILABLE_JOBS',
    'get_job_icon',
    'register_default_jobs',
    # Log cleanup job
    'cleanup_log_files_job',
]


def cleanup_log_files_job() -> None:
    """Daily cleanup job for log file retention policy.
    
    Deletes log files older than 30 days to prevent unbounded disk usage.
    Preserves current app.log and recent rotated backups managed by RotatingFileHandler.
    """
    import time
    import os
    from pathlib import Path
    
    job_id = 'log_cleanup'
    start_time = time.time()
    
    try:
        # Import job tracking
        from utils.job_tracking import mark_job_started, mark_job_completed, mark_job_failed
        
        logger.info("Starting log cleanup job...")
        
        # Mark job as started
        target_date = datetime.now(timezone.utc).date()
        mark_job_started('log_cleanup', target_date)
        
        # Get logs directory path
        # This works both in container and local development
        log_dir = Path(__file__).parent.parent / 'logs'
        
        if not log_dir.exists():
            duration_ms = int((time.time() - start_time) * 1000)
            message = f"Logs directory not found: {log_dir}"
            log_job_execution(job_id, success=False, message=message, duration_ms=duration_ms)
            logger.warning(f"⚠️ {message}")
            mark_job_failed('log_cleanup', target_date, None, message, duration_ms=duration_ms)
            return
        
        # Calculate cutoff date (30 days ago)
        cutoff_time = time.time() - (30 * 24 * 60 * 60)  # 30 days in seconds
        
        deleted_count = 0
        deleted_size = 0
        preserved_count = 0
        
        # Get all log files in the directory
        log_files = list(log_dir.glob("*.log*"))
        
        for log_file in log_files:
            try:
                # Get file modification time
                file_mtime = os.path.getmtime(log_file)
                file_size = os.path.getsize(log_file)
                
                # Skip if file is newer than cutoff
                if file_mtime > cutoff_time:
                    preserved_count += 1
                    continue
                
                # Special handling for app.log and its rotated backups
                # RotatingFileHandler creates: app.log, app.log.1, app.log.2, etc.
                # We want to preserve at least the current app.log and recent backups
                if log_file.name.startswith('app.log'):
                    # For app.log files, be more conservative
                    # Only delete if it's clearly old (60 days) and not the current app.log
                    if log_file.name == 'app.log':
                        # Never delete the current app.log file
                        preserved_count += 1
                        continue
                    elif file_mtime < (time.time() - (60 * 24 * 60 * 60)):  # 60 days for rotated backups
                        # Only delete rotated backups older than 60 days
                        os.remove(log_file)
                        deleted_count += 1
                        deleted_size += file_size
                        logger.debug(f"Deleted old rotated log: {log_file.name}")
                    else:
                        preserved_count += 1
                else:
                    # For other log files, use 30-day cutoff
                    os.remove(log_file)
                    deleted_count += 1
                    deleted_size += file_size
                    logger.debug(f"Deleted old log file: {log_file.name}")
                    
            except OSError as e:
                logger.warning(f"Could not process {log_file.name}: {e}")
                continue
        
        # Log completion
        duration_ms = int((time.time() - start_time) * 1000)
        size_mb = deleted_size / (1024 * 1024)
        message = f"Deleted {deleted_count} log files ({size_mb:.2f} MB), preserved {preserved_count} files"
        log_job_execution(job_id, success=True, message=message, duration_ms=duration_ms)
        mark_job_completed('log_cleanup', target_date, None, [], duration_ms=duration_ms)
        logger.info(f"✅ Log cleanup job completed: {message} in {duration_ms/1000:.2f}s")
        
    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        message = f"Error: {str(e)}"
        log_job_execution(job_id, success=False, message=message, duration_ms=duration_ms)
        mark_job_failed('log_cleanup', target_date, None, str(e), duration_ms=duration_ms)
        logger.error(f"❌ Log cleanup job failed: {e}", exc_info=True)


def register_default_jobs(scheduler) -> None:
    """Register all default jobs with the scheduler.
    
    Called by start_scheduler() during initialization.
    """
    from apscheduler.triggers.interval import IntervalTrigger
    from apscheduler.triggers.cron import CronTrigger
    
    # Exchange rates job - every 2 hours
    if AVAILABLE_JOBS['exchange_rates']['enabled_by_default']:
        scheduler.add_job(
            refresh_exchange_rates_job,
            trigger=IntervalTrigger(minutes=AVAILABLE_JOBS['exchange_rates']['default_interval_minutes']),
            id='exchange_rates_refresh',
            name=f"{get_job_icon('exchange_rates')} Exchange Rate Refresh",
            replace_existing=True,
            max_instances=1,
            coalesce=True
        )
        logger.info("Registered job: exchange_rates_refresh (every 2 hours)")
    
    # Performance metrics job - daily at 5 PM EST (after market close)
    if AVAILABLE_JOBS['performance_metrics']['enabled_by_default']:
        scheduler.add_job(
            populate_performance_metrics_job,
            trigger=CronTrigger(hour=17, minute=0, timezone='America/New_York'),
            id='performance_metrics_populate',
            name=f"{get_job_icon('performance_metrics')} Performance Metrics Population",
            replace_existing=True,
            max_instances=1,
            coalesce=True
        )

        logger.info("Registered job: performance_metrics_populate (daily at 5 PM EST)")

    # Scheduler Heartbeat - Updates file timestamp every 20s to detect crashes
    # This is critical for the entrypoint/Streamlit/Flask coordination
    from scheduler.scheduler_core import _update_heartbeat
    scheduler.add_job(
        _update_heartbeat,
        trigger=IntervalTrigger(seconds=20),
        id='scheduler_heartbeat',
        name='Scheduler Heartbeat',
        replace_existing=True,
        max_instances=1,
        coalesce=True
    )
    logger.info("Registered job: scheduler_heartbeat (every 20s)")
    
    # Portfolio price update job - during market hours only (weekdays 9:30 AM - 4:00 PM EST)
    # NOTE: Exchange rates are NOT required for this job - positions are stored in native currency
    # Exchange rates are only used for display/calculation purposes, not for saving positions
    if AVAILABLE_JOBS['update_portfolio_prices']['enabled_by_default']:
        # Run every 15 minutes during market hours on weekdays
        # CronTrigger ensures we don't waste API calls overnight/weekends
        scheduler.add_job(
            update_portfolio_prices_job,
            trigger=CronTrigger(
                day_of_week='mon-fri',
                hour='9-15',  # 9 AM to 3:45 PM (last run at 3:45 catches most of trading day)
                minute='0,15,30,45',
                timezone='America/New_York'
            ),
            id='update_portfolio_prices',
            name=f"{get_job_icon('update_portfolio_prices')} Portfolio Price Update",
            replace_existing=True,
            max_instances=1,
            coalesce=True
        )
        logger.info("Registered job: update_portfolio_prices (weekdays 9:00-15:45 EST, every 15 min)")
        
        # Market close job at 4:05 PM EST to get official closing prices
        # Extended misfire_grace_time: if system is down at 4:05 PM, retry ASAP within 4 hours
        # This ensures we capture closing prices even after a reboot
        scheduler.add_job(
            update_portfolio_prices_job,
            trigger=CronTrigger(
                day_of_week='mon-fri',
                hour=16,
                minute=5,
                timezone='America/New_York'
            ),
            id='update_portfolio_prices_close',
            name=f"{get_job_icon('update_portfolio_prices_close')} Portfolio Price Update (Market Close)",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=60 * 60 * 4  # 4 hours - if missed, run when system comes back up
        )
        logger.info("Registered job: update_portfolio_prices_close (weekdays 4:05 PM EST, 4hr misfire grace)")
    
    # Market research job - 4 times daily at strategic times
    if AVAILABLE_JOBS['market_research']['enabled_by_default']:
        # Pre-Market: 08:00 EST (Mon-Fri)
        scheduler.add_job(
            market_research_job,
            trigger=CronTrigger(
                day_of_week='mon-fri',
                hour=8,
                minute=0,
                timezone='America/New_York'
            ),
            id='market_research_collect_premarket',
            name=f"{get_job_icon('market_research_premarket')} Market Research (Pre-Market)",
            replace_existing=True,
            max_instances=1,
            coalesce=True
        )
        logger.info("Registered job: market_research_collect_premarket (weekdays 8:00 AM EST)")
        
        # Mid-Morning: 11:00 EST (Mon-Fri)
        scheduler.add_job(
            market_research_job,
            trigger=CronTrigger(
                day_of_week='mon-fri',
                hour=11,
                minute=0,
                timezone='America/New_York'
            ),
            id='market_research_collect_midmorning',
            name=f"{get_job_icon('market_research_midmorning')} Market Research (Mid-Morning)",
            replace_existing=True,
            max_instances=1,
            coalesce=True
        )
        logger.info("Registered job: market_research_collect_midmorning (weekdays 11:00 AM EST)")
        
        # Power Hour: 14:00 EST (Mon-Fri)
        scheduler.add_job(
            market_research_job,
            trigger=CronTrigger(
                day_of_week='mon-fri',
                hour=14,
                minute=0,
                timezone='America/New_York'
            ),
            id='market_research_collect_powerhour',
            name=f"{get_job_icon('market_research_powerhour')} Market Research (Power Hour)",
            replace_existing=True,
            max_instances=1,
            coalesce=True
        )
        logger.info("Registered job: market_research_collect_powerhour (weekdays 2:00 PM EST)")
        
        # Post-Market: 16:30 EST (Mon-Fri)
        scheduler.add_job(
            market_research_job,
            trigger=CronTrigger(
                day_of_week='mon-fri',
                hour=16,
                minute=30,
                timezone='America/New_York'
            ),
            id='market_research_collect_postmarket',
            name=f"{get_job_icon('market_research_postmarket')} Market Research (Post-Market)",
            replace_existing=True,
            max_instances=1,
            coalesce=True
        )
        logger.info("Registered job: market_research_collect_postmarket (weekdays 4:30 PM EST)")

        # Ticker Research: Every 6 hours
        scheduler.add_job(
            ticker_research_job,
            trigger=CronTrigger(
                hour='*/6',
                minute=15,
                timezone='America/New_York'
            ),
            id='ticker_research_collect',
            name=f"{get_job_icon('ticker_research_collect')} Ticker Specific Research",
            replace_existing=True,
            max_instances=1,
            coalesce=True
        )
        logger.info("Registered job: ticker_research_collect (every 6 hours)")

        # Research Report Processing: Every hour
        if AVAILABLE_JOBS.get('process_research_reports', {}).get('enabled_by_default'):
            scheduler.add_job(
                process_research_reports_job,
                trigger=IntervalTrigger(minutes=AVAILABLE_JOBS['process_research_reports']['default_interval_minutes']),
                id='process_research_reports',
                name=f"{get_job_icon('process_research_reports')} Research Report Processing",
                replace_existing=True,
                max_instances=1,
                coalesce=True
            )
            logger.info("Registered job: process_research_reports (every 60 minutes - 1 hour)")

        # Opportunity Discovery: Every 12 hours
        scheduler.add_job(
            opportunity_discovery_job,
            trigger=CronTrigger(
                hour='*/12',
                minute=30,
                timezone='America/New_York'
            ),
            id='opportunity_discovery_scan',
            name=f"{get_job_icon('opportunity_discovery_scan')} Opportunity Discovery",
            replace_existing=True,
            max_instances=1,
            coalesce=True
        )
        logger.info("Registered job: opportunity_discovery_scan (every 12 hours)")

    # Alpha Research Job: Every 6 hours (offset)
    if AVAILABLE_JOBS.get('alpha_research', {}).get('enabled_by_default'):
        from scheduler.jobs_alpha import alpha_research_job
        scheduler.add_job(
            alpha_research_job,
            trigger=CronTrigger(
                hour='*/6',
                minute=45, # Offset from others
                timezone='America/New_York'
            ),
            id='alpha_research_collect',
            name=f"{get_job_icon('alpha_research')} Alpha Hunter",
            replace_existing=True,
            max_instances=1,
            coalesce=True
        )
        logger.info("Registered job: alpha_research_collect (every 6 hours)")
    
    # Seeking Alpha Symbol Scraper: Daily at 2:00 AM EST (off-peak, avoids conflicts with 3:00 AM cleanup)
    if AVAILABLE_JOBS.get('seeking_alpha_symbol', {}).get('enabled_by_default'):
        scheduler.add_job(
            seeking_alpha_symbol_job,
            trigger=CronTrigger(
                hour=2,
                minute=0,
                timezone='America/New_York'
            ),
            id='seeking_alpha_symbol_scrape',
            name=f"{get_job_icon('seeking_alpha_symbol')} Seeking Alpha Symbol Scraper",
            replace_existing=True,
            max_instances=1,
            coalesce=True
        )
        logger.info("Registered job: seeking_alpha_symbol_scrape (daily at 2:00 AM EST)")
    
    # Benchmark refresh job - every 30 minutes during market hours (weekdays 9:30 AM - 4:00 PM EST)
    if AVAILABLE_JOBS['benchmark_refresh']['enabled_by_default']:
        # Run every 30 minutes during market hours on weekdays
        # Market hours: 9:30 AM - 4:00 PM EST
        # First run at market open (9:30 AM), then every 30 minutes until market close (4:00 PM)
        scheduler.add_job(
            benchmark_refresh_job,
            trigger=CronTrigger(
                day_of_week='mon-fri',
                hour='9',  # 9 AM
                minute='30',  # 9:30 AM (market open)
                timezone='America/New_York'
            ),
            id='benchmark_refresh_open',
            name=f"{get_job_icon('benchmark_refresh')} Benchmark Data Refresh (Market Open)",
            replace_existing=True,
            max_instances=1,
            coalesce=True
        )
        # Then every 30 minutes from 10:00 AM to 4:00 PM
        scheduler.add_job(
            benchmark_refresh_job,
            trigger=CronTrigger(
                day_of_week='mon-fri',
                hour='10-16',  # 10 AM to 4 PM EST
                minute='0,30',  # Every 30 minutes
                timezone='America/New_York'
            ),
            id='benchmark_refresh',
            name=f"{get_job_icon('benchmark_refresh')} Benchmark Data Refresh",
            replace_existing=True,
            max_instances=1,
            coalesce=True
        )
        logger.info("Registered job: benchmark_refresh (weekdays 9:30 AM - 4:00 PM EST, every 30 min during market hours)")
    
    # Social sentiment job - every 60 minutes (1 hour)
    if AVAILABLE_JOBS['social_sentiment']['enabled_by_default']:
        scheduler.add_job(
            fetch_social_sentiment_job,
            trigger=IntervalTrigger(minutes=AVAILABLE_JOBS['social_sentiment']['default_interval_minutes']),
            id='social_sentiment_fetch',
            name=f"{get_job_icon('social_sentiment')} Social Sentiment Tracking",
            replace_existing=True,
            max_instances=1,
            coalesce=True
        )
        logger.info("Registered job: social_sentiment_fetch (every 60 minutes - 1 hour)")
    
    # Social sentiment AI analysis job - every 2 hours
    # DISABLED: Redundant with inline analysis in fetch_social_sentiment_job
    # if AVAILABLE_JOBS['social_sentiment_ai']['enabled_by_default']:
    #     scheduler.add_job(
    #         social_sentiment_ai_job,
    #         trigger=IntervalTrigger(minutes=AVAILABLE_JOBS['social_sentiment_ai']['default_interval_minutes']),
    #         id='social_sentiment_ai',
    #         name=f"{get_job_icon('social_sentiment_ai')} Social Sentiment AI Analysis",
    #         replace_existing=True,
    #         max_instances=1,
    #         coalesce=True
    #     )
    #     logger.info("Registered job: social_sentiment_ai (every 2 hours)")
    
    # Social metrics cleanup job - daily at 3:00 AM
    scheduler.add_job(
        cleanup_social_metrics_job,
        trigger=CronTrigger(
            hour=3,
            minute=0,
            timezone='America/New_York'
        ),
        id='social_metrics_cleanup',
        name=f"{get_job_icon('social_metrics_cleanup')} Social Metrics Cleanup",
        replace_existing=True,
        max_instances=1,
        coalesce=True
    )
    logger.info("Registered job: social_metrics_cleanup (daily at 3:00 AM EST)")
    
    # Log cleanup job - daily at 2:00 AM EST
    if AVAILABLE_JOBS['log_cleanup']['enabled_by_default']:
        scheduler.add_job(
            cleanup_log_files_job,
            trigger=CronTrigger(
                hour=2,
                minute=0,
                timezone='America/New_York'
            ),
            id='log_cleanup',
            name=f"{get_job_icon('log_cleanup')} Log File Cleanup",
            replace_existing=True,
            max_instances=1,
            coalesce=True
        )
        logger.info("Registered job: log_cleanup (daily at 2:00 AM EST)")
    
    # Rescore Congress Sessions (Manual Only)
    # Always register this so it appears in UI, but it has no schedule
    # We use a dummy date trigger far in the future
    scheduler.add_job(
        rescore_congress_sessions_job,
        trigger='date', 
        run_date=datetime(9999, 12, 31, tzinfo=timezone.utc), # Effectively never
        id='rescore_congress_sessions',
        name=f"{get_job_icon('rescore_congress_sessions')} Rescore Congress Sessions (Manual)",
        replace_existing=True
    )
    scheduler.pause_job('rescore_congress_sessions') # Ensure it's paused/manual only
    logger.info("Registered job: rescore_congress_sessions (Manual only)")
    
    # Congress trades job - every 12 minutes (120 runs/day × 2 API calls = 240 total, stays under 250 limit)
    if AVAILABLE_JOBS['congress_trades']['enabled_by_default']:
        scheduler.add_job(
            fetch_congress_trades_job,
            trigger=IntervalTrigger(minutes=12),
            id='congress_trades_fetch',
            name=f"{get_job_icon('congress_trades')} Congress Trade Fetch",
            replace_existing=True,
            max_instances=1,
            coalesce=True
        )
        logger.info("Registered job: congress_trades_fetch (every 12 minutes - 120 runs/day, 240 API calls/day)")
    
    # Analyze congress trades job - every 30 minutes (processes unscored trades with committee data)
    if AVAILABLE_JOBS['analyze_congress_trades']['enabled_by_default']:
        scheduler.add_job(
            analyze_congress_trades_job,
            trigger=IntervalTrigger(minutes=AVAILABLE_JOBS['analyze_congress_trades']['default_interval_minutes']),
            id='analyze_congress_trades',
            name=f"{get_job_icon('analyze_congress_trades')} Congress Trade Analysis",
            replace_existing=True,
            max_instances=1,
            coalesce=True
        )
        logger.info("Registered job: analyze_congress_trades (every 30 minutes - processes unscored trades)")
    
    # Dividend processing job - daily at 2:00 AM PST
    if AVAILABLE_JOBS['dividend_processing']['enabled_by_default']:
        scheduler.add_job(
            process_dividends_job,
            trigger=CronTrigger(hour=2, minute=0, timezone='America/Los_Angeles'),
            id='dividend_processing',
            name=f"{get_job_icon('dividend_processing')} Dividend Reinvestment Processing",
            replace_existing=True,
            max_instances=1,
            coalesce=True
        )
        logger.info("Registered job: dividend_processing (daily at 2:00 AM PST)")
    
    # Watchdog job - every 30 minutes
    if AVAILABLE_JOBS['watchdog']['enabled_by_default']:
        scheduler.add_job(
            watchdog_job,
            trigger=IntervalTrigger(minutes=AVAILABLE_JOBS['watchdog']['default_interval_minutes']),
            id='watchdog',
            name=f"{get_job_icon('watchdog')} Watchdog",
            replace_existing=True,
            max_instances=1,
            coalesce=True
        )
        logger.info("Registered job: watchdog (every 30 minutes)")
    
    # Retry queue processor job - every 15 minutes
    if AVAILABLE_JOBS.get('process_retry_queue', {}).get('enabled_by_default', True):
        scheduler.add_job(
            process_retry_queue_job,
            trigger=IntervalTrigger(minutes=AVAILABLE_JOBS['process_retry_queue']['default_interval_minutes']),
            id='process_retry_queue',
            name=f"{get_job_icon('process_retry_queue')} Retry Queue Processing",
            replace_existing=True,
            max_instances=1,
            coalesce=True
        )
        logger.info("Registered job: process_retry_queue (every 15 minutes)")

    # Archive retry job - every 45 minutes
    if AVAILABLE_JOBS.get('archive_retry', {}).get('enabled_by_default', True):
        scheduler.add_job(
            archive_retry_job,
            trigger=IntervalTrigger(minutes=AVAILABLE_JOBS['archive_retry']['default_interval_minutes']),
            id='archive_retry',
            name=f"{get_job_icon('archive_retry')} Archive Retry",
            replace_existing=True,
            max_instances=1,
            coalesce=True
        )
        logger.info("Registered job: archive_retry (every 45 minutes)")

    # Subreddit Scanner - every 4 hours
    if AVAILABLE_JOBS.get('subreddit_scanner', {}).get('enabled_by_default', True):
        scheduler.add_job(
            subreddit_scanner_job,
            trigger=IntervalTrigger(minutes=AVAILABLE_JOBS['subreddit_scanner']['default_interval_minutes']),
            id='subreddit_scanner',
            name=f"{get_job_icon('subreddit_scanner')} Subreddit Discovery Scanner",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        misfire_grace_time=3600
        )
        logger.info("Registered job: subreddit_scanner (every 4 hours)")

    # ETF Watchtower - Daily at 8:00 PM EST
    if AVAILABLE_JOBS.get('etf_watchtower', {}).get('enabled_by_default', True):
        from scheduler.jobs_etf_watchtower import etf_watchtower_job
        
        # Use triggers from definition or default to 8pm EST
        config = AVAILABLE_JOBS['etf_watchtower']
        triggers = config.get('cron_triggers', [{'hour': 20, 'minute': 0, 'timezone': 'America/New_York'}])
        
        # We can only support one trigger easily here, take the first
        trigger_config = triggers[0]
        
        scheduler.add_job(
            etf_watchtower_job,
            trigger=CronTrigger(
                hour=trigger_config['hour'], 
                minute=trigger_config['minute'], 
                timezone=trigger_config.get('timezone', 'America/New_York')
            ),
            id='etf_watchtower',
            name=f"{get_job_icon('etf_watchtower')} ETF Watchtower",
            replace_existing=True,
            max_instances=1,
            coalesce=True
        )
        logger.info("Registered job: etf_watchtower (daily at 8:00 PM EST)")
    
    # Securities Metadata Refresh - Daily at 1:00 AM EST (low priority, off-peak)
    if AVAILABLE_JOBS.get('refresh_securities_metadata', {}).get('enabled_by_default', True):
        scheduler.add_job(
            refresh_securities_metadata_job,
            trigger=CronTrigger(
                hour=1,
                minute=0,
                timezone='America/New_York'
            ),
            id='refresh_securities_metadata',
            name=f"{get_job_icon('refresh_securities_metadata')} Securities Metadata Refresh",
            replace_existing=True,
            max_instances=1,
            coalesce=True
        )
        logger.info("Registered job: refresh_securities_metadata (daily at 1:00 AM EST)")