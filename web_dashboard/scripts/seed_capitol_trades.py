#!/usr/bin/env python3
"""
Congress Trading History Seeder
===============================

Scrapes historical congressional trading data from an external source
into the congress_trades table.

Uses FlareSolverr to bypass Cloudflare protection and extracts data from
the embedded Next.js data chunks.

Usage:
    python web_dashboard/scripts/seed_capitol_trades.py [--months-back N]
"""

import sys
import os
import time
import argparse
import re
import json
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List

# Fix Windows console encoding
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / 'web_dashboard'))

# Load environment variables
from dotenv import load_dotenv
env_path = project_root / 'web_dashboard' / '.env'
if env_path.exists():
    load_dotenv(env_path)
else:
    load_dotenv()

import requests
import logging
from bs4 import BeautifulSoup

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# The website URL (from environment variable)
BASE_URL = os.getenv("CONGRESS_TRADES_BASE_URL", "")
if not BASE_URL:
    raise ValueError("CONGRESS_TRADES_BASE_URL environment variable not set")

# FlareSolverr URL (for bypassing Cloudflare)
FLARESOLVERR_URL = os.getenv("FLARESOLVERR_URL", "http://localhost:8191")

# Direct request headers (fallback if FlareSolverr unavailable)
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


def fetch_page_via_flaresolverr(url: str) -> Optional[str]:
    """Fetch a page using FlareSolverr to bypass Cloudflare protection."""
    try:
        flaresolverr_endpoint = f"{FLARESOLVERR_URL}/v1"
        payload = {
            "cmd": "request.get",
            "url": url,
            "maxTimeout": 60000
        }
        
        logger.debug(f"Requesting via FlareSolverr: {url}")
        response = requests.post(
            flaresolverr_endpoint,
            json=payload,
            timeout=90
        )
        response.raise_for_status()
        
        data = response.json()
        
        if data.get("status") != "ok":
            error_msg = data.get("message", "Unknown error")
            logger.warning(f"FlareSolverr returned error: {error_msg}")
            return None
        
        solution = data.get("solution", {})
        html_content = solution.get("response", "")
        
        if not html_content:
            logger.warning("FlareSolverr returned empty response")
            return None
        
        return html_content
    
    except requests.exceptions.ConnectionError:
        logger.warning(f"FlareSolverr unavailable at {FLARESOLVERR_URL}")
        return None
    except requests.exceptions.Timeout:
        logger.warning("FlareSolverr request timed out")
        return None
    except Exception as e:
        logger.warning(f"FlareSolverr request failed: {e}")
        return None


def fetch_page_direct(url: str) -> Optional[str]:
    """Fetch a page directly (may be blocked by Cloudflare)."""
    try:
        response = requests.get(url, headers=HEADERS, timeout=30)
        if response.status_code == 200:
            return response.text
        else:
            logger.warning(f"Direct request returned status {response.status_code}")
            return None
    except Exception as e:
        logger.warning(f"Direct request failed: {e}")
        return None


def extract_trade_data_from_html(html: str) -> List[Dict[str, Any]]:
    """Extract trade data from Next.js embedded scripts."""
    trades = []
    
    soup = BeautifulSoup(html, 'html.parser')
    scripts = soup.find_all('script')
    
    # Look for __next_f.push scripts containing trade data
    all_script_text = ""
    for script in scripts:
        if script.string and '__next_f.push' in script.string:
            all_script_text += script.string
    
    if not all_script_text:
        logger.warning("No Next.js data scripts found")
        return trades
    
    # Extract JSON-like trade objects
    
    # Unescape common patterns
    unescaped = all_script_text.replace('\\"', '"').replace('\\\\', '\\')
    
    # Try to find trade entries by looking for _txId patterns and extracting surrounding context
    tx_id_pattern = r'"_txId"\s*:\s*(\d+)'
    tx_matches = list(re.finditer(tx_id_pattern, unescaped))
    
    logger.info(f"Found {len(tx_matches)} potential transaction IDs")
    
    if not tx_matches:
        # Fallback: try parsing tables from HTML
        return extract_trades_from_table(soup)
    
    # For each transaction ID, try to extract the surrounding trade object
    for match in tx_matches:
        tx_id = match.group(1)
        start_pos = match.start()
        
        # Look backwards for the opening brace
        brace_count = 0
        obj_start = start_pos
        for i in range(start_pos, -1, -1):
            if unescaped[i] == '}':
                brace_count += 1
            elif unescaped[i] == '{':
                if brace_count == 0:
                    obj_start = i
                    break
                brace_count -= 1
        
        # Look forwards for the closing brace
        brace_count = 1  # We start after the opening brace
        obj_end = len(unescaped)
        i = obj_start + 1
        while i < len(unescaped):
            if unescaped[i] == '{':
                brace_count += 1
            elif unescaped[i] == '}':
                brace_count -= 1
                if brace_count == 0:
                    obj_end = i + 1
                    break
            i += 1
        
        try:
            obj_str = unescaped[obj_start:obj_end]
            trade_obj = json.loads(obj_str)
            
            # Validate it looks like a trade
            if '_txId' in trade_obj and ('politician' in trade_obj or 'txDate' in trade_obj):
                trades.append(trade_obj)
        except json.JSONDecodeError:
            continue
    
    # Deduplicate by transaction ID
    seen_ids = set()
    unique_trades = []
    for trade in trades:
        tx_id = trade.get('_txId')
        if tx_id and tx_id not in seen_ids:
            seen_ids.add(tx_id)
            unique_trades.append(trade)
    
    logger.info(f"Successfully extracted {len(unique_trades)} unique trades from scripts")
    return unique_trades


