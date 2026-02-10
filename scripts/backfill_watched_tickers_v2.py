#!/usr/bin/env python3
"""
Backfill watched_tickers_v2
===========================

One-time migration script to copy rows from the legacy global ``watched_tickers``
table into the fund-scoped ``watched_tickers_v2`` table.

Preconditions
-------------
- ``watched_tickers_v2`` table exists in Supabase (see database/schema/supabase/tables/watched_tickers_v2.sql).
- ``funds`` table contains the target fund rows (FK constraint).
- ``securities`` table contains the referenced tickers (FK constraint).
- Virtual-env activated with project dependencies installed.

Usage
-----
::

    # Dry run — print counts without writing
    python scripts/backfill_watched_tickers_v2.py --dry-run

    # Backfill for specific funds
    python scripts/backfill_watched_tickers_v2.py --funds TEST TFSA

    # Backfill for ALL active funds
    python scripts/backfill_watched_tickers_v2.py

    # Force overwrite existing v2 rows (re-upsert)
    python scripts/backfill_watched_tickers_v2.py --force

Notes
-----
- Idempotent: uses ``ON CONFLICT (fund, ticker) DO UPDATE`` so safe to re-run.
- Skips tickers that do not exist in the ``securities`` table (FK would reject them).
- Logs every action for auditability.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

_repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_repo_root))
sys.path.insert(0, str(_repo_root / "web_dashboard"))

from supabase_client import SupabaseClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("backfill_watched_tickers_v2")


def _get_legacy_rows(client: SupabaseClient) -> list[dict]:
    """Fetch all active rows from legacy watched_tickers."""
    result = client.supabase.table("watched_tickers").select(
        "ticker, priority_tier, is_active, source, created_at"
    ).eq("is_active", True).execute()
    return result.data or []


def _get_active_funds(client: SupabaseClient, only: list[str] | None = None) -> list[str]:
    """Return list of fund names. If *only* is provided, validate they exist."""
    result = client.supabase.table("funds").select("name").execute()
    all_funds = sorted({r["name"] for r in (result.data or []) if r.get("name")})
    if only:
        missing = set(only) - set(all_funds)
        if missing:
            logger.warning("Requested funds not found in DB: %s", missing)
        return [f for f in only if f in all_funds]
    return all_funds


def _get_valid_tickers(client: SupabaseClient, needed: set[str]) -> set[str]:
    """Return the subset of *needed* tickers that exist in the securities table.

    Uses targeted lookups to avoid the default 1000-row pagination limit.
    """
    if not needed:
        return set()
    valid: set[str] = set()
    batch_list = sorted(needed)
    batch_size = 100
    for i in range(0, len(batch_list), batch_size):
        batch = batch_list[i : i + batch_size]
        result = client.supabase.table("securities").select("ticker").in_("ticker", batch).execute()
        valid.update(r["ticker"].upper() for r in (result.data or []) if r.get("ticker"))
    return valid


def _get_existing_v2_keys(client: SupabaseClient) -> set[tuple[str, str]]:
    """Return existing (fund, ticker) pairs in v2."""
    result = client.supabase.table("watched_tickers_v2").select("fund, ticker").execute()
    return {(r["fund"], r["ticker"].upper()) for r in (result.data or [])}


def backfill(
    funds: list[str] | None = None,
    dry_run: bool = False,
    force: bool = False,
) -> None:
    client = SupabaseClient(use_service_role=True)

    legacy_rows = _get_legacy_rows(client)
    logger.info("Legacy watched_tickers active rows: %d", len(legacy_rows))
    if not legacy_rows:
        logger.info("Nothing to backfill.")
        return

    target_funds = _get_active_funds(client, only=funds)
    logger.info("Target funds: %s", target_funds)
    if not target_funds:
        logger.error("No valid target funds. Aborting.")
        return

    needed_tickers = {(r.get("ticker") or "").upper().strip() for r in legacy_rows} - {""}
    valid_tickers = _get_valid_tickers(client, needed=needed_tickers)
    logger.info("Valid tickers (of %d needed): %d", len(needed_tickers), len(valid_tickers))

    existing_v2 = _get_existing_v2_keys(client) if not force else set()

    rows_to_upsert: list[dict] = []
    skipped_no_security = 0
    skipped_existing = 0

    for legacy in legacy_rows:
        ticker = (legacy.get("ticker") or "").upper().strip()
        if not ticker:
            continue
        if ticker not in valid_tickers:
            skipped_no_security += 1
            logger.debug("Skipping %s — not in securities table", ticker)
            continue
        for fund in target_funds:
            if not force and (fund, ticker) in existing_v2:
                skipped_existing += 1
                continue
            rows_to_upsert.append({
                "fund": fund,
                "ticker": ticker,
                "priority_tier": legacy.get("priority_tier") or "C",
                "is_active": True,
                "source": legacy.get("source"),
            })

    logger.info(
        "Rows to upsert: %d | Skipped (no security): %d | Skipped (already in v2): %d",
        len(rows_to_upsert),
        skipped_no_security,
        skipped_existing,
    )

    if dry_run:
        logger.info("[DRY RUN] Would upsert %d rows. Sample:", len(rows_to_upsert))
        for row in rows_to_upsert[:10]:
            logger.info("  %s / %s  (tier=%s)", row["fund"], row["ticker"], row["priority_tier"])
        return

    batch_size = 50
    upserted = 0
    for i in range(0, len(rows_to_upsert), batch_size):
        batch = rows_to_upsert[i : i + batch_size]
        try:
            client.supabase.table("watched_tickers_v2").upsert(
                batch, on_conflict="fund,ticker"
            ).execute()
            upserted += len(batch)
            logger.info("Upserted batch %d–%d (%d rows)", i, i + len(batch) - 1, len(batch))
        except Exception as e:
            logger.error("Batch %d–%d failed: %s", i, i + len(batch) - 1, e)

    logger.info("Backfill complete. Total upserted: %d / %d planned.", upserted, len(rows_to_upsert))

    final_count = client.supabase.table("watched_tickers_v2").select(
        "fund, ticker", count="exact"
    ).execute()
    logger.info("watched_tickers_v2 total row count: %s", getattr(final_count, "count", "unknown"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill watched_tickers_v2 from legacy table.")
    parser.add_argument("--dry-run", action="store_true", help="Print plan without writing.")
    parser.add_argument("--funds", nargs="*", help="Limit to specific fund names (default: all active funds).")
    parser.add_argument("--force", action="store_true", help="Re-upsert even if rows already exist in v2.")
    args = parser.parse_args()

    backfill(funds=args.funds, dry_run=args.dry_run, force=args.force)


if __name__ == "__main__":
    main()
