#!/usr/bin/env python3
"""
ETF Watchtower Job
==================
Tracks daily changes in ETF holdings via direct CSV downloads.
Detects institutional accumulation/distribution ("The Diff Engine").

Supported ETFs:
- iShares: IVV, IWM, IBIT
- ARK: ARKK, ARKQ
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
}

# Thresholds for "significant" changes
MIN_SHARE_CHANGE = 1000  # Minimum absolute share change to log
MIN_PERCENT_CHANGE = 0.5  # Minimum % change relative to previous holdings



def fetch_ishares_holdings(etf_ticker: str, csv_url: str) -> Optional[pd.DataFrame]:
    """Download and parse iShares ETF holdings CSV."""
    try:
        logger.info(f"📥 Downloading {etf_ticker} holdings from iShares...")
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/csv,application/csv;q=0.9,*/*;q=0.8',
        }
        
        response = requests.get(csv_url, timeout=30, headers=headers)
        response.raise_for_status()
        
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


def fetch_ark_holdings(etf_ticker: str, csv_url: str) -> Optional[pd.DataFrame]:
    """Download and parse ARK ETF holdings CSV.
    
    Args:
        etf_ticker: ETF ticker symbol
        csv_url: Direct CSV URL
        
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


def get_previous_holdings(db: SupabaseClient, etf_ticker: str, date: datetime) -> pd.DataFrame:
    """Fetch latest available previous holdings from database.
    
    Args:
        db: Database client
        etf_ticker: ETF ticker
        date: Current processing date
        
    Returns:
        DataFrame with previous holdings
    """
    date_str = date.strftime('%Y-%m-%d')
    
    try:
        # 1. Find latest date before today
        date_res = db.supabase.table('etf_holdings_log') \
            .select('date') \
            .eq('etf_ticker', etf_ticker) \
            .lt('date', date_str) \
            .order('date', desc=True) \
            .limit(1) \
            .execute()

        if not date_res.data:
            logger.info(f"ℹ️  No previous history found for {etf_ticker} before {date_str}")
            return pd.DataFrame(columns=['ticker', 'shares', 'weight_percent'])

        previous_date = date_res.data[0]['date']
        logger.info(f"Comparing {etf_ticker} against latest snapshot: {previous_date}")

        # 2. Fetch holdings for that date
        result = db.supabase.table('etf_holdings_log').select(
            'holding_ticker, shares_held, weight_percent'
        ).eq('etf_ticker', etf_ticker).eq('date', previous_date).execute()
        
        if not result.data:
            return pd.DataFrame(columns=['ticker', 'shares', 'weight_percent'])
        
        df = pd.DataFrame(result.data)
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
        List of dicts with significant changes
    """
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
    
    # Calculate absolute and percentage change
    merged['share_diff'] = merged['shares_now'] - merged['shares_prev']
    merged['percent_change'] = ((merged['share_diff'] / merged['shares_prev']) * 100).replace([float('inf'), -float('inf')], 100)
    
    # Filter for significant changes
    significant = merged[
        (merged['share_diff'].abs() >= MIN_SHARE_CHANGE) |
        (merged['percent_change'].abs() >= MIN_PERCENT_CHANGE)
    ].copy()
    
    # Add context
    significant['etf'] = etf_ticker
    significant['action'] = significant['share_diff'].apply(lambda x: 'BUY' if x > 0 else 'SELL')
    
    logger.info(f"📊 {etf_ticker}: Found {len(significant)} significant changes out of {len(merged)} holdings")
    
    return significant.to_dict('records')


def save_holdings_snapshot(db: SupabaseClient, etf_ticker: str, holdings: pd.DataFrame, date: datetime):
    """Save today's holdings snapshot to database.
    
    Args:
        db: Database client
        etf_ticker: ETF ticker
        holdings: Holdings DataFrame
        date: Snapshot date
    """
    date_str = date.strftime('%Y-%m-%d')
    
    # Prepare batch insert
    records = []
    for _, row in holdings.iterrows():
        record = {
            'date': date_str,
            'etf_ticker': etf_ticker,
            'holding_ticker': row.get('ticker', ''),
            'holding_name': row.get('name', ''),
        }
        
        # Add optional numeric fields
        if pd.notna(row.get('shares')):
            record['shares_held'] = float(row.get('shares', 0))
        if pd.notna(row.get('weight_percent')):
            record['weight_percent'] = float(row.get('weight_percent', 0))
            
        records.append(record)
    
    # Batch upsert
    db.supabase.table('etf_holdings_log').upsert(records).execute()
    logger.info(f"💾 Saved {len(records)} holdings for {etf_ticker} on {date_str}")


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
    
    # Import job tracking at the start
    target_date = datetime.now(timezone.utc).date()
    
    try:
        from utils.job_tracking import mark_job_started, mark_job_completed, mark_job_failed
        mark_job_started(job_id, target_date)
    except Exception as e:
        logger.warning(f"Could not mark job started: {e}")
    
    logger.info("🏛️ Starting ETF Watchtower Job...")
    
    db = SupabaseClient(use_service_role=True)  # Use service role for writes
    repo = ResearchRepository()
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    
    total_changes = 0
    
    try:
        for etf_ticker, config in ETF_CONFIGS.items():
            try:
                logger.info(f"\n{'='*60}")
                logger.info(f"Processing {etf_ticker} ({config['provider']})")
                logger.info(f"{'='*60}")
                
                # 1. Download today's holdings
                if config['provider'] == 'ARK':
                    today_holdings = fetch_ark_holdings(etf_ticker, config['url'])
                elif config['provider'] == 'iShares':
                    today_holdings = fetch_ishares_holdings(etf_ticker, config['url'])
                else:
                    logger.warning(f"⚠️ Provider {config['provider']} not yet implemented")
                    continue
                
                if today_holdings is None or today_holdings.empty:
                    logger.warning(f"⚠️ No holdings data for {etf_ticker}, skipping")
                    continue
                
                # 2. Get yesterday's holdings
                yesterday_holdings = get_previous_holdings(db, etf_ticker, today)
                
                # 3. Calculate diff (only if we have previous data)
                if not yesterday_holdings.empty:
                    changes = calculate_diff(today_holdings, yesterday_holdings, etf_ticker)
                    
                    if changes:
                        log_significant_changes(repo, changes, etf_ticker)
                        total_changes += len(changes)
                else:
                    logger.info(f"ℹ️  No previous data for {etf_ticker} - this is the first snapshot")
                
                # 4. Upsert ETF metadata (the ETF itself)
                upsert_etf_metadata(db, etf_ticker, config['provider'])
                
                # 5. Upsert holdings metadata & Save snapshot
                upsert_securities_metadata(db, today_holdings, config['provider'])
                save_holdings_snapshot(db, etf_ticker, today_holdings, today)
                
            except Exception as e:
                logger.error(f"❌ Error processing {etf_ticker}: {e}", exc_info=True)
                continue
        
        duration_ms = int((__import__('time').time() - start_time) * 1000)
        message = f"ETF Watchtower completed: {total_changes} total changes detected"
        logger.info(f"\n✅ {message}")
        
        try:
            from scheduler.scheduler_core import log_job_execution
            log_job_execution(job_id, success=True, message=message, duration_ms=duration_ms)
            mark_job_completed(job_id, target_date, None, [], duration_ms=duration_ms)
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
