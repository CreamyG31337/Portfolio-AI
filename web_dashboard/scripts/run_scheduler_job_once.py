#!/usr/bin/env python3
"""Run a single registered scheduler job once (manual / ops).

Uses the same sys.path order as app.py (repo root + web_dashboard) and loads
``web_dashboard/.env`` when python-dotenv is available.

Examples (from repo root, venv activated)::

    python web_dashboard/scripts/run_scheduler_job_once.py ui_ai_summaries
    python web_dashboard/scripts/run_scheduler_job_once.py market_daily_brief

PowerShell::

    .\\venv\\Scripts\\Activate.ps1
    python web_dashboard\\scripts\\run_scheduler_job_once.py ui_ai_summaries
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path


def _configure_paths() -> Path:
    script = Path(__file__).resolve()
    web_dashboard_root = script.parent.parent
    project_root = web_dashboard_root.parent
    if str(web_dashboard_root) not in sys.path:
        sys.path.insert(0, str(web_dashboard_root))
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    return web_dashboard_root


def _wait_for_ai_lock(max_wait_sec: int, log: logging.Logger) -> bool:
    """Poll until no AI job is running, or timeout. Returns True if lock cleared."""
    if max_wait_sec <= 0:
        return True
    from utils.job_tracking import get_running_ai_job

    deadline = time.time() + max_wait_sec
    while time.time() < deadline:
        running = get_running_ai_job()
        if not running:
            return True
        remaining = int(deadline - time.time())
        log.info("Waiting for AI lock (%s), up to %ss left...", running, remaining)
        time.sleep(min(30, max(5, remaining)))
    return get_running_ai_job() is None


def _load_env(web_dashboard_root: Path) -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    env_path = web_dashboard_root / ".env"
    if env_path.is_file():
        load_dotenv(env_path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one scheduler job function once.")
    parser.add_argument(
        "job",
        choices=(
            "ui_ai_summaries",
            "market_daily_brief",
            "ticker_analysis",
            "ticker_meta_analysis",
            "sector_meta_analysis",
            "etf_group_analysis",
            "benchmark_refresh",
        ),
        help="Job id / function to invoke",
    )
    parser.add_argument(
        "--wait-ai-lock",
        type=int,
        default=0,
        metavar="SECONDS",
        help="Wait up to N seconds for the global AI lock to clear before running",
    )
    parser.add_argument(
        "--ignore-ai-lock",
        action="store_true",
        help="Run even if another AI job is marked running (use when multiple LLM backends are free)",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    log = logging.getLogger("run_scheduler_job_once")

    web_root = _configure_paths()
    _load_env(web_root)

    log.info("Starting manual run: %s", args.job)

    queue_managed = False
    try:
        from utils.job_tracking import is_queue_managed_job

        queue_managed = is_queue_managed_job(args.job)
    except Exception:
        # Fall back to the worker-pool helper so this script still works if
        # utils/job_tracking is unavailable (e.g. partial sys.path setup).
        try:
            from scheduler.ai_task_workers import is_ai_queue_job_enabled

            queue_managed = is_ai_queue_job_enabled(args.job)
        except Exception:
            queue_managed = False

    if queue_managed:
        os.environ["AI_QUEUE_ENQUEUED_BY"] = "manual"
        log.info("Job %s is AI queue-managed; skipping global AI lock wait/check", args.job)
        # Don't silently drop the flags — record exactly what was ignored so
        # ops can see why the wait/skip behavior changed.
        if args.wait_ai_lock:
            log.info(
                "Ignoring --wait-ai-lock=%ss for queue-managed job %s",
                args.wait_ai_lock,
                args.job,
            )
        if args.ignore_ai_lock:
            log.info(
                "Ignoring --ignore-ai-lock for queue-managed job %s (already not gated)",
                args.job,
            )
    elif not args.ignore_ai_lock:
        if args.wait_ai_lock and not _wait_for_ai_lock(args.wait_ai_lock, log):
            log.error("Timed out waiting for AI lock after %ss", args.wait_ai_lock)
            return 1
        from utils.job_tracking import get_running_ai_job

        blocking = get_running_ai_job()
        if blocking:
            log.error(
                "AI lock held by %s. Use --wait-ai-lock SECONDS or --ignore-ai-lock if another LLM is free.",
                blocking,
            )
            return 1
    else:
        log.warning("Ignoring global AI lock (--ignore-ai-lock)")

    try:
        if args.job == "ui_ai_summaries":
            from scheduler.jobs_ui_ai_summaries import ui_ai_summaries_job

            ui_ai_summaries_job()
        elif args.job == "market_daily_brief":
            from scheduler.jobs_dashboard_research import market_daily_brief_job

            market_daily_brief_job()
        elif args.job == "ticker_analysis":
            from scheduler.jobs_ticker_analysis import ticker_analysis_job

            ticker_analysis_job()
        elif args.job == "ticker_meta_analysis":
            from scheduler.jobs_ticker_meta_analysis import ticker_meta_analysis_job

            ticker_meta_analysis_job()
        elif args.job == "sector_meta_analysis":
            if args.ignore_ai_lock:
                os.environ["SECTOR_META_IGNORE_AI_LOCK"] = "1"
            from scheduler.jobs_sector_meta_analysis import sector_meta_analysis_job

            sector_meta_analysis_job()
        elif args.job == "etf_group_analysis":
            from scheduler.jobs_etf_analysis import etf_group_analysis_job

            etf_group_analysis_job()
        else:
            from scheduler.jobs_metrics import benchmark_refresh_job

            benchmark_refresh_job()
    except Exception as exc:
        log.exception("Job %s failed: %s", args.job, exc)
        return 1

    log.info("Finished manual run: %s", args.job)
    return 0


if __name__ == "__main__":
    sys.exit(main())
