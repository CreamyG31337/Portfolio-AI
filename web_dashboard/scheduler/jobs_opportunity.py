

import logging
import time
import sys
import os
from pathlib import Path

# Add project root to path for utils imports
current_dir = Path(__file__).resolve().parent
if current_dir.name == 'scheduler':
    project_root = current_dir.parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

logger = logging.getLogger(__name__)


def opportunity_discovery_job() -> None:
    """Hunt for new investment opportunities using targeted search queries.
    
    This job:
    1. Rotates through a list of "hunting" queries (e.g., "undervalued microcaps")
    2. Searches for relevant news using SearXNG
    3. Saves articles with article_type="opportunity_discovery"
    
    Robots.txt enforcement: Controlled by ENABLE_ROBOTS_TXT_CHECKS environment variable.
    When enabled, checks robots.txt before accessing article URLs from search results.
    """
    job_id = 'opportunity_discovery'
    start_time = time.time()
    
    # Import job tracking at the start
    from datetime import datetime, timezone
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
        from utils.job_tracking import mark_job_started, mark_job_completed, mark_job_failed
        mark_job_started(job_id, target_date)
    except Exception as e:
        logger.warning(f"Could not mark job started: {e}")
    
    try:
        logger.info("Starting opportunity discovery job...")
        
        # Import dependencies
        try:
            from searxng_client import get_searxng_client, check_searxng_health
            from research_utils import extract_article_content
            from ollama_client import get_ollama_client, generate_summary
            from research_repository import ResearchRepository
            from settings import get_discovery_search_queries
        except ImportError as e:
            duration_ms = int((time.time() - start_time) * 1000)
            message = f"Missing dependency: {e}"
            log_job_execution(job_id, success=False, message=message, duration_ms=duration_ms)
            try:
                mark_job_failed(job_id, target_date, None, message, duration_ms=duration_ms)
            except:
                pass
            logger.error(f"❌ {message}")
            return
        
        # Check SearXNG health
        if not check_searxng_health():
            duration_ms = int((time.time() - start_time) * 1000)
            message = "SearXNG is not available - skipping opportunity discovery"
            log_job_execution(job_id, success=True, message=message, duration_ms=duration_ms)
            try:
                mark_job_completed(job_id, target_date, None, [], duration_ms=duration_ms)
            except:
                pass
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
        
        # Load domain blacklist
        from settings import get_research_domain_blacklist
        blacklist = get_research_domain_blacklist()
        
        # Get discovery queries
        queries = get_discovery_search_queries()
        logger.info(f"Using {len(queries)} discovery queries")
        
        # Rotate through queries (pick one per run to avoid overwhelming the system)
        # Use the current hour to deterministically select which query to use
        from datetime import datetime
        query_index = datetime.now().hour % len(queries)
        selected_query = queries[query_index]
        
        logger.info(f"🔭 Discovery Query: '{selected_query}'")
        
        # Search
        search_results = searxng_client.search_news(
            query=selected_query,
            max_results=8  # Get more results for discovery
        )
        
        if not search_results or not search_results.get('results'):
            duration_ms = int((time.time() - start_time) * 1000)
            message = f"No results for query: {selected_query}"
            log_job_execution(job_id, success=True, message=message, duration_ms=duration_ms)
            logger.info(f"ℹ️ {message}")
            return
        
        articles_processed = 0
        articles_saved = 0
        articles_skipped = 0
        articles_blacklisted = 0
        articles_irrelevant = 0

        # Safety timeouts (avoid runaway jobs)
        MAX_JOB_DURATION = 40 * 60  # 40 minutes total
        MAX_ARTICLE_DURATION = 4 * 60  # 4 minutes per article
        
        for result in search_results['results']:
            # Check overall job timeout
            elapsed = time.time() - start_time
            if elapsed > MAX_JOB_DURATION:
                logger.warning(f"⏱️  Job timeout reached ({elapsed/60:.1f}m). Stopping opportunity discovery")
                break

            article_start = time.time()
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
                    logger.debug(f"Skipping blacklisted: {domain}")
                    articles_blacklisted += 1
                    continue

                # Per-article timeout guard
                if time.time() - article_start > MAX_ARTICLE_DURATION:
                    logger.warning(f"⏱️  Article timeout - skipping: {title[:40]}...")
                    continue
                
                # Check if already exists
                if research_repo.article_exists(url):
                    logger.debug(f"Article already exists: {title[:50]}...")
                    articles_skipped += 1
                    continue
                
                # Extract content
                logger.info(f"  💎 Extracting: {title[:40]}...")
                extracted = extract_article_content(url)

                # Health tracking
                from research_domain_health import DomainHealthTracker
                tracker = DomainHealthTracker()
                from settings import get_system_setting
                threshold = get_system_setting("auto_blacklist_threshold", default=4)
                
                content = extracted.get('content', '')
                if not content or not extracted.get('success'):
                    error_reason = extracted.get('error', 'unknown')
                    failure_count = tracker.record_failure(url, error_reason)
                    
                    if tracker.should_auto_blacklist(url):
                        if tracker.auto_blacklist_domain(url):
                            logger.warning(f"🚫 AUTO-BLACKLISTED: {domain}")
                            articles_blacklisted += 1
                    continue

                # Per-article timeout guard after extraction
                if time.time() - article_start > MAX_ARTICLE_DURATION:
                    logger.warning(f"⏱️  Article timeout after extraction - skipping: {title[:40]}...")
                    continue
                
                tracker.record_success(url)
                
                # Generate summary and embedding
                summary = None
                summary_data = {}
                extracted_ticker = None
                extracted_sector = None
                embedding = None
                
                summary_data = generate_summary(content)

                if isinstance(summary_data, str):
                    summary = summary_data
                elif isinstance(summary_data, dict) and summary_data:
                    summary = summary_data.get("summary", "")

                    # Extract ticker and sector
                    tickers = summary_data.get("tickers", [])
                    sectors = summary_data.get("sectors", [])

                    extracted_tickers = []
                    if tickers:
                        from research_utils import validate_ticker_format, normalize_ticker
                        for t in tickers:
                            if not validate_ticker_format(t):
                                continue
                            normalized = normalize_ticker(t)
                            if normalized and normalized not in extracted_tickers:
                                extracted_tickers.append(normalized)

                    if extracted_tickers:
                        extracted_ticker = extracted_tickers[0]
                        logger.info(f"  🎯 Discovered ticker: {extracted_ticker}")

                    if sectors:
                        extracted_sector = sectors[0]

                    market_relevance = summary_data.get("market_relevance") if isinstance(summary_data, dict) else None
                    if not extracted_ticker and market_relevance == "NOT_MARKET_RELATED":
                        reason = summary_data.get("market_relevance_reason", "")
                        articles_irrelevant += 1
                        logger.info(
                            f"  🚫 Skipping non-market opportunity: {title[:50]}... "
                            f"Reason: {reason or 'No market relevance detected'}"
                        )
                        continue

                # Embedding is Ollama-only
                if ollama_client:
                    embedding = ollama_client.generate_embedding(content[:6000])
                
                # Extract logic_check for relationship confidence scoring
                logic_check = summary_data.get("logic_check") if isinstance(summary_data, dict) else None
                
                # Save article with opportunity_discovery type
                article_id = research_repo.save_article(
                    tickers=[extracted_ticker] if extracted_ticker else None,
                    sector=extracted_sector,
                    article_type="Opportunity Discovery",  # Special tag
                    title=extracted.get('title') or title,
                    url=url,
                    summary=summary,
                    content=content,
                    source=extracted.get('source'),
                    published_at=extracted.get('published_at'),
                    relevance_score=0.7,  # Moderate-high relevance
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
                    logger.info(f"  ✅ Saved opportunity: {title[:30]}")
                    
                    # Extract and save relationships (GraphRAG edges)
                    if isinstance(summary_data, dict) and logic_check and logic_check != "HYPE_DETECTED":
                        relationships = summary_data.get("relationships", [])
                        if relationships and isinstance(relationships, list):
                            # Calculate initial confidence based on logic_check
                            if logic_check == "DATA_BACKED":
                                initial_confidence = 0.8
                            else:  # NEUTRAL
                                initial_confidence = 0.4
                            
                            # Normalize and save each relationship
                            from research_utils import normalize_relationship
                            relationships_saved = 0
                            for rel in relationships:
                                if isinstance(rel, dict):
                                    source = rel.get("source", "").strip()
                                    target = rel.get("target", "").strip()
                                    rel_type = rel.get("type", "").strip()
                                    
                                    if source and target and rel_type:
                                        # Normalize relationship direction (Option A: Supplier -> Buyer)
                                        norm_source, norm_target, norm_type = normalize_relationship(source, target, rel_type)
                                        
                                        # Save relationship
                                        rel_id = research_repo.save_relationship(
                                            source_ticker=norm_source,
                                            target_ticker=norm_target,
                                            relationship_type=norm_type,
                                            initial_confidence=initial_confidence,
                                            source_article_id=article_id
                                        )
                                        if rel_id:
                                            relationships_saved += 1
                            
                            if relationships_saved > 0:
                                logger.info(f"  ✅ Saved {relationships_saved} relationship(s) from opportunity article: {title[:30]}")
                
                articles_processed += 1
                
                # Delay between articles
                time.sleep(1)
                
            except Exception as e:
                logger.error(f"Error processing discovery article: {e}")
                continue
        
        duration_ms = int((time.time() - start_time) * 1000)
        message = (
            f"Query: '{selected_query[:50]}...' - Processed {articles_processed}: {articles_saved} saved, "
            f"{articles_skipped} skipped, {articles_blacklisted} blacklisted, {articles_irrelevant} non-market"
        )
        log_job_execution(job_id, success=True, message=message, duration_ms=duration_ms)
        try:
            mark_job_completed(job_id, target_date, None, [], duration_ms=duration_ms)
        except:
            pass
        logger.info(f"✅ {message}")
        
    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        message = f"Error: {str(e)}"
        log_job_execution(job_id, success=False, message=message, duration_ms=duration_ms)
        try:
            mark_job_failed(job_id, target_date, None, message, duration_ms=duration_ms)
        except:
            pass
        logger.error(f"❌ Opportunity discovery job failed: {e}", exc_info=True)


