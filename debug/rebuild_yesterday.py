#!/usr/bin/env python3
"""
Rebuild portfolio data for yesterday only.

This script uses the backfill function to rebuild just yesterday's portfolio positions
with the fixed currency cache logic.
"""

import sys
from pathlib import Path
from datetime import date, timedelta

# Setup sys.path
current_file = Path(__file__).resolve()
project_root = current_file.parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / 'web_dashboard'))

from web_dashboard.scheduler.jobs_portfolio import backfill_portfolio_prices_range

def main():
    """Rebuild yesterday's portfolio data."""
    # Get yesterday's date
    yesterday = date.today() - timedelta(days=1)
    
    print("=" * 70)
    print("Rebuilding Portfolio Data for Yesterday")
    print("=" * 70)
    print(f"Date: {yesterday}")
    print()
    
    try:
        # Call backfill for just yesterday (same date for start and end)
        backfill_portfolio_prices_range(yesterday, yesterday)
        print()
        print("=" * 70)
        print("SUCCESS: Yesterday's data has been rebuilt!")
        print("=" * 70)
    except Exception as e:
        print()
        print("=" * 70)
        print(f"ERROR: Failed to rebuild yesterday's data: {e}")
        print("=" * 70)
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