def extract_trades_from_table(soup: BeautifulSoup) -> List[Dict[str, Any]]:
    """Fallback: Extract trade data from HTML table."""
    trades = []
    
    # Find all trade links (each row has a link like /trades/12345)
    trade_links = soup.find_all('a', href=lambda h: h and h.startswith('/trades/'))
    
    for link in trade_links:
        try:
            # Get the transaction ID from the URL
            href = link.get('href', '')
            tx_id_match = re.search(r'/trades/(\d+)', href)
            if not tx_id_match:
                continue
            tx_id = int(tx_id_match.group(1))
            
            # Navigate up to find the row container
            row = link.find_parent('tr') or link.find_parent('div')
            if not row:
                continue
            
            # Try to find cells/columns
            cells = row.find_all(['td', 'div'])
            
            # Find politician link
            politician_link = row.find('a', href=lambda h: h and '/politicians/' in h)
            # Find issuer link
            issuer_link = row.find('a', href=lambda h: h and '/issuers/' in h)
            
            trade = {
                '_txId': tx_id,
                'politician': {},
                'issuer': {}
            }
            
            if politician_link:
                politician_name = politician_link.get_text(strip=True)
                trade['politician']['firstName'] = politician_name.split()[0] if politician_name else ''
                trade['politician']['lastName'] = ' '.join(politician_name.split()[1:]) if politician_name else ''
            
            if issuer_link:
                issuer_text = issuer_link.get_text(strip=True)
                # Try to extract ticker (usually shown as "COMPANY (TICKER)")
                ticker_match = re.search(r'\(([A-Z]+)\)', issuer_text)
                if ticker_match:
                    trade['issuer']['issuerTicker'] = ticker_match.group(1) + ':US'
                trade['issuer']['issuerName'] = re.sub(r'\s*\([A-Z]+\)\s*', '', issuer_text).strip()
            
            trades.append(trade)
        
        except Exception as e:
            logger.debug(f"Error parsing table row: {e}")
            continue
    
    logger.info(f"Extracted {len(trades)} trades from table (fallback method)")
    return trades


def clean_ticker(issuer_data: Optional[Dict[str, Any]]) -> Optional[str]:
    """Extracts ticker from 'NVDA:US' format or uses the ticker field directly"""
    if not issuer_data:
        return None
    
    # Check for issuerTicker (newer format)
    raw = issuer_data.get('issuerTicker') or issuer_data.get('ticker')
    if not raw:
        return None
    
    # Handle "NVDA:US" format
    if ':' in str(raw):
        ticker = str(raw).split(':')[0].strip().upper()
    else:
        ticker = str(raw).strip().upper()
    
    # Skip invalid tickers
    if not ticker or ticker == '--' or ticker == 'N/A':
        return None
    
    return ticker


def normalize_chamber(chamber: Optional[str]) -> Optional[str]:
    """Normalize 'house'/'senate' to 'House'/'Senate'"""
    if not chamber:
        return None
    
    chamber_lower = str(chamber).lower().strip()
    if chamber_lower == 'house':
        return 'House'
    elif chamber_lower == 'senate':
        return 'Senate'
    else:
        if 'house' in chamber_lower:
            return 'House'
        elif 'senate' in chamber_lower:
            return 'Senate'
        return None


