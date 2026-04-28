#!/usr/bin/env python3
"""Read-only backlog health checks for AI job pipelines."""

from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv

project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(1, str(project_root / "web_dashboard"))

load_dotenv(project_root / "web_dashboard" / ".env")

from postgres_client import PostgresClient  # noqa: E402
from supabase_client import SupabaseClient  # noqa: E402


def _print_section(title: str) -> None:
    print(f"\n=== {title} ===")


def main() -> int:
    supabase = SupabaseClient(use_service_role=True)
    research = PostgresClient()

    _print_section("Newsletter backlog")
    newsletter_rows = research.execute_query(
        """
        SELECT
            COUNT(*) FILTER (WHERE summary IS NULL)::int AS summary_missing_count,
            COUNT(*) FILTER (WHERE embedding IS NULL)::int AS embedding_missing_count,
            COUNT(*) FILTER (WHERE summary IS NULL OR embedding IS NULL)::int AS pending_ui_count
        FROM newsletters
        """
    )
    print(f"Summary missing: {newsletter_rows[0]['summary_missing_count']}")
    print(f"Embedding missing (UI Pending): {newsletter_rows[0]['embedding_missing_count']}")
    print(f"Pending by job selector (summary OR embedding missing): {newsletter_rows[0]['pending_ui_count']}")

    _print_section("Article backlog")
    article_rows = research.execute_query(
        """
        SELECT COUNT(*)::int AS missing_summary_count
        FROM research_articles
        WHERE COALESCE(NULLIF(TRIM(summary), ''), NULL) IS NULL
        """
    )
    print(f"Articles missing summary: {article_rows[0]['missing_summary_count']}")

    _print_section("Retry queue status")
    retry_rows = supabase.supabase.table("job_retry_queue") \
        .select("status, created_at") \
        .in_("status", ["pending", "retrying", "abandoned"]) \
        .execute()
    counts = {"pending": 0, "retrying": 0, "abandoned": 0}
    oldest_created_at = None
    for row in (retry_rows.data or []):
        status = row.get("status")
        if status in counts:
            counts[status] += 1
        created_at = row.get("created_at")
        if created_at and (oldest_created_at is None or created_at < oldest_created_at):
            oldest_created_at = created_at
    print(f"pending={counts['pending']}, retrying={counts['retrying']}, abandoned={counts['abandoned']}")
    print(f"oldest retry row created_at: {oldest_created_at or 'n/a'}")

    _print_section("Stale running jobs")
    running_rows = supabase.supabase.table("job_executions") \
        .select("job_name, started_at") \
        .eq("status", "running") \
        .execute()

    bucket_counts = {"30m+": 0, "1h+": 0, "3h+": 0, "6h+": 0}
    now_rows = research.execute_query("SELECT NOW() AT TIME ZONE 'UTC' AS now_utc")
    now_utc = now_rows[0]["now_utc"]

    for row in (running_rows.data or []):
        started_at = row.get("started_at")
        if not started_at:
            continue
        age_rows = research.execute_query(
            "SELECT EXTRACT(EPOCH FROM (%s::timestamptz - %s::timestamptz))::int AS age_seconds",
            (now_utc.isoformat(), str(started_at)),
        )
        age_seconds = int(age_rows[0]["age_seconds"])
        if age_seconds >= 30 * 60:
            bucket_counts["30m+"] += 1
        if age_seconds >= 60 * 60:
            bucket_counts["1h+"] += 1
        if age_seconds >= 3 * 60 * 60:
            bucket_counts["3h+"] += 1
        if age_seconds >= 6 * 60 * 60:
            bucket_counts["6h+"] += 1

    print(
        "running job age buckets: "
        f"30m+={bucket_counts['30m+']}, "
        f"1h+={bucket_counts['1h+']}, "
        f"3h+={bucket_counts['3h+']}, "
        f"6h+={bucket_counts['6h+']}"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
