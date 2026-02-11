"""
Article Relevance Validation Job
=================================

Overnight batch job that validates ticker assignments on research articles
using GLM 4.5-air.  Articles are tagged with tickers during scraping via AI
extraction, but this is imperfect (e.g. "PRE" articles matching "Preat"
content).  This job reviews unvalidated articles and cleans up incorrect
ticker tags at the source.
"""

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
import sys

import requests

# Path setup (same pattern as other scheduler jobs)
current_dir = Path(__file__).resolve().parent
web_dashboard_path = str(current_dir.parent)
if web_dashboard_path not in sys.path:
    sys.path.insert(0, web_dashboard_path)
project_root = str(current_dir.parent.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)
elif sys.path[0] != project_root:
    sys.path.remove(project_root)
    sys.path.insert(0, project_root)

from scheduler.scheduler_core import log_job_execution

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BATCH_SIZE = 10          # Articles per GLM call
MAX_ARTICLES_PER_RUN = 200   # Total articles to process per run
LOOKBACK_DAYS = 90       # Only validate articles from the last N days
GLM_MODEL = "glm-4.5-air"   # Fast/cheap model for classification
GLM_MAX_TOKENS = 4096    # Needs headroom for reasoning chain + JSON output
GLM_TIMEOUT = 120        # seconds
DELAY_BETWEEN_BATCHES = 2    # seconds


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def article_relevance_job() -> None:
    """Validate ticker assignments on research articles using GLM 4.5-air.

    1. Fetches unvalidated articles (ticker_validated_at IS NULL)
    2. Groups into batches of BATCH_SIZE
    3. For each batch, asks GLM which tickers are genuinely relevant
    4. Updates tickers array and sets ticker_validated_at
    """
    job_id = "article_relevance"
    start_time = time.time()

    try:
        from utils.job_tracking import (
            mark_job_started,
            mark_job_completed,
            mark_job_failed,
        )

        logger.info("Starting article relevance validation job...")
        target_date = datetime.now(timezone.utc).date()
        mark_job_started(job_id, target_date)

        # Lazy imports
        from glm_config import get_zhipu_api_key, ZHIPU_BASE_URL
        from postgres_client import PostgresClient

        api_key = get_zhipu_api_key()
        if not api_key:
            duration_ms = int((time.time() - start_time) * 1000)
            msg = "GLM API key not available. Set ZHIPU_API_KEY or save via AI Settings."
            mark_job_failed(job_id, target_date, None, msg, duration_ms=duration_ms)
            logger.error(f"❌ {msg}")
            return

        pg = PostgresClient()

        # ---------------------------------------------------------------
        # 0. Auto-validate ETF articles (tickers from CSV/XLS, always correct)
        # ---------------------------------------------------------------
        etf_validated = pg.execute_update("""
            UPDATE research_articles
            SET ticker_validated_at = NOW()
            WHERE ticker_validated_at IS NULL
              AND tickers IS NOT NULL
              AND article_type = 'ETF Change'
        """)
        if etf_validated:
            logger.info(
                "Auto-validated %d ETF Change articles (tickers from holdings data)",
                etf_validated,
            )

        # ---------------------------------------------------------------
        # 1. Fetch unvalidated articles
        # ---------------------------------------------------------------
        # ETF Change articles already handled above
        articles = pg.execute_query("""
            SELECT id, title, summary, tickers
            FROM research_articles
            WHERE ticker_validated_at IS NULL
              AND tickers IS NOT NULL
              AND fetched_at >= NOW() - INTERVAL '%s days'
              AND COALESCE(article_type, '') != 'ETF Change'
            ORDER BY fetched_at DESC
            LIMIT %s
        """, (LOOKBACK_DAYS, MAX_ARTICLES_PER_RUN))

        if not articles:
            duration_ms = int((time.time() - start_time) * 1000)
            msg = "No unvalidated articles to process"
            try:
                log_job_execution(job_id, True, msg, duration_ms)
                mark_job_completed(
                    job_id, target_date, None, [],
                    duration_ms=duration_ms, message=msg,
                )
            except Exception:
                pass
            logger.info(f"✅ {msg}")
            return

        logger.info(f"Found {len(articles)} unvalidated articles to process")

        # ---------------------------------------------------------------
        # 2. Process in batches
        # ---------------------------------------------------------------
        processed = 0
        cleaned = 0
        errors = 0
        glm_calls = 0

        for batch_start in range(0, len(articles), BATCH_SIZE):
            batch = articles[batch_start : batch_start + BATCH_SIZE]

            try:
                result = _validate_batch(batch, api_key, ZHIPU_BASE_URL)
                glm_calls += 1

                if result is None:
                    # GLM call failed for this batch -- mark as validated
                    # anyway so we don't retry forever, but keep original tickers
                    for article in batch:
                        _mark_validated(pg, str(article["id"]))
                        processed += 1
                    errors += 1
                    continue

                # Apply results
                for article in batch:
                    article_id = str(article["id"])
                    idx_str = str(batch.index(article) + 1)
                    validated_tickers = result.get(idx_str)

                    if validated_tickers is None:
                        # GLM didn't return a result for this article
                        _mark_validated(pg, article_id)
                        processed += 1
                        continue

                    original = article.get("tickers") or []
                    if not isinstance(validated_tickers, list):
                        _mark_validated(pg, article_id)
                        processed += 1
                        continue

                    # Normalize to uppercase strings
                    validated_tickers = [
                        str(t).upper().strip()
                        for t in validated_tickers
                        if isinstance(t, str) and t.strip()
                    ]

                    # Check if tickers changed
                    orig_set = set(original)
                    valid_set = set(validated_tickers)
                    removed = orig_set - valid_set

                    if removed:
                        cleaned += 1
                        logger.info(
                            "Article %s: removed tickers %s (kept %s)",
                            article_id,
                            removed,
                            valid_set or "none",
                        )
                    else:
                        logger.info(
                            "Article %s: ✓ all %d tickers confirmed %s",
                            article_id,
                            len(valid_set),
                            valid_set,
                        )

                    _update_article_tickers(
                        pg, article_id, validated_tickers, removed_any=bool(removed)
                    )
                    processed += 1

            except Exception as batch_err:
                logger.warning(
                    "Batch starting at %d failed: %s", batch_start, batch_err
                )
                errors += 1
                # Still mark these as validated so we don't retry forever
                for article in batch:
                    try:
                        _mark_validated(pg, str(article["id"]))
                        processed += 1
                    except Exception:
                        pass

            # Delay between batches to avoid rate limiting
            if batch_start + BATCH_SIZE < len(articles):
                time.sleep(DELAY_BETWEEN_BATCHES)

        # ---------------------------------------------------------------
        # 3. Report
        # ---------------------------------------------------------------
        duration_ms = int((time.time() - start_time) * 1000)
        msg = (
            f"Validated {processed} articles ({cleaned} cleaned, "
            f"{errors} batch errors, {glm_calls} GLM calls)"
        )
        try:
            log_job_execution(job_id, True, msg, duration_ms)
            mark_job_completed(
                job_id, target_date, None, [],
                duration_ms=duration_ms, message=msg,
            )
        except Exception as log_err:
            logger.warning(f"Failed to log job execution: {log_err}")

        logger.info(f"✅ Article relevance job complete: {msg}")

    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        msg = f"Job failed: {e}"
        try:
            from utils.job_tracking import mark_job_failed
            mark_job_failed(job_id, target_date, None, str(e), duration_ms=duration_ms)
            log_job_execution(job_id, False, msg, duration_ms)
        except Exception:
            pass
        logger.error(f"❌ {msg}", exc_info=True)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _validate_batch(
    batch: List[Dict[str, Any]],
    api_key: str,
    base_url: str,
) -> Optional[Dict[str, List[str]]]:
    """Send a batch of articles to GLM 4.5-air for ticker validation.

    Returns a dict mapping 1-based article index (as string) to a list of
    validated tickers, or None if the call fails entirely.
    """
    # Build the numbered article list
    lines: list[str] = []
    for idx, article in enumerate(batch, start=1):
        title = (article.get("title") or "Untitled")[:150]
        summary = (article.get("summary") or "")[:200].replace("\n", " ")
        tickers = article.get("tickers") or []
        ticker_str = ", ".join(tickers) if tickers else "none"
        lines.append(f'{idx}. Tickers: [{ticker_str}] | "{title}" - {summary}')

    article_list = "\n".join(lines)

    prompt = (
        "You are validating ticker symbol assignments on research articles.\n"
        "Each article below has been automatically tagged with stock ticker symbols. "
        "Some of these tags may be WRONG -- the article might mention a similarly-named "
        "company or use an abbreviation that was mistaken for a ticker.\n\n"
        "For each article, review the title and summary and decide which of the assigned "
        "tickers are GENUINELY about that company or directly relevant. "
        "Remove any tickers that are clearly about a different company.\n\n"
        f"Articles:\n{article_list}\n\n"
        "Return ONLY a JSON object mapping article number to its validated tickers list. "
        "Example: {\"1\": [\"AAPL\"], \"2\": [], \"3\": [\"MSFT\", \"GOOG\"]}\n"
        "If an article has no relevant tickers, return an empty list for it."
    )

    system_prompt = (
        "You are a financial data quality analyst. "
        "Return ONLY valid JSON, no markdown or explanation."
    )

    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": GLM_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.0,
        "max_tokens": GLM_MAX_TOKENS,
    }

    # Retry with backoff for rate limiting
    max_retries = 3
    base_delay = 10

    for attempt in range(max_retries):
        try:
            response = requests.post(
                url, json=payload, headers=headers, timeout=GLM_TIMEOUT
            )

            if response.status_code == 429:
                if attempt < max_retries - 1:
                    delay = base_delay * (2 ** attempt)
                    logger.warning(
                        "GLM rate limited (429). Waiting %ds before retry...", delay
                    )
                    time.sleep(delay)
                    continue
                else:
                    logger.error("GLM rate limited after %d retries", max_retries)
                    return None

            response.raise_for_status()

            data = response.json()
            choices = data.get("choices") or []
            if not choices:
                logger.warning("GLM returned empty choices")
                return None

            content = (choices[0].get("message") or {}).get("content", "")
            if not content:
                logger.warning("GLM returned empty content")
                return None

            # Parse JSON from response (strip markdown fences if present)
            content = content.strip()
            if content.startswith("```"):
                # Strip ```json ... ```
                content = content.split("\n", 1)[-1] if "\n" in content else content
                if content.endswith("```"):
                    content = content[:-3]
                content = content.strip()

            result = json.loads(content)
            if isinstance(result, dict):
                return result
            logger.warning("GLM returned non-dict JSON: %s", type(result))
            return None

        except json.JSONDecodeError as e:
            logger.warning("Failed to parse GLM JSON response: %s", e)
            return None
        except requests.exceptions.Timeout:
            logger.warning("GLM request timed out (attempt %d)", attempt + 1)
            if attempt < max_retries - 1:
                time.sleep(base_delay)
                continue
            return None
        except requests.exceptions.ConnectionError as e:
            logger.warning("GLM connection error: %s", e)
            return None
        except Exception as e:
            logger.warning("GLM validation call failed: %s", e)
            return None

    return None


def _mark_validated(pg: Any, article_id: str) -> None:
    """Mark an article as validated without changing its tickers."""
    pg.execute_update(
        "UPDATE research_articles SET ticker_validated_at = NOW() WHERE id = %s",
        (article_id,),
    )


def _update_article_tickers(
    pg: Any,
    article_id: str,
    validated_tickers: List[str],
    removed_any: bool = False,
) -> None:
    """Update an article's tickers and mark as validated."""
    if validated_tickers:
        pg.execute_update(
            "UPDATE research_articles "
            "SET tickers = %s, ticker_validated_at = NOW() "
            "WHERE id = %s",
            (validated_tickers, article_id),
        )
    else:
        # All tickers removed -- clear array and lower relevance score
        pg.execute_update(
            "UPDATE research_articles "
            "SET tickers = NULL, ticker_validated_at = NOW(), "
            "    relevance_score = LEAST(relevance_score, 0.3) "
            "WHERE id = %s",
            (article_id,),
        )
