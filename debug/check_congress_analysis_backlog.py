#!/usr/bin/env python3
"""Quick backlog report for congress trade AI analysis."""

import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "web_dashboard"))

from supabase_client import SupabaseClient
from postgres_client import PostgresClient


def _count_supabase_null_conflict() -> int:
    client = SupabaseClient(use_service_role=True)
    total = 0
    offset = 0
    page = 1000
    while True:
        resp = (
            client.supabase.table("congress_trades")
            .select("id", count="exact")
            .is_("conflict_score", "null")
            .range(offset, offset + page - 1)
            .execute()
        )
        batch = resp.data or []
        if offset == 0 and resp.count is not None:
            return int(resp.count)
        if not batch:
            break
        total += len(batch)
        if len(batch) < page:
            break
        offset += page
    return total


def main() -> None:
    supabase = SupabaseClient(use_service_role=True)
    postgres = PostgresClient()

    total_resp = (
        supabase.supabase.table("congress_trades").select("id", count="exact").limit(1).execute()
    )
    total_trades = int(total_resp.count or 0)

    scored_resp = (
        supabase.supabase.table("congress_trades")
        .select("id", count="exact")
        .not_.is_("conflict_score", "null")
        .limit(1)
        .execute()
    )
    supabase_scored = int(scored_resp.count or 0)
    supabase_unscored = total_trades - supabase_scored

    pg_rows = postgres.execute_query(
        "SELECT COUNT(*) AS c FROM congress_trades_analysis WHERE conflict_score IS NOT NULL"
    )
    pg_analyzed = int(pg_rows[0]["c"]) if pg_rows else 0

    pg_distinct = postgres.execute_query(
        "SELECT COUNT(DISTINCT trade_id) AS c FROM congress_trades_analysis WHERE conflict_score IS NOT NULL"
    )
    pg_distinct_trades = int(pg_distinct[0]["c"]) if pg_distinct else 0

    # Scheduler queue: enriched view, conflict_score null (same filter as analyze job)
    sched_resp = (
        supabase.supabase.table("congress_trades_enriched")
        .select("id", count="exact")
        .is_("conflict_score", "null")
        .limit(1)
        .execute()
    )
    scheduler_queue = int(sched_resp.count or 0)

    # Recent unscored (last 30 days by transaction_date)
    recent_resp = (
        supabase.supabase.table("congress_trades_enriched")
        .select("id", count="exact")
        .is_("conflict_score", "null")
        .gte("transaction_date", "2025-06-01")
        .limit(1)
        .execute()
    )
    recent_unscored = int(recent_resp.count or 0)

    print("Congress trade analysis backlog")
    print("=" * 50)
    print(f"Total trades (Supabase):              {total_trades:,}")
    print(f"Supabase conflict_score set:          {supabase_scored:,}")
    print(f"Supabase conflict_score NULL:         {supabase_unscored:,}")
    print(f"PostgreSQL analysis rows:             {pg_analyzed:,}")
    print(f"PostgreSQL distinct trade_ids scored: {pg_distinct_trades:,}")
    print()
    print("Scheduler queue (enriched, score NULL):", f"{scheduler_queue:,}")
    print("Unscored since 2025-06-01:            ", f"{recent_unscored:,}")
    print()
    nightly_capacity = 40  # 10 per run x 4 runs
    if scheduler_queue > 0:
        nights = (scheduler_queue + nightly_capacity - 1) // nightly_capacity
        print(f"At 40 trades/night (current schedule): ~{nights} night(s) to clear scheduler queue")
    else:
        print("Scheduler queue is empty.")


if __name__ == "__main__":
    main()
