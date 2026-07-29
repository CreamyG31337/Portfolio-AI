


import logging
import time
import sys
from pathlib import Path
from scheduler.scheduler_core import log_job_execution

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
    from utils.job_tracking import log_job_step

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
        log_job_step(job_id, "init", "Starting opportunity discovery job")
        logger.info("Starting opportunity discovery job...")

        # Import dependencies
        try:
            from searxng_client import get_searxng_client, check_searxng_health
            from ollama_client import get_ollama_client
            from research_repository import ResearchRepository
            from settings import get_discovery_search_queries
        except ImportError as e:
            duration_ms = int((time.time() - start_time) * 1000)
            message = f"Missing dependency: {e}"
            log_job_step(job_id, "init", message, status="failed")
            log_job_execution(job_id, success=False, message=message, duration_ms=duration_ms)
            try:
                mark_job_failed(job_id, target_date, None, message, duration_ms=duration_ms)
            except:
                pass
            logger.error(f"❌ {message}")
            return

        # Check SearXNG health
        log_job_step(job_id, "searxng_check", "Checking SearXNG health...")
        if not check_searxng_health():
            duration_ms = int((time.time() - start_time) * 1000)
            message = "SearXNG is not available - skipping opportunity discovery"
            log_job_step(job_id, "searxng_check", message, status="skipped")
            log_job_execution(job_id, success=True, message=message, duration_ms=duration_ms)
            try:
                mark_job_completed(job_id, target_date, None, [], duration_ms=duration_ms)
            except:
                pass
            logger.info(f"ℹ️ {message}")
            return
        log_job_step(job_id, "searxng_check", "SearXNG is healthy", status="success")

        # Get clients
        searxng_client = get_searxng_client()
        ollama_client = get_ollama_client()

        if not searxng_client:
            duration_ms = int((time.time() - start_time) * 1000)
            message = "SearXNG client not initialized"
            log_job_step(job_id, "init", message, status="failed")
            log_job_execution(job_id, success=False, message=message, duration_ms=duration_ms)
            # Must pair with mark_job_started or the row stays status='running',
            # holds the global AI lock, and is later flipped to a misleading
            # "Auto-cleared stale AI lock" failure. See alpha_research_job's
            # docstring -- same bug, fixed there, missed here.
            mark_job_failed(job_id, target_date, None, message, duration_ms=duration_ms)
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
        from datetime import datetime
        query_index = datetime.now().hour % len(queries)
        selected_query = queries[query_index]

        negative_keywords = "-astrology -horoscope -zodiac -restaurant -recipe -celebrity -movie -tv -sports"
        final_query = f"{selected_query} {negative_keywords}"

        log_job_step(job_id, "search", f"Searching: '{selected_query}'")
        logger.info(f"🔭 Discovery Query: '{final_query}'")

        # Search
        search_results = searxng_client.search_news(
            query=final_query,
            max_results=8
        )

        if not search_results or not search_results.get('results'):
            duration_ms = int((time.time() - start_time) * 1000)
            message = f"No results for query: {selected_query}"
            log_job_step(job_id, "search", message, status="skipped")
            log_job_execution(job_id, success=True, message=message, duration_ms=duration_ms)
            # A query returning nothing is a correct, intentional no-op -- not an
            # execution error -- so this completes SUCCESSFULLY. Queries rotate by
            # hour, so whether this path is taken varies run to run, which is why
            # the job appeared to fail intermittently (~36% of recent runs) while
            # actually working fine.
            mark_job_completed(job_id, target_date, None, [], duration_ms=duration_ms)
            logger.info(f"ℹ️ {message}")
            return

        total_results = len(search_results['results'])
        log_job_step(job_id, "search", f"Found {total_results} results", status="success")

        articles_processed = 0
        articles_saved = 0
        articles_skipped = 0
        articles_blacklisted = 0
        articles_irrelevant = 0

        # Safety timeouts (avoid runaway jobs)
        MAX_JOB_DURATION = 40 * 60  # 40 minutes total
        MAX_ARTICLE_DURATION = 4 * 60  # 4 minutes per article

        from scheduler.alpha_opportunity_workers import (
            OpportunityDiscoveryCtx,
            process_opportunity_discovery_item,
        )
        from scheduler.article_pipeline import get_research_article_worker_count, run_article_pipeline_parallel

        workers_o = get_research_article_worker_count()
        ctx_opp = OpportunityDiscoveryCtx(
            research_repo=research_repo,
            ollama_client=ollama_client,
            blacklist=blacklist,
            job_id=job_id,
            total_results=total_results,
            max_article_duration=MAX_ARTICLE_DURATION,
            sleep_after_article_sec=0.0 if workers_o > 1 else 1.0,
        )
        indexed_opp = list(enumerate(search_results["results"], 1))
        agg_opp = run_article_pipeline_parallel(
            lambda pair, c=ctx_opp: process_opportunity_discovery_item(c, pair),
            indexed_opp,
            max_workers=workers_o,
            job_start_time=start_time,
            max_job_duration_sec=MAX_JOB_DURATION,
        )
        if (time.time() - start_time) > MAX_JOB_DURATION:
            log_job_step(
                job_id,
                "timeout",
                f"Job timeout reached ({(time.time() - start_time) / 60:.1f}m)",
                status="failed",
            )
            logger.warning(
                "⏱️  Job timeout reached (%.1fm). Stopping opportunity discovery",
                (time.time() - start_time) / 60,
            )

        articles_processed += agg_opp.processed
        articles_saved += agg_opp.saved
        articles_skipped += agg_opp.skipped
        articles_blacklisted += agg_opp.blacklisted
        articles_irrelevant += agg_opp.irrelevant

        duration_ms = int((time.time() - start_time) * 1000)
        message = (
            f"Query: '{selected_query[:50]}...' - Processed {articles_processed}: {articles_saved} saved, "
            f"{articles_skipped} skipped, {articles_blacklisted} blacklisted, {articles_irrelevant} non-market"
        )
        log_job_step(job_id, "complete", message, status="success")
        log_job_execution(job_id, success=True, message=message, duration_ms=duration_ms)
        try:
            mark_job_completed(job_id, target_date, None, [], duration_ms=duration_ms)
        except:
            pass
        logger.info(f"✅ {message}")

    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        message = f"Error: {str(e)}"
        log_job_step(job_id, "fatal", message, status="failed")
        log_job_execution(job_id, success=False, message=message, duration_ms=duration_ms)
        try:
            mark_job_failed(job_id, target_date, None, message, duration_ms=duration_ms)
        except:
            pass
        logger.error(f"❌ Opportunity discovery job failed: {e}", exc_info=True)
