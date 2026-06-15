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

from model_registry import PRIMARY_MODEL_DEFAULT

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
        'name': '📚 Market Research Collection',
        'description': 'Scrape and store general market news articles',
        'default_interval_minutes': 360,  # Every 6 hours (but uses cron triggers instead)
        'enabled_by_default': True,
        'icon': '📚'
    },
    'ticker_research': {
        'name': '🔍 Ticker Research Collection',
        'description': 'Fetch news for specific companies in the portfolio',
        'default_interval_minutes': 720,  # Every 12 hours
        'enabled_by_default': True,
        'icon': '🔍'
    },
    'process_research_reports': {
        'name': '📚 Research Report Processing',
        'description': 'Process PDF research reports from Research/ folders, extract text, generate embeddings, and store in database',
        'default_interval_minutes': 60,  # Every hour
        'enabled_by_default': True,
        'icon': '📚'
    },
    'opportunity_discovery': {
        'name': '🔍 Opportunity Discovery',
        'description': 'Hunt for new investment opportunities using targeted search queries',
        'default_interval_minutes': 1440,  # Daily
        'enabled_by_default': True,
        'icon': '🔍'
    },
    'benchmark_refresh': {
        'name': 'Benchmark Data Refresh',
        'description': 'Fetch and cache benchmark & commodity data (S&P 500, QQQ, Russell 2000, VTI, Gold, Silver, Oil, Uranium, Lithium) for chart performance',
        'default_interval_minutes': 30,  # Every 30 minutes during market hours
        'enabled_by_default': True,
        'icon': '📊'
    },
    'market_daily_brief': {
        'name': 'Market Daily Brief',
        'description': 'One LLM-backed regime summary per NY day from benchmark closes (cached in research DB)',
        'default_interval_minutes': 1440,
        'enabled_by_default': True,
        'icon': '📰',
    },
    'sector_meta_analysis': {
        'name': '🧭 Sector Meta Analysis',
        'description': 'Sector rotation synthesis from ETF Analysis articles (Phase 3b, research DB)',
        'default_interval_minutes': 1440,
        'enabled_by_default': True,
        'icon': '🧭',
        'cron_triggers': [
            {'hour': 23, 'minute': 30, 'timezone': 'America/Los_Angeles'}
        ],
    },
    'action_queue_ai_review': {
        'name': 'Action Queue AI Review',
        'description': 'Nightly cached LLM cross-check of top action-queue rows vs saved ticker research',
        'default_interval_minutes': 1440,
        'enabled_by_default': True,
        'icon': '⚡',
    },
    'stance_outcomes': {
        'name': 'Stance Outcomes Scoring',
        'description': 'Nightly no-LLM scoring of stance_history rows at 7/30/90d vs ^RUT',
        'default_interval_minutes': 1440,
        'enabled_by_default': True,
        'icon': '📈',
        'cron_triggers': [
            {'hour': 21, 'minute': 30, 'timezone': 'America/New_York'},
        ],
    },
    'contradiction_drilldown': {
        'name': 'Contradiction Drill-Down',
        'description': 'Enqueue targeted ticker_analysis when meta contradiction supply is healthy',
        'default_interval_minutes': 10080,
        'enabled_by_default': True,
        'icon': '🔬',
        'cron_triggers': [
            {'day_of_week': 'sun', 'hour': 20, 'minute': 0, 'timezone': 'America/New_York'},
        ],
    },
    'dilution_watch': {
        'name': 'Dilution Watch',
        'description': 'Flags shares-outstanding growth (dilution) on holdings + watchlist via yfinance (ROADMAP G3)',
        'default_interval_minutes': 10080,
        'enabled_by_default': True,
        'icon': '⚠️',
        # Weekly: share counts move slowly, so a daily scan would only add
        # duplicate flagged rows for the same ongoing dilution. Monday 06:30 ET.
        'cron_triggers': [
            {'day_of_week': 'mon', 'hour': 6, 'minute': 30, 'timezone': 'America/New_York'},
        ],
    },
    'weekly_stance_retro': {
        'name': 'Weekly Stance Retro',
        'description': 'Weekly log summary of stance flips and outcome hit rates',
        'default_interval_minutes': 10080,
        'enabled_by_default': True,
        'icon': '📬',
        'cron_triggers': [
            {'day_of_week': 'sun', 'hour': 17, 'minute': 0, 'timezone': 'America/New_York'},
        ],
    },
    'ui_ai_summaries': {
        'name': 'UI AI summaries',
        'description': (
            'Tier-1 dashboard portfolio digest + tier-2 per-fund rollup (research DB); '
            'skips LLM when inputs unchanged'
        ),
        'default_interval_minutes': 120,
        'enabled_by_default': True,
        'icon': '🧠',
    },
    'social_sentiment': {
        'name': '💬 Social Sentiment Tracking',
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
        'name': '💬 Social Sentiment AI Analysis',
        'description': 'Extract posts, create sessions, and perform AI analysis on social sentiment data',
        'default_interval_minutes': 60,  # Every hour
        'enabled_by_default': True,
        'icon': '💬'
    },
    'signal_scan': {
        'name': '📊 Technical Signal Scan',
        'description': 'Calculate technical signals (trend, timing, fear/risk) for watchlist tickers',
        'default_interval_minutes': 240,  # Every 4 hours
        'enabled_by_default': True,
        'icon': '📊',
        'cron_triggers': [
            {'day_of_week': 'mon-fri', 'hour': '6,10', 'minute': 15, 'timezone': 'America/Los_Angeles'}
        ]
    },
    'fundamentals_refresh': {
        'name': '📈 Fundamentals Refresh',
        'description': 'Backfill fundamental metrics (P/E, ROE, margins, etc.) from yfinance for watchlist tickers',
        'default_interval_minutes': 1440,  # Daily
        'enabled_by_default': True,
        'icon': '📈',
        'cron_triggers': [
            {'hour': 3, 'minute': 30, 'timezone': 'America/New_York'}  # 3:30 AM ET - off-peak
        ]
    },
    'article_relevance': {
        'name': '🔍 Article Relevance Validation',
        'description': 'Validate ticker assignments on research articles using GLM 4.5-air to remove incorrect tags',
        'default_interval_minutes': 1440,  # Daily
        'enabled_by_default': True,
        'icon': '🔍',
        'cron_triggers': [
            {'hour': 4, 'minute': 0, 'timezone': 'America/New_York'}  # 4:00 AM ET - after scraping jobs
        ]
    },
    'congress_trades': {
        'name': '🏛️ Congress Trade Fetch',
        'description': 'Fetch and analyze congressional stock trades from FMP API',
        'default_interval_minutes': 360,  # 6 hours (but uses cron triggers)
        'enabled_by_default': True,
        'icon': '🏛️',
        'cron_triggers': [
            {'hour': '19,21,23,1', 'minute': 0, 'timezone': 'America/Los_Angeles'}
        ]
    },
    'insider_trades': {
        'name': '🏢 Insider Trade Fetch',
        'description': 'Fetch corporate insider trading data from external source',
        'default_interval_minutes': 360,  # 6 hours
        'enabled_by_default': True,
        'icon': '🏢',
        'cron_triggers': [
            {'hour': 20, 'minute': 0, 'timezone': 'America/Los_Angeles'}
        ]
    },
    'analyze_congress_trades': {
        'name': '🏛️ Congress Trade Analysis',
        'description': 'Calculate conflict scores for unscored congress trades using committee data',
        'default_interval_minutes': 30,  # Every 30 minutes
        'enabled_by_default': False,  # DISABLED during session backfill - re-enable after
        'icon': '🏛️'
    },
    'archive_retry': {
        'name': '📚 Archive Retry',
        'description': 'Check for archived versions of paywalled articles and process them',
        'default_interval_minutes': 45,  # Every 45 minutes
        'enabled_by_default': True,
        'icon': '📚'
    },
    'rss_feed_ingest': {
        'name': '📚 RSS Feed Ingestion',
        'description': 'Fetch articles from validated RSS feeds (Push strategy)',
        'default_interval_minutes': 180,  # Every 3 hours
        'enabled_by_default': True,
        'icon': '📚'
    },
    'alpha_research': {
        'name': '📚 Alpha Hunter',
        'description': 'Targeted research on high-value alpha domains',
        'default_interval_minutes': 1440,  # Daily
        'enabled_by_default': True,
        'icon': '📚'
    },
    'symbol_article_scraper': {
        'name': '📚 Symbol Article Scraper',
        'description': 'Scrape symbol pages for portfolio tickers to extract news articles',
        'default_interval_minutes': 1440,  # Every 24 hours (daily)
        'enabled_by_default': True,
        'icon': '📚'
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
    'test_funds_cleanup': {
        'name': 'Test Funds Cleanup',
        'description': 'Delete non-production TEST_* funds and related rows created by automated tests',
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
                'default': PRIMARY_MODEL_DEFAULT,
                'description': 'AI model name (defaults to get_summarizing_model() from settings if not provided)'
            }
        }
    },
    'scrape_congress_trades': {
        'name': 'Scrape Congress Trades (Manual)',
        'description': 'Scrape historical congressional trades from external source (uses FlareSolverr if available)',
        'default_interval_minutes': 0,  # Manual only, no schedule
        'enabled_by_default': False,  # Manual execution only
        'icon': '🕷️',
        'parameters': {
            'months_back': {
                'type': 'number',
                'default': None,
                'optional': True,
                'description': 'Number of months back to scrape (None = all available trades)'
            },
            'page_size': {
                'type': 'number',
                'default': 100,
                'optional': True,
                'description': 'Number of trades per page (default: 100, max recommended: 200)'
            },
            'max_pages': {
                'type': 'number',
                'default': None,
                'optional': True,
                'description': 'Maximum number of pages to process (None = unlimited, useful for testing)'
            },
            'start_page': {
                'type': 'number',
                'default': 1,
                'optional': True,
                'description': 'Page number to start from (default: 1)'
            },
            'skip_recent': {
                'type': 'boolean',
                'default': False,
                'optional': True,
                'description': 'Skip trades on or after the most recent trade date (useful for continuing historical import)'
            }
        }
    },
    'etf_group_analysis': {
        'name': '💼 ETF Group AI Analysis',
        'description': 'Analyze daily ETF holdings changes as groups using AI',
        'default_interval_minutes': 1440,
        'enabled_by_default': True,
        'icon': '💼',
        'cron_triggers': [
            {'hour': 19, 'minute': 15, 'timezone': 'America/Los_Angeles'}  # 7:15 PM PT
        ]
    },
    'ticker_analysis': {
        'name': '🔍 Ticker AI Analysis',
        'description': 'Analyze tickers with 3-month multi-source data. Holdings first, then watched tickers. 2-hour max.',
        'default_interval_minutes': 1440,
        'enabled_by_default': True,
        'icon': '🔍',
        'cron_triggers': [
            {'hour': 21, 'minute': 0, 'timezone': 'America/Los_Angeles'}  # 9:00 PM PT
        ]
    },
    'ticker_meta_analysis': {
        'name': '🧩 Ticker Meta Analysis',
        'description': 'Second-pass synthesis over stored AI artifacts (per ticker). Runs after main ticker analysis.',
        'default_interval_minutes': 1440,
        'enabled_by_default': True,
        'icon': '🧩',
        'cron_triggers': [
            {'hour': 23, 'minute': 45, 'timezone': 'America/Los_Angeles'}  # 11:45 PM PT
        ]
    },
    'etf_watchtower': {
        'name': '💼 ETF Watchtower',
        'description': 'Track daily ETF holdings changes (ARK, iShares) to detect institutional accumulation/distribution',
        'default_interval_minutes': 1440,  # Once per day
        'enabled_by_default': True,
        'icon': '💼',
        'cron_triggers': [
            {'hour': 18, 'minute': 0, 'timezone': 'America/Los_Angeles'}  # 6:00 PM PT - after ARK publishes
        ]
    },
    'refresh_securities_metadata': {
        'name': 'Securities Metadata Refresh',
        'description': 'Refresh company names and metadata for tickers with stale or missing data',
        'default_interval_minutes': 1440,  # Once per day
        'enabled_by_default': True,
        'icon': '📋'
    },
    'thesis_update': {
        'name': '📜 Fund Thesis Update',
        'description': 'AI-driven update of fund investment thesis based on actual portfolio composition',
        'default_interval_minutes': 10080,  # Weekly (7 days)
        'enabled_by_default': True,
        'icon': '📜',
        'cron_triggers': [
            {'day_of_week': 'sun', 'hour': 20, 'minute': 0, 'timezone': 'America/Los_Angeles'}  # Sunday 8 PM PT
        ]
    },
    'rebalance_recommendation_tfsa': {
        'name': '⚖️ TFSA Rebalance Review',
        'description': 'Advisory-only concentration and cash drift review for TFSA funds',
        'default_interval_minutes': 10080,  # Weekly
        'enabled_by_default': True,
        'icon': '⚖️',
        'cron_triggers': [
            {'day_of_week': 'sun', 'hour': 18, 'minute': 0, 'timezone': 'America/Los_Angeles'}  # Sunday 6 PM PT
        ]
    },
    'rebalance_recommendation_rrsp': {
        'name': '⚖️ RRSP Rebalance Review',
        'description': 'Advisory-only concentration and cash drift review for RRSP funds',
        'default_interval_minutes': 43200,  # Monthly (30 days approximation)
        'enabled_by_default': True,
        'icon': '⚖️',
        'cron_triggers': [
            {'day': 1, 'hour': 18, 'minute': 30, 'timezone': 'America/Los_Angeles'}  # 1st day of month
        ]
    },
    'newsletter_ai_processing': {
        'name': '📰 Newsletter AI Processing',
        'description': 'Safety-net: summarize any newsletters still missing an AI summary (primary processing happens inline after webhook)',
        'default_interval_minutes': 30,  # Frequent safety net to drain backlog after webhook misses
        'enabled_by_default': True,
        'icon': '📰'
    },
    'outbound_portfolio_digest': {
        'name': 'Outbound portfolio digest',
        'description': 'Send portfolio digest via Mailgun to subscribed users (due by cadence). Requires MAILGUN_API_KEY and send domain (env or system_settings mailgun_send_domain).',
        'default_interval_minutes': 1440,
        'enabled_by_default': False,
        'icon': '📧',
        'cron_triggers': [
            {'hour': 12, 'minute': 0, 'timezone': 'America/New_York'}
        ],
    },
    'congress_trade_returns': {
        'name': 'Congress Trade Returns',
        'description': 'Compute % price change for each congress trade using yfinance adjusted close. Updates current prices daily.',
        'default_interval_minutes': 1440,  # Once per day
        'enabled_by_default': True,
        'icon': '📊',
        'cron_triggers': [
            {'hour': 6, 'minute': 0, 'timezone': 'America/New_York'}  # 6:00 AM ET (after market data settles)
        ]
    },
    'congress_positions': {
        'name': 'Congress Closed Positions',
        'description': 'Compute closed positions (buy+sell pairs) per politician/ticker. Aggregates returns and estimates dollar P&L.',
        'default_interval_minutes': 1440,  # Once per day
        'enabled_by_default': True,
        'icon': '🏛️',
        'cron_triggers': [
            {'hour': 6, 'minute': 30, 'timezone': 'America/New_York'}  # 6:30 AM ET (after trade returns job)
        ]
    },
    'daily_critical_data_backup': {
        'name': 'Daily Critical Data Backup',
        'description': (
            'Daily CSV snapshot of trade_log (per fund) and irreplaceable '
            'app/config tables (user_profiles, user_funds, funds, fund_thesis, '
            'fund_thesis_pillars, fund_contributions, system_settings, '
            'watched_tickers_v2, ai_analysis_skip_list, contributors, '
            'contributor_access) to host volume and Supabase Storage bucket '
            '"daily-backups". Operational/rebuildable tables are NOT backed up.'
        ),
        'default_interval_minutes': 1440,
        'enabled_by_default': True,
        'icon': '\U0001f4be',
        'cron_triggers': [
            # 12:00 UTC daily. Verified clean against every other registered
            # cron trigger across both PDT/PST and EDT/EST. Sits well after the
            # overnight AI pipeline (alpha_research 23:15 PT, sector_meta
            # 23:30 PT, ticker_meta 23:45 PT -- all in UTC ~06:15-07:45) and
            # well before market-hours work begins. Intentionally NOT 04:30 UTC
            # because that overlaps ticker_analysis (21:00 PT = 04:00 UTC PDT,
            # runs up to 2h).
            {'hour': 12, 'minute': 0, 'timezone': 'UTC'}
        ]
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
    # If job_id is defined directly, return it without modifications
    if job_id in AVAILABLE_JOBS:
        return AVAILABLE_JOBS[job_id].get('icon', '')

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
from scheduler.jobs_dashboard_research import (
    action_queue_ai_review_job,
    market_daily_brief_job,
)
from scheduler.jobs_stance_outcomes import stance_outcomes_job
from scheduler.jobs_contradiction_drilldown import contradiction_drilldown_job
from scheduler.jobs_dilution_watch import dilution_watch_job
from scheduler.jobs_weekly_stance_retro import weekly_stance_retro_job
from scheduler.jobs_ui_ai_summaries import ui_ai_summaries_job

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
    rescore_congress_sessions_job,
    scrape_congress_trades_job
)

