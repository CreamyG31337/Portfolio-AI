#!/usr/bin/env python3
"""
Quick script to manually trigger a rebuild from a specific date.
Usage: python manual_rebuild.py "Fund Name" "2025-12-17"
"""

import sys
from pathlib import Path
from datetime import datetime

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from web_dashboard.utils.rebuild_from_date import rebuild_fund_from_date


def main():
    if len(sys.argv) < 3:
        print("Usage: python manual_rebuild.py <fund_name> <start_date>")
        print("Example: python manual_rebuild.py 'Project Chimera' '2025-12-17'")
        sys.exit(1)

    fund_name = sys.argv[1]
    start_date_str = sys.argv[2]

    try:
        start_date = datetime.fromisoformat(start_date_str).date()
    except ValueError:
        print(f"Error: Invalid date format '{start_date_str}'. Use YYYY-MM-DD")
        sys.exit(1)

    print(f"🔄 Starting rebuild for {fund_name} from {start_date}...")
    print(f"=" * 60)

    result = rebuild_fund_from_date(fund_name, start_date)

    print(f"\n{result['message']}")
    print(f"Success: {result['success']}")
    print(f"Dates rebuilt: {result['dates_rebuilt']}")
    print(f"Positions updated: {result['positions_updated']}")

    sys.exit(0 if result['success'] else 1)


if __name__ == '__main__':
    main()
