"""
Research Jobs
=============

Jobs for fetching and storing market research articles from various sources.
"""

import logging
import time
from datetime import datetime, timezone
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
from scheduler.jobs_common import calculate_relevance_score

# Initialize logger
logger = logging.getLogger(__name__)


def _extract_and_validate_tickers(
    summary_data: dict,
    title: str,
    article_text: str,
) -> list[str]:
    """Thin wrapper around the shared extract_and_validate_tickers helper."""
    from ticker_validator import extract_and_validate_tickers
    return extract_and_validate_tickers(summary_data, title, article_text)


def market_research_job() -> None:
    """Fetch and store general market news articles.
    
    This job:
    1. Fetches general market news using SearXNG
    2. Extracts article content using trafilatura
    3. Generates AI summaries using Ollama
    4. Saves articles to the database
    
    Robots.txt enforcement: Controlled by ENABLE_ROBOTS_TXT_CHECKS environment variable.
    When enabled, checks robots.txt before accessing article URLs from search results.
    """
    job_id = 'market_research'
    start_time = time.time()
    target_date = datetime.now(timezone.utc).date()
    job_started = False
    job_finalized = False
    from utils.job_tracking import log_job_step

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

    # Global AI lock (SearXNG + Ollama workload)
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

        log_job_step(job_id, "init", "Starting market research job")
        logger.info("Starting market research job...")
        
        # Mark job as started in database
        mark_job_started('market_research', target_date)
        job_started = True
        
        # Import dependencies (lazy imports to avoid circular dependencies)
        try:
            from searxng_client import get_searxng_client, check_searxng_health
            from ollama_client import get_ollama_client
            from research_repository import ResearchRepository
        except ImportError as e:
            message = f"Missing dependency: {e}"
            logger.error(f"❌ {message}")
            _finalize_failure(message)
            return

        # Check if SearXNG is available
        log_job_step(job_id, "searxng_check", "Checking SearXNG health...")
        if not check_searxng_health():
            message = "SearXNG is not available - skipping research job"
            log_job_step(job_id, "searxng_check", message, status="skipped")
            logger.info(f"ℹ️ {message}")
            # Intentional skip (usually test/config), not an execution failure.
            # Matches alpha_research / opportunity_discovery / ticker_research.
            _finalize_success(message)
            return
        log_job_step(job_id, "searxng_check", "SearXNG is healthy", status="success")
        
        # Get clients
        searxng_client = get_searxng_client()
        ollama_client = get_ollama_client()
        
        if not searxng_client:
            message = "SearXNG client not initialized"
            logger.error(f"❌ {message}")
            _finalize_failure(message)
            return
        
        # Initialize research repository
        research_repo = ResearchRepository()
        
        # Load domain blacklist
        from settings import get_research_domain_blacklist
        blacklist = get_research_domain_blacklist()
        if blacklist:
            logger.info(f"Loaded domain blacklist: {blacklist}")
        else:
            logger.info("No domains blacklisted")
        
        # specific, high-quality queries to avoid junk (astrology, etc.)
        queries = [
            "microcap stock analysis",
            "small cap undervalued stocks",
            "biotech stock catalysts upcoming",
            "penny stock signs of breakout",
            "stock market spinoffs 2025",
            "insider buying small cap stocks",
            "merger arbitrage opportunities small cap",
            # ETF / Index Rotation Tracking
            "stock added to Russell 2000 index",
            "S&P SmallCap 600 constituent change",
            "ETF rebalancing announcement"
        ]
        
        # Select query based on hour to rotate coverage
        query_index = datetime.now().hour % len(queries)
        base_query = queries[query_index]
        
        # Add negative keywords to explicitly block known junk
        # "astrology", "horoscope", "zodiac" -> The user specifically mentioned these
        negative_keywords = "-astrology -horoscope -zodiac -lottery"
        final_query = f"{base_query} {negative_keywords}"
        
        log_job_step(job_id, "search", f"Searching: '{base_query}'")
        logger.info(f"Fetching market news with query: '{final_query}'")
        search_results = searxng_client.search_news(
            query=final_query,
            max_results=10
        )
        
        if not search_results or not search_results.get('results'):
            message = "No search results found"
            log_job_step(job_id, "search", message, status="skipped")
            logger.info(f"ℹ️ {message}")
            _finalize_success(message)
            return

        log_job_step(job_id, "search", f"Found {len(search_results.get('results', []))} results", status="success")

        articles_processed = 0
        articles_saved = 0
        articles_skipped = 0
        articles_blacklisted = 0
        articles_irrelevant = 0
        
        # Overall job timeout: 50 minutes (leave buffer before next run)
        MAX_JOB_DURATION = 50 * 60  # 50 minutes in seconds
        # Per-article timeout: 5 minutes max per article
        MAX_ARTICLE_DURATION = 5 * 60  # 5 minutes in seconds
        
        total_results = len(search_results.get('results', []))
        logger.info(f"📊 Processing {total_results} search results (max {MAX_ARTICLE_DURATION}s per article, {MAX_JOB_DURATION}s total)")
        
        from scheduler.article_pipeline import (
            get_research_article_worker_count,
            run_article_pipeline_parallel,
        )
        from scheduler.market_research_workers import MarketResearchCtx, process_market_research_pair

        ctx_mr = MarketResearchCtx(
            job_id=job_id,
            job_start_time=start_time,
            research_repo=research_repo,
            ollama_client=ollama_client,
            blacklist=blacklist,
            total_results=total_results,
            max_job_duration=MAX_JOB_DURATION,
            max_article_duration=MAX_ARTICLE_DURATION,
        )
        pairs = list(enumerate(search_results["results"], 1))
        workers_mr = get_research_article_worker_count()
        agg_mr = run_article_pipeline_parallel(
            lambda p, c=ctx_mr: process_market_research_pair(c, p),
            pairs,
            max_workers=workers_mr,
            job_start_time=start_time,
            max_job_duration_sec=MAX_JOB_DURATION,
        )
        articles_processed = agg_mr.processed
        articles_saved = agg_mr.saved
        articles_skipped = agg_mr.skipped
        articles_blacklisted = agg_mr.blacklisted
        articles_irrelevant = agg_mr.irrelevant

        duration_ms = int((time.time() - start_time) * 1000)
        duration_min = duration_ms / 60000
        message = (
            f"Processed {articles_processed} articles: {articles_saved} saved, "
            f"{articles_skipped} skipped, {articles_blacklisted} blacklisted, "
            f"{articles_irrelevant} non-market"
        )
        timed_out = (time.time() - start_time) >= MAX_JOB_DURATION and articles_processed < total_results
        if timed_out:
            message = (
                f"{message}. Timed out before full batch completion "
                f"({articles_processed}/{total_results} processed)"
            )
        log_job_step(job_id, "complete", message, status="success")
        if timed_out and articles_saved == 0:
            _finalize_failure(message)
            logger.warning(f"⚠️ Market research timed out with no saved articles in {duration_min:.1f} minutes")
        else:
            _finalize_success(message)
            logger.info(f"✅ {message} in {duration_min:.1f} minutes")

    except Exception as e:
        message = f"Error: {str(e)}"
        log_job_step(job_id, "fatal", message, status="failed")
        logger.error(f"❌ Market research job failed: {e}", exc_info=True)
        _finalize_failure(message)
    finally:
        if job_started and not job_finalized:
            _finalize_failure("Job exited without terminal status")


