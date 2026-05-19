#!/usr/bin/env python3
"""One-command catch-up: ETF group articles → sector meta synthesis.

Use when Sector Insights is stale or after deploy/outage. Holdings data lives in Research;
this only builds the AI articles and sector rollup on top.

Examples (repo root, venv activated)::

    # Default: fill last 14 days of gaps, then refresh sector meta
    python web_dashboard/scripts/backfill_etf_sector_meta.py

    # Lighter pass (7 days) or deeper after long outage (30 days)
    python web_dashboard/scripts/backfill_etf_sector_meta.py --lookback-days 30 --max-runs 30

    # See gaps only
    python web_dashboard/scripts/backfill_etf_sector_meta.py --report-only
"""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

_script = Path(__file__).resolve()
_web_root = _script.parent.parent
_project_root = _web_root.parent
sys.path.insert(0, str(_project_root))
sys.path.insert(0, str(_web_root))

from dotenv import load_dotenv

load_dotenv(_web_root / ".env")

from etf_meta_pipeline import (  # noqa: E402
    count_missing_etf_article_pairs,
    print_gap_table,
)
from postgres_client import PostgresClient  # noqa: E402


def _run_scheduler_job(
    job: str,
    wait_ai_lock: int,
    ignore_ai_lock: bool,
) -> int:
    """Invoke run_scheduler_job_once.py (same path/env as manual ops)."""
    runner = _web_root / "scripts" / "run_scheduler_job_once.py"
    cmd = [sys.executable, str(runner), job, "--wait-ai-lock", str(wait_ai_lock)]
    if ignore_ai_lock:
        cmd.append("--ignore-ai-lock")
    env = os.environ.copy()
    env.setdefault("ETF_GROUP_QUEUE_LOOKBACK_DAYS", os.getenv("ETF_GROUP_QUEUE_LOOKBACK_DAYS", "14"))
    result = subprocess.run(
        cmd,
        cwd=str(_project_root),
        env=env,
    )
    return int(result.returncode)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Backfill ETF Analysis articles and refresh sector meta synthesis.",
    )
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=int(os.getenv("ETF_GROUP_QUEUE_LOOKBACK_DAYS", "14")),
        help="Calendar days of holdings changes to ensure have ETF articles (default: 14)",
    )
    parser.add_argument(
        "--max-runs",
        type=int,
        default=20,
        help="Max etf_group_analysis invocations (6 ETFs per run; default 20)",
    )
    parser.add_argument(
        "--wait-ai-lock",
        type=int,
        default=600,
        metavar="SECONDS",
        help="Wait for global AI lock before each job (default 600)",
    )
    parser.add_argument(
        "--ignore-ai-lock",
        action="store_true",
        help="Run even if another AI job is marked running",
    )
    parser.add_argument(
        "--skip-sector-meta",
        action="store_true",
        help="Only backfill ETF articles; do not run sector_meta_analysis",
    )
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="Print gap table and exit",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    log = logging.getLogger("backfill_etf_sector_meta")

    pc = PostgresClient()
    lookback = max(1, args.lookback_days)

    print_gap_table(pc, lookback)
    missing = count_missing_etf_article_pairs(pc, lookback)
    if args.report_only:
        runs = (missing + 5) // 6
        print(f"\nEstimated etf_group runs needed (@ 6/run): ~{runs}")
        return 0

    if missing == 0:
        log.info("No missing ETF articles in last %s days.", lookback)
    else:
        log.info(
            "Backfilling ~%s missing (etf, date) pairs (max %s etf_group runs)...",
            missing,
            args.max_runs,
        )
        # Widen queue window for this process
        os.environ["ETF_GROUP_QUEUE_LOOKBACK_DAYS"] = str(lookback)
        os.environ["ETF_GROUP_QUEUE_MAX_LOOKBACK_DAYS"] = str(max(lookback, 30))

        for run_idx in range(1, args.max_runs + 1):
            missing_before = count_missing_etf_article_pairs(pc, lookback)
            if missing_before == 0:
                log.info("All gaps filled after %s run(s).", run_idx - 1)
                break
            log.info(
                "=== etf_group_analysis run %s/%s (%s pairs remaining) ===",
                run_idx,
                args.max_runs,
                missing_before,
            )
            rc = _run_scheduler_job("etf_group_analysis", args.wait_ai_lock, args.ignore_ai_lock)
            if rc != 0:
                return rc
            missing_after = count_missing_etf_article_pairs(pc, lookback)
            if missing_after >= missing_before:
                log.warning(
                    "No progress this run (%s → %s). Stopping.",
                    missing_before,
                    missing_after,
                )
                break
        else:
            log.warning(
                "Stopped at --max-runs=%s; %s pairs still missing. Re-run this script or wait for nightly jobs.",
                args.max_runs,
                count_missing_etf_article_pairs(pc, lookback),
            )

    if not args.skip_sector_meta:
        log.info("=== sector_meta_analysis (refresh Sector Insights) ===")
        rc = _run_scheduler_job("sector_meta_analysis", args.wait_ai_lock, args.ignore_ai_lock)
        if rc != 0:
            return rc

    print_gap_table(pc, lookback)
    log.info("Done. Check ETF Holdings → Sector Insights in the dashboard.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
