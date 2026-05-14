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
import sys
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
            "ticker_meta_analysis",
            "sector_meta_analysis",
            "benchmark_refresh",
        ),
        help="Job id / function to invoke",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    log = logging.getLogger("run_scheduler_job_once")

    web_root = _configure_paths()
    _load_env(web_root)

    log.info("Starting manual run: %s", args.job)

    try:
        if args.job == "ui_ai_summaries":
            from scheduler.jobs_ui_ai_summaries import ui_ai_summaries_job

            ui_ai_summaries_job()
        elif args.job == "market_daily_brief":
            from scheduler.jobs_dashboard_research import market_daily_brief_job

            market_daily_brief_job()
        elif args.job == "ticker_meta_analysis":
            from scheduler.jobs_ticker_meta_analysis import ticker_meta_analysis_job

            ticker_meta_analysis_job()
        elif args.job == "sector_meta_analysis":
            from scheduler.jobs_sector_meta_analysis import sector_meta_analysis_job

            sector_meta_analysis_job()
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