def rss_feed_ingest_job() -> None:
    """Ingest articles from validated RSS feeds (Push strategy).
    
    This job:
    1. Fetches all enabled RSS feeds from database
    2. Parses each feed for new articles
    3. Applies junk filtering before AI processing
    4. Saves high-quality articles to research database
    
    Robots.txt enforcement: Controlled by ENABLE_ROBOTS_TXT_CHECKS environment variable.
    When enabled, checks robots.txt before fetching RSS feeds and article URLs.
    """
    job_id = 'rss_feed_ingest'
    start_time = time.time()
    target_date = datetime.now(timezone.utc).date()
   
    try:
        # Import job tracking
        from utils.job_tracking import mark_job_started, mark_job_completed, mark_job_failed
        
        logger.info("Starting RSS feed ingestion job...")
        
        # Mark job as started in database
        mark_job_started('rss_feed_ingest', target_date)
        
        # Import dependencies
        try:
            from rss_utils import get_rss_client
            from ollama_client import get_ollama_client
            from research_repository import ResearchRepository
            from postgres_client import PostgresClient
        except ImportError as e:
            duration_ms = int((time.time() - start_time) * 1000)
            message = f"Missing dependency: {e}"
            log_job_execution(job_id, success=False, message=message, duration_ms=duration_ms)
            logger.error(f"❌ {message}")
            try:
                mark_job_failed('rss_feed_ingest', target_date, None, message, duration_ms=duration_ms)
            except Exception:
                pass
            return
        
        # Get clients
        rss_client = get_rss_client()
        ollama_client = get_ollama_client()
        research_repo = ResearchRepository()
        postgres_client = PostgresClient()
        
        # Fetch enabled RSS feeds from database
        try:
            feeds_result = postgres_client.execute_query(
                "SELECT id, name, url FROM rss_feeds WHERE enabled = true"
            )
        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            message = f"Error fetching RSS feeds from database: {e}"
            log_job_execution(job_id, success=False, message=message, duration_ms=duration_ms)
            logger.error(f"❌ {message}")
            try:
                mark_job_failed('rss_feed_ingest', target_date, None, message, duration_ms=duration_ms)
            except Exception:
                pass
            return
        
        if not feeds_result:
            duration_ms = int((time.time() - start_time) * 1000)
            message = "No enabled RSS feeds found"
            log_job_execution(job_id, success=True, message=message, duration_ms=duration_ms)
            try:
                mark_job_completed('rss_feed_ingest', target_date, None, [], duration_ms=duration_ms, message=message)
            except Exception:
                pass
            logger.info(f"ℹ️ {message}")
            return
        
        logger.info(f"Found {len(feeds_result)} enabled RSS feeds")
        
        total_articles_processed = 0
        total_articles_saved = 0
        total_articles_skipped = 0
        total_articles_irrelevant = 0
        total_junk_filtered = 0  # NEW: Track junk filtering
        feeds_processed = 0
        feeds_failed = 0
        
        # Get owned tickers for relevance scoring
        from supabase_client import SupabaseClient
        client = SupabaseClient(use_service_role=True)
        funds_result = client.supabase.table("funds").select("name").eq("is_production", True).execute()
        
        owned_tickers = set()
        if funds_result.data:
            prod_funds = [f['name'] for f in funds_result.data]
            positions_result = client.supabase.table("latest_positions").select("ticker").in_("fund", prod_funds).execute()
            if positions_result.data:
                owned_tickers = set(pos['ticker'] for pos in positions_result.data)
        
        # Process each feed
        for feed in feeds_result:
            feed_id = feed['id']
            feed_name = feed['name']
            feed_url = feed['url']
            
            try:
                logger.info(f"📡 Fetching feed: {feed_name}")
                
                # Check robots.txt compliance for feed URL (if enabled)
                try:
                    from robots_utils import check_url_allowed
                    if not check_url_allowed(feed_url):
                        logger.info(f"  Skipping feed disallowed by robots.txt: {feed_url[:60]}...")
                        feeds_failed += 1
                        continue
                except ImportError:
                    # robots_utils not available, skip check
                    pass
                
                # Fetch and parse RSS feed
                feed_data = rss_client.fetch_feed(feed_url)
                
                if not feed_data or not feed_data.get('items'):
                    logger.warning(f"No items found in feed: {feed_name}")
                    feeds_failed += 1
                    continue
                
                items = feed_data['items']
                junk_filtered = feed_data.get('junk_filtered', 0)
                total_junk_filtered += junk_filtered
                
                logger.info(f"  Found {len(items)} items (filtered {junk_filtered} junk articles)")
                
                from scheduler.article_pipeline import (
                    get_research_article_worker_count,
                    run_article_pipeline_parallel,
                )
                from scheduler.rss_feed_workers import RssFeedItemCtx, process_rss_feed_item

                workers_rss = get_research_article_worker_count()
                ctx_rss = RssFeedItemCtx(
                    research_repo=research_repo,
                    ollama_client=ollama_client,
                    owned_tickers=owned_tickers,
                    feed_name=feed_name,
                    sleep_after_article_sec=0.0 if workers_rss > 1 else 0.5,
                )
                agg_rss = run_article_pipeline_parallel(
                    lambda it, c=ctx_rss: process_rss_feed_item(c, it),
                    items,
                    max_workers=workers_rss,
                    job_start_time=start_time,
                    max_job_duration_sec=50 * 60,
                )
                total_articles_processed += agg_rss.processed
                total_articles_saved += agg_rss.saved
                total_articles_skipped += agg_rss.skipped
                total_articles_irrelevant += agg_rss.irrelevant

                # Update feed's last_fetched_at timestamp
                try:
                    postgres_client.execute_update(
                        "UPDATE rss_feeds SET last_fetched_at = NOW() WHERE id = %s",
                        (feed_id,)
                    )
                except Exception as e:
                    logger.warning(f"Failed to update last_fetched_at for {feed_name}: {e}")
                
                feeds_processed += 1
                time.sleep(2)  # Delay between feeds
                
            except Exception as e:
                logger.error(f"Error processing feed '{feed_name}': {e}")
                feeds_failed += 1
                continue
        
        duration_ms = int((time.time() - start_time) * 1000)
        message = (
            f"Processed {feeds_processed} feeds: {total_articles_saved} saved, "
            f"{total_articles_skipped} skipped, {total_articles_irrelevant} non-market, "
            f"{total_junk_filtered} junk filtered"
        )
        log_job_execution(job_id, success=True, message=message, duration_ms=duration_ms)
        mark_job_completed('rss_feed_ingest', target_date, None, [], duration_ms=duration_ms, message=message)
        logger.info(f"✅ {message}")
        
    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        message = f"Error: {str(e)}"
        log_job_execution(job_id, success=False, message=message, duration_ms=duration_ms)
        try:
            mark_job_failed('rss_feed_ingest', target_date, None, message, duration_ms=duration_ms)
        except Exception:
            pass
        logger.error(f"❌ RSS feed ingestion job failed: {e}", exc_info=True)



