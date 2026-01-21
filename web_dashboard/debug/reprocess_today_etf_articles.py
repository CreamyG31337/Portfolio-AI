#!/usr/bin/env python3
"""
Re-process Today's ETF Articles
================================

Re-fetches today's ETF holdings from source (fresh CSV download) and
generates correct research articles. This fixes articles that were created
with the pagination bug.

Only works for TODAY's data since we can fetch fresh CSVs.
Historical dates cannot be re-processed (CSVs not saved).
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
    fetch_ark_holdings,
    get_previous_holdings,
    calculate_diff,
    save_holdings_snapshot,
    log_significant_changes,
    upsert_etf_metadata,
    upsert_securities_metadata,
    ETF_CONFIGS
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def reprocess_etf(etf_ticker: str, db: SupabaseClient, repo: ResearchRepository, today: datetime):
    """Re-process a single ETF for today"""
    print(f"\n{'='*80}")
    print(f"Re-processing {etf_ticker}")
    print(f"{'='*80}")
    
    config = ETF_CONFIGS.get(etf_ticker)
    if not config:
        print(f"[SKIP] {etf_ticker} not in ETF_CONFIGS")
        return False
    
    try:
        # 1. Delete any existing article for today
        today_str = today.strftime('%Y-%m-%d')
        existing_articles = repo.client.execute_query("""
            SELECT id, title
            FROM research_articles
            WHERE article_type = 'ETF Change'
              AND title LIKE %s
              AND DATE(fetched_at) = %s
        """, (f"{etf_ticker} Daily Holdings Update%", today_str))
        
        if existing_articles:
            print(f"  Deleting {len(existing_articles)} existing article(s)...")
            for article in existing_articles:
                repo.delete_article(str(article['id']))
                print(f"    Deleted: {article['title']}")
        
        # 2. Fetch today's holdings from source
        print(f"\n  Fetching current holdings from {config['provider']}...")
        if config['provider'] == 'ARK':
            today_holdings = fetch_ark_holdings(etf_ticker, config['url'])
        elif config['provider'] == 'iShares':
            today_holdings = fetch_ishares_holdings(etf_ticker, config['url'])
        else:
            print(f"  [SKIP] Provider {config['provider']} not supported")
            return False
        
        if today_holdings is None or today_holdings.empty:
            print(f"  [ERROR] Failed to fetch holdings")
            return False
        
        print(f"  Fetched {len(today_holdings)} holdings")
        
        # 3. Get previous holdings (with pagination fix)
        print(f"  Fetching previous holdings from database...")
        yesterday_holdings = get_previous_holdings(db, etf_ticker, today)
        
        if yesterday_holdings.empty:
            print(f"  [INFO] No previous holdings found - will save snapshot but skip article")
            # Still save the snapshot
            upsert_etf_metadata(db, etf_ticker, config['provider'])
            upsert_securities_metadata(db, today_holdings, config['provider'])
            save_holdings_snapshot(db, etf_ticker, today_holdings, today)
            return True
        
        print(f"  Found {len(yesterday_holdings)} previous holdings")
        
        # 4. Calculate changes
        print(f"  Calculating changes...")
        changes = calculate_diff(today_holdings, yesterday_holdings, etf_ticker)
        
        print(f"  Found {len(changes)} significant changes")
        
        # 5. Generate article if there are changes
        if changes:
            num_changes = len(changes)
            num_holdings = len(today_holdings)
            change_ratio = num_changes / num_holdings if num_holdings > 0 else 1
            
            if change_ratio > 0.9:
                print(f"  [WARNING] Skipping article - {num_changes}/{num_holdings} holdings changed ({change_ratio:.1%}), likely incomplete historical data")
            else:
                print(f"  Generating research article...")
                log_significant_changes(repo, changes, etf_ticker)
                print(f"  [OK] Article generated")
        
        # 6. Update metadata and save snapshot
        print(f"  Updating metadata and saving snapshot...")
        upsert_etf_metadata(db, etf_ticker, config['provider'])
        upsert_securities_metadata(db, today_holdings, config['provider'])
        save_holdings_snapshot(db, etf_ticker, today_holdings, today)
        
        print(f"  [OK] {etf_ticker} re-processed successfully")
        return True
        
    except Exception as e:
        print(f"  [ERROR] Error re-processing {etf_ticker}: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Re-process today\'s ETF articles')
    parser.add_argument('--etf', type=str, help='Specific ETF ticker to process (default: all problematic ETFs)')
    args = parser.parse_args()
    
    db = SupabaseClient(use_service_role=True)
    repo = ResearchRepository()
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    
    print("=" * 80)
    print("Re-process Today's ETF Articles")
    print("=" * 80)
    print()
    print("This will:")
    print("  1. Delete existing articles for today")
    print("  2. Fetch fresh CSV data from source")
    print("  3. Calculate changes with pagination fix")
    print("  4. Generate correct research articles")
    print()
    print(f"Processing date: {today.strftime('%Y-%m-%d')}")
    print()
    
    # Determine which ETFs to process
    if args.etf:
        etfs_to_process = [args.etf.upper()]
    else:
        # Process problematic ETFs that likely had bad articles
        etfs_to_process = ['IWM', 'IWC', 'IWO', 'IVV']
    
    print(f"ETFs to process: {', '.join(etfs_to_process)}")
    print()
    
    results = []
    for etf_ticker in etfs_to_process:
        success = reprocess_etf(etf_ticker, db, repo, today)
        results.append({'etf': etf_ticker, 'success': success})
    
    print("\n" + "=" * 80)
    print("Summary")
    print("=" * 80)
    
    successful = [r for r in results if r['success']]
    failed = [r for r in results if not r['success']]
    
    if successful:
        print(f"\n[OK] Successfully re-processed {len(successful)} ETF(s):")
        for r in successful:
            print(f"  - {r['etf']}")
    
    if failed:
        print(f"\n[ERROR] Failed to re-process {len(failed)} ETF(s):")
        for r in failed:
            print(f"  - {r['etf']}")
    
    print("\nNote: Only today's data can be re-processed (fresh CSV fetch).")
    print("Historical dates cannot be re-processed (CSVs not saved).")

if __name__ == "__main__":
    main()