# Import insider trades jobs
from scheduler.jobs_insiders import (
    fetch_insider_trades_job
)

# Import opportunity discovery job
from scheduler.jobs_opportunity import opportunity_discovery_job

# Import symbol article scraper job
from scheduler.jobs_symbol_articles import symbol_article_scraper_job

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

# Import signals jobs
from scheduler.jobs_signals import signal_scan_job, fundamentals_refresh_job

# Import article relevance job
from scheduler.jobs_article_relevance import article_relevance_job

# Import thesis update job
from scheduler.thesis_update_job import thesis_update_job

# Import rebalance recommendation jobs
from scheduler.jobs_rebalance import (
    rebalance_recommendation_tfsa_job,
    rebalance_recommendation_rrsp_job,
)

# Import newsletter AI processing job
from scheduler.jobs_newsletter import newsletter_ai_processing_job

# Outbound portfolio digest (Mailgun)
from scheduler.jobs_outbound_newsletter import outbound_portfolio_digest_job

# Import daily critical data backup job (trade_log + irreplaceable app tables)
from scheduler.jobs_daily_backup import daily_critical_data_backup_job

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
    'market_daily_brief_job',
    'action_queue_ai_review_job',
    'stance_outcomes_job',
    'contradiction_drilldown_job',
    'dilution_watch_job',
    'weekly_stance_retro_job',
    'ui_ai_summaries_job',
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
    'scrape_congress_trades_job',
    # Insider trades jobs
    'fetch_insider_trades_job',
    # Opportunity discovery
    'opportunity_discovery_job',
    # Symbol article scraper
    'symbol_article_scraper_job',
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
    # Signals jobs
    'signal_scan_job',
    'fundamentals_refresh_job',
    # Article relevance job
    'article_relevance_job',
    # Thesis update job
    'thesis_update_job',
    # Rebalance recommendation jobs
    'rebalance_recommendation_tfsa_job',
    'rebalance_recommendation_rrsp_job',
    # Newsletter AI processing job
    'newsletter_ai_processing_job',
    # Outbound portfolio digest
    'outbound_portfolio_digest_job',
    # Daily critical data backup (trade_log + critical app tables)
    'daily_critical_data_backup_job',
    # Shared utilities
    'calculate_relevance_score',
    # Registry functions (defined in this file)
    'AVAILABLE_JOBS',
    'get_job_icon',
    'register_default_jobs',
    # Log cleanup job
    'cleanup_log_files_job',
    # Test funds cleanup job
    'cleanup_test_funds_job',
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
            try:
                log_job_execution(job_id, False, message, duration_ms)
            except Exception as log_error:
                logger.warning(f"Failed to log job execution: {log_error}")
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
        
        # Clean up old job step logs (7-day retention)
        steps_deleted = 0
        try:
            from utils.job_tracking import cleanup_old_job_steps
            steps_deleted = cleanup_old_job_steps(retention_days=7)
            if steps_deleted > 0:
                logger.info(f"Cleaned up {steps_deleted} old job step log entries")
        except Exception as e:
            logger.warning(f"Job step cleanup failed (non-fatal): {e}")

        # Log completion
        duration_ms = int((time.time() - start_time) * 1000)
        size_mb = deleted_size / (1024 * 1024)
        steps_msg = f", {steps_deleted} step log entries" if steps_deleted else ""
        message = f"Deleted {deleted_count} log files ({size_mb:.2f} MB), preserved {preserved_count} files{steps_msg}"
        try:
            log_job_execution(job_id, True, message, duration_ms)
        except Exception as log_error:
            logger.warning(f"Failed to log job execution: {log_error}")
        mark_job_completed('log_cleanup', target_date, None, [], duration_ms=duration_ms, message=message)
        logger.info(f"✅ Log cleanup job completed: {message} in {duration_ms/1000:.2f}s")
        
    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        message = f"Error: {str(e)}"
        try:
            log_job_execution(job_id, False, message, duration_ms)
        except Exception as log_error:
            logger.warning(f"Failed to log job execution error: {log_error}")
        mark_job_failed('log_cleanup', target_date, None, str(e), duration_ms=duration_ms)
        logger.error(f"❌ Log cleanup job failed: {e}", exc_info=True)


