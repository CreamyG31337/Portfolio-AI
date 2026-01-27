#!/usr/bin/env python3
"""
ETF Watchtower Job
==================
Tracks daily changes in ETF holdings via direct CSV downloads.
Detects institutional accumulation/distribution ("The Diff Engine").

Supported ETFs:
- iShares: IVV, IWM, IWC, IWO
- ARK: ARKK, ARKQ, ARKW, ARKG, ARKF, ARKX, IZRL, PRNT
- SPDR: XBI
- Global X: BOTZ, LIT

Change Detection:
- Detects significant changes in holdings (MIN_SHARE_CHANGE or MIN_PERCENT_CHANGE)
- Filters out non-stock holdings (cash, futures, derivatives)
- Filters out systematic adjustments (expense ratio deductions, data normalization)

Systematic Adjustment Filtering:
---------------------------------
The job automatically filters out systematic adjustments that affect all holdings
proportionally. These are NOT trading activity.

A systematic adjustment is detected when:
1. 80%+ of changes cluster around the same percentage (within 0.1%)
2. That percentage is ≤2% (small adjustments, not large trades)
3. All changes are in the same direction (all buys OR all sells)

Examples of systematic adjustments:
- Expense ratio deductions (~0.5% annually, applied proportionally)
- Data normalization/rounding adjustments
- Systematic rebalancing calculations

Real trading activity shows:
- Different percentages for different holdings
- Mixed buys and sells
- New positions added / old positions removed
- Varied change patterns

Pagination:
-----------
For ETFs with >1000 holdings (IWM, IWC, IWO), the job uses pagination to fetch
all holdings from the database. This prevents false positives where holdings
beyond the 1000-row limit appear as "new" positions.
"""

import logging
import sys
import base64
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional, Tuple
import pandas as pd
import requests

# Add parent directory to path for imports
sys.path.append(str(Path(__file__).resolve().parent.parent))

from supabase_client import SupabaseClient
from research_repository import ResearchRepository
from postgres_client import PostgresClient

logger = logging.getLogger(__name__)

# Base URLs (obfuscated)
_ARK_BASE_ENCODED = "aHR0cHM6Ly9hc3NldHMuYXJrLWZ1bmRzLmNvbQ=="
_ISHARES_BASE_ENCODED = "aHR0cHM6Ly93d3cuaXNoYXJlcy5jb20="
_ARK_BASE = base64.b64decode(_ARK_BASE_ENCODED).decode('utf-8')
_ISHARES_BASE = base64.b64decode(_ISHARES_BASE_ENCODED).decode('utf-8')

# ETF Configuration
# Format: {ticker: {provider, csv_url}}
ETF_CONFIGS = {
    # ARK Invest (Direct CSV links)
    "ARKK": { "provider": "ARK", "url": f"{_ARK_BASE}/fund-documents/funds-etf-csv/ARK_INNOVATION_ETF_ARKK_HOLDINGS.csv" },
    "ARKQ": { "provider": "ARK", "url": f"{_ARK_BASE}/fund-documents/funds-etf-csv/ARK_AUTONOMOUS_TECH._%26_ROBOTICS_ETF_ARKQ_HOLDINGS.csv" },
    "ARKW": { "provider": "ARK", "url": f"{_ARK_BASE}/fund-documents/funds-etf-csv/ARK_NEXT_GENERATION_INTERNET_ETF_ARKW_HOLDINGS.csv" },
    "ARKG": { "provider": "ARK", "url": f"{_ARK_BASE}/fund-documents/funds-etf-csv/ARK_GENOMIC_REVOLUTION_ETF_ARKG_HOLDINGS.csv" },
    "ARKF": { "provider": "ARK", "url": f"{_ARK_BASE}/fund-documents/funds-etf-csv/ARK_BLOCKCHAIN_%26_FINTECH_INNOVATION_ETF_ARKF_HOLDINGS.csv" },
    "ARKX": { "provider": "ARK", "url": f"{_ARK_BASE}/fund-documents/funds-etf-csv/ARK_SPACE_%26_DEFENSE_INNOVATION_ETF_ARKX_HOLDINGS.csv" },
    "IZRL": { "provider": "ARK", "url": f"{_ARK_BASE}/fund-documents/funds-etf-csv/ARK_ISRAEL_INNOVATIVE_TECHNOLOGY_ETF_IZRL_HOLDINGS.csv" },
    "PRNT": { "provider": "ARK", "url": f"{_ARK_BASE}/fund-documents/funds-etf-csv/THE_3D_PRINTING_ETF_PRNT_HOLDINGS.csv" },
    # Removed single-holding funds (ARKB, ARKD, ARKT) and venture funds (ARKSX, ARKVX, ARKUX) - they don't provide useful stock signals
    
    # iShares (BlackRock) - Requires specific AJAX URL with Product ID
    "IVV": { "provider": "iShares", "url": f"{_ISHARES_BASE}/us/products/239726/ishares-core-sp-500-etf/1467271812596.ajax?fileType=csv&fileName=IVV_holdings&dataType=fund" },
    "IWM": { "provider": "iShares", "url": f"{_ISHARES_BASE}/us/products/239710/ishares-russell-2000-etf/1467271812596.ajax?fileType=csv&fileName=IWM_holdings&dataType=fund" },
    "IWC": { "provider": "iShares", "url": f"{_ISHARES_BASE}/us/products/239716/ishares-microcap-etf/1467271812596.ajax?fileType=csv&fileName=IWC_holdings&dataType=fund" },
    "IWO": { "provider": "iShares", "url": f"{_ISHARES_BASE}/us/products/239709/ishares-russell-2000-growth-etf/1467271812596.ajax?fileType=csv&fileName=IWO_holdings&dataType=fund" },
    "SOXX": { "provider": "iShares", "url": f"{_ISHARES_BASE}/us/products/239705/ishares-phlx-semiconductor-sector-index-fund/1467271812596.ajax?fileType=csv&fileName=SOXX_holdings&dataType=fund" },
    "ICLN": { "provider": "iShares", "url": f"{_ISHARES_BASE}/us/products/239738/ishares-global-clean-energy-etf/1467271812596.ajax?fileType=csv&fileName=ICLN_holdings&dataType=fund" },
    "IBB": { "provider": "iShares", "url": f"{_ISHARES_BASE}/us/products/239699/ishares-nasdaq-biotechnology-etf/1467271812596.ajax?fileType=csv&fileName=IBB_holdings&dataType=fund" },
    
    # SPDR (State Street) - Excel format
    "XBI": { "provider": "SPDR", "url": "https://www.ssga.com/library-content/products/fund-data/etfs/us/holdings-daily-us-en-xbi.xlsx" },
    
    # Global X - Date-based CSV URLs (updated daily)
    "BOTZ": { "provider": "Global X", "url": "https://assets.globalxetfs.com/funds/holdings/botz_full-holdings_{date}.csv" },
    "LIT": { "provider": "Global X", "url": "https://assets.globalxetfs.com/funds/holdings/lit_full-holdings_{date}.csv" },
    "BUG": { "provider": "Global X", "url": "https://assets.globalxetfs.com/funds/holdings/bug_full-holdings_{date}.csv" },
    "FINX": { "provider": "Global X", "url": "https://assets.globalxetfs.com/funds/holdings/finx_full-holdings_{date}.csv" },
    
    # Direxion - Direct CSV (non-leveraged thematic)
    "MOON": { "provider": "Direxion", "url": "https://www.direxion.com/holdings/MOON.csv" },
    
    # VanEck - Direct XLSX download via /downloads/holdings endpoint
    "SMH": { "provider": "VanEck", "url": "https://www.vaneck.com/us/en/investments/semiconductor-etf-smh/downloads/holdings" },
    "DAPP": { "provider": "VanEck", "url": "https://www.vaneck.com/us/en/investments/digital-transformation-etf-dapp/downloads/holdings" },
    "BBH": { "provider": "VanEck", "url": "https://www.vaneck.com/us/en/investments/biotech-etf-bbh/downloads/holdings" },
    "BUZZ": { "provider": "VanEck", "url": "https://www.vaneck.com/us/en/investments/social-sentiment-etf-buzz/downloads/holdings" },
    "IBOT": { "provider": "VanEck", "url": "https://www.vaneck.com/us/en/investments/robotics-etf-ibot/downloads/holdings" },
    "MOAT": { "provider": "VanEck", "url": "https://www.vaneck.com/us/en/investments/morningstar-wide-moat-etf-moat/downloads/holdings" },
    "PPH": { "provider": "VanEck", "url": "https://www.vaneck.com/us/en/investments/pharmaceutical-etf-pph/downloads/holdings" },
    "RTH": { "provider": "VanEck", "url": "https://www.vaneck.com/us/en/investments/retail-etf-rth/downloads/holdings" },
    "SMHX": { "provider": "VanEck", "url": "https://www.vaneck.com/us/en/investments/fabless-semiconductor-etf-smhx/downloads/holdings" },
    "SMOT": { "provider": "VanEck", "url": "https://www.vaneck.com/us/en/investments/morningstar-smid-moat-etf-smot/downloads/holdings" },
    "OIH": { "provider": "VanEck", "url": "https://www.vaneck.com/us/en/investments/oil-services-etf-oih/downloads/holdings" },
}

