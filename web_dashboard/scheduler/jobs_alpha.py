import time
import logging
from datetime import datetime, timezone

# Add parent directory to path if needed (standard boilerplate for these jobs)
import sys
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

    Job-tracking contract: every code path that runs AFTER ``mark_job_started``
    MUST call exactly one of ``mark_job_completed`` / ``mark_job_failed``
    before returning. Otherwise the ``job_executions`` row stays in
    ``status='running'`` and the stale-lock cleaner in
    ``utils/job_tracking.get_running_ai_job`` eventually marks it as
    ``failed`` ("Auto-cleared stale AI lock") -- which is what was producing
    the false-positive "failed" status the user reported. Skips for
    configuration reasons (no domains/queries, SearXNG offline, no results)
    are treated as **successful** completions because they reflect a
    correct, intentional no-op, not an execution error.
    """
    job_id = 'alpha_research'
    start_time = time.time()
    target_date = datetime.now(timezone.utc).date()
    from utils.job_tracking import log_job_step

    # Global AI lock (SearXNG + Ollama workload). This check runs BEFORE
    # mark_job_started, so an early return here does not leak a running row.
    try:
        from utils.job_tracking import get_running_ai_job
        running_ai = get_running_ai_job(exclude_job_name=job_id)
        if running_ai:
            logger.info(f"⏸️  AI lock active: {running_ai} is running. Skipping {job_id}.")
            return
    except Exception as e:
        logger.warning(f"AI lock check failed (continuing): {e}")

    # Resolve job-tracking utilities up front so every early-return branch
    # below can clear the running lock symmetrically.
    try:
        from scheduler.scheduler_core import log_job_execution
        from utils.job_tracking import (
            mark_job_completed,
            mark_job_failed,
            mark_job_started,
        )
    except ImportError as e:
        # If we cannot import the tracking utilities, we also have no way to
        # leak a running row (mark_job_started never ran), so bail loudly.
        logger.error(
            f"alpha_research: failed to import job tracking utilities: {e}",
            exc_info=True,
        )
        return

    def _finalize_success(message: str) -> None:
        """Successful (or successfully-skipped) completion: clear the lock."""
        duration_ms = int((time.time() - start_time) * 1000)
        try:
            log_job_execution(job_id, success=True, message=message, duration_ms=duration_ms)
        except Exception:
            logger.debug("log_job_execution failed", exc_info=True)
        try:
            mark_job_completed(
                job_id, target_date, None, [], duration_ms=duration_ms, message=message
            )
        except Exception:
            logger.debug("mark_job_completed failed", exc_info=True)

    def _finalize_failure(message: str) -> None:
        """Real execution failure: clear the lock and record the error."""
        duration_ms = int((time.time() - start_time) * 1000)
        try:
            log_job_execution(job_id, success=False, message=message, duration_ms=duration_ms)
        except Exception:
            logger.debug("log_job_execution failed", exc_info=True)
        try:
            mark_job_failed(
                job_id, target_date, None, message, duration_ms=duration_ms
            )
        except Exception:
            logger.debug("mark_job_failed failed", exc_info=True)

    try:
        # Mark started -- from this point on we MUST call _finalize_success
        # or _finalize_failure before returning.
        try:
            mark_job_started(job_id, target_date)
        except Exception:
            logger.debug("mark_job_started failed", exc_info=True)

        log_job_step(job_id, "init", "Starting Alpha Research job")
        logger.info("Starting Alpha Research job...")

        # Import dependencies
        try:
            from searxng_client import get_searxng_client, check_searxng_health
            from ollama_client import get_ollama_client
            from research_repository import ResearchRepository
            from settings import get_alpha_research_domains, get_alpha_search_queries
        except ImportError as e:
            message = f"Missing dependency: {e}"
            log_job_step(job_id, "init", message, status="failed")
            _finalize_failure(message)
            logger.error(f"❌ {message}")
            return

        # Check SearXNG health
        log_job_step(job_id, "searxng_check", "Checking SearXNG health...")
        if not check_searxng_health():
            message = "SearXNG is not available - skipping alpha research"
            log_job_step(job_id, "searxng_check", message, status="skipped")
            # Intentional skip, not an execution failure.
            _finalize_success(message)
            logger.info(f"ℹ️ {message}")
            return
        log_job_step(job_id, "searxng_check", "SearXNG is healthy", status="success")

        # Get clients
        searxng_client = get_searxng_client()
        ollama_client = get_ollama_client()

        if not searxng_client:
            message = "SearXNG client not initialized"
            log_job_step(job_id, "init", message, status="failed")
            _finalize_failure(message)
            logger.error(f"❌ {message}")
            return

        # Initialize research repository
        research_repo = ResearchRepository()

        # Load config
        domains = get_alpha_research_domains()
        queries = get_alpha_search_queries()

        if not domains or not queries:
            # Config-driven skip -- a clean no-op, not a failure. This is the
            # specific path that was leaving running rows for the stale-lock
            # cleaner to clobber as "failed".
            message = "No alpha domains or queries configured"
            log_job_step(job_id, "init", message, status="skipped")
            _finalize_success(message)
            logger.warning(message)
            return

        logger.info(f"Using {len(domains)} alpha domains and {len(queries)} queries")

        # Construct Search Dorks
        site_dork = " OR ".join([f"site:{d}" for d in domains])

        # Rotate queries based on hour to avoid hammering
        query_index = datetime.now().hour % len(queries)
        base_query = queries[query_index]

        # Full query with site restrictions
        negative_keywords = "-astrology -horoscope -zodiac -restaurant -recipe -celebrity -movie -tv -sports"
        final_query = f'{base_query} ({site_dork}) {negative_keywords}'

        log_job_step(job_id, "search", f"Searching: '{base_query}'")
        logger.info(f"🔭 Alpha Query: '{final_query}'")

        # Search
        search_results = searxng_client.search_news(
            query=final_query,
            max_results=10  # Get decent chunk
        )

        if not search_results or not search_results.get('results'):
            message = f"No results for alpha query: {base_query}"
            log_job_step(job_id, "search", message, status="skipped")
            _finalize_success(message)
            logger.info(f"ℹ️ {message}")
            return

        total_results = len(search_results['results'])
        log_job_step(job_id, "search", f"Found {total_results} results", status="success")

        articles_processed = 0
        articles_saved = 0
        articles_skipped = 0
        articles_irrelevant = 0

        # Safety timeouts (avoid runaway jobs)
        MAX_JOB_DURATION = 40 * 60  # 40 minutes total
        MAX_ARTICLE_DURATION = 4 * 60  # 4 minutes per article

        # Load blacklist for safety (even though we are targeting specific sites, redundancy is good)
        from settings import get_research_domain_blacklist
        blacklist = get_research_domain_blacklist()

        from scheduler.alpha_opportunity_workers import AlphaResearchCtx, process_alpha_research_item
        from scheduler.article_pipeline import get_research_article_worker_count, run_article_pipeline_parallel

        workers_n = get_research_article_worker_count()
        ctx_alpha = AlphaResearchCtx(
            research_repo=research_repo,
            ollama_client=ollama_client,
            blacklist=blacklist,
            job_id=job_id,
            total_results=total_results,
            max_article_duration=MAX_ARTICLE_DURATION,
            sleep_after_article_sec=0.0 if workers_n > 1 else 1.0,
        )
        indexed_results = list(enumerate(search_results["results"], 1))
        agg_alpha = run_article_pipeline_parallel(
            lambda pair, c=ctx_alpha: process_alpha_research_item(c, pair),
            indexed_results,
            max_workers=workers_n,
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
                "⏱️  Job timeout reached (%.1fm). Stopping alpha research",
                (time.time() - start_time) / 60,
            )

        articles_processed += agg_alpha.processed
        articles_saved += agg_alpha.saved
        articles_skipped += agg_alpha.skipped
        articles_irrelevant += agg_alpha.irrelevant

        message = (
            f"Query: '{base_query}' - Processed {articles_processed}: {articles_saved} saved, "
            f"{articles_skipped} skipped, {articles_irrelevant} non-market"
        )
        log_job_step(job_id, "complete", message, status="success")
        _finalize_success(message)
        logger.info(f"✅ {message}")

    except Exception as e:
        message = f"Error: {e!r}"
        log_job_step(job_id, "fatal", message, status="failed")
        _finalize_failure(message)
        logger.error(f"❌ Alpha Research job failed: {e}", exc_info=True)
