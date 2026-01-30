"""
Cleanup script to delete test funds created by automated tests.

This script removes funds that match test patterns:
- TEST_XXXXXXXX (test funds with UUID suffix)
- test (lowercase test fund)
- Test Fund (test fund management tests)

The script handles foreign key constraints by deleting related data first.
"""

import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
from supabase import create_client


def cleanup_test_funds(dry_run: bool = True) -> None:
    """Delete test funds from the database.

    Args:
        dry_run: If True, only show what would be deleted without actually deleting.
    """
    # Load production credentials
    load_dotenv(project_root / "web_dashboard" / ".env")

    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_SECRET_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY")

    if not supabase_url or not supabase_key:
        print("ERROR: Supabase credentials not found in web_dashboard/.env")
        sys.exit(1)

    supabase = create_client(supabase_url, supabase_key)

    # Find all test funds
    print("Searching for test funds...")

    # Get funds matching test patterns
    all_funds = supabase.table("funds").select("name, id").execute()

    test_funds = []
    for fund in all_funds.data:
        name = fund["name"]
        # Match TEST_XXXXXXXX pattern, 'test', or 'Test Fund'
        if (name.startswith("TEST_") and len(name) == 13) or name == "test" or name == "Test Fund":
            test_funds.append(fund)

    if not test_funds:
        print("No test funds found.")
        return

    print(f"\nFound {len(test_funds)} test funds to delete:")
    for fund in test_funds[:20]:  # Show first 20
        print(f"  - {fund['name']}")
    if len(test_funds) > 20:
        print(f"  ... and {len(test_funds) - 20} more")

    if dry_run:
        print("\n[DRY RUN] No changes made. Run with --execute to delete.")
        return

    print("\nDeleting test funds and related data...")

    # Tables that reference funds by name (need to delete data first due to FK constraints)
    related_tables = [
        "portfolio_positions",
        "trade_log",
        "cash_balances",
        "performance_metrics",
        "dividend_log",
        "fund_contributions",
        "fund_thesis",
    ]

    deleted_count = 0
    error_count = 0

    for fund in test_funds:
        fund_name = fund["name"]
        try:
            # Delete related data from all tables
            for table in related_tables:
                try:
                    supabase.table(table).delete().eq("fund", fund_name).execute()
                except Exception as e:
                    # Table might not have this fund or might not exist
                    pass

            # Now delete the fund itself
            supabase.table("funds").delete().eq("name", fund_name).execute()
            deleted_count += 1
            print(f"  Deleted: {fund_name}")
        except Exception as e:
            error_count += 1
            print(f"  ERROR deleting {fund_name}: {e}")

    print(f"\nDone! Deleted {deleted_count} funds, {error_count} errors.")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Clean up test funds from the database")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually delete the funds (default is dry run)"
    )
    args = parser.parse_args()

    cleanup_test_funds(dry_run=not args.execute)