# ETF Names for metadata
ETF_NAMES = {
    "ARKK": "ARK Innovation ETF",
    "ARKQ": "ARK Autonomous Technology & Robotics ETF",
    "ARKW": "ARK Next Generation Internet ETF",
    "ARKG": "ARK Genomic Revolution ETF",
    "ARKF": "ARK Fintech Innovation ETF",
    "ARKX": "ARK Space Exploration & Innovation ETF",
    "IZRL": "ARK Israel Innovative Technology ETF",
    "PRNT": "The 3D Printing ETF",
    "IVV": "iShares Core S&P 500 ETF",
    "IWM": "iShares Russell 2000 ETF",
    "IWC": "iShares Micro-Cap ETF",
    "IWO": "iShares Russell 2000 Growth ETF",
    "SOXX": "iShares Semiconductor ETF",
    "ICLN": "iShares Global Clean Energy ETF",
    "IBB": "iShares Biotechnology ETF",
    "XBI": "SPDR S&P Biotech ETF",
    "BOTZ": "Global X Robotics & Artificial Intelligence ETF",
    "LIT": "Global X Lithium & Battery Tech ETF",
    "BUG": "Global X Cybersecurity ETF",
    "FINX": "Global X FinTech ETF",
    "MOON": "Direxion Moonshot Innovators ETF",
    "SMH": "VanEck Semiconductor ETF",
    "DAPP": "VanEck Digital Transformation ETF",
    "BBH": "VanEck Biotech ETF",
    "BUZZ": "VanEck Social Sentiment ETF",
    "IBOT": "VanEck Robotics ETF",
    "MOAT": "VanEck Morningstar Wide Moat ETF",
    "PPH": "VanEck Pharmaceutical ETF",
    "RTH": "VanEck Retail ETF",
    "SMHX": "VanEck Fabless Semiconductor ETF",
    "SMOT": "VanEck Morningstar SMID Moat ETF",
    "OIH": "VanEck Oil Services ETF",
}

# Thresholds for "significant" changes
MIN_SHARE_CHANGE = 1000  # Minimum absolute share change to log
MIN_PERCENT_CHANGE = 0.5  # Minimum % change relative to previous holdings

# Systematic Adjustment Detection
# ===============================
# The change detection logic filters out systematic adjustments (e.g., expense ratio deductions)
# that affect all holdings proportionally. These are NOT trading activity.
#
# A systematic adjustment is detected when:
# 1. 80%+ of changes cluster around the same percentage (within 0.1%)
# 2. That percentage is ≤2% (small adjustments, not large trades)
# 3. All changes are in the same direction (all buys OR all sells)
#
# Examples of systematic adjustments:
# - Expense ratio deductions (~0.5% annually, applied proportionally)
# - Data normalization/rounding adjustments
# - Systematic rebalancing calculations
#
# Real trading activity shows:
# - Different percentages for different holdings
# - Mixed buys and sells
# - New positions added / old positions removed
# - Varied change patterns

# Tickers to exclude from change detection (cash, futures, derivatives, etc.)
# These are valid holdings but not actionable stock signals
EXCLUDED_TICKERS = {
    # Cash and cash equivalents
    'USD', 'CASH', 'CASHCOLLATERAL', 'MARGIN_CASH', 'MONEY_MARKET',
    # Futures and derivatives
    'XTSLA', 'MSFUT', 'SGAFT', 'ESH6', 'ESH5', 'ESM6', 'ESU6', 'ESZ6',
    'NQH6', 'NQM6', 'NQU6', 'NQZ6', 'RTY', 'RTYM6', 'SPY_FUT',
    'ETD_USD', 'FUT', 'SWAP', 'FWD',
    # Treasury/bonds (often in ETFs but not stock signals)
    'TBILL', 'USINTR', 'BIL',
}

# Patterns that indicate non-stock holdings
EXCLUDED_TICKER_PATTERNS = [
    'FUT',   # Futures
    '_USD',  # USD-denominated derivatives
    'SWAP',  # Swaps
    'FWD',   # Forwards
]


def is_stock_ticker(ticker: str) -> bool:
    """Check if a ticker represents a tradeable stock (not cash/futures/derivatives).
    
    Args:
        ticker: Ticker symbol
        
    Returns:
        True if it's a stock ticker, False if it should be excluded
    """
    if not ticker or not isinstance(ticker, str):
        return False
    
    ticker_upper = ticker.upper().strip()
    
    # Check explicit exclusions
    if ticker_upper in EXCLUDED_TICKERS:
        return False
    
    # Check patterns
    for pattern in EXCLUDED_TICKER_PATTERNS:
        if pattern in ticker_upper:
            return False
    
    # Exclude tickers that are just numbers (often futures contracts)
    if ticker_upper.isdigit():
        return False
    
    # Exclude very long tickers (usually derivatives or internal codes)
    if len(ticker_upper) > 10:
        return False
    
    return True


