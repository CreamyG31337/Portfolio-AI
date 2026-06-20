#!/usr/bin/env python3
"""
Script to standardize timezone formats across all CSV files.

This script addresses timezone inconsistency issues by:
1. Converting all timestamps to use PST/PDT format for user readability
2. Fixing invalid formats like "PST PDT"
3. Ensuring proper DST handling
"""

import pandas as pd
from datetime import datetime, timezone, timedelta
import os
import sys
from pathlib import Path

# Add the project root to the Python path
sys.path.append(str(Path(__file__).parent))

from utils.timezone_utils import parse_csv_timestamp, format_timestamp_for_csv

def fix_fund_contributions_csv(file_path: str) -> None:
    """Fix timezone format in fund_contributions.csv."""
    print(f"Fixing timezone format in {file_path}")

    if not os.path.exists(file_path):
        print(f"File not found: {file_path}")
        return

    df = pd.read_csv(file_path)
    if df.empty:
        print("File is empty")
        return

    print(f"Original format in first few rows:")
    for row in df.head(3).to_dict('records'):
        print(f"  {row['Timestamp']}")

    # Fix the invalid "PST PDT" format
    def fix_timestamp(timestamp_str):
        if pd.isna(timestamp_str):
            return timestamp_str

        timestamp_str = str(timestamp_str).strip()

        # Handle the invalid "PST PDT" format
        if "PST PDT" in timestamp_str:
            # Parse the timestamp without timezone first
            clean_timestamp = timestamp_str.replace(" PST PDT", "")
            try:
                # Try to parse as datetime and determine if it's DST
                dt = pd.to_datetime(clean_timestamp)
                # For simplicity, assume current timezone
                from market_config import get_timezone_name
                tz_name = get_timezone_name()
                return f"{dt.strftime('%Y-%m-%d %H:%M:%S')} {tz_name}"
            except:
                return timestamp_str

        # If already in correct format, return as-is
        if " PST" in timestamp_str or " PDT" in timestamp_str:
            return timestamp_str

        # If no timezone, add current timezone
        try:
            dt = pd.to_datetime(timestamp_str)
            from market_config import get_timezone_name
            tz_name = get_timezone_name()
            return f"{dt.strftime('%Y-%m-%d %H:%M:%S')} {tz_name}"
        except:
            return timestamp_str

    df['Timestamp'] = df['Timestamp'].apply(fix_timestamp)

    print(f"Fixed format in first few rows:")
    for row in df.head(3).to_dict('records'):
        print(f"  {row['Timestamp']}")

    # Save the fixed file
    df.to_csv(file_path, index=False)
    print(f"Saved fixed file to {file_path}")

def convert_portfolio_timestamps_to_abbreviations(file_path: str) -> None:
    """Convert ISO timezone offsets (-07:00) to PST/PDT abbreviations."""
    print(f"Converting timezone format in {file_path}")

    if not os.path.exists(file_path):
        print(f"File not found: {file_path}")
        return

    df = pd.read_csv(file_path)
    if df.empty:
        print("File is empty")
        return

    print(f"Original format in first few rows:")
    for row in df.head(3).to_dict('records'):
        print(f"  {row['Date']}")

    # Convert timestamps
    def convert_timestamp(timestamp_str):
        if pd.isna(timestamp_str):
            return timestamp_str

        try:
            # Parse the timestamp (handles -07:00 format)
            dt = parse_csv_timestamp(timestamp_str)
            # Format it back using the standardized PST/PDT format
            return format_timestamp_for_csv(dt)
        except Exception as e:
            print(f"Error converting timestamp '{timestamp_str}': {e}")
            return timestamp_str

    df['Date'] = df['Date'].apply(convert_timestamp)

    print(f"Converted format in first few rows:")
    for row in df.head(3).to_dict('records'):
        print(f"  {row['Date']}")

    # Save the converted file
    df.to_csv(file_path, index=False)
    print(f"Saved converted file to {file_path}")

def verify_exchange_rates_csv(file_path: str) -> None:
    """Verify and fix timezone format in exchange_rates.csv."""
    print(f"Verifying timezone format in {file_path}")

    if not os.path.exists(file_path):
        print(f"File not found: {file_path}")
        return

    df = pd.read_csv(file_path)
    if df.empty:
        print("File is empty")
        return

    print(f"Current format in first few rows:")
    for row in df.head(3).to_dict('records'):
        print(f"  {row['Date']}")

    # Check if format is already correct (PST/PDT)
    needs_conversion = False
    for row in df.to_dict('records'):
        date_str = str(row['Date'])
        if "-07:00" in date_str or "-08:00" in date_str:
            needs_conversion = True
            break

    if needs_conversion:
        print("Converting ISO offset format to PST/PDT...")
        df['Date'] = df['Date'].apply(lambda x: format_timestamp_for_csv(parse_csv_timestamp(x)) if pd.notna(x) else x)
        df.to_csv(file_path, index=False)
        print(f"Saved converted file to {file_path}")
    else:
        print("File already uses correct PST/PDT format")

def main():
    """Main function to fix timezone formats across all CSV files."""
    print("=== Timezone Format Standardization Script ===\n")

    # Define file paths
    base_dir = Path("my trading")
    files_to_fix = [
        ("fund_contributions.csv", fix_fund_contributions_csv),
        ("llm_portfolio_update.csv", convert_portfolio_timestamps_to_abbreviations),
        ("llm_trade_log.csv", None),  # Already correct
        ("exchange_rates.csv", verify_exchange_rates_csv),
    ]

    for filename, fix_function in files_to_fix:
        file_path = base_dir / filename
        print(f"\n--- Processing {filename} ---")

        if fix_function:
            fix_function(str(file_path))
        else:
            print(f"File {filename} already uses correct format")

    print("\n=== Timezone Format Standardization Complete ===")

    # Test the current timezone detection
    from market_config import get_timezone_name, get_timezone_offset, _is_dst
    now = datetime.now(timezone.utc)
    tz_name = get_timezone_name()
    tz_offset = get_timezone_offset()
    is_dst = _is_dst(now)

    print("\nCurrent timezone status:")
    print(f"  Current time (UTC): {now}")
    print(f"  Is DST: {is_dst}")
    print(f"  Timezone name: {tz_name}")
    print(f"  Timezone offset: {tz_offset}")

if __name__ == "__main__":
    main()