def cleanup_test_funds_job() -> None:
    """Daily cleanup job to delete test funds and their related data.

    This is a safety net for test suites that create TEST_* funds but don't
    reliably clean them up (e.g., interruptions or FK constraint failures).
    """
    import time

    job_id = "test_funds_cleanup"
    start_time = time.time()
    target_date = datetime.now(timezone.utc).date()

    try:
        from utils.job_tracking import mark_job_started, mark_job_completed, mark_job_failed
        mark_job_started(job_id, target_date)

        from supabase_client import SupabaseClient
        client = SupabaseClient(use_service_role=True)

        funds_result = client.supabase.table("funds").select("id, name, is_production").execute()
        funds = funds_result.data or []

        test_funds = []
        for fund in funds:
            name = fund.get("name", "")
            is_production = fund.get("is_production", False)
            name_upper = name.upper()
            if is_production:
                continue
            if name_upper.startswith("TEST_") or name_upper == "TEST" or name_upper == "TEST FUND":
                test_funds.append(fund)

        if not test_funds:
            duration_ms = int((time.time() - start_time) * 1000)
            message = "No test funds found"
            log_job_execution(job_id, True, message, duration_ms)
            mark_job_completed(job_id, target_date, None, [], duration_ms=duration_ms, message=message)
            logger.info("✅ Test funds cleanup: no test funds found")
            return

        deleted_funds = []
        errors = []

        for fund in test_funds:
            fund_id = fund.get("id")
            fund_name = fund.get("name")
            try:
                # fund_thesis_pillars -> fund_thesis
                thesis_result = client.supabase.table("fund_thesis").select("id").eq("fund", fund_name).execute()
                thesis_ids = [row["id"] for row in (thesis_result.data or []) if row.get("id")]
                if thesis_ids:
                    client.supabase.table("fund_thesis_pillars").delete().in_("thesis_id", thesis_ids).execute()
                client.supabase.table("fund_thesis").delete().eq("fund", fund_name).execute()

                # Dependent rows with FK to funds.name
                client.supabase.table("dividend_log").delete().eq("fund", fund_name).execute()
                client.supabase.table("portfolio_positions").delete().eq("fund", fund_name).execute()
                client.supabase.table("performance_metrics").delete().eq("fund", fund_name).execute()
                client.supabase.table("cash_balances").delete().eq("fund", fund_name).execute()
                client.supabase.table("trade_log").delete().eq("fund", fund_name).execute()

                # Rows that reference fund by name or ID
                client.supabase.table("fund_contributions").delete().eq("fund", fund_name).execute()
                if fund_id is not None:
                    client.supabase.table("fund_contributions").delete().eq("fund_id", fund_id).execute()

                client.supabase.table("user_funds").delete().eq("fund_name", fund_name).execute()
                if fund_id is not None:
                    client.supabase.table("user_funds").delete().eq("fund_id", fund_id).execute()

                # Delete the fund itself
                if fund_id is not None:
                    client.supabase.table("funds").delete().eq("id", fund_id).execute()
                else:
                    client.supabase.table("funds").delete().eq("name", fund_name).execute()

                deleted_funds.append(fund_name)
            except Exception as fund_error:
                errors.append(f"{fund_name}: {fund_error}")

        duration_ms = int((time.time() - start_time) * 1000)
        message = f"Deleted {len(deleted_funds)} test fund(s), {len(errors)} error(s)"
        if errors:
            logger.warning(f"Test funds cleanup errors: {errors[:5]}")
        log_job_execution(job_id, True, message, duration_ms)
        mark_job_completed(job_id, target_date, None, deleted_funds, duration_ms=duration_ms, message=message)
        logger.info(f"✅ Test funds cleanup job completed: {message}")

    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        message = f"Error: {str(e)}"
        log_job_execution(job_id, success=False, message=message, duration_ms=duration_ms)
        try:
            from utils.job_tracking import mark_job_failed
            mark_job_failed(job_id, target_date, None, message, duration_ms=duration_ms)
        except Exception:
            pass
        logger.error(f"❌ Test funds cleanup job failed: {e}", exc_info=True)


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

    # Heartbeat registration is owned by scheduler_core.start_scheduler().
    # Keep a single authoritative registration path to avoid drift.
    
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

        # Ticker Research: Twice daily (7:15 AM/PM PT)
        scheduler.add_job(
            ticker_research_job,
            trigger=CronTrigger(
                hour='7,19',
                minute=15,
                timezone='America/Los_Angeles'
            ),
            id='ticker_research_collect',
            name=f"{get_job_icon('ticker_research_collect')} Ticker Specific Research",
            replace_existing=True,
            max_instances=1,
            coalesce=True
        )
        logger.info("Registered job: ticker_research_collect (daily at 7:15 AM/PM PT)")

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

        # Opportunity Discovery: Daily at 9:30 PM PT
        scheduler.add_job(
            opportunity_discovery_job,
            trigger=CronTrigger(
                hour=21,
                minute=30,
                timezone='America/Los_Angeles'
            ),
            id='opportunity_discovery_scan',
            name=f"{get_job_icon('opportunity_discovery_scan')} Opportunity Discovery",
            replace_existing=True,
            max_instances=1,
            coalesce=True
        )
        logger.info("Registered job: opportunity_discovery_scan (daily at 9:30 PM PT)")

    # Alpha Research Job: Daily at 10:15 PM PT.
    # Runs INLINE (holds the global AI lock while extracting + summarizing, up to
    # its 40-min budget -> ~10:55 PM PT). Scheduled at 22:15 so its Ollama work
    # finishes before the queue-managed sector_meta (23:30) and ticker_meta
    # (23:45) enqueue their tasks into the AI worker pool, minimizing Ollama
    # throughput contention. opportunity_discovery (21:30, also inline) finishes
    # well before this starts.
    if AVAILABLE_JOBS.get('alpha_research', {}).get('enabled_by_default'):
        from scheduler.jobs_alpha import alpha_research_job
        scheduler.add_job(
            alpha_research_job,
            trigger=CronTrigger(
                hour=22,
                minute=15,
                timezone='America/Los_Angeles'
            ),
            id='alpha_research_collect',
            name=f"{get_job_icon('alpha_research')} Alpha Hunter",
            replace_existing=True,
            max_instances=1,
            coalesce=True
        )
        logger.info("Registered job: alpha_research_collect (daily at 10:15 PM PT)")

    if AVAILABLE_JOBS.get('sector_meta_analysis', {}).get('enabled_by_default', True):
        from scheduler.jobs_sector_meta_analysis import sector_meta_analysis_job

        sec_cfg = AVAILABLE_JOBS['sector_meta_analysis']
        sec_triggers = sec_cfg.get(
            'cron_triggers', [{'hour': 23, 'minute': 30, 'timezone': 'America/Los_Angeles'}]
        )
        sec_trig = sec_triggers[0]
        scheduler.add_job(
            sector_meta_analysis_job,
            trigger=CronTrigger(
                hour=sec_trig['hour'],
                minute=sec_trig['minute'],
                timezone=sec_trig.get('timezone', 'America/Los_Angeles'),
            ),
            id='sector_meta_analysis',
            name=f"{get_job_icon('sector_meta_analysis')} Sector Meta Analysis",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=3600,
        )
        logger.info(
            "Registered job: sector_meta_analysis (daily 11:30 PM PT; after alpha_research, before ticker_meta)"
        )

    # Symbol Article Scraper: Daily at 2:10 AM EST.
    # Staggered to reduce overlap with other 2:00 AM jobs.
    if AVAILABLE_JOBS.get('symbol_article_scraper', {}).get('enabled_by_default'):
        scheduler.add_job(
            symbol_article_scraper_job,
            trigger=CronTrigger(
                hour=2,
                minute=10,
                timezone='America/New_York'
            ),
            id='symbol_article_scraper',
            name=f"{get_job_icon('symbol_article_scraper')} Symbol Article Scraper",
            replace_existing=True,
            max_instances=1,
            coalesce=True
        )
        logger.info("Registered job: symbol_article_scraper (daily at 2:10 AM EST)")
    
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

    if AVAILABLE_JOBS.get('stance_outcomes', {}).get('enabled_by_default', True):
        stance_cfg = AVAILABLE_JOBS['stance_outcomes']
        stance_triggers = stance_cfg.get(
            'cron_triggers',
            [{'hour': 21, 'minute': 30, 'timezone': 'America/New_York'}],
        )
        stance_trigger = stance_triggers[0]
        scheduler.add_job(
            stance_outcomes_job,
            trigger=CronTrigger(
                hour=stance_trigger.get('hour', 21),
                minute=stance_trigger.get('minute', 30),
                timezone=stance_trigger.get('timezone', 'America/New_York'),
            ),
            id='stance_outcomes',
            name=f"{get_job_icon('stance_outcomes')} Stance Outcomes Scoring",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=3600,
        )
        logger.info("Registered job: stance_outcomes (nightly after benchmark refresh)")

    if AVAILABLE_JOBS.get('contradiction_drilldown', {}).get('enabled_by_default', True):
        cd_cfg = AVAILABLE_JOBS['contradiction_drilldown']
        cd_triggers = cd_cfg.get(
            'cron_triggers',
            [{'day_of_week': 'sun', 'hour': 20, 'minute': 0, 'timezone': 'America/New_York'}],
        )
        cd_trigger = cd_triggers[0]
        scheduler.add_job(
            contradiction_drilldown_job,
            trigger=CronTrigger(
                day_of_week=cd_trigger.get('day_of_week', 'sun'),
                hour=cd_trigger.get('hour', 20),
                minute=cd_trigger.get('minute', 0),
                timezone=cd_trigger.get('timezone', 'America/New_York'),
            ),
            id='contradiction_drilldown',
            name=f"{get_job_icon('contradiction_drilldown')} Contradiction Drill-Down",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        logger.info("Registered job: contradiction_drilldown (weekly)")

    if AVAILABLE_JOBS.get('dilution_watch', {}).get('enabled_by_default', True):
        dw_cfg = AVAILABLE_JOBS['dilution_watch']
        dw_triggers = dw_cfg.get(
            'cron_triggers',
            [{'hour': 6, 'minute': 30, 'timezone': 'America/New_York'}],
        )
        dw_trigger = dw_triggers[0]
        scheduler.add_job(
            dilution_watch_job,
            trigger=CronTrigger(
                hour=dw_trigger.get('hour', 6),
                minute=dw_trigger.get('minute', 30),
                timezone=dw_trigger.get('timezone', 'America/New_York'),
            ),
            id='dilution_watch',
            name=f"{get_job_icon('dilution_watch')} Dilution Watch",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        logger.info("Registered job: dilution_watch (daily advisory)")

    if AVAILABLE_JOBS.get('weekly_stance_retro', {}).get('enabled_by_default', True):
        wr_cfg = AVAILABLE_JOBS['weekly_stance_retro']
        wr_triggers = wr_cfg.get(
            'cron_triggers',
            [{'day_of_week': 'sun', 'hour': 17, 'minute': 0, 'timezone': 'America/New_York'}],
        )
        wr_trigger = wr_triggers[0]
        scheduler.add_job(
            weekly_stance_retro_job,
            trigger=CronTrigger(
                day_of_week=wr_trigger.get('day_of_week', 'sun'),
                hour=wr_trigger.get('hour', 17),
                minute=wr_trigger.get('minute', 0),
                timezone=wr_trigger.get('timezone', 'America/New_York'),
            ),
            id='weekly_stance_retro',
            name=f"{get_job_icon('weekly_stance_retro')} Weekly Stance Retro",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        logger.info("Registered job: weekly_stance_retro (weekly)")

    if AVAILABLE_JOBS.get('market_daily_brief', {}).get('enabled_by_default', True):
        scheduler.add_job(
            market_daily_brief_job,
            trigger=CronTrigger(
                day_of_week='mon-fri',
                hour=17,
                minute=45,
                timezone='America/New_York'
            ),
            id='market_daily_brief',
            name=f"{get_job_icon('market_daily_brief')} Market Daily Brief",
            replace_existing=True,
            max_instances=1,
            coalesce=True
        )
        logger.info("Registered job: market_daily_brief (weekdays 5:45 PM ET, after benchmark window)")
        # If 5:45 PM hits the global AI lock, jobs_dashboard_research schedules a one-shot retry (~60s).
        # Morning job: safety net after rest or if retries were unavailable.
        scheduler.add_job(
            market_daily_brief_job,
            trigger=CronTrigger(
                day_of_week='mon-fri',
                hour=8,
                minute=15,
                timezone='America/New_York'
            ),
            id='market_daily_brief_catchup',
            name=f"{get_job_icon('market_daily_brief')} Market Daily Brief (Catch-up)",
            replace_existing=True,
            max_instances=1,
            coalesce=True
        )
        logger.info("Registered job: market_daily_brief_catchup (weekdays 8:15 AM ET)")

    if AVAILABLE_JOBS.get('action_queue_ai_review', {}).get('enabled_by_default', True):
        scheduler.add_job(
            action_queue_ai_review_job,
            trigger=CronTrigger(
                day_of_week='mon-fri',
                hour=19,
                minute=0,
                timezone='America/New_York'
            ),
            id='action_queue_ai_review',
            name=f"{get_job_icon('action_queue_ai_review')} Action Queue AI Review",
            replace_existing=True,
            max_instances=1,
            coalesce=True
        )
        logger.info("Registered job: action_queue_ai_review (weekdays 7:00 PM ET)")

    if AVAILABLE_JOBS.get('ui_ai_summaries', {}).get('enabled_by_default', True):
        scheduler.add_job(
            ui_ai_summaries_job,
            trigger=CronTrigger(
                day_of_week='mon-fri',
                hour='10,12,14,16,18',
                minute=10,
                timezone='America/New_York',
            ),
            id='ui_ai_summaries',
            name=f"{get_job_icon('ui_ai_summaries')} UI AI summaries",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=3600,
        )
        scheduler.add_job(
            ui_ai_summaries_job,
            trigger=CronTrigger(
                day_of_week='sat-sun',
                hour=10,
                minute=10,
                timezone='America/New_York',
            ),
            id='ui_ai_summaries_weekend',
            name=f"{get_job_icon('ui_ai_summaries')} UI AI summaries (weekend)",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=3600,
        )
        logger.info(
            "Registered job: ui_ai_summaries (weekdays 10/12/14/16/18 ET + Sat/Sun 10:10 ET; lock retry; digest skip when unchanged)"
        )

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
    
    # Signal scan job - weekday pre-market + mid-morning (Pacific time)
    if AVAILABLE_JOBS['signal_scan']['enabled_by_default']:
        signal_triggers = AVAILABLE_JOBS['signal_scan'].get('cron_triggers', [])
        if signal_triggers:
            trigger_config = signal_triggers[0]
            scheduler.add_job(
                signal_scan_job,
                trigger=CronTrigger(
                    day_of_week=trigger_config.get('day_of_week', 'mon-fri'),
                    hour=trigger_config['hour'],
                    minute=trigger_config['minute'],
                    timezone=trigger_config.get('timezone', 'America/Los_Angeles')
                ),
                id='signal_scan',
                name=f"{get_job_icon('signal_scan')} Technical Signal Scan",
                replace_existing=True,
                max_instances=1,
                coalesce=True
            )
            logger.info("Registered job: signal_scan (weekdays 6:15 AM + 10:15 AM PT)")
        else:
            scheduler.add_job(
                signal_scan_job,
                trigger=IntervalTrigger(minutes=AVAILABLE_JOBS['signal_scan']['default_interval_minutes']),
                id='signal_scan',
                name=f"{get_job_icon('signal_scan')} Technical Signal Scan",
                replace_existing=True,
                max_instances=1,
                coalesce=True
            )
            logger.info("Registered job: signal_scan (every 240 minutes - 4 hours)")

    # Fundamentals Refresh - Daily at 3:30 AM ET (off-peak, after market close)
    if AVAILABLE_JOBS.get('fundamentals_refresh', {}).get('enabled_by_default', True):
        fund_triggers = AVAILABLE_JOBS['fundamentals_refresh'].get('cron_triggers', [])
        if fund_triggers:
            trigger_config = fund_triggers[0]
            scheduler.add_job(
                fundamentals_refresh_job,
                trigger=CronTrigger(
                    hour=trigger_config.get('hour', 3),
                    minute=trigger_config.get('minute', 30),
                    timezone=trigger_config.get('timezone', 'America/New_York')
                ),
                id='fundamentals_refresh',
                name=f"{get_job_icon('fundamentals_refresh')} Fundamentals Refresh",
                replace_existing=True,
                max_instances=1,
                coalesce=True
            )
            logger.info("Registered job: fundamentals_refresh (daily at 3:30 AM ET)")
        else:
            scheduler.add_job(
                fundamentals_refresh_job,
                trigger=IntervalTrigger(minutes=AVAILABLE_JOBS['fundamentals_refresh']['default_interval_minutes']),
                id='fundamentals_refresh',
                name=f"{get_job_icon('fundamentals_refresh')} Fundamentals Refresh",
                replace_existing=True,
                max_instances=1,
                coalesce=True
            )
            logger.info("Registered job: fundamentals_refresh (every 1440 minutes - daily)")

    # Article relevance validation job - daily at 4:00 AM ET
    if AVAILABLE_JOBS['article_relevance']['enabled_by_default']:
        ar_triggers = AVAILABLE_JOBS['article_relevance'].get('cron_triggers', [])
        if ar_triggers:
            ar_trigger = ar_triggers[0]
            scheduler.add_job(
                article_relevance_job,
                trigger=CronTrigger(
                    hour=ar_trigger.get('hour', 4),
                    minute=ar_trigger.get('minute', 0),
                    timezone=ar_trigger.get('timezone', 'America/New_York')
                ),
                id='article_relevance',
                name=f"{get_job_icon('article_relevance')} Article Relevance Validation",
                replace_existing=True,
                max_instances=1,
                coalesce=True
            )
            logger.info("Registered job: article_relevance (daily at 4:00 AM ET)")

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

    # Test funds cleanup job - daily at 3:30 AM EST (after social metrics cleanup)
    if AVAILABLE_JOBS.get('test_funds_cleanup', {}).get('enabled_by_default', True):
        scheduler.add_job(
            cleanup_test_funds_job,
            trigger=CronTrigger(
                hour=3,
                minute=30,
                timezone='America/New_York'
            ),
            id='test_funds_cleanup',
            name=f"{get_job_icon('test_funds_cleanup')} Test Funds Cleanup",
            replace_existing=True,
            max_instances=1,
            coalesce=True
        )
        logger.info("Registered job: test_funds_cleanup (daily at 3:30 AM EST)")
    
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
    
    # Scrape Congress Trades (Manual Only)
    # Always register this so it appears in UI, but it has no schedule
    # We use a dummy date trigger far in the future
    scheduler.add_job(
        scrape_congress_trades_job,
        trigger='date', 
        run_date=datetime(9999, 12, 31, tzinfo=timezone.utc), # Effectively never
        id='scrape_congress_trades',
        name=f"{get_job_icon('scrape_congress_trades')} Scrape Congress Trades (Manual)",
        replace_existing=True
    )
    scheduler.pause_job('scrape_congress_trades') # Ensure it's paused/manual only
    logger.info("Registered job: scrape_congress_trades (Manual only)")
    
    # Congress trades job - nightly batches (Pacific time)
    if AVAILABLE_JOBS['congress_trades']['enabled_by_default']:
        congress_triggers = AVAILABLE_JOBS['congress_trades'].get('cron_triggers', [])
        if congress_triggers:
            trigger_config = congress_triggers[0]
            scheduler.add_job(
                fetch_congress_trades_job,
                trigger=CronTrigger(
                    hour=trigger_config['hour'],
                    minute=trigger_config['minute'],
                    timezone=trigger_config.get('timezone', 'America/Los_Angeles')
                ),
                id='congress_trades_fetch',
                name=f"{get_job_icon('congress_trades')} Congress Trade Fetch",
                replace_existing=True,
                max_instances=1,
                coalesce=True
            )
            logger.info("Registered job: congress_trades_fetch (nightly at 7 PM, 9 PM, 11 PM, 1 AM PT)")
        else:
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
    
    # Analyze congress trades job - nightly after fetch batches (Pacific time)
    if AVAILABLE_JOBS['analyze_congress_trades']['enabled_by_default']:
        scheduler.add_job(
            analyze_congress_trades_job,
            trigger=CronTrigger(
                hour=2,
                minute=0,
                timezone='America/Los_Angeles'
            ),
            id='analyze_congress_trades',
            name=f"{get_job_icon('analyze_congress_trades')} Congress Trade Analysis",
            replace_existing=True,
            max_instances=1,
            coalesce=True
        )
        logger.info("Registered job: analyze_congress_trades (daily at 2:00 AM PT)")

    # Congress trade returns - daily (Eastern time, after market data settles)
    if AVAILABLE_JOBS.get('congress_trade_returns', {}).get('enabled_by_default', True):
        from scheduler.jobs_congress_returns import compute_congress_trade_returns_job
        scheduler.add_job(
            compute_congress_trade_returns_job,
            trigger=CronTrigger(
                hour=6,
                minute=0,
                timezone='America/New_York'
            ),
            id='congress_trade_returns',
            name=f"{get_job_icon('congress_trade_returns')} Congress Trade Returns",
            replace_existing=True,
            max_instances=1,
            coalesce=True
        )
        logger.info("Registered job: congress_trade_returns (daily at 6:00 AM ET)")

    # Congress closed positions - daily (Eastern time, after trade returns job)
    if AVAILABLE_JOBS.get('congress_positions', {}).get('enabled_by_default', True):
        from scheduler.jobs_congress_positions import compute_congress_positions_job
        scheduler.add_job(
            compute_congress_positions_job,
            trigger=CronTrigger(
                hour=6,
                minute=30,
                timezone='America/New_York'
            ),
            id='congress_positions',
            name=f"{get_job_icon('congress_positions')} Congress Closed Positions",
            replace_existing=True,
            max_instances=1,
            coalesce=True
        )
        logger.info("Registered job: congress_positions (daily at 6:30 AM ET)")

    # Insider trades job - nightly (Pacific time)
    if AVAILABLE_JOBS['insider_trades']['enabled_by_default']:
        insider_triggers = AVAILABLE_JOBS['insider_trades'].get('cron_triggers', [])
        if insider_triggers:
            trigger_config = insider_triggers[0]
            scheduler.add_job(
                fetch_insider_trades_job,
                trigger=CronTrigger(
                    hour=trigger_config['hour'],
                    minute=trigger_config['minute'],
                    timezone=trigger_config.get('timezone', 'America/Los_Angeles')
                ),
                id='insider_trades_fetch',
                name=f"{get_job_icon('insider_trades')} Insider Trade Fetch",
                replace_existing=True,
                max_instances=1,
                coalesce=True
            )
            logger.info("Registered job: insider_trades_fetch (daily at 8:00 PM PT)")
        else:
            scheduler.add_job(
                fetch_insider_trades_job,
                trigger=IntervalTrigger(minutes=AVAILABLE_JOBS['insider_trades']['default_interval_minutes']),
                id='insider_trades_fetch',
                name=f"{get_job_icon('insider_trades')} Insider Trade Fetch",
                replace_existing=True,
                max_instances=1,
                coalesce=True
            )
            logger.info("Registered job: insider_trades_fetch (every 6 hours - scrapes external source)")
    
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

    # ETF Watchtower - Daily at 6:00 PM PT
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
        logger.info("Registered job: etf_watchtower (daily at 6:00 PM PT)")
    
    # ETF Group Analysis - Daily at 7:15 PM PT (after ETF Watchtower)
    if AVAILABLE_JOBS.get('etf_group_analysis', {}).get('enabled_by_default', True):
        from scheduler.jobs_etf_analysis import etf_group_analysis_job
        
        config = AVAILABLE_JOBS['etf_group_analysis']
        triggers = config.get('cron_triggers', [{'hour': 21, 'minute': 0, 'timezone': 'America/New_York'}])
        trigger_config = triggers[0]
        
        scheduler.add_job(
            etf_group_analysis_job,
            trigger=CronTrigger(
                hour=trigger_config['hour'],
                minute=trigger_config['minute'],
                timezone=trigger_config.get('timezone', 'America/New_York')
            ),
            id='etf_group_analysis',
            name=f"{get_job_icon('etf_group_analysis')} ETF Group AI Analysis",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=3600  # 1 hour grace period
        )
        logger.info("Registered job: etf_group_analysis (daily at 7:15 PM PT)")
    
    # Ticker Analysis - Daily at 9:00 PM PT (2-hour max, resumable)
    if AVAILABLE_JOBS.get('ticker_analysis', {}).get('enabled_by_default', True):
        from scheduler.jobs_ticker_analysis import ticker_analysis_job
        
        config = AVAILABLE_JOBS['ticker_analysis']
        triggers = config.get('cron_triggers', [{'hour': 22, 'minute': 0, 'timezone': 'America/New_York'}])
        trigger_config = triggers[0]
        
        scheduler.add_job(
            ticker_analysis_job,
            trigger=CronTrigger(
                hour=trigger_config['hour'],
                minute=trigger_config['minute'],
                timezone=trigger_config.get('timezone', 'America/New_York')
            ),
            id='ticker_analysis',
            name=f"{get_job_icon('ticker_analysis')} Ticker AI Analysis",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=3600  # 1 hour grace period
        )
        logger.info("Registered job: ticker_analysis (daily at 9:00 PM PT, 2-hour max)")
    
    if AVAILABLE_JOBS.get('ticker_meta_analysis', {}).get('enabled_by_default', True):
        from scheduler.jobs_ticker_meta_analysis import ticker_meta_analysis_job

        meta_cfg = AVAILABLE_JOBS['ticker_meta_analysis']
        meta_triggers = meta_cfg.get(
            'cron_triggers', [{'hour': 22, 'minute': 30, 'timezone': 'America/Los_Angeles'}]
        )
        meta_trig = meta_triggers[0]
        scheduler.add_job(
            ticker_meta_analysis_job,
            trigger=CronTrigger(
                hour=meta_trig['hour'],
                minute=meta_trig['minute'],
                timezone=meta_trig.get('timezone', 'America/Los_Angeles'),
            ),
            id='ticker_meta_analysis',
            name=f"{get_job_icon('ticker_meta_analysis')} Ticker Meta Analysis",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=3600,
        )
        logger.info("Registered job: ticker_meta_analysis (daily after ticker analysis)")

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

    # Fund Thesis Update - Weekly on Sunday at 8 PM PT
    if AVAILABLE_JOBS.get('thesis_update', {}).get('enabled_by_default', True):
        config = AVAILABLE_JOBS['thesis_update']
        triggers = config.get('cron_triggers', [{'day_of_week': 'sun', 'hour': 20, 'minute': 0, 'timezone': 'America/Los_Angeles'}])
        trigger_config = triggers[0]

        scheduler.add_job(
            thesis_update_job,
            trigger=CronTrigger(
                day_of_week=trigger_config.get('day_of_week', 'sun'),
                hour=trigger_config['hour'],
                minute=trigger_config['minute'],
                timezone=trigger_config.get('timezone', 'America/Los_Angeles')
            ),
            id='thesis_update',
            name=f"{get_job_icon('thesis_update')} Fund Thesis Update",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=3600  # 1 hour grace period
        )
        logger.info("Registered job: thesis_update (weekly on Sunday at 8:00 PM PT)")

    # TFSA Rebalance Recommendation - weekly advisory run
    if AVAILABLE_JOBS.get('rebalance_recommendation_tfsa', {}).get('enabled_by_default', True):
        config = AVAILABLE_JOBS['rebalance_recommendation_tfsa']
        triggers = config.get('cron_triggers', [{'day_of_week': 'sun', 'hour': 18, 'minute': 0, 'timezone': 'America/Los_Angeles'}])
        trigger_config = triggers[0]

        scheduler.add_job(
            rebalance_recommendation_tfsa_job,
            trigger=CronTrigger(
                day_of_week=trigger_config.get('day_of_week', 'sun'),
                hour=trigger_config['hour'],
                minute=trigger_config['minute'],
                timezone=trigger_config.get('timezone', 'America/Los_Angeles')
            ),
            id='rebalance_recommendation_tfsa',
            name=f"{get_job_icon('rebalance_recommendation_tfsa')} TFSA Rebalance Review",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=3600
        )
        logger.info("Registered job: rebalance_recommendation_tfsa (weekly Sunday 6:00 PM PT)")

    # RRSP Rebalance Recommendation - monthly advisory run
    if AVAILABLE_JOBS.get('rebalance_recommendation_rrsp', {}).get('enabled_by_default', True):
        config = AVAILABLE_JOBS['rebalance_recommendation_rrsp']
        triggers = config.get('cron_triggers', [{'day': 1, 'hour': 18, 'minute': 30, 'timezone': 'America/Los_Angeles'}])
        trigger_config = triggers[0]

        scheduler.add_job(
            rebalance_recommendation_rrsp_job,
            trigger=CronTrigger(
                day=trigger_config.get('day', 1),
                hour=trigger_config['hour'],
                minute=trigger_config['minute'],
                timezone=trigger_config.get('timezone', 'America/Los_Angeles')
            ),
            id='rebalance_recommendation_rrsp',
            name=f"{get_job_icon('rebalance_recommendation_rrsp')} RRSP Rebalance Review",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=3600
        )
        logger.info("Registered job: rebalance_recommendation_rrsp (monthly on day 1 at 6:30 PM PT)")

    # Newsletter AI Processing - every 30 minutes
    if AVAILABLE_JOBS.get('newsletter_ai_processing', {}).get('enabled_by_default', True):
        scheduler.add_job(
            newsletter_ai_processing_job,
            trigger=IntervalTrigger(
                minutes=AVAILABLE_JOBS['newsletter_ai_processing']['default_interval_minutes']
            ),
            id='newsletter_ai_processing',
            name=f"{get_job_icon('newsletter_ai_processing')} Newsletter AI Processing",
            replace_existing=True,
            max_instances=1,
            coalesce=True
        )
        logger.info("Registered job: newsletter_ai_processing (every 30 minutes safety net)")

    # Daily Critical Data Backup -- 12:00 UTC. Captures trade_log per fund AND
    # the irreplaceable app/config tables (user_profiles, user_funds, funds,
    # fund_thesis, fund_thesis_pillars, fund_contributions, system_settings,
    # watched_tickers_v2, ai_analysis_skip_list, contributors, contributor_access)
    # to a host volume AND a private Supabase Storage bucket. See
    # scheduler/jobs_daily_backup.py for scope and the explicit non-goals.
    if AVAILABLE_JOBS.get('daily_critical_data_backup', {}).get('enabled_by_default', True):
        dcb_cfg = AVAILABLE_JOBS['daily_critical_data_backup']
        dcb_triggers = dcb_cfg.get(
            'cron_triggers', [{'hour': 12, 'minute': 0, 'timezone': 'UTC'}]
        )
        dcb_trigger = dcb_triggers[0]
        scheduler.add_job(
            daily_critical_data_backup_job,
            trigger=CronTrigger(
                hour=dcb_trigger.get('hour', 12),
                minute=dcb_trigger.get('minute', 0),
                timezone=dcb_trigger.get('timezone', 'UTC'),
            ),
            id='daily_critical_data_backup',
            name=f"{get_job_icon('daily_critical_data_backup')} Daily Critical Data Backup",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=60 * 60 * 6,  # 6h grace -- run on next start if missed
        )
        logger.info("Registered job: daily_critical_data_backup (daily at 12:00 UTC)")

    if AVAILABLE_JOBS.get("outbound_portfolio_digest", {}).get("enabled_by_default", False):
        ot = AVAILABLE_JOBS["outbound_portfolio_digest"].get(
            "cron_triggers", [{"hour": 12, "minute": 0, "timezone": "America/New_York"}]
        )[0]
        scheduler.add_job(
            outbound_portfolio_digest_job,
            trigger=CronTrigger(
                hour=ot.get("hour", 12),
                minute=ot.get("minute", 0),
                timezone=ot.get("timezone", "America/New_York"),
            ),
            id="outbound_portfolio_digest",
            name=f"{get_job_icon('outbound_portfolio_digest')} Outbound portfolio digest",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=3600,
        )
        logger.info("Registered job: outbound_portfolio_digest (scheduled send)")