def save_raw_etf_file(etf_ticker: str, file_content: bytes, file_extension: str, date: datetime) -> Optional[Path]:
    """Save raw ETF file for later reprocessing.
    
    Files are organized as: logs/etf_raw_data/YYYY-MM-DD/ETF_TICKER.csv (or .xlsx)
    This directory is mounted as a Docker volume, so files persist across restarts.
    
    Args:
        etf_ticker: ETF ticker symbol
        file_content: Raw file content (bytes)
        file_extension: File extension ('.csv' or '.xlsx')
        date: Date of the data
        
    Returns:
        Path to saved file, or None if save failed
    """
    try:
        # Use logs directory (mounted as Docker volume: /home/lance/trading-dashboard-logs:/app/web_dashboard/logs)
        log_dir = Path(__file__).parent.parent / 'logs'
        etf_raw_data_dir = log_dir / 'etf_raw_data'
        etf_data_dir = etf_raw_data_dir / date.strftime('%Y-%m-%d')
        etf_data_dir.mkdir(parents=True, exist_ok=True)
        
        # Check for excessive file accumulation (warn if 365+ days of data)
        if etf_raw_data_dir.exists():
            date_dirs = [d for d in etf_raw_data_dir.iterdir() if d.is_dir()]
            if len(date_dirs) >= 365:
                logger.warning(
                    f"⚠️ ETF raw data directory has {len(date_dirs)} date folders (365+ days). "
                    f"Consider cleaning up old files to save disk space. "
                    f"Location: {etf_raw_data_dir.relative_to(log_dir)}"
                )
        
        # Save file: ETF_TICKER.csv or ETF_TICKER.xlsx
        filename = f"{etf_ticker}{file_extension}"
        file_path = etf_data_dir / filename
        
        # Write binary content
        file_path.write_bytes(file_content)
        
        logger.info(f"💾 Saved raw file: {file_path.relative_to(log_dir)}")
        return file_path
        
    except Exception as e:
        logger.warning(f"⚠️ Failed to save raw file for {etf_ticker}: {e}")
        return None


