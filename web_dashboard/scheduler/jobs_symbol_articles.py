"""
Symbol Article Scraper Job
===========================

Scheduled job that scrapes symbol pages for portfolio tickers
to extract and store news articles.
"""

import time
import logging
from datetime import datetime, timezone
from pathlib import Path
import sys

# Add parent directory to path if needed (standard boilerplate for these jobs)
current_dir = Path(__file__).resolve().parent
if current_dir.name == 'scheduler':
    project_root = current_dir.parent.parent
else:
    project_root = current_dir.parent.parent

# Also ensure web_dashboard is in path
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

# Initialize logger
logger = logging.getLogger(__name__)


def symbol_article_scraper_job() -> None:
    """Scrape symbol pages for portfolio tickers.
    
    This job:
    1. Gets tickers from production fund holdings
    2. For each ticker, fetches the symbol page
    3. Extracts article links from the page
    4. Validates and filters to real articles
    5. Extracts content using existing extract_article_content()
    6. Detects and handles paywalled articles
    7. Saves articles to database with article_type="symbol_article"
    
    Robots.txt enforcement: Controlled by ENABLE_ROBOTS_TXT_CHECKS environment variable.
    When enabled, checks robots.txt before accessing symbol pages and article URLs.
    """
    job_id = 'symbol_article_scraper'
    start_time = time.time()
    
    try:
        from scheduler.scheduler_core import log_job_execution
        from utils.job_tracking import mark_job_started, mark_job_completed, mark_job_failed
        
        # Mark started
        target_date = datetime.now(timezone.utc).date()
        try:
            mark_job_started(job_id, target_date)
        except Exception:
            pass  # Job might not be tracked in main table yet
        
        logger.info("Starting symbol article scraper job...")
        
        # Import dependencies
        try:
            from symbol_article_scraper import (
                scrape_symbol_articles,
                build_symbol_url,
                is_paywalled_content,
            )
            from research_utils import extract_article_content, extract_source_from_url
            from ollama_client import get_ollama_client
            from research_repository import ResearchRepository
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
        
        # Initialize clients
        ollama_client = get_ollama_client()
        research_repo = ResearchRepository()
        
        # Connect to Supabase to get portfolio tickers
        client = SupabaseClient(use_service_role=True)
        
        # Get production funds
        funds_result = client.supabase.table("funds")\
            .select("name")\
            .eq("is_production", True)\
            .execute()
        
        if not funds_result.data:
            duration_ms = int((time.time() - start_time) * 1000)
            message = "No production funds found"
            try:
                log_job_execution(job_id, True, message, duration_ms)
            except Exception as log_error:
                logger.warning(f"Failed to log job execution: {log_error}")
            logger.info(f"ℹ️ {message}")
            return
        
        prod_funds = [f['name'] for f in funds_result.data]
        logger.info(f"Scanning symbol pages for funds: {prod_funds}")
        
        # Get distinct tickers from portfolio positions
        positions_result = client.supabase.table("latest_positions")\
            .select("ticker, company, fund")\
            .in_("fund", prod_funds)\
            .execute()
        
        if not positions_result.data:
            duration_ms = int((time.time() - start_time) * 1000)
            message = "No active positions found in production funds"
            try:
                log_job_execution(job_id, True, message, duration_ms)
            except Exception as log_error:
                logger.warning(f"Failed to log job execution: {log_error}")
            logger.info(f"ℹ️ {message}")
            return
        
        # Deduplicate tickers
        targets = {}
        for pos in positions_result.data:
            ticker = pos['ticker']
            company = pos.get('company')
            
            if ticker not in targets:
                targets[ticker] = company
        
        logger.info(f"Found {len(targets)} unique tickers to scrape")
        
        # Load blacklist
        from settings import get_research_domain_blacklist
        blacklist = get_research_domain_blacklist()
        
        # Statistics
        articles_processed = 0
        articles_saved = 0
        articles_skipped = 0
        articles_paywalled = 0
        articles_failed = 0
        tickers_processed = 0
        tickers_failed = 0
        
        # Process each ticker
        for ticker, company_name in targets.items():
            try:
                tickers_processed += 1
                logger.info(f"Processing {ticker} ({tickers_processed}/{len(targets)})...")
                
                # Determine if Canadian ticker (check for exchange prefix)
                exchange = None
                if ':' in ticker:
                    # Already has exchange prefix (e.g., "TSX:ABC")
                    parts = ticker.split(':', 1)
                    if len(parts) == 2:
                        exchange = parts[0]
                        ticker = parts[1]
                elif ticker.endswith('.TO'):
                    # Canadian TSX ticker
                    exchange = 'TSX'
                    ticker = ticker.replace('.TO', '')
                elif ticker.endswith('.V'):
                    # Canadian TSXV ticker
                    exchange = 'TSXV'
                    ticker = ticker.replace('.V', '')
                
                # Scrape article URLs from symbol page
                article_urls = scrape_symbol_articles(ticker, exchange, max_articles=20)
                
                if not article_urls:
                    logger.debug(f"No articles found for {ticker}")
                    continue
                
                logger.info(f"  Found {len(article_urls)} articles for {ticker}")
                
                # Process each article
                for article_url in article_urls:
                    try:
                        articles_processed += 1
                        
                        # Check robots.txt compliance (if enabled)
                        try:
                            from robots_utils import check_url_allowed
                            if not check_url_allowed(article_url):
                                logger.debug(f"  Skipping URL disallowed by robots.txt: {article_url[:60]}...")
                                articles_skipped += 1
                                continue
                        except ImportError:
                            # robots_utils not available, skip check
                            pass
                        
                        # Check blacklist
                        from research_utils import is_domain_blacklisted
                        is_blocked, domain = is_domain_blacklisted(article_url, blacklist)
                        if is_blocked:
                            logger.debug(f"Skipping blacklisted: {domain}")
                            articles_skipped += 1
                            continue
                        
                        # Check if already exists
                        if research_repo.article_exists(article_url):
                            logger.debug(f"Article already exists: {article_url[:50]}...")
                            articles_skipped += 1
                            continue
                        
                        # Extract content
                        logger.debug(f"  Extracting: {article_url[:60]}...")
                        extracted = extract_article_content(article_url)
                        
                        # Check for paid subscription articles
                        if extracted.get('error') == 'paid_subscription':
                            # Check if archive was submitted
                            if extracted.get('archive_submitted'):
                                logger.info(f"  🔒 Paywalled article submitted to archive, saving for retry: {article_url[:60]}...")
                                # Save article with minimal content so retry job can find it
                                article_id = research_repo.save_article(
                                    tickers=[ticker.upper()],
                                    sector=None,
                                    article_type="Ticker News",
                                    title=title or "Paywalled Article",
                                    url=article_url,
                                    summary="[Paywalled - Submitted to archive for processing]",
                                    content="[Paywalled - Submitted to archive for processing]",
                                    source=extracted.get('source'),
                                    published_at=None,
                                    relevance_score=0.0,
                                    embedding=None
                                )
                                if article_id:
                                    # Mark as archive submitted
                                    research_repo.mark_archive_submitted(article_id, article_url)
                                    articles_paywalled += 1
                                    logger.info(f"  Saved paywalled article for archive retry: {article_id}")
                            else:
                                logger.info(f"  🔒 Skipping paid subscription article: {article_url[:60]}...")
                                articles_paywalled += 1
                            continue
                        
                        content = extracted.get('content', '')
                        title = extracted.get('title', '')
                        
                        # Check for paywall
                        if is_paywalled_content(content, title):
                            logger.info(f"  🔒 Paywalled article detected: {title[:50]}...")
                            articles_paywalled += 1
                            # Still save the URL and title for reference, but mark as paywalled
                            # We'll save with minimal content
                            content = f"[Paywalled - Full content requires account]\n\n{content[:500]}"  # Keep first 500 chars
                        
                        if not content or not extracted.get('success'):
                            error_reason = extracted.get('error', 'unknown')
                            logger.warning(f"  ⚠️ Failed to extract: {error_reason}")
                            articles_failed += 1
                            continue
                        
                        # Generate summary and embedding (if content is substantial)
                        summary = None
                        summary_data = {}
                        extracted_tickers = [ticker.upper()]  # Associate with the ticker we're scraping
                        extracted_sector = None
                        embedding = None
                        
                        # Only generate AI summary if content is substantial (not just paywall message)
                        if len(content) > 500 and ollama_client:
                            try:
                                summary_data = ollama_client.generate_summary(content)
                                
                                if isinstance(summary_data, str):
                                    summary = summary_data
                                elif isinstance(summary_data, dict) and summary_data:
                                    summary = summary_data.get("summary", "")
                                    
                                    # Extract additional tickers from content
                                    tickers = summary_data.get("tickers", [])
                                    sectors = summary_data.get("sectors", [])
                                    
                                    from research_utils import validate_ticker_format, normalize_ticker
                                    for t in tickers:
                                        if validate_ticker_format(t):
                                            normalized = normalize_ticker(t)
                                            if normalized and normalized not in extracted_tickers:
                                                extracted_tickers.append(normalized)
                                    
                                    if sectors:
                                        extracted_sector = sectors[0]
                                
                                # Generate embedding
                                embedding = ollama_client.generate_embedding(content[:6000])
                            except Exception as e:
                                logger.warning(f"  ⚠️ AI processing failed: {e}")
                        
                        # Extract additional metadata
                        logic_check = summary_data.get("logic_check") if isinstance(summary_data, dict) else None
                        
                        # Save article
                        article_id = research_repo.save_article(
                            tickers=extracted_tickers if extracted_tickers else None,
                            sector=extracted_sector,
                            article_type="Symbol Article",
                            title=title or f"Symbol Article - {ticker}",
                            url=article_url,
                            summary=summary,
                            content=content,
                            source=extracted.get('source') or 'symbol-article-source',
                            published_at=extracted.get('published_at'),
                            relevance_score=0.80,  # Good relevance for direct symbol scraping
                            embedding=embedding,
                            claims=summary_data.get("claims") if isinstance(summary_data, dict) else None,
                            fact_check=summary_data.get("fact_check") if isinstance(summary_data, dict) else None,
                            conclusion=summary_data.get("conclusion") if isinstance(summary_data, dict) else None,
                            sentiment=summary_data.get("sentiment") if isinstance(summary_data, dict) else None,
                            sentiment_score=summary_data.get("sentiment_score") if isinstance(summary_data, dict) else None,
                            logic_check=logic_check
                        )
                        
                        if article_id:
                            articles_saved += 1
                            logger.info(f"  ✅ Saved: {title[:40]}...")
                        
                        # Be gentle with rate limiting
                        time.sleep(1)
                        
                    except Exception as e:
                        logger.error(f"Error processing article {article_url}: {e}")
                        articles_failed += 1
                        continue
                
                # Delay between tickers
                time.sleep(2)
                
            except Exception as e:
                logger.error(f"Error processing ticker {ticker}: {e}")
                tickers_failed += 1
                continue
        
        # Log results
        duration_ms = int((time.time() - start_time) * 1000)
        message = (
            f"Processed {tickers_processed} tickers: "
            f"{articles_saved} saved, {articles_skipped} skipped, "
            f"{articles_paywalled} paywalled, {articles_failed} failed"
        )
        try:
            log_job_execution(job_id, True, message, duration_ms)
        except Exception as log_error:
            logger.warning(f"Failed to log job execution: {log_error}")
        try:
            mark_job_completed(job_id, target_date, None, [], duration_ms=duration_ms)
        except Exception:
            pass
        logger.info(f"✅ {message}")
        
    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        message = f"Error: {str(e)}"
        try:
            log_job_execution(job_id, False, message, duration_ms)
        except Exception as log_error:
            logger.warning(f"Failed to log job execution error: {log_error}")
        logger.error(f"❌ Symbol article scraper job failed: {e}", exc_info=True)

