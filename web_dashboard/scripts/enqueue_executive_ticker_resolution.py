#!/usr/bin/env python3
"""Enqueue LLM ticker-resolution tasks for unresolved OGE asset descriptions.

Walks the Open Cabinet transactions, runs the deterministic resolver
(open_cabinet -> suffix -> securities -> yfinance -> cache), and enqueues an
``executive_ticker_resolve`` AI task for every description that is still
unresolved (and is not a bond/muni). Tasks are deduped by canonical company
name via the queue's ``target_key``, so re-running is safe and idempotent.

The AI task queue workers (Ollama + GLM in parallel) then propose a ticker per
task, validate it against yfinance, and cache confirmed hits in
``og_asset_ticker_map`` with ``source='llm'``.

Usage (from web_dashboard/):
    python scripts/enqueue_executive_ticker_resolution.py            # enqueue
    python scripts/enqueue_executive_ticker_resolution.py --dry-run  # report only
    python scripts/enqueue_executive_ticker_resolution.py --use-yfinance
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Any

WEB_DASHBOARD_DIR = Path(__file__).resolve().parent.parent
if str(WEB_DASHBOARD_DIR) not in sys.path:
    sys.path.insert(0, str(WEB_DASHBOARD_DIR))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("enqueue_executive_ticker_resolution")


def collect_unresolved_names(
    transactions: list[dict[str, Any]],
    *,
    cache: dict[str, dict],
    use_yfinance: bool,
) -> list[tuple[str, str, int]]:
    """Return ``(canonical_name, representative_description, priority)`` tuples.

    Deduped by canonical name; skips bonds/munis and anything the deterministic
    resolver already handles (or that is already cached, including prior LLM
    hits).
    """
    from executive_ticker_resolver import resolve_executive_asset

    seen: dict[str, str] = {}
    for txn in transactions:
        description = str(txn.get("description") or "").strip()
        if not description:
            continue
        resolution = resolve_executive_asset(
            description,
            open_cabinet_ticker=txn.get("ticker"),
            cache=cache,
            use_yfinance=use_yfinance,
        )
        if resolution.source == "skipped_bond" or resolution.ticker:
            continue
        canonical = resolution.canonical_description
        if not canonical or canonical in seen:
            continue
        seen[canonical] = description

    # Priority 0 (background); newest-first ordering is irrelevant for a backfill.
    return [(name, desc, 0) for name, desc in seen.items()]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report how many tasks would be enqueued without enqueuing.",
    )
    parser.add_argument(
        "--use-yfinance",
        action="store_true",
        help="Run yfinance resolution first so only truly unresolved names queue.",
    )
    parser.add_argument(
        "--url",
        default=None,
        help="Override the Open Cabinet source URL.",
    )
    args = parser.parse_args()

    from supabase_client import SupabaseClient

    from scheduler.ai_task_workers import enqueue_executive_ticker_tasks
    from scheduler.jobs_executive import (
        TRUMP_OPEN_CABINET_URL,
        fetch_open_cabinet_transactions,
        load_og_asset_cache,
    )

    url = args.url or TRUMP_OPEN_CABINET_URL
    supabase = SupabaseClient(use_service_role=True)

    logger.info("Fetching Open Cabinet transactions from %s", url)
    transactions = fetch_open_cabinet_transactions(url)
    logger.info("Fetched %d transactions", len(transactions))

    cache = load_og_asset_cache(supabase)
    logger.info("Loaded %d cached resolutions", len(cache))

    names = collect_unresolved_names(
        transactions, cache=cache, use_yfinance=args.use_yfinance
    )
    logger.info("Found %d unique unresolved names", len(names))

    if args.dry_run:
        for canonical, description, _ in names[:50]:
            logger.info("  %s  <=  %s", canonical, description)
        if len(names) > 50:
            logger.info("  ... and %d more", len(names) - 50)
        logger.info("Dry run: no tasks enqueued.")
        return 0

    if not names:
        logger.info("Nothing to enqueue.")
        return 0

    stats = enqueue_executive_ticker_tasks(
        supabase, names, enqueued_by="manual_backfill"
    )
    logger.info(
        "Enqueue complete: attempted=%d enqueued=%d failed=%d",
        stats["attempted"],
        stats["enqueued"],
        stats["failed"],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
