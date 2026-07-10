#!/usr/bin/env python3
"""
One-time / catch-up: mirror Postgres congress_trades_analysis.conflict_score
onto Supabase congress_trades for rows still NULL.

Needed because analysis lived only in Research Postgres until Jul 2026, when
sync_supabase_conflict_score() was added. The scheduler queue keys off
Supabase conflict_score IS NULL, so historical scores never drained the queue.

Usage (from repo root, venv active):
  python web_dashboard/scripts/sync_congress_conflict_scores.py
  python web_dashboard/scripts/sync_congress_conflict_scores.py --dry-run
  python web_dashboard/scripts/sync_congress_conflict_scores.py --batch-size 100
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Tuple

_web_dashboard = Path(__file__).resolve().parent.parent
_repo_root = _web_dashboard.parent
for _p in (str(_web_dashboard), str(_repo_root)):
    if _p in sys.path:
        sys.path.remove(_p)
sys.path.insert(0, str(_web_dashboard))
sys.path.insert(0, str(_repo_root))

from dotenv import load_dotenv

load_dotenv(_web_dashboard / ".env")
load_dotenv(_repo_root / ".env")

from postgres_client import PostgresClient
from supabase_client import SupabaseClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("sync_congress_conflict_scores")


def load_latest_scores(postgres: PostgresClient) -> Dict[int, float]:
    """Latest non-null conflict_score per trade_id from Research Postgres."""
    rows = postgres.execute_query(
        """
        SELECT DISTINCT ON (trade_id)
            trade_id,
            conflict_score
        FROM congress_trades_analysis
        WHERE conflict_score IS NOT NULL
        ORDER BY trade_id, analyzed_at DESC NULLS LAST, id DESC
        """
    )
    scores: Dict[int, float] = {}
    for row in rows or []:
        trade_id = int(row["trade_id"])
        scores[trade_id] = float(row["conflict_score"])
    return scores


def fetch_null_conflict_ids(supabase: SupabaseClient, page_size: int = 1000) -> List[int]:
    """All congress_trades ids with conflict_score IS NULL."""
    ids: List[int] = []
    offset = 0
    while True:
        resp = (
            supabase.supabase.table("congress_trades")
            .select("id")
            .is_("conflict_score", "null")
            .order("id")
            .range(offset, offset + page_size - 1)
            .execute()
        )
        batch = resp.data or []
        if not batch:
            break
        ids.extend(int(r["id"]) for r in batch)
        if len(batch) < page_size:
            break
        offset += page_size
    return ids


def _update_one(supabase: SupabaseClient, trade_id: int, score: float) -> None:
    last_exc: Exception | None = None
    for attempt in range(4):
        try:
            supabase.supabase.table("congress_trades").update(
                {"conflict_score": score}
            ).eq("id", trade_id).execute()
            return
        except Exception as exc:
            last_exc = exc
            time.sleep(0.15 * (attempt + 1))
    assert last_exc is not None
    raise last_exc


def sync_scores(
    supabase: SupabaseClient,
    pairs: List[Tuple[int, float]],
    *,
    dry_run: bool,
    batch_size: int,
    workers: int,
) -> Tuple[int, int]:
    """Update Supabase conflict_score. Returns (updated, errors)."""
    updated = 0
    errors = 0
    total = len(pairs)
    started = time.time()

    if dry_run:
        logger.info("Dry-run: would update %s rows", f"{total:,}")
        return total, 0

    # Keep concurrency modest — shared httpx client + Windows sockets flake under load.
    workers = max(1, min(workers, 6))

    for i in range(0, total, batch_size):
        chunk = pairs[i : i + batch_size]
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(_update_one, supabase, trade_id, score): trade_id
                for trade_id, score in chunk
            }
            for fut in as_completed(futures):
                trade_id = futures[fut]
                try:
                    fut.result()
                    updated += 1
                except Exception as exc:
                    errors += 1
                    logger.error("Failed trade_id=%s: %s", trade_id, exc)

        done = min(i + batch_size, total)
        elapsed = time.time() - started
        rate = done / elapsed if elapsed > 0 else 0.0
        eta = (total - done) / rate if rate > 0 else 0.0
        logger.info(
            "Progress %s/%s (%.1f/s, ETA %.0fs)",
            done,
            total,
            rate,
            eta,
        )

    return updated, errors


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Mirror Postgres congress analysis scores onto Supabase conflict_score"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Count what would be synced without writing",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=200,
        help="Rows per progress chunk (default 200)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Concurrent Supabase update workers (default 4)",
    )
    args = parser.parse_args()

    supabase = SupabaseClient(use_service_role=True)
    postgres = PostgresClient()

    logger.info("Loading latest scores from Postgres...")
    scores = load_latest_scores(postgres)
    logger.info("Postgres scored trade_ids: %s", f"{len(scores):,}")

    logger.info("Fetching Supabase rows with conflict_score IS NULL...")
    null_ids = fetch_null_conflict_ids(supabase)
    logger.info("Supabase NULL conflict_score: %s", f"{len(null_ids):,}")

    pairs: List[Tuple[int, float]] = []
    for trade_id in null_ids:
        score = scores.get(trade_id)
        if score is not None:
            pairs.append((trade_id, score))

    still_need_ai = len(null_ids) - len(pairs)
    logger.info("Can sync from Postgres: %s", f"{len(pairs):,}")
    logger.info("Still need AI (no Postgres score): %s", f"{still_need_ai:,}")

    if not pairs:
        logger.info("Nothing to sync.")
        return 0

    updated, errors = sync_scores(
        supabase,
        pairs,
        dry_run=args.dry_run,
        batch_size=max(1, args.batch_size),
        workers=max(1, args.workers),
    )
    logger.info(
        "Done. updated=%s errors=%s dry_run=%s",
        f"{updated:,}",
        errors,
        args.dry_run,
    )
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
