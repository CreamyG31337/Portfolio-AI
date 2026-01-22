#!/usr/bin/env python3
"""
Analyze ETF Changes Scale
==========================

Analyzes actual ETF holdings data to understand:
1. How many changes per day (typical vs worst case)
2. Distribution of changes (are most small? few large?)
3. Whether patterns exist that LLM can extract
4. What batching/aggregation strategy makes sense

This validates the approach before building the full system.
"""

import sys
import logging
from pathlib import Path
from datetime import datetime, timezone, timedelta
from collections import Counter, defaultdict
import pandas as pd

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from supabase_client import SupabaseClient

# Constants from jobs_etf_watchtower (copied to avoid import issues)
MIN_SHARE_CHANGE = 1000  # Minimum absolute share change to log
MIN_PERCENT_CHANGE = 0.5  # Minimum % change relative to previous holdings

# Tickers to exclude from change detection
EXCLUDED_TICKERS = {
    'USD', 'CASH', 'CASHCOLLATERAL', 'MARGIN_CASH', 'MONEY_MARKET',
    'XTSLA', 'MSFUT', 'SGAFT', 'ESH6', 'ESH5', 'ESM6', 'ESU6', 'ESZ6',
    'NQH6', 'NQM6', 'NQU6', 'NQZ6', 'RTY', 'RTYM6', 'SPY_FUT',
    'ETD_USD', 'FUT', 'SWAP', 'FWD', 'TBILL', 'USINTR', 'BIL',
}

EXCLUDED_TICKER_PATTERNS = ['FUT', '_USD', 'SWAP', 'FWD']

def is_stock_ticker(ticker: str) -> bool:
    """Check if a ticker represents a tradeable stock (not cash/futures/derivatives)."""
    if not ticker or not isinstance(ticker, str):
        return False
    
    ticker_upper = ticker.upper().strip()
    
    # Direct exclusion list
    if ticker_upper in EXCLUDED_TICKERS:
        return False
    
    # Pattern matching
    for pattern in EXCLUDED_TICKER_PATTERNS:
        if pattern in ticker_upper:
            return False
    
    return True

def get_previous_holdings(db: SupabaseClient, etf_ticker: str, date: datetime) -> pd.DataFrame:
    """Fetch latest available previous holdings from database."""
    date_str = date.strftime('%Y-%m-%d')
    
    try:
        # Find latest date before today
        date_res = db.supabase.table('etf_holdings_log') \
            .select('date') \
            .eq('etf_ticker', etf_ticker) \
            .lt('date', date_str) \
            .order('date', desc=True) \
            .limit(1) \
            .execute()

        if not date_res.data:
            return pd.DataFrame(columns=['ticker', 'shares', 'weight_percent'])

        previous_date = date_res.data[0]['date']

        # Fetch holdings for that date (with pagination)
        all_data = []
        page_size = 1000
        offset = 0
        
        while True:
            result = db.supabase.table('etf_holdings_log').select(
                'holding_ticker, shares_held, weight_percent'
            ).eq('etf_ticker', etf_ticker).eq('date', previous_date).range(offset, offset + page_size - 1).execute()
            
            if not result.data:
                break
            
            all_data.extend(result.data)
            
            if len(result.data) < page_size:
                break
            
            offset += page_size
        
        if not all_data:
            return pd.DataFrame(columns=['ticker', 'shares', 'weight_percent'])
        
        df = pd.DataFrame(all_data)
        df = df.rename(columns={
            'holding_ticker': 'ticker',
            'shares_held': 'shares'
        })
        
        return df
        
    except Exception as e:
        logger.error(f"Error getting previous holdings: {e}")
        return pd.DataFrame(columns=['ticker', 'shares', 'weight_percent'])

