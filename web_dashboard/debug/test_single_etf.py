#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Debug script to test a single ETF through the Watchtower job logic
Usage: python debug/test_single_etf.py SMH
"""

import sys
import logging
import io
from pathlib import Path
from datetime import datetime, timezone

# Fix Windows console encoding for emojis
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Add parent directory to path
sys.path.append(str(Path(__file__).resolve().parent.parent))

# Setup logging to see all output
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

def test_single_etf(etf_ticker: str):
    """Test a single ETF through the Watchtower job logic."""
    from scheduler.jobs_etf_watchtower import (
        ETF_CONFIGS,
        fetch_ark_holdings,
        fetch_ishares_holdings,
        fetch_spdr_holdings,
        fetch_globalx_holdings,
        fetch_direxion_holdings,
        fetch_vaneck_holdings,
        get_previous_holdings,
        calculate_diff,
        save_holdings_snapshot,
        upsert_etf_metadata,
        upsert_securities_metadata,
        log_significant_changes
    )
    from supabase_client import SupabaseClient
    from postgres_client import PostgresClient
    from research_repository import ResearchRepository
    
    print("=" * 80)
    print(f"Testing ETF: {etf_ticker}")
    print("=" * 80)
    print()
    
    # Check if ETF is in config
    if etf_ticker not in ETF_CONFIGS:
        print(f"[ERROR] {etf_ticker} not found in ETF_CONFIGS")
        print(f"Available ETFs: {', '.join(sorted(ETF_CONFIGS.keys()))}")
        return False
    
    config = ETF_CONFIGS[etf_ticker]
    provider = config['provider']
    url = config['url']
    
    print(f"ETF: {etf_ticker}")
    print(f"Provider: {provider}")
    print(f"URL: {url}")
    print()
    
    try:
        db = SupabaseClient(use_service_role=True)
        pc = PostgresClient()
        repo = ResearchRepository()
        today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        
        # Step 1: Download today's holdings
        print("Step 1: Downloading holdings...")
        print("-" * 80)
        
        if provider == 'ARK':
            today_holdings = fetch_ark_holdings(etf_ticker, url)
        elif provider == 'iShares':
            today_holdings = fetch_ishares_holdings(etf_ticker, url)
        elif provider == 'SPDR':
            today_holdings = fetch_spdr_holdings(etf_ticker, url)
        elif provider == 'Global X':
            today_holdings = fetch_globalx_holdings(etf_ticker, url)
        elif provider == 'Direxion':
            today_holdings = fetch_direxion_holdings(etf_ticker, url)
        elif provider == 'VanEck':
            today_holdings = fetch_vaneck_holdings(etf_ticker, url)
        else:
            print(f"[ERROR] Provider {provider} not yet implemented")
            return False
        
        if today_holdings is None:
            print(f"[ERROR] fetch function returned None")
            return False
        
        if today_holdings.empty:
            print(f"[ERROR] fetch function returned empty DataFrame")
            print(f"   This usually means:")
            print(f"   - Download failed (network error, 403, timeout)")
            print(f"   - Parsing failed (CSV format changed, Excel format different)")
            print(f"   - URL is wrong or requires authentication")
            return False
        
        print(f"[OK] Downloaded {len(today_holdings)} holdings")
        print(f"   Columns: {list(today_holdings.columns)}")
        if len(today_holdings) > 0:
            print(f"   Sample tickers: {today_holdings['ticker'].head(5).tolist()}")
        print()
        
        # Step 2: Get yesterday's holdings
        print("Step 2: Getting previous holdings...")
        print("-" * 80)
        yesterday_holdings = get_previous_holdings(pc, etf_ticker, today)
        
        if yesterday_holdings.empty:
            print(f"ℹ️  No previous holdings found (first time tracking this ETF)")
        else:
            print(f"[OK] Found {len(yesterday_holdings)} previous holdings")
        print()
        
        # Step 3: Calculate diff
        print("Step 3: Calculating changes...")
        print("-" * 80)
        if not yesterday_holdings.empty:
            changes = calculate_diff(today_holdings, yesterday_holdings, etf_ticker)
            if changes:
                print(f"[OK] Found {len(changes)} significant changes")
                # Show first few changes
                for i, change in enumerate(changes[:5]):
                    print(f"   {change.get('ticker', 'N/A')}: {change.get('action', 'N/A')} "
                          f"{change.get('share_diff', 0):+,.0f} shares "
                          f"({change.get('percent_change', 0):.1f}%)")
                if len(changes) > 5:
                    print(f"   ... and {len(changes) - 5} more")
            else:
                print("ℹ️  No significant changes detected")
        else:
            print("ℹ️  Skipping change calculation (no previous data)")
        print()
        
        # Step 4: Save snapshot
        print("Step 4: Saving holdings snapshot...")
        print("-" * 80)
        try:
            save_holdings_snapshot(pc, etf_ticker, today_holdings, today)
            print("[OK] Holdings snapshot saved")
        except Exception as e:
            print(f"[ERROR] saving snapshot: {e}")
            import traceback
            traceback.print_exc()
            return False
        print()
        
        # Step 5: Upsert metadata
        print("Step 5: Upserting metadata...")
        print("-" * 80)
        try:
            upsert_etf_metadata(db, etf_ticker, provider)
            upsert_securities_metadata(db, today_holdings, provider)
            print("[OK] Metadata upserted")
        except Exception as e:
            print(f"⚠️  WARNING upserting metadata: {e}")
        print()
        
        print("=" * 80)
        print(f"[OK] {etf_ticker} processed successfully!")
        print("=" * 80)
        return True
        
    except Exception as e:
        print()
        print("=" * 80)
        print(f"[ERROR] processing {etf_ticker}: {e}")
        print("=" * 80)
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python debug/test_single_etf.py <ETF_TICKER>")
        print()
        print("Example: python debug/test_single_etf.py SMH")
        print("Example: python debug/test_single_etf.py BUG")
        sys.exit(1)
    
    etf_ticker = sys.argv[1].upper()
    success = test_single_etf(etf_ticker)
    sys.exit(0 if success else 1)
