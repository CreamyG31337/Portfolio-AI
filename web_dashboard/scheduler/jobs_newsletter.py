"""
Newsletter AI Processing Job
=============================

Processes newly-ingested newsletters that don't yet have an AI summary.
Runs every 10 minutes so newsletters are summarized shortly after arrival
without blocking the Mailgun webhook.
"""

import logging
import time
from datetime import datetime, timezone
from pathlib import Path
import sys

# Add project root and web_dashboard to path (standard boilerplate)
current_dir = Path(__file__).resolve().parent
web_dashboard_path = str(current_dir.parent)
if web_dashboard_path not in sys.path:
    sys.path.insert(0, web_dashboard_path)

project_root = current_dir.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))
elif sys.path[0] != str(project_root):
    sys.path.remove(str(project_root))
    sys.path.insert(0, str(project_root))

from scheduler.scheduler_core import log_job_execution

logger = logging.getLogger(__name__)


def newsletter_ai_processing_job() -> None:
    """Process newsletters that are missing AI summaries.

    For each newsletter without a summary:
    1. Clean the body text (strip forwarded-message headers, invisible chars)
    2. Generate an AI summary via Ollama (with tickers, sentiment, etc.)
    3. Re-extract tickers using the cleaned text
    4. Generate a vector embedding for semantic search
    5. Update the database record

    The job is idempotent — it only touches rows where ``summary IS NULL``.
    """
    job_id = "newsletter_ai_processing"
    start_time = time.time()

    # AI lock — don't overlap with other AI-heavy jobs
    try:
        from utils.job_tracking import get_running_ai_job
        running_ai = get_running_ai_job(exclude_job_name=job_id)
        if running_ai:
            logger.info(f"⏸️  AI lock active: {running_ai} is running. Skipping {job_id}.")
            return
    except Exception as e:
        logger.warning(f"AI lock check failed (continuing): {e}")

    processed = 0
    failed = 0

    try:
        from utils.job_tracking import mark_job_started, mark_job_completed, mark_job_failed
        target_date = datetime.now(timezone.utc).date()
        mark_job_started(job_id, target_date)

        from newsletter_repository import NewsletterRepository
        from newsletter_service import NewsletterService
        from ollama_client import generate_summary

        repo = NewsletterRepository()
        service = NewsletterService()

        # Fetch newsletters that haven't been summarized yet (limit batch size)
        pending_query = """
            SELECT id, subject, body_plain, body_html
            FROM newsletters
            WHERE summary IS NULL
            ORDER BY received_at ASC
            LIMIT 10
        """
        rows = repo.client.execute_query(pending_query, ())

        if not rows:
            duration_ms = int((time.time() - start_time) * 1000)
            logger.info(f"📰 Newsletter AI job: no pending newsletters to process.")
            log_job_execution(job_id, success=True,
                              message="No pending newsletters", duration_ms=duration_ms)
            mark_job_completed(job_id, target_date,
                               message="No pending newsletters", duration_ms=duration_ms)
            return

        logger.info(f"📰 Newsletter AI job: processing {len(rows)} pending newsletter(s)…")

        for row in rows:
            nl_id = str(row["id"])
            subject = row.get("subject") or "(No subject)"
            try:
                # Get content (prefer plain text, fall back to HTML extraction)
                content = row.get("body_plain") or ""
                if not content and row.get("body_html"):
                    content = service.extract_text_from_html(row["body_html"])

                # Clean forwarded body if not already cleaned
                content = service.clean_forwarded_body(content)

                if not content:
                    logger.warning(f"Newsletter {nl_id} has no content — skipping.")
                    continue

                # Generate AI summary
                clean_subj = service.clean_subject(subject)
                summary_input = f"Subject: {clean_subj}\n\n{content}" if clean_subj else content
                summary_data = generate_summary(summary_input, article_type="Newsletter")
                summary = None
                tickers = []
                if isinstance(summary_data, str):
                    summary = summary_data
                elif isinstance(summary_data, dict):
                    summary = summary_data.get("summary", "")
                    tickers = service.sanitize_ai_tickers(summary_data.get("tickers", []))
                    try:
                        from ticker_inference import infer_tickers_from_companies, infer_tickers_from_text
                        tickers = sorted(
                            set(tickers)
                            | set(infer_tickers_from_companies(summary_data.get("companies", [])))
                            | set(infer_tickers_from_text(subject))
                        )
                    except Exception as infer_err:
                        logger.warning(f"Company->ticker inference failed for newsletter {nl_id}: {infer_err}")

                # Also re-extract tickers from cleaned subject+body
                extracted_tickers = service.extract_tickers(f"{clean_subj}\n\n{content}")
                # Merge AI-detected tickers with regex-extracted ones (deduplicated)
                all_tickers = sorted(set(tickers) | set(extracted_tickers)) if tickers else extracted_tickers

                # Generate embedding
                embedding = service.generate_embedding(content)

                # Update database
                update_query = """
                    UPDATE newsletters
                    SET summary = %s,
                        tickers = %s,
                        subject = %s,
                        processed_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                """
                repo.client.execute_update(
                    update_query,
                    (summary, all_tickers if all_tickers else None, clean_subj, nl_id),
                )

                if embedding:
                    repo.update_embedding(nl_id, embedding)

                processed += 1
                logger.info(f"✅ Newsletter {nl_id} summarized: {clean_subj[:60]}")

            except Exception as e:
                failed += 1
                logger.error(f"❌ Error processing newsletter {nl_id}: {e}", exc_info=True)

        duration_ms = int((time.time() - start_time) * 1000)
        msg = f"Processed {processed}, failed {failed} of {len(rows)} newsletters"
        logger.info(f"📰 Newsletter AI job complete: {msg} ({duration_ms}ms)")
        log_job_execution(job_id, success=(failed == 0), message=msg, duration_ms=duration_ms)
        mark_job_completed(job_id, target_date, message=msg, duration_ms=duration_ms)

    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        logger.error(f"❌ Newsletter AI job failed: {e}", exc_info=True)
        log_job_execution(job_id, success=False, message=str(e), duration_ms=duration_ms)
        try:
            from utils.job_tracking import mark_job_failed
            mark_job_failed(job_id, target_date, message=str(e), duration_ms=duration_ms)
        except Exception:
            pass