def normalize_transaction_type(tx_type: Optional[str]) -> Optional[str]:
    """Normalize 'buy'/'sell' to 'Purchase'/'Sale'"""
    if not tx_type:
        return None
    
    tx_lower = str(tx_type).lower().strip()
    if 'buy' in tx_lower or 'purchase' in tx_lower:
        return 'Purchase'
    elif 'sell' in tx_lower or 'sale' in tx_lower:
        return 'Sale'
    elif 'exchange' in tx_lower:
        return 'Exchange'
    else:
        return 'Purchase'


def map_trade_to_schema(trade_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Map scraped trade data to congress_trades schema"""
    try:
        # Extract politician info
        politician = trade_data.get('politician', {})
        if not politician:
            return None
        
        # Build politician name
        first_name = politician.get('firstName', '').strip()
        last_name = politician.get('lastName', '').strip()
        if not first_name and not last_name:
            return None
        
        politician_name = f"{first_name} {last_name}".strip()
        if not politician_name:
            return None
        
        # Get chamber
        chamber = normalize_chamber(politician.get('chamber'))
        if not chamber:
            # Try to infer from party info or default
            chamber = 'House'  # Default, will be updated if better info available
        
        # Extract issuer/ticker
        issuer = trade_data.get('issuer', {})
        ticker = clean_ticker(issuer)
        if not ticker:
            return None
        
        # Parse dates
        tx_date_str = trade_data.get('txDate')
        pub_date_str = trade_data.get('pubDate')
        
        if not tx_date_str:
            return None
        
        # Parse transaction date (can be "2025-12-01" or ISO format)
        try:
            if 'T' in tx_date_str:
                tx_date = datetime.fromisoformat(tx_date_str.replace('Z', '+00:00')).date()
            else:
                tx_date = datetime.strptime(tx_date_str[:10], "%Y-%m-%d").date()
        except (ValueError, TypeError):
            return None
        
        # Parse disclosure date
        if pub_date_str:
            try:
                if 'T' in pub_date_str:
                    disclosure_date = datetime.fromisoformat(pub_date_str.replace('Z', '+00:00')).date()
                else:
                    disclosure_date = datetime.strptime(pub_date_str[:10], "%Y-%m-%d").date()
            except (ValueError, TypeError):
                disclosure_date = tx_date
        else:
            disclosure_date = tx_date
        
        # Get transaction type
        tx_type = normalize_transaction_type(trade_data.get('txType'))
        if not tx_type:
            return None
        
        # Get amount/value
        value = trade_data.get('value') or trade_data.get('txSize') or ''
        if value:
            # Convert numeric value to range string if needed
            if isinstance(value, (int, float)):
                if value < 1000:
                    amount = f"$1 - $1,000"
                elif value < 15000:
                    amount = f"$1,001 - $15,000"
                elif value < 50000:
                    amount = f"$15,001 - $50,000"
                elif value < 100000:
                    amount = f"$50,001 - $100,000"
                elif value < 250000:
                    amount = f"$100,001 - $250,000"
                elif value < 500000:
                    amount = f"$250,001 - $500,000"
                elif value < 1000000:
                    amount = f"$500,001 - $1,000,000"
                else:
                    amount = f"Over $1,000,000"
            else:
                amount = str(value).strip()
        else:
            amount = ''
        
        # Asset type defaults to Stock
        asset_type = 'Stock'
        
        # Build record for congress_trades table
        return {
            'ticker': ticker,
            'politician': politician_name,
            'chamber': chamber,
            'transaction_date': tx_date.isoformat(),
            'disclosure_date': disclosure_date.isoformat(),
            'type': tx_type,
            'amount': amount,
            'asset_type': asset_type,
            'conflict_score': None,
            'notes': 'Imported from public records (scraped)'
        }
    
    except Exception as e:
        logger.debug(f"Error mapping trade data: {e}, data: {trade_data}")
        return None


def seed_congress_trades(months_back: int = 3, page_size: int = 100) -> None:
    """Main seeder function - scrapes historical data from source"""
    print("=" * 70)
    print("CONGRESS TRADES HISTORY SEEDER")
    print("=" * 70)
    print()
    
    # Check FlareSolverr availability
    flaresolverr_available = False
    try:
        health_response = requests.get(f"{FLARESOLVERR_URL}/health", timeout=5)
        if health_response.status_code == 200:
            flaresolverr_available = True
            print(f"✅ FlareSolverr available at {FLARESOLVERR_URL}")
    except:
        print(f"⚠️  FlareSolverr not available at {FLARESOLVERR_URL}")
        print("   Will attempt direct requests (may be blocked by Cloudflare)")
    
    # Initialize Supabase client
    try:
        from supabase_client import SupabaseClient
        client = SupabaseClient(use_service_role=True)
        print("✅ Connected to Supabase")
    except Exception as e:
        print(f"❌ Failed to connect to Supabase: {e}")
        return
    
    # Calculate cutoff date
    cutoff_date = datetime.now() - timedelta(days=months_back * 30)
    print(f"📉 Starting Data Scrape (Target: Trades after {cutoff_date.date()})...")
    print(f"   Using page size: {page_size}")
    print()
    
    page = 1
    total_added = 0
    total_skipped = 0
    total_errors = 0
    
    while True:
        try:
            print(f"   Fetching Page {page}...")
            
            # Build URL with pagination
            url = f"{BASE_URL}?pageSize={page_size}&page={page}"
            
            # Fetch page content
            html = None
            if flaresolverr_available:
                html = fetch_page_via_flaresolverr(url)
            
            if not html:
                html = fetch_page_direct(url)
            
            if not html:
                print(f"❌ Failed to fetch page {page}")
                break
            
            # Extract trade data
            trades = extract_trade_data_from_html(html)
            
            if not trades:
                print("✅ No more trades found (reached end of data).")
                break
            
            # Process the trades
            page_records = []
            oldest_on_page = None
            
            for trade in trades:
                try:
                    # Map to schema
                    mapped_record = map_trade_to_schema(trade)
                    if not mapped_record:
                        total_skipped += 1
                        continue
                    
                    # Check if transaction date is before cutoff
                    tx_date = datetime.strptime(mapped_record['transaction_date'], "%Y-%m-%d").date()
                    if oldest_on_page is None or tx_date < oldest_on_page:
                        oldest_on_page = tx_date
                    
                    # Only add records that are after cutoff date
                    if tx_date >= cutoff_date.date():
                        page_records.append(mapped_record)
                
                except Exception as e:
                    total_errors += 1
                    logger.debug(f"Error processing trade: {e}")
                    continue
            
            # Deduplicate records within the batch by unique key
            # (politician, ticker, transaction_date, amount)
            seen_keys = set()
            unique_records = []
            for record in page_records:
                key = (record['politician'], record['ticker'], record['transaction_date'], record['amount'])
                if key not in seen_keys:
                    seen_keys.add(key)
                    unique_records.append(record)
            page_records = unique_records
            
            # Insert records in batch
            if page_records:
                try:
                    result = client.supabase.table("congress_trades")\
                        .upsert(
                            page_records,
                            on_conflict="politician,ticker,transaction_date,amount"
                        )\
                        .execute()
                    
                    page_added = len(page_records)
                    total_added += page_added
                    
                    print(f"   ✅ Saved {page_added} trades. (Oldest: {oldest_on_page})")
                    
                except Exception as e:
                    total_errors += len(page_records)
                    print(f"   ⚠️  Error inserting batch: {e}")
            
            # Check if we should stop (reached cutoff date)
            if oldest_on_page and oldest_on_page < cutoff_date.date():
                print(f"🛑 Reached cutoff date ({oldest_on_page}). Stopping.")
                break
            
            # Move to next page
            page += 1
            
            # Be polite - add delay between requests
            time.sleep(2)
        
        except requests.exceptions.RequestException as e:
            print(f"❌ Network error: {e}")
            break
        except Exception as e:
            print(f"❌ Critical error: {e}")
            logger.exception("Critical error in seeder")
            break
    
    print()
    print("=" * 70)
    print("✅ SEEDING COMPLETE")
    print("=" * 70)
    print(f"Total trades imported: {total_added:,}")
    print(f"Total skipped: {total_skipped:,}")
    print(f"Total errors: {total_errors:,}")
    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Import historical congressional trades')
    parser.add_argument(
        '--months-back',
        type=int,
        default=3,
        help='Number of months back to import (default: 3)'
    )
    parser.add_argument(
        '--page-size',
        type=int,
        default=100,
        help='Number of trades per page (default: 100, max recommended: 200)'
    )
    
    args = parser.parse_args()
    seed_congress_trades(months_back=args.months_back, page_size=args.page_size)