def fetch_ishares_holdings(etf_ticker: str, csv_url: str, date: Optional[datetime] = None) -> Optional[pd.DataFrame]:
    """Download and parse iShares ETF holdings CSV."""
    try:
        logger.info(f"📥 Downloading {etf_ticker} holdings from iShares...")
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/csv,application/csv;q=0.9,*/*;q=0.8',
        }
        
        response = requests.get(csv_url, timeout=30, headers=headers)
        response.raise_for_status()
        
        # Save raw file for reprocessing
        save_date = date if date else datetime.now(timezone.utc)
        save_raw_etf_file(etf_ticker, response.content, '.csv', save_date)
        
        from io import StringIO
        # iShares CSVs often have metadata headers. Look for "Ticker"
        content = response.text
        lines = content.split('\n')
        header_row = 0
        for i, line in enumerate(lines[:25]):
            if 'Ticker' in line and ('Name' in line or 'Security Name' in line):
                header_row = i
                break
        
        df = pd.read_csv(StringIO(content), skiprows=header_row)
        df.columns = df.columns.str.strip()
        
        column_mapping = {
            'Ticker': 'ticker',
            'Name': 'name',
            'Security Name': 'name', 
            'Shares': 'shares',
            'Quantity': 'shares',  # Common in iShares CSV
            'Weight (%)': 'weight_percent',
            'Sector': 'sector',
            'Asset Class': 'asset_class',
            'Exchange': 'exchange',
            'Market Currency': 'currency'
        }
        
        df = df.rename(columns=column_mapping)
        
        if 'ticker' not in df.columns or 'shares' not in df.columns:
            logger.error(f"❌ iShares CSV missing required columns. Found: {df.columns.tolist()}")
            return None
            
        df = df[df['ticker'].notna()]
        df = df[df['ticker'] != '-']
        # Truncate ticker to avoid DB errors (max 50 chars)
        df['ticker'] = df['ticker'].astype(str).str.upper().str.strip().str.slice(0, 50)
        df['shares'] = pd.to_numeric(df['shares'].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
        
        if 'weight_percent' in df.columns:
            df['weight_percent'] = pd.to_numeric(df['weight_percent'].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
        
        logger.info(f"✅ Parsed {len(df)} holdings for {etf_ticker}")
        return df

    except Exception as e:
        logger.error(f"❌ Error parsing {etf_ticker} iShares CSV: {e}", exc_info=True)
        return None


def fetch_spdr_holdings(etf_ticker: str, xlsx_url: str, date: Optional[datetime] = None) -> Optional[pd.DataFrame]:
    """Download and parse SPDR ETF holdings Excel file.
    
    Args:
        etf_ticker: ETF ticker symbol
        xlsx_url: Direct Excel URL
        date: Optional date for file organization (defaults to now)
        
    Returns:
        DataFrame with columns: [ticker, name, shares, weight_percent]
    """
    try:
        logger.info(f"📥 Downloading {etf_ticker} holdings from SPDR...")
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        }
        
        response = requests.get(xlsx_url, timeout=30, headers=headers)
        response.raise_for_status()
        
        # Save raw file for reprocessing
        save_date = date if date else datetime.now(timezone.utc)
        save_raw_etf_file(etf_ticker, response.content, '.xlsx', save_date)
        
        from io import BytesIO
        # SPDR Excel files have 4-5 metadata rows at the top
        df = pd.read_excel(BytesIO(response.content), engine='openpyxl', skiprows=4)
        
        # Clean column names and deduplicate (SPDR files sometimes have duplicate columns)
        df.columns = df.columns.str.strip()
        
        # Deduplicate column names by adding _1, _2, etc. to duplicates
        cols = pd.Series(df.columns)
        for dup in cols[cols.duplicated()].unique():
            cols[cols[cols == dup].index.values.tolist()] = [dup + '_' + str(i) if i != 0 else dup for i in range(sum(cols == dup))]
        df.columns = cols
        
        # Map SPDR columns to standard schema
        # Note: 'Identifier' is NOT renamed because it creates duplicate 'ticker' columns
        column_mapping = {
            'Ticker': 'ticker',
            'Name': 'name',
            'Weight': 'weight_percent',
            'Shares Held': 'shares',
        }
        
        df = df.rename(columns=column_mapping)
        
        if 'ticker' not in df.columns:
            logger.error(f"❌ SPDR Excel missing ticker column. Found: {df.columns.tolist()}")
            return None
            
        # Clean data
        df = df[df['ticker'].notna()]
        df = df[df['ticker'] != '']
        df['ticker'] = df['ticker'].astype(str).str.upper().str.strip()
        
        # Convert numeric columns
        if 'shares' in df.columns:
            df['shares'] = pd.to_numeric(df['shares'], errors='coerce').fillna(0)
        if 'weight_percent' in df.columns:
            df['weight_percent'] = pd.to_numeric(df['weight_percent'], errors='coerce').fillna(0)
        
        logger.info(f"✅ Parsed {len(df)} holdings for {etf_ticker}")
        return df
        
    except Exception as e:
        logger.error(f"❌ Error parsing {etf_ticker} SPDR Excel: {e}", exc_info=True)
        return None


def fetch_globalx_holdings(etf_ticker: str, csv_url_template: str, date: Optional[datetime] = None) -> Optional[pd.DataFrame]:
    """Download and parse Global X ETF holdings CSV.
    
    Args:
        etf_ticker: ETF ticker symbol
        csv_url_template: URL template with {date} placeholder
        date: Optional date for file organization (defaults to now)
        
    Returns:
        DataFrame with columns: [ticker, name, shares, weight_percent]
    """
    try:
        logger.info(f"📥 Downloading {etf_ticker} holdings from Global X...")
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        }
        
        # Global X uses date in filename: YYYYMMDD format (US market time, not UTC)
        # Try today first, then fall back to previous days (files may not be published on weekends/holidays)
        today = datetime.now()
        response = None
        found_date = None
        
        for days_back in range(5):  # Try up to 5 days back
            check_date = today - timedelta(days=days_back)
            date_str = check_date.strftime('%Y%m%d')
            csv_url = csv_url_template.format(date=date_str)
            
            try:
                response = requests.get(csv_url, timeout=30, headers=headers)
                if response.status_code == 200:
                    logger.info(f"📄 Found {etf_ticker} holdings file for {date_str}")
                    found_date = check_date
                    break
                else:
                    logger.debug(f"No file for {date_str} (HTTP {response.status_code})")
            except requests.exceptions.RequestException:
                continue
        
        if response is None or response.status_code != 200:
            logger.error(f"❌ Could not find {etf_ticker} holdings file in last 5 days")
            return None
        
        # Save raw file for reprocessing
        save_date = date if date else (found_date if found_date else datetime.now(timezone.utc))
        save_raw_etf_file(etf_ticker, response.content, '.csv', save_date)
        
        # Global X CSVs have 2 header rows (title, date, then column headers)
        from io import StringIO
        df = pd.read_csv(StringIO(response.text), skiprows=2)
        
        # Clean column names
        df.columns = df.columns.str.strip()
        
        # Map Global X columns to standard schema
        column_mapping = {
            'Ticker': 'ticker',
            'Name': 'name',
            'Shares Held': 'shares',
            'Market Value ($)': 'market_value',
            '% of Net Assets': 'weight_percent',
        }
        
        df = df.rename(columns=column_mapping)
        
        if 'ticker' not in df.columns:
            logger.error(f"❌ Global X CSV missing ticker column. Found: {df.columns.tolist()}")
            return None
            
        # Clean data
        df = df[df['ticker'].notna()]
        df = df[df['ticker'] != '']
        df['ticker'] = df['ticker'].astype(str).str.upper().str.strip()
        
        # Convert numeric columns (remove commas)
        if 'shares' in df.columns:
            df['shares'] = df['shares'].astype(str).str.replace(',', '').str.strip()
            df['shares'] = pd.to_numeric(df['shares'], errors='coerce').fillna(0)
        if 'weight_percent' in df.columns:
            df['weight_percent'] = pd.to_numeric(df['weight_percent'], errors='coerce').fillna(0)
        
        logger.info(f"✅ Parsed {len(df)} holdings for {etf_ticker}")
        return df
        
    except Exception as e:
        logger.error(f"❌ Error parsing {etf_ticker} Global X CSV: {e}", exc_info=True)
        return None


def fetch_ark_holdings(etf_ticker: str, csv_url: str, date: Optional[datetime] = None) -> Optional[pd.DataFrame]:
    """Download and parse ARK ETF holdings CSV.
    
    Args:
        etf_ticker: ETF ticker symbol
        csv_url: Direct CSV URL
        date: Optional date for file organization (defaults to now)
        
    Returns:
        DataFrame with columns: [ticker, name, shares, weight]
    """
    try:
        logger.info(f"📥 Downloading {etf_ticker} holdings from ARK...")
        
        # Add browser-like headers to avoid 403
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
        }
        
        response = requests.get(csv_url, timeout=30, headers=headers)
        response.raise_for_status()
        
        # Save raw file for reprocessing
        save_date = date if date else datetime.now(timezone.utc)
        save_raw_etf_file(etf_ticker, response.content, '.csv', save_date)
        
        # ARK CSVs have headers on different rows depending on fund
        # Try reading with pandas auto-detection
        from io import StringIO
        df = pd.read_csv(StringIO(response.text))
        
        # Normalize column names (ARK uses different formats)
        df.columns = df.columns.str.lower().str.strip()
        
        # Map to standard schema
        # ARK columns: 'ticker', 'company', 'shares', 'weight (%)'
        column_mapping = {
            'ticker': 'ticker',
            'company': 'name',
            'shares': 'shares',
            'weight (%)': 'weight_percent'  # Note the space!
        }
        
        # Find actual column names (case-insensitive matching)
        actual_mapping = {}
        for expected, standard in column_mapping.items():
            for col in df.columns:
                if expected in col or standard in col:
                    actual_mapping[col] = standard
                    break
        
        if not actual_mapping:
            logger.error(f"❌ Could not map ARK CSV columns: {df.columns.tolist()}")
            return None
        
        df = df.rename(columns=actual_mapping)
        
        # Ensure required columns exist
        required = ['ticker', 'shares']
        if not all(col in df.columns for col in required):
            logger.error(f"❌ Missing required columns. Found: {df.columns.tolist()}")
            return None
        
        # Clean data
        df = df[df['ticker'].notna()]  # Remove empty rows
        df = df[df['ticker'] != '']
        df['ticker'] = df['ticker'].str.upper().str.strip()
        
        # Convert shares to numeric (remove commas first)
        if 'shares' in df.columns:
            df['shares'] = df['shares'].astype(str).str.replace(',', '').str.strip()
            df['shares'] = pd.to_numeric(df['shares'], errors='coerce')
        
        # Convert weight_percent to numeric (remove % sign first)
        if 'weight_percent' in df.columns:
            df['weight_percent'] = df['weight_percent'].astype(str).str.replace('%', '').str.strip()
            df['weight_percent'] = pd.to_numeric(df['weight_percent'], errors='coerce')
        
        logger.info(f"✅ Parsed {len(df)} holdings for {etf_ticker}")
        return df
        
    except requests.exceptions.RequestException as e:
        logger.error(f"❌ Failed to download {etf_ticker} CSV: {e}")
        return None
    except Exception as e:
        logger.error(f"❌ Error parsing {etf_ticker} CSV: {e}", exc_info=True)
        return None


def fetch_direxion_holdings(etf_ticker: str, csv_url: str, date: Optional[datetime] = None) -> Optional[pd.DataFrame]:
    """Download and parse Direxion ETF holdings CSV.
    
    Direxion CSVs have a specific format:
    - Line 1: Fund name
    - Line 2: Ticker
    - Line 3: Shares outstanding info
    - Lines 4-5: Empty
    - Line 6: Header row
    - Lines 7+: Data
    
    Args:
        etf_ticker: ETF ticker symbol
        csv_url: Direct CSV URL
        date: Optional date for file organization (defaults to now)
        
    Returns:
        DataFrame with columns: [ticker, name, shares, weight_percent]
    """
    try:
        logger.info(f"📥 Downloading {etf_ticker} holdings from Direxion...")
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        }
        
        response = requests.get(csv_url, timeout=30, headers=headers)
        response.raise_for_status()
        
        # Save raw file for reprocessing
        save_date = date if date else datetime.now(timezone.utc)
        save_raw_etf_file(etf_ticker, response.content, '.csv', save_date)
        
        from io import StringIO
        # Direxion CSV has 5 metadata rows before the header (including blank lines)
        df = pd.read_csv(StringIO(response.text), skiprows=5)
        df.columns = df.columns.str.strip()
        
        # Map Direxion columns to standard schema
        # Columns: TradeDate, AccountTicker, StockTicker, SecurityDescription, Shares, Price, MarketValue, Cusip, HoldingsPercent
        column_mapping = {
            'StockTicker': 'ticker',
            'SecurityDescription': 'name',
            'Shares': 'shares',
            'HoldingsPercent': 'weight_percent',
            'MarketValue': 'market_value',
        }
        
        df = df.rename(columns=column_mapping)
        
        if 'ticker' not in df.columns:
            logger.error(f"❌ Direxion CSV missing ticker column. Found: {df.columns.tolist()}")
            return None
        
        # Clean data
        df = df[df['ticker'].notna()]
        df = df[df['ticker'] != '']
        df['ticker'] = df['ticker'].astype(str).str.upper().str.strip()
        
        # Filter to valid stock tickers only (exclude cash, futures, etc.)
        df = df[df['ticker'].apply(is_stock_ticker)]
        
        # Convert numeric columns
        if 'shares' in df.columns:
            df['shares'] = pd.to_numeric(df['shares'].astype(str).str.replace(',', ''), errors='coerce').fillna(0)
        if 'weight_percent' in df.columns:
            # HoldingsPercent is already in percentage form (e.g., 2.36 = 2.36%)
            df['weight_percent'] = pd.to_numeric(df['weight_percent'], errors='coerce').fillna(0)
        
        logger.info(f"✅ Parsed {len(df)} holdings for {etf_ticker}")
        return df
        
    except requests.exceptions.RequestException as e:
        logger.error(f"❌ Failed to download {etf_ticker} Direxion CSV: {e}")
        return None
    except Exception as e:
        logger.error(f"❌ Error parsing {etf_ticker} Direxion CSV: {e}", exc_info=True)
        return None


def fetch_vaneck_holdings(etf_ticker: str, xlsx_url: str, date: Optional[datetime] = None) -> Optional[pd.DataFrame]:
    """Download and parse VanEck ETF holdings from direct XLSX download.
    
    VanEck provides direct XLSX downloads at /downloads/holdings endpoints.
    
    Args:
        etf_ticker: ETF ticker symbol
        xlsx_url: Direct XLSX download URL
        date: Optional date for file organization (defaults to now)
        
    Returns:
        DataFrame with columns: [ticker, name, shares, weight_percent]
    """
    try:
        logger.info(f"📥 Downloading {etf_ticker} holdings from VanEck...")
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36',
            'Accept': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,*/*',
            'Accept-Language': 'en-US,en;q=0.5',
        }
        
        response = requests.get(xlsx_url, headers=headers, timeout=30)
        response.raise_for_status()
        
        # Save raw file for reprocessing
        save_date = date if date else datetime.now(timezone.utc)
        save_raw_etf_file(etf_ticker, response.content, '.xlsx', save_date)
        
        # Verify we got an Excel file
        content_type = response.headers.get('Content-Type', '')
        is_excel = (
            'spreadsheet' in content_type or 
            'octet-stream' in content_type or
            response.content[:4] == b'PK\x03\x04'  # XLSX magic bytes
        )
        
        if not is_excel:
            logger.error(f"❌ VanEck returned non-Excel content for {etf_ticker}: {content_type}")
            return None
        
        # Parse XLSX
        from io import BytesIO
        
        # VanEck XLSX format:
        # Row 0: Title "Daily Holdings (%) MM/DD/YYYY"
        # Row 1: Empty
        # Row 2: Headers (Number, Ticker, Holding Name, Identifier, Shares, Asset Class, Market Value, Notional Value, % of Net Assets)
        # Row 3+: Data
        
        # Read without header first to find the header row
        df_raw = pd.read_excel(BytesIO(response.content), header=None)
        
        # Find the header row (contains "Ticker")
        header_row_idx = None
        for idx in range(min(10, len(df_raw))):
            row_values = [str(v).lower() for v in df_raw.iloc[idx].values if pd.notna(v)]
            if any('ticker' in v for v in row_values):
                header_row_idx = idx
                break
        
        if header_row_idx is None:
            logger.error(f"❌ Could not find header row in VanEck XLSX for {etf_ticker}")
            return None
        
        # Re-read with correct header
        df = pd.read_excel(BytesIO(response.content), header=header_row_idx)
        df.columns = df.columns.astype(str).str.strip()
        
        # Map columns to standard schema
        column_mapping = {}
        for col in df.columns:
            col_lower = col.lower()
            if 'ticker' in col_lower and 'stock' not in col_lower:
                column_mapping[col] = 'ticker'
            elif 'holding name' in col_lower:
                column_mapping[col] = 'name'
            elif '% of net' in col_lower or 'net assets' in col_lower:
                column_mapping[col] = 'weight_percent'
            elif col_lower == 'shares':
                column_mapping[col] = 'shares'
        
        df = df.rename(columns=column_mapping)
        
        if 'ticker' not in df.columns:
            logger.error(f"❌ VanEck XLSX missing ticker column. Found: {df.columns.tolist()}")
            return None
        
        # Clean data
        df = df[df['ticker'].notna()]
        df = df[df['ticker'] != '']
        
        # Clean ticker (VanEck uses "NVDA US" format - extract just ticker)
        df['ticker'] = df['ticker'].astype(str).str.split().str[0].str.upper().str.strip()
        
        # Filter to valid stock tickers only
        df = df[df['ticker'].apply(is_stock_ticker)]
        
        # Convert numeric columns
        if 'shares' in df.columns:
            df['shares'] = pd.to_numeric(
                df['shares'].astype(str).str.replace(',', '').str.replace('$', ''),
                errors='coerce'
            ).fillna(0)
        if 'weight_percent' in df.columns:
            # Remove % sign and convert
            df['weight_percent'] = pd.to_numeric(
                df['weight_percent'].astype(str).str.replace('%', '').str.strip(),
                errors='coerce'
            ).fillna(0)
        
        logger.info(f"✅ Parsed {len(df)} holdings for {etf_ticker}")
        return df
        
    except requests.exceptions.RequestException as e:
        logger.error(f"❌ Failed to download {etf_ticker} VanEck XLSX: {e}")
        return None
    except Exception as e:
        logger.error(f"❌ Error parsing {etf_ticker} VanEck XLSX: {e}", exc_info=True)
        return None