def ticker_research_job() -> None:
    """Fetch news for companies held in the portfolio.
    
    This job:
    1. Identifies all tickers held in production funds
    2. Searches for news specific to each ticker + company name
    3. Saves relevant articles to the database
    
    Robots.txt enforcement: Controlled by ENABLE_ROBOTS_TXT_CHECKS environment variable.
    When enabled, checks robots.txt before accessing article URLs from search results.
    """
    job_id = 'ticker_research'
    start_time = time.time()
    target_date = datetime.now(timezone.utc).date()

    # Global AI lock (SearXNG + Ollama workload)
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
        
        logger.info("Starting ticker research job...")
        
        # Mark job as started in database
        mark_job_started('ticker_research', target_date)
        
        # Import dependencies (lazy imports)
        try:
            from searxng_client import get_searxng_client, check_searxng_health
            from ollama_client import get_ollama_client
            from research_repository import ResearchRepository
            from supabase_client import SupabaseClient
        except ImportError as e:
            duration_ms = int((time.time() - start_time) * 1000)
            message = f"Missing dependency: {e}"
            log_job_execution(job_id, success=False, message=message, duration_ms=duration_ms)
            logger.error(f"❌ {message}")
            mark_job_failed('ticker_research', target_date, None, message, duration_ms=duration_ms)
            return

        # Check SearXNG health
        if not check_searxng_health():
            duration_ms = int((time.time() - start_time) * 1000)
            message = "SearXNG is not available - skipping ticker research"
            log_job_execution(job_id, success=True, message=message, duration_ms=duration_ms)
            mark_job_completed('ticker_research', target_date, None, [], duration_ms=duration_ms, message=message)
            logger.info(f"ℹ️ {message}")
            return
            
        searxng_client = get_searxng_client()
        ollama_client = get_ollama_client()
        research_repo = ResearchRepository()
        
        if not searxng_client:
            duration_ms = int((time.time() - start_time) * 1000)
            message = "SearXNG client not initialized"
            log_job_execution(job_id, success=False, message=message, duration_ms=duration_ms)
            logger.error(f"❌ {message}")
            mark_job_failed('ticker_research', target_date, None, message, duration_ms=duration_ms)
            return

        # Load domain blacklist
        from settings import get_research_domain_blacklist
        blacklist = get_research_domain_blacklist()

        # Connect to Supabase
        client = SupabaseClient(use_service_role=True)
        
        # 1. Get production funds
        funds_result = client.supabase.table("funds")\
            .select("name")\
            .eq("is_production", True)\
            .execute()
            
        if not funds_result.data:
            duration_ms = int((time.time() - start_time) * 1000)
            message = "No production funds found"
            log_job_execution(job_id, success=True, message=message, duration_ms=duration_ms)
            mark_job_completed('ticker_research', target_date, None, [], duration_ms=duration_ms, message=message)
            logger.info(f"ℹ️ {message}")
            return
            
        prod_funds = [f['name'] for f in funds_result.data]
        logger.info(f"Scanning holdings for funds: {prod_funds}")
        
        # 2. Get distinct tickers and company names from portfolio_positions for these funds
        # We look at the most recent snapshot for each fund
        
        # Efficient query to get distinct ticker/company pairs from current positions
        # Using the latest_positions view is easiest as it aggregates valid positions
        positions_result = client.supabase.table("latest_positions")\
            .select("ticker, company, fund")\
            .in_("fund", prod_funds)\
            .execute()
            
        if not positions_result.data:
            duration_ms = int((time.time() - start_time) * 1000)
            message = "No active positions found in production funds"
            log_job_execution(job_id, success=True, message=message, duration_ms=duration_ms)
            mark_job_completed('ticker_research', target_date, None, [], duration_ms=duration_ms, message=message)
            logger.info(f"ℹ️ {message}")
            return
        
        # Deduplicate tickers (same ticker might be in multiple funds)
        # Store as dict: ticker -> company_name
        targets = {}
        for pos in positions_result.data:
            ticker = pos['ticker']
            company = pos.get('company')
            
            # Prefer longer company name if multiple exist (more descriptive)
            if ticker not in targets:
                targets[ticker] = company
            elif company and (not targets[ticker] or len(company) > len(targets[ticker])):
                targets[ticker] = company
        
        # Separate ETFs from regular tickers
        # ETFs will be researched by sector instead
        etf_tickers = {}
        regular_tickers = {}
        
        for ticker, company in targets.items():
            # Check if ticker or company name contains "ETF" (case-insensitive)
            is_etf = (
                'etf' in ticker.lower() or 
                (company and 'etf' in company.lower())
            )
            
            if is_etf:
                etf_tickers[ticker] = company
            else:
                regular_tickers[ticker] = company
        
        # Get sectors for ETF tickers from securities table
        etf_sectors = set()
        if etf_tickers:
            etf_ticker_list = list(etf_tickers.keys())
            # Query securities table for sector information
            # Need to query in batches if there are many ETFs
            batch_size = 50
            for i in range(0, len(etf_ticker_list), batch_size):
                batch = etf_ticker_list[i:i + batch_size]
                try:
                    securities_result = client.supabase.table("securities")\
                        .select("ticker, sector")\
                        .in_("ticker", batch)\
                        .execute()
                    
                    for sec in securities_result.data:
                        sector = sec.get('sector')
                        if sector and sector.strip():
                            etf_sectors.add(sector.strip())
                except Exception as e:
                    logger.warning(f"Error fetching sectors for ETFs: {e}")
        
        if etf_tickers:
            logger.info(f"Found {len(etf_tickers)} ETF tickers (skipping direct research): {list(etf_tickers.keys())}")
            if etf_sectors:
                logger.info(f"Will research {len(etf_sectors)} sectors instead: {sorted(etf_sectors)}")
            else:
                logger.warning("No sector information found for ETFs - they will be skipped")
        
        logger.info(f"Found {len(regular_tickers)} regular tickers to research: {list(regular_tickers.keys())}")
        
        # Create owned_tickers set for relevance scoring (includes both ETFs and regular tickers)
        owned_tickers = set(targets.keys())
        
        articles_saved = 0
        articles_skipped = 0
        articles_failed = 0
        tickers_processed = 0
        sectors_researched = 0
        articles_irrelevant = 0

        # Safety timeouts (avoid runaway jobs)
        MAX_JOB_DURATION = 60 * 60  # 60 minutes total
        MAX_ITEM_DURATION = 4 * 60  # 4 minutes per sector/ticker
        
        # 3. Research sectors for ETFs first
        for sector in sorted(etf_sectors):
            # Check overall job timeout
            elapsed = time.time() - start_time
            if elapsed > MAX_JOB_DURATION:
                logger.warning(f"⏱️  Job timeout reached ({elapsed/60:.1f}m). Stopping ticker research")
                break

            item_start = time.time()
            try:
                query = f"{sector} sector news investment"
                logger.info(f"🔎 Researching sector for ETFs: '{query}'")
                
                search_results = searxng_client.search_news(query=query, max_results=5)
                
                if not search_results or not search_results.get('results'):
                    logger.debug(f"No results for sector: {sector}")
                    continue

                from scheduler.article_pipeline import (
                    get_research_article_worker_count,
                    run_article_pipeline_parallel,
                )
                from scheduler.ticker_research_workers import (
                    SectorArticleCtx,
                    process_sector_search_result,
                )

                workers_sec = get_research_article_worker_count()
                item_start_sec = time.time()
                deadline_sec = item_start_sec + MAX_ITEM_DURATION
                ctx_sec = SectorArticleCtx(
                    research_repo=research_repo,
                    ollama_client=ollama_client,
                    blacklist=blacklist,
                    sector=sector,
                    result_deadline=deadline_sec,
                    sleep_after_article_sec=0.0 if workers_sec > 1 else 1.0,
                )
                agg_sec = run_article_pipeline_parallel(
                    lambda r, c=ctx_sec: process_sector_search_result(c, r),
                    search_results["results"],
                    max_workers=workers_sec,
                    job_start_time=start_time,
                    max_job_duration_sec=MAX_JOB_DURATION,
                )
                articles_saved += agg_sec.saved
                articles_skipped += agg_sec.skipped
                articles_irrelevant += agg_sec.irrelevant
                articles_failed += agg_sec.failed

                sectors_researched += 1
                
                # Delay between sectors
                time.sleep(3)
                
            except Exception as e:
                logger.error(f"Error researching sector {sector}: {e}")
        
        # 4. Iterate and search for each regular (non-ETF) ticker
        for ticker, company in regular_tickers.items():
            # Check overall job timeout
            elapsed = time.time() - start_time
            if elapsed > MAX_JOB_DURATION:
                logger.warning(f"⏱️  Job timeout reached ({elapsed/60:.1f}m). Stopping ticker research")
                break

            item_start = time.time()
            try:
                # Construct search query
                # Use company name if available for better results, otherwise just ticker + "stock"
                if company and company.lower() != 'none':
                    query = f"{ticker} {company} stock news"
                else:
                    query = f"{ticker} stock news"
                
                logger.info(f"🔎 Searching for: '{query}'")
                
                # Fetch search results
                # Limit to 5 per ticker to avoid overwhelming the system/logs
                search_results = searxng_client.search_news(query=query, max_results=5)
                
                if not search_results or not search_results.get('results'):
                    logger.debug(f"No results for {ticker}")
                    continue

                from scheduler.article_pipeline import (
                    get_research_article_worker_count,
                    run_article_pipeline_parallel,
                )
                from scheduler.ticker_research_workers import (
                    TickerArticleCtx,
                    process_ticker_search_result,
                )

                workers_tk = get_research_article_worker_count()
                item_start_sec = time.time()
                deadline_sec = item_start_sec + MAX_ITEM_DURATION
                ctx_tk = TickerArticleCtx(
                    research_repo=research_repo,
                    ollama_client=ollama_client,
                    blacklist=blacklist,
                    ticker=ticker,
                    company=company or "",
                    owned_tickers=owned_tickers,
                    result_deadline=deadline_sec,
                    sleep_after_article_sec=0.0 if workers_tk > 1 else 1.0,
                )
                agg_tk = run_article_pipeline_parallel(
                    lambda r, c=ctx_tk: process_ticker_search_result(c, r),
                    search_results["results"],
                    max_workers=workers_tk,
                    job_start_time=start_time,
                    max_job_duration_sec=MAX_JOB_DURATION,
                )
                articles_saved += agg_tk.saved
                articles_skipped += agg_tk.skipped
                articles_irrelevant += agg_tk.irrelevant
                articles_failed += agg_tk.failed

                tickers_processed += 1
                
                # Delay between tickers to avoid rate limiting SearXNG
                time.sleep(3)
                
            except Exception as e:
                logger.error(f"Error searching for {ticker}: {e}")
        
        duration_ms = int((time.time() - start_time) * 1000)
        message_parts = [f"Processed {tickers_processed} tickers"]
        if sectors_researched > 0:
            message_parts.append(f"{sectors_researched} sectors (for ETFs)")
        message_parts.append(f"Saved {articles_saved} new articles")
        if articles_skipped > 0:
            message_parts.append(f"Skipped {articles_skipped} duplicate/in-flight articles")
        if articles_irrelevant > 0:
            message_parts.append(f"Skipped {articles_irrelevant} non-market articles")
        message = ". ".join(message_parts) + "."
        log_job_execution(job_id, success=True, message=message, duration_ms=duration_ms)
        mark_job_completed('ticker_research', target_date, None, [], duration_ms=duration_ms, message=message)
        logger.info(f"✅ {message}")
        
    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        message = f"Error: {str(e)}"
        log_job_execution(job_id, success=False, message=message, duration_ms=duration_ms)
        try:
            mark_job_failed('ticker_research', target_date, None, message, duration_ms=duration_ms)
        except Exception:
            pass  # Don't fail if tracking fails
        logger.error(f"❌ Ticker research job failed: {e}", exc_info=True)


