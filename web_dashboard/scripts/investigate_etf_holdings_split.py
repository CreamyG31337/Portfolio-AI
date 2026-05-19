#!/usr/bin/env python3
"""Read-only prod audit: Supabase vs Research ETF holdings (no writes)."""

from __future__ import annotations

import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "web_dashboard"))

from dotenv import load_dotenv

load_dotenv(project_root / "web_dashboard" / ".env")

from postgres_client import PostgresClient  # noqa: E402
from supabase_client import SupabaseClient  # noqa: E402


def main() -> None:
    pc = PostgresClient()
    sb = SupabaseClient(use_service_role=True)

    print("=== Holdings split (read-only) ===\n")
    sb_count = (
        sb.supabase.table("etf_holdings_log").select("*", count="exact").limit(0).execute().count
        or 0
    )
    pg = pc.execute_query(
        "SELECT COUNT(*) c, MIN(date) mn, MAX(date) mx, COUNT(DISTINCT date) d FROM etf_holdings_log"
    )[0]
    print(f"Supabase rows: {sb_count:,}  (stale copy)")
    print(
        f"Research rows: {pg['c']:,}  dates {pg['mn']}..{pg['mx']} ({pg['d']} distinct days)"
    )

    only_sb = sb_count > 0 and pg["mx"] and str(pg["mx"]) > "2026-01-24"
    print(f"\nResearch is superset of Supabase dates: {only_sb}")

    print("\n=== Recent Research snapshot days ===")
    for r in pc.execute_query(
        """
        SELECT date::text d, COUNT(*) cnt, COUNT(DISTINCT etf_ticker) etfs
        FROM etf_holdings_log
        WHERE date >= CURRENT_DATE - 7
        GROUP BY date ORDER BY date DESC
        """
    ):
        print(f"  {r['d']}: {r['cnt']} rows, {r['etfs']} ETFs")

    print("\n=== ETF Analysis articles (Research) ===")
    for r in pc.execute_query(
        """
        SELECT DATE(fetched_at) d, COUNT(*) cnt
        FROM research_articles
        WHERE article_type = 'ETF Analysis'
        GROUP BY 1 ORDER BY 1 DESC LIMIT 5
        """
    ):
        print(f"  {r['d']}: {r['cnt']} articles")

    print("\n=== Changes vs articles (gap) ===")
    for day in ("2026-05-18", "2026-05-15", "2026-01-24"):
        ch = pc.execute_query(
            "SELECT COUNT(DISTINCT etf_ticker) n FROM etf_holdings_changes WHERE date = %s",
            (day,),
        )[0]["n"]
        arts = pc.execute_query(
            """
            SELECT COUNT(*) n FROM research_articles
            WHERE article_type = 'ETF Analysis' AND url LIKE %s
            """,
            (f"etf-analysis://%/{day}",),
        )[0]["n"]
        print(f"  {day}: {ch} ETFs with changes, {arts} ETF Analysis articles")

    print("\n=== May 18 ETFs with changes (sample) ===")
    rows = pc.execute_query(
        """
        SELECT etf_ticker, COUNT(*) n
        FROM etf_holdings_changes WHERE date = '2026-05-18'
        GROUP BY etf_ticker ORDER BY etf_ticker
        """
    )
    print(f"  {len(rows or [])} ETFs")
    for r in (rows or [])[:10]:
        print(f"    {r['etf_ticker']}: {r['n']} holding changes")

    # Supabase view still works?
    try:
        sb_ch = (
            sb.supabase.from_("etf_holdings_changes")
            .select("etf_ticker", count="exact")
            .eq("date", "2026-05-18")
            .limit(0)
            .execute()
        )
        print(f"\nSupabase etf_holdings_changes on 2026-05-18: {sb_ch.count or 0} rows")
    except Exception as exc:
        print(f"\nSupabase etf_holdings_changes query failed: {exc}")


if __name__ == "__main__":
    main()
