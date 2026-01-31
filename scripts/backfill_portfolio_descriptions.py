#!/usr/bin/env python3
"""
Backfill Portfolio Descriptions
================================

Fetches descriptions from yfinance for all portfolio tickers that are missing
descriptions in the securities table.

Usage:
    python scripts/backfill_portfolio_descriptions.py [--dry-run] [--limit N]

Options:
    --dry-run   Show what would be updated without making changes
    --limit N   Limit to first N tickers (useful for testing)
"""

import sys
from pathlib import Path
import argparse
import time

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Load environment variables BEFORE importing SupabaseClient
from dotenv import load_dotenv
load_dotenv(project_root / 'web_dashboard' / '.env')

import yfinance as yf
from datetime import datetime
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Import Supabase client
try:
    from web_dashboard.supabase_client import SupabaseClient
except ImportError:
    logger.error("Could not import SupabaseClient. Make sure you're running from the project root.")
    sys.exit(1)


def fetch_description(ticker: str) -> tuple[str | None, str | None]:
    """Fetch description and company name for a single ticker from yfinance"""
    try:
        stock = yf.Ticker(ticker)
        info = stock.info

        description = (
            info.get('longBusinessSummary') or
            info.get('longDescription') or
            info.get('description')
        )

        company_name = info.get('longName') or info.get('shortName')

        if description:
            description = description.strip()

        return description, company_name
    except Exception as e:
        logger.warning(f"Failed to fetch data for {ticker}: {e}")
        return None, None


def get_portfolio_tickers(client: SupabaseClient) -> set:
    """Get all distinct tickers from portfolio_positions (handles pagination)"""
    tickers = set()
    offset = 0
    page_size = 1000

    while True:
        result = client.supabase.table("portfolio_positions") \
            .select("ticker") \
            .range(offset, offset + page_size - 1) \
            .execute()

        if not result.data:
            break

        for row in result.data:
            ticker = row.get("ticker")
            if ticker:
                tickers.add(ticker)

        if len(result.data) < page_size:
            break

        offset += page_size
        if offset > 50000:  # Safety limit
            logger.warning("Reached 50,000 row safety limit")
            break

    return tickers


def get_tickers_missing_descriptions(client: SupabaseClient, portfolio_tickers: set) -> list:
    """Get portfolio tickers that are missing descriptions"""
    if not portfolio_tickers:
        return []

    # Query securities table for these tickers
    result = client.supabase.table("securities") \
        .select("ticker, company_name, description") \
        .in_("ticker", list(portfolio_tickers)) \
        .execute()

    existing_data = {row["ticker"]: row for row in (result.data or [])}

    # Find tickers missing descriptions
    missing = []
    for ticker in sorted(portfolio_tickers):
        data = existing_data.get(ticker)
        if not data:
            # Ticker not in securities table at all
            missing.append({"ticker": ticker, "status": "not_in_table"})
        elif not data.get("description") or not data.get("description", "").strip():
            # Ticker exists but no description
            missing.append({"ticker": ticker, "status": "no_description", "company_name": data.get("company_name")})

    return missing


def backfill_descriptions(dry_run: bool = False, limit: int | None = None):
    """Main function to backfill descriptions"""
    logger.info("=" * 60)
    logger.info("BACKFILL PORTFOLIO DESCRIPTIONS")
    logger.info("=" * 60)
    if dry_run:
        logger.info("DRY RUN MODE - No changes will be made")
    logger.info("")

    # Initialize Supabase client
    client = SupabaseClient(use_service_role=True)

    # Get portfolio tickers
    logger.info("Fetching portfolio tickers...")
    portfolio_tickers = get_portfolio_tickers(client)
    logger.info(f"Found {len(portfolio_tickers)} unique tickers in portfolio")

    # Find tickers missing descriptions
    logger.info("Checking for missing descriptions...")
    missing = get_tickers_missing_descriptions(client, portfolio_tickers)
    logger.info(f"Found {len(missing)} tickers missing descriptions")

    if not missing:
        logger.info("All portfolio tickers have descriptions!")
        return

    # Apply limit if specified
    if limit:
        missing = missing[:limit]
        logger.info(f"Limited to first {limit} tickers")

    logger.info("")
    logger.info("-" * 60)

    # Process each ticker
    success_count = 0
    error_count = 0
    no_description_available = 0

    for idx, item in enumerate(missing, 1):
        ticker = item["ticker"]
        status = item["status"]

        logger.info(f"[{idx}/{len(missing)}] Processing {ticker} ({status})...")

        # Rate limiting - yfinance can be rate limited
        if idx > 1:
            time.sleep(0.5)

        description, company_name = fetch_description(ticker)

        if not description:
            logger.info(f"  ⚠ No description available from yfinance")
            no_description_available += 1
            continue

        # Preview
        preview = description[:100] + "..." if len(description) > 100 else description
        logger.info(f"  → {preview}")

        if dry_run:
            logger.info(f"  [DRY RUN] Would update {ticker}")
            success_count += 1
            continue

        try:
            # Check if ticker exists in securities table
            check_result = client.supabase.table("securities") \
                .select("ticker") \
                .eq("ticker", ticker) \
                .execute()

            update_data = {
                "description": description,
                "last_updated": datetime.now().isoformat()
            }

            # Add company_name if we got one and ticker is new
            if company_name and status == "not_in_table":
                update_data["company_name"] = company_name

            if not check_result.data:
                # Insert new record
                insert_data = {"ticker": ticker, **update_data}
                if company_name:
                    insert_data["company_name"] = company_name
                client.supabase.table("securities").insert(insert_data).execute()
                logger.info(f"  ✓ Inserted {ticker}")
            else:
                # Update existing record
                client.supabase.table("securities") \
                    .update(update_data) \
                    .eq("ticker", ticker) \
                    .execute()
                logger.info(f"  ✓ Updated {ticker}")

            success_count += 1

        except Exception as e:
            logger.error(f"  ✗ Failed to update {ticker}: {e}")
            error_count += 1

    # Summary
    logger.info("")
    logger.info("=" * 60)
    logger.info("SUMMARY")
    logger.info("=" * 60)
    logger.info(f"Total tickers processed: {len(missing)}")
    logger.info(f"Successfully updated: {success_count}")
    logger.info(f"No description available: {no_description_available}")
    logger.info(f"Errors: {error_count}")
    if dry_run:
        logger.info("(DRY RUN - no actual changes made)")
    logger.info("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill descriptions for portfolio tickers")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be updated without making changes")
    parser.add_argument("--limit", type=int, help="Limit to first N tickers")
    args = parser.parse_args()

    backfill_descriptions(dry_run=args.dry_run, limit=args.limit)