def archive_retry_job() -> None:
    """Retry checking for archived versions of paywalled articles.
    
    This job:
    1. Finds articles submitted to archive service but not yet archived
    2. Checks if they're now archived (waits at least 5 minutes after submission)
    3. If archived, extracts content and runs AI analysis
    4. Updates articles with archived content
    
    Robots.txt enforcement: Controlled by ENABLE_ROBOTS_TXT_CHECKS environment variable.
    When enabled, checks robots.txt before accessing archive service domains.
    """
    job_id = 'archive_retry'
    start_time = time.time()
    
    try:
        # Import job tracking
        from utils.job_tracking import mark_job_started, mark_job_completed, mark_job_failed
        
        logger.info("Starting archive retry job...")
        
        # Mark job as started
        target_date = datetime.now(timezone.utc).date()
        mark_job_started('archive_retry', target_date)
        
        # Import dependencies
        try:
            from research_repository import ResearchRepository
            from archive_service import check_archived, get_archived_content
            from paywall_detector import is_paywalled_article
            from ollama_client import get_ollama_client, generate_summary
        except ImportError as e:
            duration_ms = int((time.time() - start_time) * 1000)
            message = f"Missing dependency: {e}"
            log_job_execution(job_id, success=False, message=message, duration_ms=duration_ms)
            logger.error(f"❌ {message}")
            try:
                mark_job_failed('archive_retry', target_date, None, message, duration_ms=duration_ms)
            except Exception:
                pass
            return
        
        # Get clients
        research_repo = ResearchRepository()
        ollama_client = get_ollama_client()
        
        # Get owned tickers for relevance scoring
        from supabase_client import SupabaseClient
        client = SupabaseClient(use_service_role=True)
        funds_result = client.supabase.table("funds").select("name").eq("is_production", True).execute()
        
        owned_tickers = set()
        if funds_result.data:
            prod_funds = [f['name'] for f in funds_result.data]
            positions_result = client.supabase.table("latest_positions").select("ticker").in_("fund", prod_funds).execute()
            if positions_result.data:
                owned_tickers = set(pos['ticker'] for pos in positions_result.data)
        
        # Get pending archive articles (submitted at least 5 minutes ago)
        pending_articles = research_repo.get_pending_archive_articles(min_wait_minutes=5)
        
        if not pending_articles:
            duration_ms = int((time.time() - start_time) * 1000)
            message = "No pending archive articles to check"
            log_job_execution(job_id, success=True, message=message, duration_ms=duration_ms)
            mark_job_completed('archive_retry', target_date, None, [], duration_ms=duration_ms, message=message)
            logger.info(f"ℹ️ {message}")
            return
        
        logger.info(f"Found {len(pending_articles)} pending archive articles to check")
        
        articles_checked = 0
        articles_archived = 0
        articles_processed = 0
        
        # Process each pending article
        for article in pending_articles:
            try:
                article_id = article['id']
                url = article['url']
                submitted_at = article['archive_submitted_at']
                
                logger.info(f"Checking archive status for: {url[:60]}...")
                
                # Check robots.txt compliance for original URL (if enabled)
                try:
                    from robots_utils import check_url_allowed
                    if not check_url_allowed(url):
                        logger.info(f"Skipping URL disallowed by robots.txt: {url[:60]}...")
                        articles_checked += 1
                        continue
                except ImportError:
                    # robots_utils not available, skip check
                    pass
                
                # Check if archived
                archived_url = check_archived(url)
                
                if archived_url:
                    logger.info(f"✅ Found archived version: {archived_url}")
                    
                    # Check robots.txt for archived URL too (if enabled)
                    try:
                        from robots_utils import check_url_allowed
                        if not check_url_allowed(archived_url):
                            logger.info(f"Skipping archived URL disallowed by robots.txt: {archived_url[:60]}...")
                            articles_checked += 1
                            continue
                    except ImportError:
                        # robots_utils not available, skip check
                        pass
                    
                    # Mark as checked with archived URL
                    research_repo.mark_archive_checked(article_id, archived_url, success=True)
                    
                    # Fetch content from archived page using our custom function with browser headers
                    # This avoids rate limiting that trafilatura.fetch_url() might trigger
                    try:
                        import trafilatura
                        from archive_service import get_archived_content
                        
                        # Add delay to avoid rate limiting (retry job runs every 45 min, so this should be safe)
                        time.sleep(2)
                        
                        logger.debug(f"Fetching archived content with browser headers: {archived_url}")
                        archived_html = get_archived_content(archived_url)
                        
                        if archived_html:
                            # Extract content using trafilatura
                            extracted_content = trafilatura.extract(
                                archived_html,
                                include_comments=False,
                                include_links=False,
                                include_images=False,
                                include_tables=False
                            )
                            
                            if extracted_content and len(extracted_content) > 200:
                                # Check if archived version also has paywall
                                if is_paywalled_article(extracted_content, archived_url):
                                    logger.warning(f"⚠️ Archived version still has paywall for {article_id}")
                                    research_repo.mark_archive_checked(article_id, None, success=False)
                                    continue
                                
                                # Generate AI summary and embedding
                                summary = None
                                summary_data = {}
                                extracted_tickers = []
                                extracted_sector = None
                                embedding = None
                                title = article.get("title", "Untitled")
                                
                                summary_input = f"Title: {title}\n\n{extracted_content}" if title else extracted_content
                                summary_data = generate_summary(summary_input)

                                if isinstance(summary_data, str):
                                    summary = summary_data
                                elif isinstance(summary_data, dict) and summary_data:
                                    summary = summary_data.get("summary", "")

                                    # Extract tickers with real-company validation
                                    extracted_tickers = _extract_and_validate_tickers(
                                        summary_data, title, extracted_content,
                                    )

                                    # Extract sector
                                    sectors = summary_data.get("sectors", [])
                                    if sectors:
                                        extracted_sector = sectors[0]

                                # Generate embedding (Ollama-only)
                                if ollama_client:
                                    embedding = ollama_client.generate_embedding(extracted_content)
                                
                                # Calculate relevance score
                                relevance_score = calculate_relevance_score(
                                    extracted_tickers if extracted_tickers else [],
                                    extracted_sector,
                                    owned_tickers=list(owned_tickers) if owned_tickers else None
                                )
                                
                                # Extract metadata
                                metadata = trafilatura.extract_metadata(archived_html)
                                title = metadata.title if metadata and metadata.title else article.get('title', 'Untitled')
                                
                                # Update article with archived content
                                success = research_repo.update_article_analysis(
                                    article_id=article_id,
                                    summary=summary,
                                    tickers=extracted_tickers if extracted_tickers else None,
                                    sector=extracted_sector,
                                    embedding=embedding,
                                    relevance_score=relevance_score,
                                    claims=summary_data.get("claims") if isinstance(summary_data, dict) else None,
                                    fact_check=summary_data.get("fact_check") if isinstance(summary_data, dict) else None,
                                    conclusion=summary_data.get("conclusion") if isinstance(summary_data, dict) else None,
                                    sentiment=summary_data.get("sentiment") if isinstance(summary_data, dict) else None,
                                    sentiment_score=summary_data.get("sentiment_score") if isinstance(summary_data, dict) else None
                                )
                                
                                # Also update content
                                try:
                                    update_query = "UPDATE research_articles SET content = %s, title = %s WHERE id = %s"
                                    research_repo.client.execute_query(update_query, (extracted_content, title, article_id))
                                except Exception as e:
                                    logger.warning(f"Failed to update content for {article_id}: {e}")
                                
                                if success:
                                    articles_processed += 1
                                    logger.info(f"✅ Processed archived article: {title[:40]}...")
                                else:
                                    logger.warning(f"⚠️ Failed to update article {article_id}")
                            else:
                                logger.warning(f"⚠️ Archived content too short for {article_id}")
                        else:
                            logger.warning(f"⚠️ Failed to fetch archived HTML for {article_id}")
                    except ImportError:
                        logger.error("trafilatura not available for content extraction")
                    except Exception as e:
                        logger.error(f"Error extracting archived content: {e}", exc_info=True)
                    
                    articles_archived += 1
                else:
                    # Not archived yet, mark as checked but don't update
                    research_repo.mark_archive_checked(article_id, None, success=False)
                    logger.debug(f"Article not yet archived: {url[:60]}...")
                
                articles_checked += 1
                
            except Exception as e:
                logger.error(f"Error processing article {article.get('id', 'unknown')}: {e}", exc_info=True)
                continue
        
        # Log completion
        duration_ms = int((time.time() - start_time) * 1000)
        message = f"Checked {articles_checked} articles, found {articles_archived} archived, processed {articles_processed}"
        log_job_execution(job_id, success=True, message=message, duration_ms=duration_ms)
        mark_job_completed('archive_retry', target_date, None, [], duration_ms=duration_ms, message=message)
        logger.info(f"✅ {message}")
        
    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        message = f"Error: {str(e)}"
        log_job_execution(job_id, success=False, message=message, duration_ms=duration_ms)
        try:
            from utils.job_tracking import mark_job_failed
            target_date = datetime.now(timezone.utc).date()
            mark_job_failed('archive_retry', target_date, None, message, duration_ms=duration_ms)
        except Exception:
            pass
        logger.error(f"❌ Archive retry job failed: {e}", exc_info=True)