def get_previous_holdings(pc: PostgresClient, etf_ticker: str, date: datetime) -> pd.DataFrame:
    """Fetch latest available previous holdings from Research DB.
    
    Args:
        pc: PostgresClient for research database
        etf_ticker: ETF ticker
        date: Current processing date
        
    Returns:
        DataFrame with previous holdings
    """
    date_str = date.strftime('%Y-%m-%d')
    
    try:
        # 1. Find latest date before today
        date_res = pc.execute_query("""
            SELECT date FROM etf_holdings_log
            WHERE etf_ticker = %s AND date < %s
            ORDER BY date DESC
            LIMIT 1
        """, (etf_ticker, date_str))

        if not date_res:
            logger.info(f"ℹ️  No previous history found for {etf_ticker} before {date_str}")
            return pd.DataFrame(columns=['ticker', 'shares', 'weight_percent'])

        previous_date = date_res[0]['date']
        logger.info(f"Comparing {etf_ticker} against latest snapshot: {previous_date}")

        # 2. Fetch holdings for that date
        result = pc.execute_query("""
            SELECT holding_ticker, shares_held, weight_percent
            FROM etf_holdings_log
            WHERE etf_ticker = %s AND date = %s
        """, (etf_ticker, previous_date))
        
        if not result:
            return pd.DataFrame(columns=['ticker', 'shares', 'weight_percent'])
        
        df = pd.DataFrame(result)
        # Rename to match expected schema
        df = df.rename(columns={
            'holding_ticker': 'ticker',
            'shares_held': 'shares'
        })
        
        return df
        
    except Exception as e:
        logger.error(f"Error getting previous holdings: {e}")
        return pd.DataFrame(columns=['ticker', 'shares', 'weight_percent'])


