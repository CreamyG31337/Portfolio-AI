"""
Check if new records are missing pre-converted currency values.
This helps diagnose if the root cause is still creating records without pre-converted values.
"""
import os
import sys
import pandas as pd
from datetime import datetime, timedelta, timezone

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from web_dashboard.supabase_client import SupabaseClient

def check_nulls(fund_name: str = "Project Chimera", days_back: int = 30):
    """Check if new records are missing pre-converted values.
    
    Args:
        fund_name: Fund to check (default: "Project Chimera")
        days_back: How many days back to consider "recent" (default: 30)
    """
    client = SupabaseClient(use_service_role=True)
    
    print("=" * 70)
    print(f"CHECKING PRE-CONVERTED VALUES FOR FUND: {fund_name}")
    print("=" * 70)
    
    # Get all data (paginated)
    print(f"\nFetching all portfolio positions...")
    all_rows = []
    offset = 0
    batch_size = 1000
    
    while True:
        result = client.supabase.table("portfolio_positions") \
            .select("id, date, created_at, fund, ticker, currency, "
                   "total_value, cost_basis, pnl, "
                   "total_value_base, cost_basis_base, pnl_base, "
                   "base_currency, exchange_rate") \
            .eq("fund", fund_name) \
            .order("date", desc=False) \
            .range(offset, offset + batch_size - 1) \
            .execute()
        
        if not result.data:
            break
        all_rows.extend(result.data)
        if len(result.data) < batch_size:
            break
        offset += batch_size
    
    if not all_rows:
        print("No data found.")
        return
    
    df = pd.DataFrame(all_rows)
    df['date'] = pd.to_datetime(df['date'])
    if 'created_at' in df.columns:
        df['created_at'] = pd.to_datetime(df['created_at'])
    
    print(f"Fetched {len(df)} total records")
    
    # Overall statistics
    print("\n" + "=" * 70)
    print("OVERALL STATISTICS")
    print("=" * 70)
    
    total_records = len(df)
    missing_base = df['total_value_base'].isnull().sum()
    missing_pct = (missing_base / total_records * 100) if total_records > 0 else 0
    
    print(f"\nTotal records: {total_records:,}")
    print(f"Records missing total_value_base: {missing_base:,} ({missing_pct:.1f}%)")
    print(f"Records WITH total_value_base: {total_records - missing_base:,} ({100 - missing_pct:.1f}%)")
    
    # Check if we meet the 80% threshold
    if missing_pct > 20:
        print(f"\nWARNING: Only {100 - missing_pct:.1f}% have pre-converted values (need >80% for fast path)")
    else:
        print(f"\nGood: {100 - missing_pct:.1f}% have pre-converted values (meets >80% threshold)")
    
    # Analyze by date (to see if newer records have the problem)
    print("\n" + "=" * 70)
    print("ANALYSIS BY DATE (Recent vs Old)")
    print("=" * 70)
    
    df['date_only'] = df['date'].dt.date
    date_stats = df.groupby('date_only').agg({
        'id': 'count',  # Count total records
        'total_value_base': lambda x: x.isnull().sum(),  # Count missing
        'date': 'max'
    }).reset_index()
    date_stats.columns = ['date', 'total_records', 'missing_base', 'max_timestamp']
    date_stats['has_preconverted_pct'] = ((date_stats['total_records'] - date_stats['missing_base']) / date_stats['total_records'] * 100).round(1)
    date_stats = date_stats.sort_values('date', ascending=False)
    
    # Show last 10 dates
    print("\nLast 10 dates:")
    print(date_stats[['date', 'total_records', 'missing_base', 'has_preconverted_pct']].head(10).to_string(index=False))
    
    # Detailed breakdown of last 7 days
    print("\n" + "=" * 70)
    print("DETAILED BREAKDOWN - LAST 7 DAYS")
    print("=" * 70)
    
    last_7_days = date_stats.head(7).sort_values('date', ascending=False)
    for row in last_7_days.to_dict('records'):
        date_str = str(row['date'])
        total = int(row['total_records'])
        missing = int(row['missing_base'])
        has_preconverted = total - missing
        pct = row['has_preconverted_pct']
        
        print(f"\n{date_str}:")
        print(f"  Total records: {total}")
        print(f"  Missing pre-converted: {missing} ({100-pct:.1f}%)")
        print(f"  Has pre-converted: {has_preconverted} ({pct:.1f}%)")
        
        # Show sample records for this date
        date_df = df[df['date_only'] == row['date']]
        if len(date_df) > 0:
            missing_for_date = date_df[date_df['total_value_base'].isnull()]
            if len(missing_for_date) > 0:
                print(f"  Sample missing records:")
                sample = missing_for_date.head(3)[['ticker', 'currency', 'total_value', 'base_currency', 'exchange_rate']]
                for rec in sample.to_dict('records'):
                    print(f"    {rec['ticker']:6s} {rec['currency']:3s} value=${rec['total_value']:>10.2f} base={rec.get('base_currency', 'N/A')} rate={rec.get('exchange_rate', 'N/A')}")
    
    # Compare Dec 24 (working) vs Dec 23-16 (broken) to identify code path
    print("\n" + "=" * 70)
    print("CODE PATH ANALYSIS - Dec 24 (WORKING) vs Dec 23-16 (BROKEN)")
    print("=" * 70)
    
    if 'created_at' in df.columns and df['created_at'].notna().any():
        dec24_df = df[df['date_only'] == pd.Timestamp('2025-12-24').date()]
        dec23_df = df[df['date_only'] == pd.Timestamp('2025-12-23').date()]
        
        if len(dec24_df) > 0 and len(dec23_df) > 0:
            dec24_created = pd.to_datetime(dec24_df['created_at']).min()
            dec23_created = pd.to_datetime(dec23_df['created_at']).min()
            
            print(f"\nDec 24 records (100% have pre-converted values):")
            print(f"  Earliest created_at: {dec24_created}")
            print(f"  Total records: {len(dec24_df)}")
            print(f"  All have pre-converted values: {dec24_df['total_value_base'].notna().all()}")
            
            print(f"\nDec 23 records (57.1% missing pre-converted values):")
            print(f"  Earliest created_at: {dec23_created}")
            print(f"  Total records: {len(dec23_df)}")
            print(f"  Missing pre-converted: {dec23_df['total_value_base'].isnull().sum()}")
            
            time_diff = abs((dec24_created - dec23_created).total_seconds() / 3600)
            print(f"\nTime difference: {time_diff:.1f} hours")
            if time_diff < 1:
                print("  -> Records created around the same time - likely same code path")
                print("  -> Dec 24 working suggests fix is in place, but Dec 23-16 need backfill")
            else:
                print(f"  -> Records created at different times - likely different code paths")
                print(f"  -> Dec 24: Scheduled job (works correctly)")
                print(f"  -> Dec 23-16: Rebuild script (has bug)")
    
    # Check recent records (last N days)
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_back)
    recent_df = df[df['date'] >= cutoff_date]
    old_df = df[df['date'] < cutoff_date]
    
    print("\n" + "=" * 70)
    print(f"RECENT RECORDS (Last {days_back} days) vs OLD RECORDS")
    print("=" * 70)
    
    if len(recent_df) > 0:
        recent_missing = recent_df['total_value_base'].isnull().sum()
        recent_pct = (recent_missing / len(recent_df) * 100)
        print(f"\nRecent records (last {days_back} days):")
        print(f"   Total: {len(recent_df):,}")
        print(f"   Missing pre-converted: {recent_missing:,} ({recent_pct:.1f}%)")
        print(f"   Has pre-converted: {len(recent_df) - recent_missing:,} ({100 - recent_pct:.1f}%)")
        
        if recent_pct > 20:
            print(f"   PROBLEM: Recent records still missing pre-converted values!")
        else:
            print(f"   Good: Recent records have pre-converted values")
    else:
        print(f"\nNo recent records found (last {days_back} days)")
    
    if len(old_df) > 0:
        old_missing = old_df['total_value_base'].isnull().sum()
        old_pct = (old_missing / len(old_df) * 100)
        print(f"\nOld records (before {days_back} days ago):")
        print(f"   Total: {len(old_df):,}")
        print(f"   Missing pre-converted: {old_missing:,} ({old_pct:.1f}%)")
        print(f"   Has pre-converted: {len(old_df) - old_missing:,} ({100 - old_pct:.1f}%)")
    
    # Check by created_at (if available) - this shows when records were actually inserted
    if 'created_at' in df.columns and df['created_at'].notna().any():
        print("\n" + "=" * 70)
        print("ANALYSIS BY CREATED_AT (When records were inserted)")
        print("=" * 70)
        
        recent_created = df[df['created_at'] >= cutoff_date]
        if len(recent_created) > 0:
            recent_created_missing = recent_created['total_value_base'].isnull().sum()
            recent_created_pct = (recent_created_missing / len(recent_created) * 100)
            print(f"\nRecords created in last {days_back} days:")
            print(f"   Total: {len(recent_created):,}")
            print(f"   Missing pre-converted: {recent_created_missing:,} ({recent_created_pct:.1f}%)")
            
            if recent_created_pct > 20:
                print(f"   ROOT CAUSE STILL ACTIVE: Newly created records missing pre-converted values!")
            else:
                print(f"   Good: Newly created records have pre-converted values")
    
    # Sample records with missing values
    print("\n" + "=" * 70)
    print("SAMPLE RECORDS WITH MISSING PRE-CONVERTED VALUES")
    print("=" * 70)
    
    missing_df = df[df['total_value_base'].isnull()].head(10)
    if len(missing_df) > 0:
        print(f"\nShowing {len(missing_df)} sample records:")
        sample_cols = ['date', 'ticker', 'currency', 'total_value', 'cost_basis', 
                      'base_currency', 'exchange_rate', 'created_at']
        available_cols = [col for col in sample_cols if col in missing_df.columns]
        print(missing_df[available_cols].to_string(index=False))
    else:
        print("\nNo records with missing pre-converted values found!")
    
    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    
    if len(recent_df) > 0:
        recent_pct = (recent_df['total_value_base'].isnull().sum() / len(recent_df) * 100)
        if recent_pct > 20:
            print("\nPROBLEM DETECTED: Recent records are still missing pre-converted values.")
            print("   This indicates the root cause is still active.")
            print("   Action needed: Fix the code that creates new records.")
        else:
            print("\nRecent records look good - they have pre-converted values.")
            print("   The issue is likely only with old historical data.")
            print("   Action needed: Run backfill script for old records.")
    else:
        print("\nNo recent records to analyze.")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Check if new records are missing pre-converted values")
    parser.add_argument("--fund", type=str, default="Project Chimera", help="Fund name to check")
    parser.add_argument("--days", type=int, default=30, help="Days back to consider 'recent' (default: 30)")
    args = parser.parse_args()
    
    check_nulls(fund_name=args.fund, days_back=args.days)