def process_research_reports_job() -> None:
    """Process PDF research reports from Research/ folders.
    
    This job:
    1. Scans Research/ directory for PDF files
    2. Checks if files are already processed (by url path)
    3. Adds YYYYMMDD date prefix if missing
    4. Extracts text and tables using pdfplumber
    5. Generates embeddings and AI summaries
    6. Stores in research_articles database
    """
    job_id = 'process_research_reports'
    start_time = time.time()
    target_date = datetime.now(timezone.utc).date()
    
    try:
        # Import job tracking
        from utils.job_tracking import mark_job_started, mark_job_completed, mark_job_failed
        
        logger.info("Starting research reports processing job...")
        
        # Mark job as started
        mark_job_started('process_research_reports', target_date)
        
        # Import dependencies
        try:
            from research_report_service import (
                scan_research_folder,
                add_date_prefix_to_filename,
                extract_title_from_filename,
                determine_report_type,
                get_relative_path,
                check_file_already_processed,
                parse_filename_date
            )
            from file_parsers import parse_pdf
            from ollama_client import get_ollama_client, generate_summary
            from research_repository import ResearchRepository
        except ImportError as e:
            duration_ms = int((time.time() - start_time) * 1000)
            message = f"Missing dependency: {e}"
            log_job_execution(job_id, success=False, message=message, duration_ms=duration_ms)
            logger.error(f"❌ {message}")
            try:
                mark_job_failed('process_research_reports', target_date, None, message, duration_ms=duration_ms)
            except Exception:
                pass
            return
        
        # Initialize clients
        research_repo = ResearchRepository()
        ollama_client = get_ollama_client()
        
        if not ollama_client:
            logger.warning("Ollama client not available - continuing with summary fallback; embeddings will be skipped")
        
        # Scan for PDF files
        pdf_files = scan_research_folder()
        
        if not pdf_files:
            duration_ms = int((time.time() - start_time) * 1000)
            message = "No PDF files found in Research directory"
            log_job_execution(job_id, success=True, message=message, duration_ms=duration_ms)
            mark_job_completed('process_research_reports', target_date, None, [], duration_ms=duration_ms, message=message)
            logger.info(f"ℹ️ {message}")
            return
        
        processed_count = 0
        skipped_count = 0
        failed_count = 0
        
        # Process each PDF file
        total_files = len(pdf_files)
        logger.info(f"Found {total_files} PDF file(s) to process")
        
        for idx, pdf_file in enumerate(pdf_files, 1):
            try:
                # Check if already processed
                if check_file_already_processed(pdf_file, research_repo):
                    logger.info(f"[{idx}/{total_files}] ⏭️  Skipping already processed: {pdf_file.name}")
                    skipped_count += 1
                    continue
                
                logger.info(f"[{idx}/{total_files}] 📄 Processing: {pdf_file.name}")
                
                # Add date prefix if missing
                pdf_file = add_date_prefix_to_filename(pdf_file)
                
                # Extract metadata from filename and folder
                filename = pdf_file.name
                title = extract_title_from_filename(filename)
                published_at = parse_filename_date(filename) or datetime.now(timezone.utc)
                
                # Determine report type from folder
                folder_path = pdf_file.parent
                report_info = determine_report_type(folder_path)
                
                # Extract text from PDF
                logger.info(f"  📖 Extracting text from PDF...")
                with open(pdf_file, 'rb') as f:
                    text_content = parse_pdf(f)
                
                if not text_content or len(text_content.strip()) < 50:
                    logger.warning(f"  ⚠️  No text extracted from {pdf_file.name} (file may be empty or corrupted)")
                    failed_count += 1
                    continue
                
                logger.info(f"  ✅ Extracted {len(text_content):,} characters")
                
                # Generate embedding and summary
                logger.info(f"  🤖 Generating AI summary and embedding...")
                summary_result = {}
                
                try:
                    summary_input = f"Title: {title}\n\n{text_content}" if title else text_content
                    summary_result = generate_summary(summary_input, article_type="Research Report")
                except Exception as e:
                    logger.warning(f"  AI summary failed: {e}")
                
                # Extract tickers from AI summary with real-company validation
                extracted_tickers = _extract_and_validate_tickers(
                    summary_result if isinstance(summary_result, dict) else {},
                    title,
                    text_content,
                )

                # For ticker-specific reports, ensure folder ticker is included even if AI misses it
                from research_utils import normalize_ticker
                if report_info['ticker']:
                    folder_ticker = normalize_ticker(report_info['ticker'])
                    if folder_ticker and folder_ticker not in extracted_tickers:
                        extracted_tickers.append(folder_ticker)
                        logger.debug(f"Added folder ticker to extracted list: {folder_ticker}")
                
                if extracted_tickers:
                    logger.info(f"  📊 Extracted {len(extracted_tickers)} ticker(s): {', '.join(extracted_tickers)}")
                else:
                    logger.info(f"  ℹ️  No tickers extracted from content")
                
                # Prepare article data
                relative_path = get_relative_path(pdf_file)
                
                # Determine fund from report_info (already extracted from folder name)
                fund = report_info.get('fund')
                
                # Save to database
                logger.info(f"  💾 Saving to database...")
                article_id = research_repo.save_article(
                    tickers=extracted_tickers if extracted_tickers else None,
                    sector=None,
                    article_type="Research Report",
                    title=title,
                    url=relative_path,  # Store file path as URL
                    summary=summary_result.get('summary', "No summary available.") if isinstance(summary_result, dict) else (summary_result if isinstance(summary_result, str) else "No summary available."),
                    content=text_content,
                    source="Research Report",
                    published_at=published_at,
                    relevance_score=0.9,  # Research reports are highly relevant
                    embedding=summary_result.get('embedding') if isinstance(summary_result, dict) else None,
                    fund=fund,
                    claims=summary_result.get("claims") if isinstance(summary_result, dict) else None,
                    fact_check=summary_result.get("fact_check") if isinstance(summary_result, dict) else None,
                    conclusion=summary_result.get("conclusion") if isinstance(summary_result, dict) else None,
                    sentiment=summary_result.get("sentiment") if isinstance(summary_result, dict) else None,
                    sentiment_score=summary_result.get("sentiment_score") if isinstance(summary_result, dict) else None,
                    logic_check=summary_result.get("logic_check") if isinstance(summary_result, dict) else None
                )
                
                if article_id:
                    logger.info(f"  ✅ Successfully saved: {title[:60]}...")
                    processed_count += 1
                else:
                    logger.warning(f"  ⚠️  Failed to save: {title[:60]}...")
                    failed_count += 1
                    
            except Exception as e:
                logger.error(f"Error processing {pdf_file}: {e}", exc_info=True)
                failed_count += 1
                continue
        
        # If running locally, upload PDFs to server
        upload_success = None
        if processed_count > 0 or skipped_count > 0:
            try:
                from research_upload import upload_research_files_to_server, get_server_config, is_running_locally
                from research_report_service import RESEARCH_BASE_DIR
                
                if is_running_locally():
                    server_config = get_server_config()
                    if server_config:
                        logger.info("")
                        logger.info("=" * 60)
                        logger.info("📤 UPLOADING PDFs TO SERVER")
                        logger.info("=" * 60)
                        logger.info(f"Server: {server_config['user']}@{server_config['host']}")
                        logger.info(f"Path: {server_config['path']}")
                        if server_config.get('ssh_key'):
                            logger.info(f"SSH Key: {server_config['ssh_key']}")
                        else:
                            logger.info("SSH Key: Using default keys or password")
                        logger.info("")
                        upload_success = upload_research_files_to_server(
                            local_research_dir=RESEARCH_BASE_DIR,
                            server_host=server_config["host"],
                            server_user=server_config["user"],
                            server_path=server_config["path"],
                            ssh_key_path=server_config.get("ssh_key")
                        )
                        logger.info("")
                        if upload_success:
                            logger.info("✅ PDFs uploaded to server successfully")
                        else:
                            logger.warning("⚠️  Failed to upload PDFs to server (processing still succeeded)")
                    else:
                        logger.debug("Server config not found - skipping upload (set RESEARCH_SERVER_HOST, RESEARCH_SERVER_USER env vars)")
            except ImportError:
                logger.debug("Upload module not available - skipping upload")
            except Exception as e:
                logger.warning(f"Error uploading files to server: {e} (processing still succeeded)")
        
        # Log completion
        duration_ms = int((time.time() - start_time) * 1000)
        message = f"Processed {processed_count} reports, skipped {skipped_count} already processed, {failed_count} failed"
        if upload_success is not None:
            message += f", upload: {'success' if upload_success else 'failed'}"
        log_job_execution(job_id, success=True, message=message, duration_ms=duration_ms)
        mark_job_completed('process_research_reports', target_date, None, [], duration_ms=duration_ms, message=message)
        logger.info(f"✅ {message}")
        
    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        message = f"Error: {str(e)}"
        log_job_execution(job_id, success=False, message=message, duration_ms=duration_ms)
        try:
            mark_job_failed('process_research_reports', target_date, None, message, duration_ms=duration_ms)
        except Exception:
            pass
        logger.error(f"❌ Research reports processing job failed: {e}", exc_info=True)