def calculate_diff(today: pd.DataFrame, yesterday: pd.DataFrame, etf_ticker: str) -> List[Dict]:
    """Calculate significant holding changes.
    
    Args:
        today: Today's holdings DataFrame
        yesterday: Yesterday's holdings DataFrame
        etf_ticker: ETF ticker for logging
        
    Returns:
        List of dicts with significant changes (filtered to stocks only, excluding systematic adjustments)
    """
    # Convert shares to float to avoid Decimal/float type mismatch
    # PostgreSQL returns NUMERIC as Decimal, but pandas operations need float
    if 'shares' in yesterday.columns:
        yesterday = yesterday.copy()
        yesterday['shares'] = pd.to_numeric(yesterday['shares'], errors='coerce').astype(float)
    
    # Merge on ticker
    merged = today.merge(
        yesterday,
        on='ticker',
        how='outer',
        suffixes=('_now', '_prev')
    )
    
    # Fill NaN (new/removed positions)
    merged['shares_now'] = merged['shares_now'].fillna(0)
    merged['shares_prev'] = merged['shares_prev'].fillna(0)
    
    # Ensure both are float for arithmetic operations
    merged['shares_now'] = pd.to_numeric(merged['shares_now'], errors='coerce').astype(float).fillna(0)
    merged['shares_prev'] = pd.to_numeric(merged['shares_prev'], errors='coerce').astype(float).fillna(0)
    
    # Calculate absolute and percentage change
    merged['share_diff'] = merged['shares_now'] - merged['shares_prev']
    merged['percent_change'] = ((merged['share_diff'] / merged['shares_prev']) * 100).replace([float('inf'), -float('inf')], 100)
    
    # Filter for significant changes
    significant = merged[
        (merged['share_diff'].abs() >= MIN_SHARE_CHANGE) |
        (merged['percent_change'].abs() >= MIN_PERCENT_CHANGE)
    ].copy()
    
    # Filter out non-stock tickers (cash, futures, derivatives)
    before_filter = len(significant)
    significant = significant[significant['ticker'].apply(is_stock_ticker)].copy()
    filtered_out = before_filter - len(significant)

    if filtered_out > 0:
        logger.info(f"🔍 {etf_ticker}: Filtered out {filtered_out} non-stock changes (cash/futures/derivatives)")

    # Early return if all changes were filtered out
    if len(significant) == 0:
        logger.info(f"📊 {etf_ticker}: No significant stock changes after filtering")
        return []

    # Detect and filter systematic adjustments (e.g., expense ratio deductions)
    # Systematic adjustments affect all holdings by approximately the same percentage
    # This is NOT trading activity - it's administrative adjustments like fee deductions
    # See documentation at top of file for detection criteria
    if len(significant) > 5:  # Need enough data points to detect pattern
        from collections import Counter
        # Round percentages to 0.1% to detect clustering
        rounded_pcts = [round(abs(row['percent_change']), 1) for _, row in significant.iterrows()]
        pct_counts = Counter(rounded_pcts)
        most_common_pct, most_common_count = pct_counts.most_common(1)[0]
        
        # If 80%+ of changes cluster around the same percentage, it's likely systematic
        if most_common_count >= len(significant) * 0.8:
            # Additional check: ensure it's a small percentage (systematic adjustments are typically <2%)
            if most_common_pct <= 2.0:
                # Check if all changes are in same direction (systematic adjustments are uniform)
                all_same_direction = (
                    all(row['share_diff'] > 0 for _, row in significant.iterrows()) or
                    all(row['share_diff'] < 0 for _, row in significant.iterrows())
                )
                
                if all_same_direction:
                    logger.info(f"🔍 {etf_ticker}: Detected systematic adjustment ({most_common_count}/{len(significant)} changes at ~{most_common_pct:.1f}%) - filtering out")
                    # Return empty list - these aren't real trading changes
                    return []
    
    # Add context
    significant['etf'] = etf_ticker
    significant['action'] = significant['share_diff'].apply(lambda x: 'BUY' if x > 0 else 'SELL')
    
    logger.info(f"📊 {etf_ticker}: Found {len(significant)} significant stock changes out of {len(merged)} holdings")
    
    return significant.to_dict('records')


