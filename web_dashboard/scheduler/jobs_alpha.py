import time
import logging
from datetime import datetime, timezone

# Add parent directory to path if needed (standard boilerplate for these jobs)
import sys
import os
from pathlib import Path

# Add project root to path for utils imports
current_dir = Path(__file__).resolve().parent
if current_dir.name == 'scheduler':
    project_root = current_dir.parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

# Initialize logger
logger = logging.getLogger(__name__)

def alpha_research_job() -> None:
    """Targeted 'Alpha Hunter' job that searches specific high-value domains.
    
    This job:
    1. Gets specific 'alpha' domains from configuration
    2. Gets specific 'opportunity' queries
    3. Constructs 'site:' dork queries to find high-quality analysis
    4. Saves articles with article_type="alpha_research"
    
    Robots.txt enforcement: Controlled by ENABLE_ROBOTS_TXT_CHECKS environment variable.
    When enabled, checks robots.txt before accessing article URLs from search results.
    """
    job_id = 'alpha_research'
    start_time = time.time()
    
    # We need to import log_job_execution and mark_job_* functions
    # Assuming they are available or we need to import them like in other jobs
    # For now, following the pattern in jobs_opportunity.py
    
    try:
        from scheduler.scheduler_core import log_job_execution
        from utils.job_tracking import mark_job_started, mark_job_completed, mark_job_failed
        
        # Mark started
        target_date = datetime.now(timezone.utc).date()
        # Note: mark_job_started might fail if job not in DB constraints, but usually okay
        try:
             mark_job_started(job_id, target_date)
        except Exception:
             pass # Job might not be tracked in main table yet
        
        logger.info("Starting Alpha Research job...")
        
        # Import dependencies
        try:
            from searxng_client import get_searxng_client, check_searxng_health
            from research_utils import extract_article_content
            from ollama_client import get_ollama_client
            from research_repository import ResearchRepository
            from settings import get_alpha_research_domains, get_alpha_search_queries
        except ImportError as e:
            duration_ms = int((time.time() - start_time) * 1000)
            message = f"Missing dependency: {e}"
            log_job_execution(job_id, success=False, message=message, duration_ms=duration_ms)
            logger.error(f"❌ {message}")
            return
        
        # Check SearXNG health
        if not check_searxng_health():
            duration_ms = int((time.time() - start_time) * 1000)
            message = "SearXNG is not available - skipping alpha research"
            log_job_execution(job_id, success=True, message=message, duration_ms=duration_ms)
            logger.info(f"ℹ️ {message}")
            return
        
        # Get clients
        searxng_client = get_searxng_client()
        ollama_client = get_ollama_client()
        
        if not searxng_client:
            duration_ms = int((time.time() - start_time) * 1000)
            message = "SearXNG client not initialized"
            log_job_execution(job_id, success=False, message=message, duration_ms=duration_ms)
            logger.error(f"❌ {message}")
            return
        
        # Initialize research repository
        research_repo = ResearchRepository()
        
        # Load config
        domains = get_alpha_research_domains()
        queries = get_alpha_search_queries()
        
        if not domains or not queries:
            message = "No alpha domains or queries configured"
            logger.warning(message)
            return

        logger.info(f"Using {len(domains)} alpha domains and {len(queries)} queries")
        
        # Construct Search Dorks
        site_dork = " OR ".join([f"site:{d}" for d in domains])
        
        # Rotate queries based on hour to avoid hammering
        query_index = datetime.now().hour % len(queries)
        base_query = queries[query_index]
        
        # Full query with site restrictions
        final_query = f'{base_query} ({site_dork})'
        
        logger.info(f"🔭 Alpha Query: '{final_query}'")
        
        # Search
        search_results = searxng_client.search_news(
            query=final_query,
            max_results=10  # Get decent chunk
        )
        
        if not search_results or not search_results.get('results'):
            duration_ms = int((time.time() - start_time) * 1000)
            message = f"No results for alpha query: {base_query}"
            log_job_execution(job_id, success=True, message=message, duration_ms=duration_ms)
            logger.info(f"ℹ️ {message}")
            return
        
        articles_processed = 0
        articles_saved = 0
        articles_skipped = 0
        articles_irrelevant = 0
        
        # Load blacklist for safety (even though we are targeting specific sites, redundancy is good)
        from settings import get_research_domain_blacklist
        blacklist = get_research_domain_blacklist()
        
        for result in search_results['results']:
            try:
                url = result.get('url', '')
                title = result.get('title', '')
                
                if not url or not title:
                    continue
                
                # Check robots.txt compliance (if enabled)
                try:
                    from robots_utils import check_url_allowed
                    if not check_url_allowed(url):
                        logger.debug(f"Skipping URL disallowed by robots.txt: {url[:60]}...")
                        articles_skipped += 1
                        continue
                except ImportError:
                    # robots_utils not available, skip check
                    pass
                
                # Check blacklist
                from research_utils import is_domain_blacklisted
                is_blocked, domain = is_domain_blacklisted(url, blacklist)
                if is_blocked:
                    logger.debug(f"Skipping explicitly blacklisted: {domain}")
                    continue
                
                # Check if already exists
                if research_repo.article_exists(url):
                    logger.debug(f"Article already exists: {title[:50]}...")
                    articles_skipped += 1
                    continue
                
                # Extract content
                logger.info(f"  💎 Extracting Alpha: {title[:40]}...")
                extracted = extract_article_content(url)
                
                content = extracted.get('content', '')
                if not content or not extracted.get('success'):
                    continue
                
                # Generate summary and embedding
                summary = None
                summary_data = {}
                extracted_tickers = []
                extracted_sector = None
                embedding = None
                
                if ollama_client:
                    summary_data = ollama_client.generate_summary(content)
                    
                    if isinstance(summary_data, str):
                        summary = summary_data
                    elif isinstance(summary_data, dict) and summary_data:
                        summary = summary_data.get("summary", "")
                        
                        # Extract ticker and sector
                        tickers = summary_data.get("tickers", [])
                        sectors = summary_data.get("sectors", [])
                        
                        # Extract all validated tickers
                        from research_utils import validate_ticker_format, normalize_ticker
                        for ticker in tickers:
                            # Validate format only
                            if not validate_ticker_format(ticker):
                                continue
                            normalized = normalize_ticker(ticker)
                            if normalized:
                                extracted_tickers.append(normalized)
                        
                        if extracted_tickers:
                            logger.info(f"  🎯 Discovered ticker(s): {extracted_tickers}")
                        
                        if sectors:
                            extracted_sector = sectors[0]

                        market_relevance = summary_data.get("market_relevance") if isinstance(summary_data, dict) else None
                        if not extracted_tickers and market_relevance == "NOT_MARKET_RELATED":
                            reason = summary_data.get("market_relevance_reason", "")
                            articles_irrelevant += 1
                            logger.info(
                                f"  🚫 Skipping non-market alpha article: {title[:50]}... "
                                f"Reason: {reason or 'No market relevance detected'}"
                            )
                            continue
                    
                    # Generate embedding
                    embedding = ollama_client.generate_embedding(content[:6000])
                
                # Extract logic_check
                logic_check = summary_data.get("logic_check") if isinstance(summary_data, dict) else None
                
                # Save article with alpha_research type
                article_id = research_repo.save_article(
                    tickers=extracted_tickers if extracted_tickers else None,
                    sector=extracted_sector,
                    article_type="Alpha Research",  # Special tag for these high-value articles
                    title=extracted.get('title') or title,
                    url=url,
                    summary=summary,
                    content=content,
                    source=extracted.get('source'),
                    published_at=extracted.get('published_at'),
                    relevance_score=0.85,  # High relevance for these focused searches
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
                    logger.info(f"  ✅ Saved Alpha Research: {title[:30]}")
                
                articles_processed += 1
                time.sleep(1) # Be gentle
                
            except Exception as e:
                logger.error(f"Error processing alpha article: {e}")
                continue
        
        duration_ms = int((time.time() - start_time) * 1000)
        message = (
            f"Query: '{base_query}' - Processed {articles_processed}: {articles_saved} saved, "
            f"{articles_skipped} skipped, {articles_irrelevant} non-market"
        )
        log_job_execution(job_id, success=True, message=message, duration_ms=duration_ms)
        try:
            mark_job_completed(job_id, target_date, None, [], duration_ms=duration_ms)
        except Exception:
            pass
        logger.info(f"✅ {message}")
        
    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        message = f"Error: {str(e)}"
        try:
             log_job_execution(job_id, success=False, message=message, duration_ms=duration_ms)
        except:
             pass
        logger.error(f"❌ Alpha Research job failed: {e}", exc_info=True)
