#!/usr/bin/env python3
"""
Cleanup Bad ETF Change Articles
================================

Identifies and removes ETF Change articles with suspiciously high change counts
that were caused by the pagination bug (where only 1000 holdings were fetched).

The bug caused ETFs like IWM (1957 holdings) to flag ~958 holdings as "new"
because only the first 1000 were fetched from the previous day.
"""

import sys
import logging
from pathlib import Path
from datetime import datetime, timezone, timedelta
import re

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from research_repository import ResearchRepository

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Known ETF sizes (approximate - for detecting suspicious change counts)
ETF_SIZES = {
    'IWM': 1957,
    'IWC': 1316,
    'IWO': 1102,
    'IVV': 509,
    'ARKK': 45,
    'ARKQ': 37,
    'ARKW': 45,
    'ARKG': 34,
    'ARKF': 41,
    'ARKX': 33,
    'IZRL': 64,
    'PRNT': 44,
}

def extract_change_count(summary: str) -> int:
    """Extract number of changes from summary like 'IWM made 955 significant changes today'"""
    if not summary:
        return 0
    
    # Pattern: "IWM made 955 significant changes today"
    match = re.search(r'made (\d+) significant changes', summary)
    if match:
        return int(match.group(1))
    return 0

def is_suspicious_change_count(etf_ticker: str, change_count: int) -> bool:
    """Check if change count is suspiciously high (likely caused by pagination bug)"""
    etf_size = ETF_SIZES.get(etf_ticker, 0)
    if etf_size == 0:
        return False
    
    # If change count is > 50% of ETF size, it's suspicious
    # The bug would cause ~958 changes for IWM (1957 - 1000 + 1)
    # So anything > 50% is likely bad
    threshold = etf_size * 0.5
    
    # Also check for specific known bad patterns
    # IWM with ~955 changes is definitely bad
    if etf_ticker == 'IWM' and change_count > 900:
        return True
    if etf_ticker == 'IWC' and change_count > 600:
        return True
    if etf_ticker == 'IWO' and change_count > 500:
        return True
    
    return change_count > threshold

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Cleanup bad ETF Change articles')
    parser.add_argument('--delete', action='store_true', help='Actually delete the articles (default: dry-run)')
    args = parser.parse_args()
    
    repo = ResearchRepository()
    
    print("=" * 80)
    print("Cleanup Bad ETF Change Articles")
    print("=" * 80)
    if not args.delete:
        print("[DRY-RUN MODE] Use --delete to actually delete articles")
    print()
    
    # Find all ETF Change articles
    query = """
        SELECT id, title, summary, source, fetched_at, tickers
        FROM research_articles
        WHERE article_type = 'ETF Change'
        ORDER BY fetched_at DESC
    """
    
    articles = repo.client.execute_query(query)
    
    if not articles:
        print("[OK] No ETF Change articles found.")
        return
    
    print(f"Found {len(articles)} ETF Change articles total")
    print()
    
    # Identify suspicious articles
    suspicious_articles = []
    
    for article in articles:
        title = article.get('title', '')
        summary = article.get('summary', '')
        
        # Extract ETF ticker from title (e.g., "IWM Daily Holdings Update")
        etf_match = re.match(r'^(\w+) Daily Holdings Update', title)
        if not etf_match:
            continue
        
        etf_ticker = etf_match.group(1)
        change_count = extract_change_count(summary)
        
        if change_count > 0 and is_suspicious_change_count(etf_ticker, change_count):
            suspicious_articles.append({
                'id': article['id'],
                'etf_ticker': etf_ticker,
                'title': title,
                'summary': summary,
                'change_count': change_count,
                'fetched_at': article.get('fetched_at'),
            })
    
    if not suspicious_articles:
        print("[OK] No suspicious articles found. All change counts look reasonable.")
        return
    
    print(f"[WARNING] Found {len(suspicious_articles)} suspicious articles:")
    print()
    
    for article in suspicious_articles:
        print(f"  {article['etf_ticker']}: {article['change_count']} changes")
        print(f"    Title: {article['title']}")
        print(f"    Summary: {article['summary']}")
        print(f"    Date: {article['fetched_at']}")
        print(f"    ID: {article['id']}")
        print()
    
    print("=" * 80)
    if not args.delete:
        print("\n[DRY-RUN] Would delete these articles. Run with --delete to actually delete.")
        return
    
    print()
    print("Deleting suspicious articles...")
    
    deleted_count = 0
    for article in suspicious_articles:
        try:
            if repo.delete_article(str(article['id'])):
                deleted_count += 1
                print(f"  [OK] Deleted: {article['title']}")
            else:
                print(f"  [ERROR] Failed to delete: {article['title']}")
        except Exception as e:
            print(f"  [ERROR] Error deleting {article['title']}: {e}")
    
    print()
    print("=" * 80)
    print(f"[OK] Deleted {deleted_count} suspicious articles")
    print("=" * 80)
    
    # Show remaining articles
    remaining = repo.client.execute_query(query)
    print(f"\nRemaining ETF Change articles: {len(remaining)}")
    
    if remaining:
        print("\nRecent remaining articles:")
        for article in remaining[:5]:
            print(f"  - {article.get('title')}: {article.get('summary')}")

if __name__ == "__main__":
    main()