def save_holdings_snapshot(pc: PostgresClient, etf_ticker: str, holdings: pd.DataFrame, date: datetime):
    """Save today's holdings snapshot to Research DB.
    
    Args:
        pc: PostgresClient for research database
        etf_ticker: ETF ticker
        holdings: Holdings DataFrame
        date: Snapshot date
    """
    import math
    
    date_str = date.strftime('%Y-%m-%d')
    
    # First, clean the data and aggregate duplicates
    # Some ETFs have duplicate tickers (e.g., CVRs, different share classes)
    clean_holdings = holdings.copy()
    
    # Remove rows with empty/invalid tickers
    clean_holdings = clean_holdings[clean_holdings['ticker'].notna()]
    clean_holdings = clean_holdings[clean_holdings['ticker'] != '']
    clean_holdings = clean_holdings[clean_holdings['ticker'].apply(lambda x: not (isinstance(x, float) and math.isnan(x)))]
    clean_holdings['ticker'] = clean_holdings['ticker'].astype(str).str.strip()
    
    # Replace NaN/inf with 0 for numeric columns before aggregation
    if 'shares' in clean_holdings.columns:
        clean_holdings['shares'] = pd.to_numeric(clean_holdings['shares'], errors='coerce').fillna(0)
    if 'weight_percent' in clean_holdings.columns:
        clean_holdings['weight_percent'] = pd.to_numeric(clean_holdings['weight_percent'], errors='coerce').fillna(0)
    
    # Aggregate duplicates: sum shares and weights, keep first name
    duplicates_before = len(clean_holdings)
    aggregated = clean_holdings.groupby('ticker', as_index=False).agg({
        'name': 'first',
        'shares': 'sum',
        'weight_percent': 'sum'
    })
    duplicates_removed = duplicates_before - len(aggregated)
    
    if duplicates_removed > 0:
        logger.info(f"📊 {etf_ticker}: Aggregated {duplicates_removed} duplicate ticker entries")
    
    # Prepare records
    records = []
    for _, row in aggregated.iterrows():
        record = (
            date_str,
            etf_ticker,
            row['ticker'],
            str(row.get('name', '')) if pd.notna(row.get('name')) else '',
            float(row['shares']) if row.get('shares', 0) > 0 else None,
            float(row['weight_percent']) if row.get('weight_percent', 0) > 0 else None,
        )
        records.append(record)
    
    skipped_count = len(holdings) - duplicates_before
    if skipped_count > 0:
        logger.warning(f"⚠️ Skipped {skipped_count} rows with invalid/empty tickers for {etf_ticker}")
    
    if not records:
        logger.error(f"❌ No valid records to save for {etf_ticker}")
        return
    
    # Batch upsert with error handling using PostgresClient
    try:
        batch_size = 500
        with pc.get_connection() as conn:
            cursor = conn.cursor()
            
            for i in range(0, len(records), batch_size):
                batch = records[i:i + batch_size]
                
                # Use executemany with ON CONFLICT for upsert
                cursor.executemany("""
                    INSERT INTO etf_holdings_log 
                    (date, etf_ticker, holding_ticker, holding_name, shares_held, weight_percent)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (date, etf_ticker, holding_ticker) DO UPDATE SET
                        holding_name = EXCLUDED.holding_name,
                        shares_held = EXCLUDED.shares_held,
                        weight_percent = EXCLUDED.weight_percent
                """, batch)
                
                if len(records) > batch_size:
                    logger.debug(f"  Saved batch {i//batch_size + 1} ({len(batch)} records)")
            
            conn.commit()
        
        logger.info(f"💾 Saved {len(records)} holdings for {etf_ticker} on {date_str}")
    except Exception as e:
        logger.error(f"❌ Failed to save holdings for {etf_ticker}: {type(e).__name__}: {e}")
        raise


def upsert_securities_metadata(db: SupabaseClient, df: pd.DataFrame, provider: str):
    """Upsert security metadata into securities table."""
    try:
        # Deduplicate by ticker
        if 'ticker' not in df.columns:
            return
            
        unique_securities = df.drop_duplicates(subset=['ticker']).copy()
        
        # Ensure all columns exist
        cols = ['ticker', 'name', 'sector', 'industry', 'asset_class', 'exchange', 'currency']
        for col in cols:
            if col not in unique_securities.columns:
                unique_securities[col] = None
        
        records = []
        for _, row in unique_securities.iterrows():
            ticker = row['ticker']
            if not ticker or len(str(ticker)) > 20:  # Skip long garbage tickers
                continue
                
            record = {
                'ticker': ticker,
                'company_name': row['name'],
                'last_updated': datetime.now(timezone.utc).isoformat()
            }
            
            # Add optional fields if they have values
            if row.get('sector'):
                record['sector'] = row['sector']
            if row.get('industry'):
                record['industry'] = row['industry']
            # Note: asset_class, exchange, and first_detected_by don't exist in Supabase securities table
            if row.get('currency'):
                record['currency'] = row['currency']
                
            records.append(record)
            
        if not records:
            return
            
        # Batch upsert
        db.supabase.table('securities').upsert(records).execute()
        logger.info(f"ℹ️  Upserted metadata for {len(records)} securities from {provider}")
        
    except Exception as e:
        logger.error(f"❌ Error upserting securities metadata: {e}")


def upsert_etf_metadata(db: SupabaseClient, etf_ticker: str, provider: str):
    """Upsert ETF metadata into securities table."""
    try:
        etf_name = ETF_NAMES.get(etf_ticker, etf_ticker)
        
        record = {
            'ticker': etf_ticker,
            'company_name': etf_name,
            'last_updated': datetime.now(timezone.utc).isoformat()
        }
        # Note: asset_class and first_detected_by don't exist in Supabase securities table
        
        db.supabase.table('securities').upsert(record).execute()
        logger.info(f"ℹ️  Upserted ETF metadata for {etf_ticker}")
        
    except Exception as e:
        logger.error(f"❌ Error upserting ETF metadata for {etf_ticker}: {e}")


def log_significant_changes(repo: ResearchRepository, changes: List[Dict], etf_ticker: str):
    """Log significant ETF changes to research_articles.
    
    Args:
        repo: Research repository
        changes: List of change dicts
        etf_ticker: ETF ticker
    """
    if not changes:
        return
    
    # Group by action for cleaner summary
    buys = [c for c in changes if c['action'] == 'BUY']
    sells = [c for c in changes if c['action'] == 'SELL']
    
    summary_lines = []
    if buys:
        top_buys = sorted(buys, key=lambda x: abs(x['share_diff']), reverse=True)[:5]
        summary_lines.append(f"**Top Buys ({len(buys)} total)**:")
        for c in top_buys:
            summary_lines.append(f"- {c['ticker']}: +{c['share_diff']:,.0f} shares ({c['percent_change']:.1f}%)")
    
    if sells:
        top_sells = sorted(sells, key=lambda x: abs(x['share_diff']), reverse=True)[:5]
        summary_lines.append(f"\n**Top Sells ({len(sells)} total)**:")
        for c in top_sells:
            summary_lines.append(f"- {c['ticker']}: {c['share_diff']:,.0f} shares ({c['percent_change']:.1f}%)")
    
    content = "\n".join(summary_lines)
    
    # Save to research_articles
    repo.save_article(
        title=f"{etf_ticker} Daily Holdings Update",
        url=f"{_ARK_BASE.replace('assets.', '')}/funds/{etf_ticker.lower()}",  # Generic URL
        content=content,
        summary=f"{etf_ticker} made {len(changes)} significant changes today",
        source="ETF Watchtower",
        article_type="ETF Change",
        tickers=[c['ticker'] for c in changes[:10]]  # Top 10 tickers
    )
    
    logger.info(f"📰 Logged {len(changes)} changes to research_articles")


