#!/usr/bin/env python3
"""Debug script to check recent ETF changes in research_articles."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "web_dashboard"))

from research_repository import ResearchRepository

def main():
    repo = ResearchRepository()
    
    # Direct query for ETF Change articles
    query = """
        SELECT id, title, summary, content, source, article_type, tickers, fetched_at
        FROM research_articles
        WHERE article_type = 'ETF Change'
        ORDER BY fetched_at DESC
        LIMIT 20
    """
    
    articles = repo.client.execute_query(query)
    print(f"Found {len(articles)} ETF Change articles total")
    print()
    
    # Show one full content for IWM to see the actual changes
    iwm_article = next((a for a in articles if 'IWM' in a.get('title', '')), None)
    if iwm_article:
        print("=== IWM Full Content ===")
        print(iwm_article.get('content', 'No content')[:2000])
        print("\n" + "=" * 60 + "\n")
    
    for a in articles[:5]:
        print(f"Date: {a.get('fetched_at', 'N/A')}")
        print(f"Title: {a.get('title')}")
        print(f"Summary: {a.get('summary')}")
        tickers = a.get('tickers') or []
        print(f"Tickers ({len(tickers)}): {tickers[:5]}{'...' if len(tickers) > 5 else ''}")
        print("-" * 60)
    
    # Also check etf_holdings_log for recent snapshots
    print("\n\n=== Recent ETF Holdings Snapshots (Supabase) ===\n")
    from supabase_client import SupabaseClient
    db = SupabaseClient()
    
    # First, check total count
    count_result = db.supabase.table('etf_holdings_log').select('*', count='exact').limit(1).execute()
    print(f"Total rows in etf_holdings_log: {count_result.count}")
    
    if count_result.count == 0:
        print("\n*** NO DATA IN etf_holdings_log TABLE ***")
        print("This explains why EVERY holding is flagged as a 'change' - there's no previous data to compare against!")
        print("\nThe job should have saved today's snapshot, but the table is still empty.")
        print("Let me check RLS policies or permission issues...")
        
        # Try to fetch with service role
        db_admin = SupabaseClient(use_service_role=True)
        admin_count = db_admin.supabase.table('etf_holdings_log').select('*', count='exact').limit(1).execute()
        print(f"\nWith service role: {admin_count.count} rows")
        
        if admin_count.count > 0:
            print("*** RLS POLICY ISSUE - Data exists but regular client can't see it ***")
            
            # Get distinct dates
            from collections import Counter, defaultdict
            all_data = db_admin.supabase.table('etf_holdings_log').select('date, etf_ticker').execute()
            
            # Count by date and ETF
            counts = Counter((r['date'], r['etf_ticker']) for r in all_data.data)
            
            # Group by ETF to see history
            etf_dates = defaultdict(list)
            for (date, etf), count in counts.items():
                etf_dates[etf].append((date, count))
            
            # Get ALL data with pagination
            print("Fetching full data (with pagination)...")
            all_rows = []
            offset = 0
            page_size = 1000
            while True:
                page = db_admin.supabase.table('etf_holdings_log') \
                    .select('date, etf_ticker') \
                    .range(offset, offset + page_size - 1) \
                    .execute()
                if not page.data:
                    break
                all_rows.extend(page.data)
                offset += page_size
                if len(page.data) < page_size:
                    break
            
            print(f"Total rows fetched: {len(all_rows)}")
            
            # Count by date and ETF
            counts = Counter((r['date'], r['etf_ticker']) for r in all_rows)
            
            # Group by ETF to see history
            etf_dates = defaultdict(list)
            for (date, etf), count in counts.items():
                etf_dates[etf].append((date, count))
            
            print("\nETF snapshot history (using service role):")
            for etf in sorted(etf_dates.keys()):
                dates = sorted(etf_dates[etf], reverse=True)
                print(f"\n  {etf}:")
                for date, count in dates[:5]:
                    print(f"    {date}: {count} holdings")
                if len(dates) > 5:
                    print(f"    ... and {len(dates) - 5} more days")
                elif len(dates) == 1:
                    print("    *** ONLY ONE SNAPSHOT - first comparison will show all as changes ***")
        else:
            print("Data truly doesn't exist - the save_holdings_snapshot() might have failed silently")
        return
    
    # Get all unique dates per ETF
    result = db.supabase.table('etf_holdings_log').select('date, etf_ticker').execute()
    
    # Count by date and ETF
    from collections import Counter, defaultdict
    counts = Counter((r['date'], r['etf_ticker']) for r in result.data)
    
    # Group by ETF to see history
    etf_dates = defaultdict(list)
    for (date, etf), count in counts.items():
        etf_dates[etf].append((date, count))
    
    print("ETF snapshot history (how many days of data per ETF):")
    for etf in sorted(etf_dates.keys()):
        dates = sorted(etf_dates[etf], reverse=True)
        print(f"\n  {etf}:")
        for date, count in dates[:5]:
            print(f"    {date}: {count} holdings")
        if len(dates) > 5:
            print(f"    ... and {len(dates) - 5} more days")
        elif len(dates) == 1:
            print("    *** FIRST SNAPSHOT - explains why all holdings flagged as changes! ***")

if __name__ == "__main__":
    main()
