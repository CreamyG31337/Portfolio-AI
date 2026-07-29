#!/usr/bin/env python3
"""
Enqueue unscored congress trades into the AI task queue for parallel catch-up.

Resumable: re-running is safe (active pending/leased rows dedupe on trade id).
Configured queue workers (primary Ollama, optional secondary Ollama, optional GLM)
drain ``ai_task_queue`` when ``analyze_congress_trades`` is listed in ``AI_QUEUE_JOBS``.
Unconfigured backends are skipped automatically (single-host installs need only
``OLLAMA_BASE_URL``).

Usage (repo root, venv active):
  python web_dashboard/scripts/enqueue_congress_trade_analysis.py
  python web_dashboard/scripts/enqueue_congress_trade_analysis.py --limit 500 --priority 0
  python web_dashboard/scripts/enqueue_congress_trade_analysis.py --dry-run
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import List

_web_dashboard = Path(__file__).resolve().parent.parent
_repo_root = _web_dashboard.parent
for _p in (str(_repo_root), str(_web_dashboard)):
    if _p in sys.path:
        sys.path.remove(_p)
sys.path.insert(0, str(_repo_root))
sys.path.insert(0, str(_web_dashboard))

from dotenv import load_dotenv

load_dotenv(_web_dashboard / ".env")
load_dotenv(_repo_root / ".env")

from scheduler.ai_task_workers import enqueue_congress_trade_analysis_tasks
from supabase_client import SupabaseClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("enqueue_congress_trade_analysis")


def fetch_unscored_trade_ids(
    supabase: SupabaseClient,
    *,
    limit: int,
    page_size: int = 1000,
) -> List[int]:
    """Newest-first trade ids with conflict_score IS NULL (up to limit; 0 = all)."""
    ids: List[int] = []
    offset = 0
    remaining = limit if limit > 0 else None
    while True:
        take = page_size
        if remaining is not None:
            take = min(page_size, remaining)
            if take <= 0:
                break
        resp = (
            supabase.supabase.table("congress_trades")
            .select("id")
            .is_("conflict_score", "null")
            .neq("quality_status", "garbage")
            .order("transaction_date", desc=True)
            .order("id", desc=True)
            .range(offset, offset + take - 1)
            .execute()
        )
        batch = resp.data or []
        if not batch:
            break
        ids.extend(int(r["id"]) for r in batch)
        if remaining is not None:
            remaining -= len(batch)
        if len(batch) < take:
            break
        offset += take
    return ids


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Enqueue unscored congress trades for AI task queue catch-up"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Max trades to enqueue (0 = all unscored)",
    )
    parser.add_argument(
        "--priority",
        type=int,
        default=0,
        help="Queue priority (default 0 = below scheduled ticker/meta work)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List how many would be enqueued without writing",
    )
    parser.add_argument(
        "--enqueued-by",
        type=str,
        default="manual_catchup",
        help="enqueued_by label stored on queue rows",
    )
    args = parser.parse_args()

    client = SupabaseClient(use_service_role=True)
    logger.info("Fetching unscored congress trades (limit=%s)...", args.limit or "all")
    trade_ids = fetch_unscored_trade_ids(client, limit=max(0, args.limit))
    logger.info("Found %s unscored trade(s)", f"{len(trade_ids):,}")

    if not trade_ids:
        logger.info("Nothing to enqueue.")
        return 0

    if args.dry_run:
        logger.info(
            "Dry-run: would enqueue %s tasks at priority=%s",
            f"{len(trade_ids):,}",
            args.priority,
        )
        return 0

    stats = enqueue_congress_trade_analysis_tasks(
        client,
        trade_ids,
        priority=args.priority,
        enqueued_by=args.enqueued_by,
    )
    logger.info(
        "Enqueue done: attempted=%s enqueued=%s failed=%s",
        stats["attempted"],
        stats["enqueued"],
        stats["failed"],
    )
    return 1 if stats["failed"] and not stats["enqueued"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
