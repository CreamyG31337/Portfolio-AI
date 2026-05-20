"""Throwaway: why does ticker_analysis pick zero tickers?"""
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path("web_dashboard") / ".env")
sys.path.insert(0, "web_dashboard")

from postgres_client import PostgresClient  # noqa: E402
from supabase_client import SupabaseClient  # noqa: E402

pc = PostgresClient()
sb = SupabaseClient(use_service_role=True)

# 1. portfolio_positions (holdings tier)
hp = sb.supabase.table("portfolio_positions").select("ticker,fund", count="exact").limit(10).execute()
print(f"portfolio_positions total: {hp.count}")
seen_tickers = set()
for r in hp.data or []:
    seen_tickers.add(r.get("ticker"))
print(f"  sample: {sorted(seen_tickers)[:10]}")

# 2. manual queue (ticker analysis_type, priority>=1000)
mq = (
    sb.supabase.table("ai_analysis_queue")
    .select("*", count="exact")
    .eq("analysis_type", "ticker")
    .eq("status", "pending")
    .gte("priority", 1000)
    .execute()
)
print(f"\nmanual ticker queue (pending, priority>=1000): {mq.count}")

# 3. watchlist via ticker_utils helper
try:
    sys.path.insert(0, "web_dashboard")
    from ticker_utils import get_active_watchlist_tickers
    wl = get_active_watchlist_tickers(sb)
    print(f"\nactive watchlist tickers: {len(wl or [])}")
    print(f"  sample: {list(wl or [])[:10]}")
except Exception as e:
    print(f"\nwatchlist helper error: {e}")

# Also see if there are recently_analyzed filters: when was the last ticker_analysis row in Supabase?
print("\nDoes Supabase have ticker_analysis table?", end=" ")
try:
    r = sb.supabase.table("ticker_analysis").select("ticker").limit(1).execute()
    print("yes")
except Exception as e:
    print("no")

print("--- Research DB connection ---")
print(pc.execute_query(
    "SELECT current_database() AS db, inet_server_addr() AS host, inet_server_port() AS port"
)[0])

# Row counts for the meta pipeline tables in Research
print("\n--- Research row counts ---")
for tbl in ("ticker_analysis", "ticker_meta_analysis", "sector_meta_analysis", "research_articles"):
    try:
        n = pc.execute_query(f"SELECT COUNT(*) AS n FROM {tbl}")[0]['n']
        print(f"  {tbl:<25} {n}")
    except Exception as e:
        print(f"  {tbl:<25} ERROR: {e}")

# Check Supabase job_executions for ticker_analysis / ticker_meta_analysis success
print("\n--- Recent ticker pipeline runs in Supabase job_executions ---")
for job in ("ticker_analysis", "ticker_meta_analysis", "ticker_research"):
    r = (
        sb.supabase.table("job_executions")
        .select("status,started_at,completed_at,error_message")
        .eq("job_name", job)
        .order("started_at", desc=True)
        .limit(3)
        .execute()
    )
    print(f"\n  {job}: {len(r.data or [])} most recent runs")
    for row in r.data or []:
        err = (row.get('error_message') or '')[:60]
        print(
            f"    status={row['status']:<10} started={row['started_at']} "
            f"completed={row.get('completed_at')} err={err!r}"
        )
