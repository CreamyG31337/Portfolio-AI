#!/usr/bin/env python3
"""
Script to fix timezone format in llm_portfolio_update.csv.

This script specifically handles the conversion from ISO offset format (-07:00)
to PST/PDT format for the portfolio file.
"""

import pandas as pd
from datetime import datetime
import os
import sys
from pathlib import Path

def fix_portfolio_timezone(file_path: str) -> None:
    """Fix timezone format in portfolio CSV file."""
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
        print(f"  {row['Date']}")

    # Simple string replacement approach for -07:00 format
    def convert_timezone_format(timestamp_str):
        if pd.isna(timestamp_str):
            return timestamp_str

        timestamp_str = str(timestamp_str).strip()

        # Replace -07:00 with PDT (Pacific Daylight Time)
        if "-07:00" in timestamp_str:
            return timestamp_str.replace("-07:00", " PDT")

        # Replace -08:00 with PST (Pacific Standard Time)
        if "-08:00" in timestamp_str:
            return timestamp_str.replace("-08:00", " PST")

        # If already in correct format, return as-is
        if " PST" in timestamp_str or " PDT" in timestamp_str:
            return timestamp_str

        # If no timezone info, add current timezone
        try:
            # Parse and reformat with current timezone
            dt = pd.to_datetime(timestamp_str)
            from market_config import get_timezone_name
            tz_name = get_timezone_name()
            return f"{dt.strftime('%Y-%m-%d %H:%M:%S')} {tz_name}"
        except:
            return timestamp_str

    df['Date'] = df['Date'].apply(convert_timezone_format)

    print(f"Fixed format in first few rows:")
    for row in df.head(3).to_dict('records'):
        print(f"  {row['Date']}")

    # Save the fixed file
    df.to_csv(file_path, index=False)
    print(f"Saved fixed file to {file_path}")

def main():
    """Main function."""
    print("=== Portfolio Timezone Fix Script ===\n")

    file_path = "my trading/llm_portfolio_update.csv"
    fix_portfolio_timezone(file_path)

    print("\n=== Portfolio Timezone Fix Complete ===")

if __name__ == "__main__":
    main()
