#!/usr/bin/env python3
"""Clear Executive conflict scores and enqueue them for re-analysis (H6).

Usage (from repo root, venv on):
  python web_dashboard/scripts/rescore_executive_trades.py --dry-run
  python web_dashboard/scripts/rescore_executive_trades.py --clear-only
  python web_dashboard/scripts/rescore_executive_trades.py --enqueue-limit 200
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

_web = Path(__file__).resolve().parent.parent
_repo = _web.parent
for p in (str(_web), str(_repo)):
    if p not in sys.path:
        sys.path.insert(0, p)

from env_loader import load_project_dotenv

load_project_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("rescore_executive_trades")

_PAGE = 1000


def _fetch_executive_ids(supabase, *, scored_only: bool) -> list[int]:
    ids: list[int] = []
    offset = 0
    while True:
        q = (
            supabase.supabase.table("congress_trades")
            .select("id")
            .eq("chamber", "Executive")
            .neq("quality_status", "garbage")
            .order("id")
            .range(offset, offset + _PAGE - 1)
        )
        if scored_only:
            q = q.not_.is_("conflict_score", "null")
        else:
            q = q.is_("conflict_score", "null")
        page = q.execute()
        rows = page.data or []
        ids.extend(int(r["id"]) for r in rows if r.get("id") is not None)
        if len(rows) < _PAGE:
            break
        offset += _PAGE
    return ids


def clear_executive_scores(supabase, *, dry_run: bool) -> int:
    ids = _fetch_executive_ids(supabase, scored_only=True)
    logger.info("Executive trades with scores to clear: %s", f"{len(ids):,}")
    if dry_run or not ids:
        return len(ids)
    cleared = 0
    for i in range(0, len(ids), 100):
        chunk = ids[i : i + 100]
        supabase.supabase.table("congress_trades").update(
            {"conflict_score": None}
        ).in_("id", chunk).execute()
        cleared += len(chunk)
        logger.info("Cleared %s / %s", f"{cleared:,}", f"{len(ids):,}")
    return cleared


def enqueue_executive_nulls(supabase, *, limit: int, dry_run: bool) -> dict:
    from scheduler.ai_task_workers import (
        AIQueueConfig,
        enqueue_congress_trade_analysis_tasks,
    )

    ids = _fetch_executive_ids(supabase, scored_only=False)
    ids = ids[: max(0, limit)]
    logger.info("Executive NULL scores to enqueue (capped): %s", f"{len(ids):,}")
    if dry_run or not ids:
        return {"enqueued": 0, "attempted": len(ids), "failed": 0, "dry_run": dry_run}
    config = AIQueueConfig.from_env()
    # Priority above cron catch-up (10) so H6 drain runs first.
    return enqueue_congress_trade_analysis_tasks(
        supabase,
        ids,
        priority=20,
        enqueued_by="rescore_executive_trades",
        max_attempts=config.max_attempts,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--clear-only",
        action="store_true",
        help="Only NULL Executive conflict_score; do not enqueue",
    )
    parser.add_argument(
        "--enqueue-only",
        action="store_true",
        help="Only enqueue existing NULL Executive rows (no clear)",
    )
    parser.add_argument(
        "--enqueue-limit",
        type=int,
        default=500,
        help="Max Executive NULLs to enqueue (default 500)",
    )
    args = parser.parse_args()

    from supabase_client import SupabaseClient

    supabase = SupabaseClient(use_service_role=True)

    if not args.enqueue_only:
        n = clear_executive_scores(supabase, dry_run=args.dry_run)
        logger.info("Clear step done (count=%s dry_run=%s)", n, args.dry_run)

    if args.clear_only:
        return 0

    stats = enqueue_executive_nulls(
        supabase, limit=args.enqueue_limit, dry_run=args.dry_run
    )
    logger.info("Enqueue stats: %s", stats)
    return 0 if stats.get("failed", 0) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
