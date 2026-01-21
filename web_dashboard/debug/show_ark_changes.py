#!/usr/bin/env python3
"""
Show ARK ETF Changes
=====================

Shows the actual changes detected for ARK ETFs on specific dates
to verify if high change counts were legitimate or bugs.
"""

import sys
import logging
from pathlib import Path
from datetime import datetime, timezone, timedelta
import pandas as pd

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from supabase_client import SupabaseClient
from research_repository import ResearchRepository
from scheduler.jobs_etf_watchtower import (
    fetch_ark_holdings,
    get_previous_holdings,
    calculate_diff,
    ETF_CONFIGS
)

logging.basicConfig(
    level=logging.WARNING,  # Reduce noise
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def show_changes_for_date(etf_ticker: str, target_date: datetime, db: SupabaseClient):
    """Show changes for a specific ETF on a specific date"""
    print(f"\n{'='*80}")
    print(f"{etf_ticker} Changes on {target_date.strftime('%Y-%m-%d')}")
    print(f"{'='*80}")
    
    # Get holdings from database for that date
    date_str = target_date.strftime('%Y-%m-%d')
    
    # Fetch holdings for target date
    target_result = db.supabase.table('etf_holdings_log').select(
        'holding_ticker, shares_held, weight_percent'
    ).eq('etf_ticker', etf_ticker).eq('date', date_str).execute()
    
    if not target_result.data:
        print(f"[ERROR] No holdings found for {etf_ticker} on {date_str}")
        return
    
    target_holdings = pd.DataFrame(target_result.data)
    target_holdings = target_holdings.rename(columns={
        'holding_ticker': 'ticker',
        'shares_held': 'shares'
    })
    
    print(f"\nTarget date ({date_str}): {len(target_holdings)} holdings")
    
    # Get previous holdings
    previous_holdings = get_previous_holdings(db, etf_ticker, target_date)
    
    if previous_holdings.empty:
        print(f"[INFO] No previous holdings found - all {len(target_holdings)} holdings would appear as 'new'")
        print("\nFirst 20 'new' holdings:")
        for idx, row in target_holdings.head(20).iterrows():
            print(f"  {row['ticker']}: {row['shares']:,.0f} shares")
        return
    
    print(f"Previous date: {len(previous_holdings)} holdings")
    
    # Calculate diff
    changes = calculate_diff(target_holdings, previous_holdings, etf_ticker)
    
    print(f"\n{'='*80}")
    print(f"Detected {len(changes)} significant changes")
    print(f"{'='*80}\n")
    
    if not changes:
        print("No significant changes detected.")
        return
    
    # Group by action
    buys = [c for c in changes if c.get('action') == 'BUY']
    sells = [c for c in changes if c.get('action') == 'SELL']
    
    print(f"BUYS: {len(buys)}")
    print(f"SELLS: {len(sells)}\n")
    
    if buys:
        print("Top 20 Buys:")
        for i, change in enumerate(sorted(buys, key=lambda x: abs(x.get('share_diff', 0)), reverse=True)[:20], 1):
            ticker = change.get('ticker', 'N/A')
            share_diff = change.get('share_diff', 0)
            percent_change = change.get('percent_change', 0)
            shares_now = change.get('shares_now', 0)
            shares_prev = change.get('shares_prev', 0)
            print(f"  {i:2d}. {ticker:6s} | {shares_prev:>12,.0f} -> {shares_now:>12,.0f} | "
                  f"Change: {share_diff:>+12,.0f} ({percent_change:>+6.1f}%)")
    
    if sells:
        print("\nTop 20 Sells:")
        for i, change in enumerate(sorted(sells, key=lambda x: abs(x.get('share_diff', 0)), reverse=True)[:20], 1):
            ticker = change.get('ticker', 'N/A')
            share_diff = change.get('share_diff', 0)
            percent_change = change.get('percent_change', 0)
            shares_now = change.get('shares_now', 0)
            shares_prev = change.get('shares_prev', 0)
            print(f"  {i:2d}. {ticker:6s} | {shares_prev:>12,.0f} -> {shares_now:>12,.0f} | "
                  f"Change: {share_diff:>+12,.0f} ({percent_change:>+6.1f}%)")
    
    # Check for suspicious patterns
    print(f"\n{'='*80}")
    print("Analysis:")
    print(f"{'='*80}")
    
    # Check if many changes are "new" positions (shares_prev = 0)
    new_positions = [c for c in changes if c.get('shares_prev', 0) == 0]
    removed_positions = [c for c in changes if c.get('shares_now', 0) == 0]
    
    print(f"New positions (shares_prev = 0): {len(new_positions)}")
    print(f"Removed positions (shares_now = 0): {len(removed_positions)}")
    print(f"Modified positions: {len(changes) - len(new_positions) - len(removed_positions)}")
    
    if len(new_positions) > len(changes) * 0.5:
        print(f"\n[WARNING] More than 50% of changes are 'new' positions!")
        print("This suggests missing previous data or a data issue.")
    
    # Check for duplicate tickers
    tickers = [c.get('ticker') for c in changes]
    duplicates = [t for t in tickers if tickers.count(t) > 1]
    if duplicates:
        print(f"\n[WARNING] Found duplicate tickers in changes: {set(duplicates)}")
        print("This suggests a data aggregation issue.")
    
    # Check for systematic adjustments (all changes clustered around same percentage)
    if changes:
        percent_changes = [abs(c.get('percent_change', 0)) for c in changes]
        if len(percent_changes) > 5:
            # Check if most changes are within 0.1% of each other
            from collections import Counter
            rounded_pcts = [round(p, 1) for p in percent_changes]
            pct_counts = Counter(rounded_pcts)
            most_common_pct, most_common_count = pct_counts.most_common(1)[0]
            
            if most_common_count >= len(changes) * 0.8:  # 80% or more at same percentage
                print(f"\n{'='*80}")
                print(f"[SYSTEMATIC ADJUSTMENT DETECTED]")
                print(f"{'='*80}")
                print(f"{most_common_count} out of {len(changes)} changes ({most_common_count/len(changes)*100:.1f}%)")
                print(f"are clustered around {most_common_pct:.1f}% change.")
                print(f"\nThis is NOT legitimate trading activity!")
                print(f"It's likely:")
                print(f"  - Expense ratio/fee deduction")
                print(f"  - Data normalization/rounding")
                print(f"  - Systematic rebalancing calculation")
                print(f"\nExample changes showing the pattern:")
                example_changes = [c for c in changes if abs(abs(c.get('percent_change', 0)) - most_common_pct) < 0.1][:5]
                for c in example_changes:
                    print(f"  {c.get('ticker'):6s}: {c.get('percent_change'):>+6.2f}% "
                          f"({c.get('shares_prev', 0):>12,.0f} -> {c.get('shares_now', 0):>12,.0f})")

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Show ARK ETF changes for a specific date')
    parser.add_argument('--etf', type=str, required=True, help='ETF ticker (e.g., ARKG, ARKK)')
    parser.add_argument('--date', type=str, help='Date in YYYY-MM-DD format (default: check recent articles)')
    args = parser.parse_args()
    
    db = SupabaseClient(use_service_role=True)
    repo = ResearchRepository()
    
    etf_ticker = args.etf.upper()
    
    if args.date:
        target_date = datetime.strptime(args.date, '%Y-%m-%d').replace(tzinfo=timezone.utc)
    else:
        # Find the date of the suspicious article
        articles = repo.client.execute_query("""
            SELECT id, title, summary, fetched_at
            FROM research_articles
            WHERE article_type = 'ETF Change'
              AND title LIKE %s
            ORDER BY fetched_at DESC
            LIMIT 5
        """, (f"{etf_ticker} Daily Holdings Update%",))
        
        if not articles:
            print(f"[ERROR] No articles found for {etf_ticker}")
            return
        
        # Use the most recent article's date
        article = articles[0]
        fetched_at = article.get('fetched_at')
        if isinstance(fetched_at, str):
            fetched_at = datetime.fromisoformat(fetched_at.replace('Z', '+00:00'))
        target_date = fetched_at.replace(hour=0, minute=0, second=0, microsecond=0)
        
        summary = article.get('summary', '')
        import re
        match = re.search(r'made (\d+) significant changes', summary)
        change_count = int(match.group(1)) if match else 0
        
        print(f"Found article: {article['title']}")
        print(f"Date: {target_date.strftime('%Y-%m-%d')}")
        print(f"Article says: {change_count} changes")
        print()
    
    show_changes_for_date(etf_ticker, target_date, db)

if __name__ == "__main__":
    main()