def calculate_diff(today: pd.DataFrame, yesterday: pd.DataFrame, etf_ticker: str) -> list:
    """Calculate significant holding changes."""
    # Merge on ticker
    merged = today.merge(
        yesterday,
        on='ticker',
        how='outer',
        suffixes=('_now', '_prev')
    )
    
    # Fill NaN (new/removed positions)
    merged['shares_now'] = merged['shares_now'].fillna(0)
    merged['shares_prev'] = merged['shares_prev'].fillna(0)
    
    # Calculate absolute and percentage change
    merged['share_diff'] = merged['shares_now'] - merged['shares_prev']
    merged['percent_change'] = ((merged['share_diff'] / merged['shares_prev']) * 100).replace([float('inf'), -float('inf')], 100)
    
    # Filter for significant changes
    significant = merged[
        (merged['share_diff'].abs() >= MIN_SHARE_CHANGE) |
        (merged['percent_change'].abs() >= MIN_PERCENT_CHANGE)
    ].copy()
    
    # Filter out non-stock tickers
    before_filter = len(significant)
    significant = significant[significant['ticker'].apply(is_stock_ticker)]
    
    # Detect and filter systematic adjustments
    if len(significant) > 5:
        from collections import Counter
        rounded_pcts = [round(abs(row['percent_change']), 1) for _, row in significant.iterrows()]
        pct_counts = Counter(rounded_pcts)
        most_common_pct, most_common_count = pct_counts.most_common(1)[0]
        
        if most_common_count >= len(significant) * 0.8:
            if most_common_pct <= 2.0:
                all_same_direction = (
                    all(row['share_diff'] > 0 for _, row in significant.iterrows()) or
                    all(row['share_diff'] < 0 for _, row in significant.iterrows())
                )
                
                if all_same_direction:
                    return []
    
    # Add context
    significant['etf'] = etf_ticker
    significant['action'] = significant['share_diff'].apply(lambda x: 'BUY' if x > 0 else 'SELL')
    
    return significant.to_dict('records')

