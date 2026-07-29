"""
Newsletter AI Processing Job
=============================

Processes newly-ingested newsletters that don't yet have an AI summary.
Runs every 10 minutes so newsletters are summarized shortly after arrival
without blocking the Mailgun webhook.
"""

import logging
import time
from datetime import UTC, datetime
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


def _has_summary_value(row: dict) -> bool:
    s = row.get("summary")
    return s is not None and str(s).strip() != ""


def newsletter_ai_processing_job() -> None:
    """Process newsletters that are missing AI summaries.

    For each newsletter without a summary:
    1. Clean the body text (strip forwarded-message headers, invisible chars)
    2. Generate an AI summary via Ollama (with tickers, sentiment, etc.)
    3. Re-extract tickers using the cleaned text
    4. Generate a vector embedding for semantic search
    5. Update the database record

    The job is idempotent — it touches rows where the summary is missing
    (``NULL`` or empty string) or the embedding is missing. Treating an empty
    summary as missing is important: a prior pipeline failure can leave
    ``summary = ''`` on a row that already has an embedding, which the UI
    surfaces as a permanent "Embedded" badge instead of "Processed".
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
    skipped = 0

    try:
        from utils.job_tracking import mark_job_started, mark_job_completed, mark_job_failed
        target_date = datetime.now(UTC).date()
        mark_job_started(job_id, target_date)

        from newsletter_repository import NewsletterRepository
        from newsletter_service import NewsletterService, run_newsletter_ai_pipeline
        from ollama_client import generate_summary

        repo = NewsletterRepository()
        service = NewsletterService()

        # Fetch newsletters that are not fully processed yet (limit batch size).
        # A row is "pending" if its summary is missing/empty OR its embedding
        # is missing. The empty-string case matters: prior runs sometimes saved
        # `summary = ''` after a failed Ollama call, which `summary IS NULL`
        # alone would skip forever.
        pending_query = """
            SELECT id, subject, body_plain, body_html, received_at, summary,
                   (embedding IS NULL) AS embedding_is_null
            FROM newsletters
            WHERE summary IS NULL
               OR TRIM(COALESCE(summary, '')) = ''
               OR embedding IS NULL
            ORDER BY received_at ASC
            LIMIT 10
        """
        rows = repo.client.execute_query(pending_query, ())

        if not rows:
            duration_ms = int((time.time() - start_time) * 1000)
            logger.info("📰 Newsletter AI job: no pending newsletters to process.")
            log_job_execution(job_id, success=True,
                              message="No pending newsletters", duration_ms=duration_ms)
            mark_job_completed(
                job_id,
                target_date,
                None,
                [],
                duration_ms=duration_ms,
                message="No pending newsletters",
            )
            return

        now = datetime.now(UTC)
        summary_missing = sum(1 for r in rows if not _has_summary_value(r))
        embedding_only = sum(
            1 for r in rows if _has_summary_value(r) and r.get("embedding_is_null")
        )
        received_dates = [r["received_at"] for r in rows if r.get("received_at")]
        oldest = min(received_dates) if received_dates else None
        oldest_age_min = 0.0
        oldest_iso = ""
        if oldest is not None:
            if isinstance(oldest, datetime) and oldest.tzinfo is None:
                oldest = oldest.replace(tzinfo=UTC)
            if isinstance(oldest, datetime):
                oldest_iso = oldest.isoformat()
                oldest_age_min = (now - oldest.astimezone(UTC)).total_seconds() / 60.0
            else:
                oldest_iso = str(oldest)

        logger.info(
            "newsletter_ai_processing batch: pending=%d summary_missing=%d "
            "embedding_only_missing=%d oldest_received_at=%s oldest_age_min=%.1f",
            len(rows),
            summary_missing,
            embedding_only,
            oldest_iso or "n/a",
            oldest_age_min,
        )

        for row in rows:
            nl_id = str(row["id"])
            subject = row.get("subject") or "(No subject)"
            try:
                content = row.get("body_plain") or ""
                src = "plain"
                if not content and row.get("body_html"):
                    content = service.extract_text_from_html(row["body_html"])
                    src = "html"

                t_ce = time.perf_counter()
                NewsletterService.log_step(
                    nl_id,
                    "content_extract",
                    "start",
                    source=src,
                    pipeline_source="scheduled_job",
                )
                pre_len = len(content or "")
                content = service.clean_forwarded_body(content)
                NewsletterService.log_step(
                    nl_id,
                    "content_extract",
                    "ok" if (content or "").strip() else "skip",
                    duration_ms=int((time.perf_counter() - t_ce) * 1000),
                    chars_pre_clean=pre_len,
                    chars_after_clean=len(content or ""),
                    source=src,
                    pipeline_source="scheduled_job",
                )

                if not (content or "").strip():
                    NewsletterService.log_step(
                        nl_id,
                        "body_clean",
                        "skip",
                        reason="empty_after_clean",
                        pipeline_source="scheduled_job",
                    )
                    logger.warning(f"Newsletter {nl_id} has no content — skipping.")
                    skipped += 1
                    continue

                NewsletterService.log_step(
                    nl_id,
                    "body_clean",
                    "ok",
                    chars=len(content),
                    pipeline_source="scheduled_job",
                )

                run_newsletter_ai_pipeline(
                    nl_id,
                    content=content,
                    subject=subject,
                    service=service,
                    repo=repo,
                    generate_summary=generate_summary,
                    pipeline_source="scheduled_job",
                    include_subject_in_update=True,
                )

                processed += 1
                clean_subj = service.clean_subject(subject)
                logger.info(f"✅ Newsletter {nl_id} summarized: {clean_subj[:60]}")

            except Exception as e:
                failed += 1
                logger.error(f"❌ Error processing newsletter {nl_id}: {e}", exc_info=True)

        duration_ms = int((time.time() - start_time) * 1000)
        msg = (
            f"processed={processed} failed={failed} skipped={skipped} "
            f"of={len(rows)} newsletters"
        )
        logger.info(
            "newsletter_ai_processing complete: %s duration_ms=%d",
            msg,
            duration_ms,
        )
        log_job_execution(job_id, success=(failed == 0), message=msg, duration_ms=duration_ms)
        mark_job_completed(
            job_id,
            target_date,
            None,
            [],
            duration_ms=duration_ms,
            message=msg,
        )

    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        logger.error(f"❌ Newsletter AI job failed: {e}", exc_info=True)
        log_job_execution(job_id, success=False, message=str(e), duration_ms=duration_ms)
        try:
            from utils.job_tracking import mark_job_failed
            mark_job_failed(job_id, target_date, None, str(e), duration_ms=duration_ms)
        except Exception:
            pass