def etf_watchtower_job():
    """Main ETF Watchtower job - run daily after market close."""
    job_id = 'etf_watchtower'
    start_time = __import__('time').time()
    
    logger.info("🏛️ Starting ETF Watchtower Job...")
    
    # CRITICAL: Use US Eastern timezone for date (not UTC)
    # Job runs at 8:00 PM EST, which is after market close (4:00 PM EST)
    # Using UTC would give wrong date (e.g., 8 PM EST = 1 AM UTC next day)
    # ETF data is for the trading day that just closed, so use EST date
    try:
        import pytz
        et = pytz.timezone('America/New_York')
        now_et = datetime.now(et)
        today_et = now_et.date()  # Use ET date, not UTC date
        # Convert to UTC datetime for database operations (midnight ET = 4-5 AM UTC depending on DST)
        today = datetime.combine(today_et, datetime.min.time()).replace(tzinfo=et).astimezone(timezone.utc)
        target_date = today_et  # Use ET date for job tracking
    except ImportError:
        # Fallback to UTC if pytz not available (shouldn't happen)
        logger.warning("⚠️ pytz not available, using UTC date (may cause timezone issues)")
        today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        target_date = datetime.now(timezone.utc).date()
    
    # Import job tracking at the start
    try:
        from utils.job_tracking import mark_job_started, mark_job_completed, mark_job_failed
        mark_job_started(job_id, target_date)
    except Exception as e:
        logger.warning(f"Could not mark job started: {e}")
    
    db = SupabaseClient(use_service_role=True)  # Use service role for securities metadata
    pc = PostgresClient()  # Research DB for etf_holdings_log
    repo = ResearchRepository()
    
    total_changes = 0
    successful_etfs = []
    failed_etfs = []
    
    try:
        for etf_ticker, config in ETF_CONFIGS.items():
            try:
                logger.info(f"\n{'='*60}")
                logger.info(f"Processing {etf_ticker} ({config['provider']})")
                logger.info(f"{'='*60}")
                
                # 1. Download today's holdings
                if config['provider'] == 'ARK':
                    today_holdings = fetch_ark_holdings(etf_ticker, config['url'], today)
                elif config['provider'] == 'iShares':
                    today_holdings = fetch_ishares_holdings(etf_ticker, config['url'], today)
                elif config['provider'] == 'SPDR':
                    today_holdings = fetch_spdr_holdings(etf_ticker, config['url'], today)
                elif config['provider'] == 'Global X':
                    today_holdings = fetch_globalx_holdings(etf_ticker, config['url'], today)
                elif config['provider'] == 'Direxion':
                    today_holdings = fetch_direxion_holdings(etf_ticker, config['url'], today)
                elif config['provider'] == 'VanEck':
                    today_holdings = fetch_vaneck_holdings(etf_ticker, config['url'], today)
                else:
                    logger.warning(f"⚠️ Provider {config['provider']} not yet implemented")
                    continue
                
                if today_holdings is None or today_holdings.empty:
                    logger.warning(f"⚠️ No holdings data for {etf_ticker}, skipping")
                    continue
                
                # 2. Get yesterday's holdings (from Research DB)
                yesterday_holdings = get_previous_holdings(pc, etf_ticker, today)
                
                # 3. Calculate diff and generate article (only if we have previous data)
                if not yesterday_holdings.empty:
                    changes = calculate_diff(today_holdings, yesterday_holdings, etf_ticker)
                    
                    if changes:
                        num_changes = len(changes)
                        num_holdings = len(today_holdings)
                        change_ratio = num_changes / num_holdings if num_holdings > 0 else 1
                        
                        if change_ratio > 0.9:
                            # More than 90% of holdings changed = likely bad comparison data
                            logger.warning(f"⚠️ {etf_ticker}: Skipping article - {num_changes}/{num_holdings} holdings changed ({change_ratio:.1%}), likely incomplete historical data")
                        else:
                            log_significant_changes(repo, changes, etf_ticker)
                            total_changes += num_changes
                else:
                    logger.info(f"ℹ️ {etf_ticker}: First snapshot - saving holdings but skipping article generation (no historical data to compare)")
                
                # 4. Upsert ETF metadata (the ETF itself)
                upsert_etf_metadata(db, etf_ticker, config['provider'])
                
                # 5. Upsert holdings metadata (to Supabase) & Save snapshot (to Research DB)
                upsert_securities_metadata(db, today_holdings, config['provider'])
                save_holdings_snapshot(pc, etf_ticker, today_holdings, today)
                
                successful_etfs.append(etf_ticker)
                logger.info(f"✅ {etf_ticker} processed successfully")
                
            except Exception as e:
                failed_etfs.append(etf_ticker)
                logger.error(f"❌ Error processing {etf_ticker}: {e}", exc_info=True)
                continue
        
        duration_ms = int((__import__('time').time() - start_time) * 1000)
        
        # Build summary message
        if failed_etfs:
            message = f"ETF Watchtower completed with errors: {len(successful_etfs)} succeeded, {len(failed_etfs)} failed ({', '.join(failed_etfs)}). {total_changes} changes detected."
            logger.warning(f"\n⚠️ {message}")
        else:
            message = f"ETF Watchtower completed: {len(successful_etfs)} ETFs processed, {total_changes} changes detected"
            logger.info(f"\n✅ {message}")
        
        try:
            from scheduler.scheduler_core import log_job_execution
            # Mark as failed if any ETFs failed
            success = len(failed_etfs) == 0
            log_job_execution(job_id, success=success, message=message, duration_ms=duration_ms)
            if success:
                mark_job_completed(job_id, target_date, None, [], duration_ms=duration_ms)
            else:
                mark_job_failed(job_id, target_date, None, message, duration_ms=duration_ms)
        except:
            pass
            
    except Exception as e:
        duration_ms = int((__import__('time').time() - start_time) * 1000)
        message = f"ETF Watchtower failed: {str(e)}"
        logger.error(f"❌ {message}", exc_info=True)
        try:
            from scheduler.scheduler_core import log_job_execution
            log_job_execution(job_id, success=False, message=message, duration_ms=duration_ms)
            mark_job_failed(job_id, target_date, None, message, duration_ms=duration_ms)
        except:
            pass


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    etf_watchtower_job()
