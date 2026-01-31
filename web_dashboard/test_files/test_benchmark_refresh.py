#!/usr/bin/env python3
"""
Simple test script to verify benchmark_refresh_job logic.
This version avoids importing the scheduler module.
"""

import sys
import os
from pathlib import Path

# Add parent directory to path
parent_dir = Path(__file__).parent.parent
sys.path.insert(0, str(parent_dir))
sys.path.insert(0, str(Path(__file__).parent))

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

# Import required modules
import logging
import time
from datetime import datetime, timedelta
import yfinance as yf
from supabase_client import SupabaseClient

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def test_benchmark_refresh():
    """Test the benchmark refresh logic."""
    start_time = time.time()
    
    try:
        logger.info("=" * 60)
        logger.info("Testing Benchmark Refresh Job")
        logger.info("=" * 60)
        
        # Initialize Supabase client (use service role for writing)
        client = SupabaseClient(use_service_role=True)
        
        # Define benchmarks and commodities to refresh
        benchmarks = [
            # Market Indices
            {"ticker": "^GSPC", "name": "S&P 500"},
            {"ticker": "QQQ", "name": "Nasdaq-100"},
            {"ticker": "^RUT", "name": "Russell 2000"},
            {"ticker": "VTI", "name": "Total Market"},
            
            # Commodities
            {"ticker": "GC=F", "name": "Gold Futures"},
            {"ticker": "SI=F", "name": "Silver Futures"},
            {"ticker": "CL=F", "name": "Crude Oil Futures"},
            {"ticker": "URA", "name": "Uranium ETF"},
            {"ticker": "LIT", "name": "Lithium ETF"}
        ]

        
        # Fetch data for the last 30 days to ensure we have recent data
        end_date = datetime.now()
        start_date = end_date - timedelta(days=30)
        
        benchmarks_updated = 0
        benchmarks_failed = 0
        total_rows_cached = 0
        
        for benchmark in benchmarks:
            ticker = benchmark["ticker"]
            name = benchmark["name"]
            
            try:
                logger.info(f"Fetching {name} ({ticker})...")
                
                # Fetch data from Yahoo Finance
                data = yf.download(
                    ticker,
                    start=start_date,
                    end=end_date,
                    progress=False,
                    auto_adjust=False
                )
                
                if data.empty:
                    logger.warning(f"No data available for {name} ({ticker})")
                    benchmarks_failed += 1
                    continue
                
                # Reset index to get Date as a column
                data = data.reset_index()
                
                # Handle MultiIndex columns from yfinance
                if hasattr(data.columns, 'levels'):
                    data.columns = data.columns.get_level_values(0)
                
                # Convert to list of dicts for caching
                rows = data.to_dict('records')
                
                # Cache in database
                if client.cache_benchmark_data(ticker, rows):
                    total_rows_cached += len(rows)
                    benchmarks_updated += 1
                    logger.info(f"✅ Cached {len(rows)} rows for {name} ({ticker})")
                else:
                    benchmarks_failed += 1
                    logger.warning(f"Failed to cache data for {name} ({ticker})")
                
            except Exception as e:
                logger.error(f"Error fetching {name} ({ticker}): {e}")
                benchmarks_failed += 1
        
        duration_s = time.time() - start_time
        logger.info("=" * 60)
        logger.info(f"✅ Test Complete in {duration_s:.2f}s")
        logger.info(f"Updated {benchmarks_updated} benchmarks ({total_rows_cached} rows)")
        logger.info(f"Failed: {benchmarks_failed}")
        logger.info("=" * 60)
        
        return benchmarks_updated > 0
        
    except Exception as e:
        logger.error(f"❌ Test failed: {e}", exc_info=True)
        return False

if __name__ == "__main__":
    success = test_benchmark_refresh()
    sys.exit(0 if success else 1)