logging.basicConfig(
    level=logging.WARNING,  # Reduce noise
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ETF sizes for context
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

def analyze_etf_date(etf_ticker: str, target_date: datetime, db: SupabaseClient) -> dict:
    """Analyze changes for a specific ETF on a specific date"""
    
    # Get holdings for target date
    date_str = target_date.strftime('%Y-%m-%d')
    target_result = db.supabase.table('etf_holdings_log').select(
        'holding_ticker, shares_held'
    ).eq('etf_ticker', etf_ticker).eq('date', date_str).execute()
    
    if not target_result.data:
        return None
    
    target_holdings = pd.DataFrame(target_result.data)
    target_holdings = target_holdings.rename(columns={
        'holding_ticker': 'ticker',
        'shares_held': 'shares'
    })
    
    # Get previous holdings
    previous_holdings = get_previous_holdings(db, etf_ticker, target_date)
    
    if previous_holdings.empty:
        return {
            'etf': etf_ticker,
            'date': date_str,
            'total_holdings': len(target_holdings),
            'changes': 0,
            'note': 'No previous data'
        }
    
    # Calculate diff
    changes = calculate_diff(target_holdings, previous_holdings, etf_ticker)
    
    if not changes:
        return {
            'etf': etf_ticker,
            'date': date_str,
            'total_holdings': len(target_holdings),
            'changes': 0,
            'note': 'No significant changes'
        }
    
    # Analyze distribution
    buys = [c for c in changes if c.get('action') == 'BUY']
    sells = [c for c in changes if c.get('action') == 'SELL']
    
    # Calculate statistics
    share_changes = [abs(c.get('share_diff', 0)) for c in changes]
    percent_changes = [abs(c.get('percent_change', 0)) for c in changes]
    
    # Group by magnitude
    large_changes = [c for c in changes if abs(c.get('share_diff', 0)) >= 10000]
    medium_changes = [c for c in changes if 1000 <= abs(c.get('share_diff', 0)) < 10000]
    small_changes = [c for c in changes if abs(c.get('share_diff', 0)) < 1000]
    
    # Check for patterns
    tickers_changed = [c.get('ticker') for c in changes]
    ticker_counts = Counter(tickers_changed)
    repeated_tickers = {t: count for t, count in ticker_counts.items() if count > 1}
    
    # Sector analysis (if we can get it)
    # For now, just count unique tickers
    
    return {
        'etf': etf_ticker,
        'date': date_str,
        'total_holdings': len(target_holdings),
        'total_changes': len(changes),
        'buys': len(buys),
        'sells': len(sells),
        'large_changes': len(large_changes),  # >= 10k shares
        'medium_changes': len(medium_changes),  # 1k-10k shares
        'small_changes': len(small_changes),  # < 1k shares (but still significant by %)
        'unique_tickers': len(set(tickers_changed)),
        'repeated_tickers': len(repeated_tickers),
        'avg_share_change': sum(share_changes) / len(share_changes) if share_changes else 0,
        'max_share_change': max(share_changes) if share_changes else 0,
        'avg_percent_change': sum(percent_changes) / len(percent_changes) if percent_changes else 0,
        'top_5_tickers': [c.get('ticker') for c in sorted(changes, key=lambda x: abs(x.get('share_diff', 0)), reverse=True)[:5]],
        'changes': changes  # Full list for detailed analysis
    }

def analyze_multiple_dates(etf_ticker: str, days: int = 7, db: SupabaseClient = None) -> list:
    """Analyze multiple dates to see patterns"""
    if db is None:
        db = SupabaseClient(use_service_role=True)
    
    results = []
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    
    for i in range(days):
        target_date = today - timedelta(days=i)
        result = analyze_etf_date(etf_ticker, target_date, db)
        if result:
            results.append(result)
    
    return results

def summarize_analysis(results: list) -> dict:
    """Summarize analysis across multiple dates"""
    if not results:
        return {}
    
    total_changes = sum(r.get('total_changes', 0) for r in results)
    avg_changes = total_changes / len(results) if results else 0
    max_changes = max((r.get('total_changes', 0) for r in results), default=0)
    
    # Distribution analysis
    all_changes = []
    for r in results:
        changes = r.get('changes', [])
        if isinstance(changes, list):
            all_changes.extend(changes)
    
    if not all_changes:
        return {
            'avg_changes_per_day': avg_changes,
            'max_changes_per_day': max_changes,
            'total_days_analyzed': len(results),
            'note': 'No changes found'
        }
    
    # Group by magnitude
    large = [c for c in all_changes if abs(c.get('share_diff', 0)) >= 10000]
    medium = [c for c in all_changes if 1000 <= abs(c.get('share_diff', 0)) < 10000]
    small = [c for c in all_changes if abs(c.get('share_diff', 0)) < 1000]
    
    # Pattern detection
    ticker_activity = Counter([c.get('ticker') for c in all_changes])
    most_active_tickers = ticker_activity.most_common(10)
    
    # Direction analysis
    buys = [c for c in all_changes if c.get('action') == 'BUY']
    sells = [c for c in all_changes if c.get('action') == 'SELL']
    
    return {
        'avg_changes_per_day': avg_changes,
        'max_changes_per_day': max_changes,
        'total_days_analyzed': len(results),
        'total_changes_analyzed': len(all_changes),
        'distribution': {
            'large': len(large),  # >= 10k shares
            'medium': len(medium),  # 1k-10k shares
            'small': len(small),  # < 1k shares
        },
        'direction': {
            'buys': len(buys),
            'sells': len(sells),
            'buy_ratio': len(buys) / len(all_changes) if all_changes else 0
        },
        'most_active_tickers': most_active_tickers,
        'llm_analysis_feasibility': {
            'total_items': len(all_changes),
            'can_batch': len(all_changes) > 50,
            'recommended_batch_size': min(50, max(10, len(all_changes) // 5)),
            'needs_aggregation': len(all_changes) > 100
        }
    }

def test_llm_analysis_sample(changes: list, sample_size: int = 50) -> str:
    """Test if LLM can meaningfully analyze a sample of changes"""
    if not changes:
        return "No changes to analyze"
    
    # Take a representative sample
    sample = sorted(changes, key=lambda x: abs(x.get('share_diff', 0)), reverse=True)[:sample_size]
    
    # Format for LLM
    formatted = []
    for c in sample:
        formatted.append(
            f"{c.get('ticker')}: {c.get('action')} {abs(c.get('share_diff', 0)):,.0f} shares "
            f"({c.get('percent_change', 0):+.1f}%)"
        )
    
    sample_text = "\n".join(formatted)
    
    # This is what we'd send to LLM
    prompt = f"""Analyze these ETF holdings changes:

{sample_text}

Provide:
1. Overall pattern (accumulation, distribution, rotation, mixed)
2. Key themes (sectors, tickers, trends)
3. Notable changes (largest buys/sells)
4. Sentiment (bullish, bearish, neutral)

Keep response under 500 words."""

    return prompt

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Analyze ETF changes scale')
    parser.add_argument('--etf', type=str, required=True, help='ETF ticker (e.g., IWC, IWM, ARKK)')
    parser.add_argument('--days', type=int, default=7, help='Number of days to analyze (default: 7)')
    parser.add_argument('--date', type=str, help='Specific date in YYYY-MM-DD format')
    parser.add_argument('--test-llm', action='store_true', help='Generate sample LLM prompt')
    args = parser.parse_args()
    
    db = SupabaseClient(use_service_role=True)
    etf_ticker = args.etf.upper()
    
    print(f"\n{'='*80}")
    print(f"ETF Changes Scale Analysis: {etf_ticker}")
    print(f"{'='*80}\n")
    
    if args.date:
        # Single date analysis
        target_date = datetime.strptime(args.date, '%Y-%m-%d').replace(tzinfo=timezone.utc)
        result = analyze_etf_date(etf_ticker, target_date, db)
        
        if result:
            print(f"Date: {result['date']}")
            print(f"Total Holdings: {result['total_holdings']}")
            print(f"Significant Changes: {result['total_changes']}")
            print(f"  - Buys: {result['buys']}")
            print(f"  - Sells: {result['sells']}")
            print(f"\nDistribution:")
            print(f"  - Large (>=10k shares): {result['large_changes']}")
            print(f"  - Medium (1k-10k shares): {result['medium_changes']}")
            print(f"  - Small (<1k shares, but >0.5%): {result['small_changes']}")
            print(f"\nTop 5 Tickers by Change:")
            for ticker in result['top_5_tickers']:
                print(f"  - {ticker}")
            
            if args.test_llm and result.get('changes'):
                print(f"\n{'='*80}")
                print("Sample LLM Prompt (50 changes):")
                print(f"{'='*80}\n")
                prompt = test_llm_analysis_sample(result['changes'], sample_size=50)
                print(prompt)
    else:
        # Multi-date analysis
        results = analyze_multiple_dates(etf_ticker, days=args.days, db=db)
        summary = summarize_analysis(results)
        
        print(f"Analysis Period: Last {args.days} days")
        print(f"Days with Data: {summary.get('total_days_analyzed', 0)}")
        print(f"\nScale Metrics:")
        print(f"  - Average changes per day: {summary.get('avg_changes_per_day', 0):.1f}")
        print(f"  - Maximum changes in one day: {summary.get('max_changes_per_day', 0)}")
        print(f"  - Total changes analyzed: {summary.get('total_changes_analyzed', 0)}")
        
        if summary.get('distribution'):
            print(f"\nDistribution (across all days):")
            dist = summary['distribution']
            print(f"  - Large (>=10k shares): {dist['large']}")
            print(f"  - Medium (1k-10k shares): {dist['medium']}")
            print(f"  - Small (<1k shares): {dist['small']}")
        
        if summary.get('direction'):
            dir_info = summary['direction']
            print(f"\nDirection:")
            print(f"  - Buys: {dir_info['buys']}")
            print(f"  - Sells: {dir_info['sells']}")
            print(f"  - Buy Ratio: {dir_info['buy_ratio']:.1%}")
        
        if summary.get('most_active_tickers'):
            print(f"\nMost Active Tickers (across all days):")
            for ticker, count in summary['most_active_tickers'][:10]:
                print(f"  - {ticker}: {count} changes")
        
        if summary.get('llm_analysis_feasibility'):
            feasibility = summary['llm_analysis_feasibility']
            print(f"\n{'='*80}")
            print("LLM Analysis Feasibility:")
            print(f"{'='*80}")
            print(f"  - Total items to analyze: {feasibility['total_items']}")
            print(f"  - Needs batching: {feasibility['can_batch']}")
            print(f"  - Recommended batch size: {feasibility['recommended_batch_size']}")
            print(f"  - Needs aggregation: {feasibility['needs_aggregation']}")
            
            if feasibility['needs_aggregation']:
                print(f"\n[WARNING] RECOMMENDATION: Use aggregation strategy")
                print(f"   - Analyze top N changes individually (e.g., top 20)")
                print(f"   - Aggregate remaining changes by pattern (accumulation, distribution)")
                print(f"   - Generate summary article with embeddings")
            else:
                print(f"\n[OK] RECOMMENDATION: Can analyze all changes")
                print(f"   - All changes fit in single LLM context")
                print(f"   - Generate individual analysis per change")
                print(f"   - Store with embeddings for search")

if __name__ == "__main__":
    main()
