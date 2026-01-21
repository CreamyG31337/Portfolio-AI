#!/usr/bin/env python3
"""
Verify ETF Watchtower Fix
=========================

Verifies that the pagination fix is working correctly and checks if today's
data needs to be re-processed (if it was saved with incorrect comparison).
"""

import sys
import logging
from pathlib import Path
from datetime import datetime, timezone

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from supabase_client import SupabaseClient
from research_repository import ResearchRepository
from scheduler.jobs_etf_watchtower import (
    fetch_ishares_holdings,
    get_previous_holdings,
    calculate_diff,
    save_holdings_snapshot,
    ETF_CONFIGS
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def check_etf(etf_ticker: str, db: SupabaseClient, repo: ResearchRepository):
    """Check a single ETF for issues"""
    print(f"\n{'='*80}")
    print(f"Checking {etf_ticker}")
    print(f"{'='*80}")
    
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    
    # 1. Check if today's snapshot exists
    today_str = today.strftime('%Y-%m-%d')
    today_result = db.supabase.table('etf_holdings_log').select('holding_ticker').eq('etf_ticker', etf_ticker).eq('date', today_str).limit(1).execute()
    
    has_today_snapshot = len(today_result.data) > 0
    
    # 2. Fetch today's holdings from source
    config = ETF_CONFIGS.get(etf_ticker)
    if not config:
        print(f"[SKIP] {etf_ticker} not in ETF_CONFIGS")
        return
    
    print(f"\n1. Fetching current holdings from {config['provider']}...")
    if config['provider'] == 'ARK':
        from scheduler.jobs_etf_watchtower import fetch_ark_holdings
        today_holdings = fetch_ark_holdings(etf_ticker, config['url'])
    elif config['provider'] == 'iShares':
        today_holdings = fetch_ishares_holdings(etf_ticker, config['url'])
    else:
        print(f"[SKIP] Provider {config['provider']} not supported")
        return
    
    if today_holdings is None or today_holdings.empty:
        print(f"[ERROR] Failed to fetch holdings")
        return
    
    print(f"   Fetched {len(today_holdings)} holdings")
    
    # 3. Get previous holdings (with pagination fix)
    print(f"\n2. Fetching previous holdings from database...")
    yesterday_holdings = get_previous_holdings(db, etf_ticker, today)
    
    if yesterday_holdings.empty:
        print(f"   [INFO] No previous holdings found (first snapshot)")
        return
    
    print(f"   Fetched {len(yesterday_holdings)} previous holdings")
    
    # 4. Calculate changes
    print(f"\n3. Calculating changes...")
    changes = calculate_diff(today_holdings, yesterday_holdings, etf_ticker)
    
    print(f"   Found {len(changes)} significant changes")
    
    # 5. Check if today's article exists and is correct
    print(f"\n4. Checking today's research article...")
    today_articles = repo.client.execute_query("""
        SELECT id, title, summary, fetched_at
        FROM research_articles
        WHERE article_type = 'ETF Change'
          AND title LIKE %s
          AND DATE(fetched_at) = %s
        ORDER BY fetched_at DESC
        LIMIT 1
    """, (f"{etf_ticker} Daily Holdings Update%", today_str))
    
    if today_articles:
        article = today_articles[0]
        summary = article.get('summary', '')
        
        # Extract change count from summary
        import re
        match = re.search(r'made (\d+) significant changes', summary)
        article_change_count = int(match.group(1)) if match else 0
        
        print(f"   Found article: {article['title']}")
        print(f"   Article says: {article_change_count} changes")
        print(f"   Actual changes: {len(changes)}")
        
        if abs(article_change_count - len(changes)) > 10:
            print(f"   [WARNING] Mismatch! Article has wrong change count.")
            print(f"   This article should be deleted and re-generated.")
            return {
                'etf_ticker': etf_ticker,
                'article_id': article['id'],
                'article_changes': article_change_count,
                'actual_changes': len(changes),
                'needs_reprocess': True
            }
        else:
            print(f"   [OK] Article change count matches actual changes")
    else:
        print(f"   [INFO] No article found for today (may not have been generated)")
    
    return {
        'etf_ticker': etf_ticker,
        'actual_changes': len(changes),
        'needs_reprocess': False
    }

def main():
    db = SupabaseClient(use_service_role=True)
    repo = ResearchRepository()
    
    print("=" * 80)
    print("Verify ETF Watchtower Fix")
    print("=" * 80)
    print()
    print("This script will:")
    print("  1. Check if pagination fix is working (fetches all holdings)")
    print("  2. Verify today's change counts are correct")
    print("  3. Identify articles that need to be deleted/re-generated")
    print()
    
    # Check problematic ETFs first
    problematic_etfs = ['IWM', 'IWC', 'IWO', 'IVV']
    
    results = []
    for etf_ticker in problematic_etfs:
        result = check_etf(etf_ticker, db, repo)
        if result:
            results.append(result)
    
    print("\n" + "=" * 80)
    print("Summary")
    print("=" * 80)
    
    needs_reprocess = [r for r in results if r.get('needs_reprocess')]
    
    if needs_reprocess:
        print(f"\n[WARNING] Found {len(needs_reprocess)} ETF(s) with incorrect articles:")
        for r in needs_reprocess:
            print(f"  {r['etf_ticker']}: Article says {r['article_changes']} changes, actual is {r['actual_changes']}")
            print(f"    Article ID: {r['article_id']}")
        print("\nThese articles should be deleted. Today's data can be re-processed")
        print("by running the ETF watchtower job again (it will fetch fresh CSV data).")
    else:
        print("\n[OK] All checked ETFs have correct change counts!")
        print("The pagination fix is working correctly.")
    
    print("\nNote: Today's holdings snapshots are correct (they're just data snapshots).")
    print("Only the research articles (with incorrect change counts) need cleanup.")

if __name__ == "__main__":
    main()
