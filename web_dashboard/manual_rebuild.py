#!/usr/bin/env python3
"""
Quick script to manually trigger a rebuild from a specific date.

Dry-run is the DEFAULT. Pass --apply to actually delete/write.

Usage:
  python manual_rebuild.py "Fund Name" "2025-12-17"           # dry-run
  python manual_rebuild.py "Fund Name" "2025-12-17" --apply
"""

import argparse
import sys
from pathlib import Path
from datetime import datetime

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from web_dashboard.utils.rebuild_from_date import rebuild_fund_from_date


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Rebuild portfolio from a specific date (dry-run by default)"
    )
    parser.add_argument("fund_name", help="Fund name to rebuild")
    parser.add_argument("start_date", help="Start date (YYYY-MM-DD)")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=None,
        help="Plan only (default if --apply not passed)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually delete and rewrite positions/metrics",
    )
    parser.add_argument(
        "--allow-day-loss",
        action="store_true",
        help="Allow writing fewer days than the holding-day span",
    )
    args = parser.parse_args()

    try:
        start_date = datetime.fromisoformat(args.start_date).date()
    except ValueError:
        print(f"Error: Invalid date format '{args.start_date}'. Use YYYY-MM-DD")
        sys.exit(1)

    if args.apply and args.dry_run:
        print("Error: pass only one of --dry-run / --apply")
        sys.exit(1)

    dry_run = not args.apply  # default dry-run unless --apply

    mode = "DRY-RUN" if dry_run else "APPLY"
    print(f"Starting rebuild ({mode}) for {args.fund_name} from {start_date}...")
    print("=" * 60)

    result = rebuild_fund_from_date(
        args.fund_name,
        start_date,
        dry_run=dry_run,
        allow_day_loss=args.allow_day_loss,
    )

    print(f"\n{result['message']}")
    print(f"Success: {result['success']}")
    print(f"Dates rebuilt: {result['dates_rebuilt']}")
    print(f"Positions updated: {result['positions_updated']}")
    print(f"Dry run: {result.get('dry_run')}")

    sys.exit(0 if result["success"] else 1)


if __name__ == "__main__":
    main()
