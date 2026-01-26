#!/usr/bin/env python3
"""
Congress Trading History Seeder (STAGING)
==========================================

Scrapes historical congressional trading data from an external source
into the congress_trades_STAGING table for validation before production.

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
import uuid

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

# Module-level cache for politician state lookups (avoids repeated DB queries)
_POLITICIAN_STATE_CACHE = {}

# Pre-loaded flag to avoid repeated bulk queries
_POLITICIAN_CACHE_LOADED = False

# Reusable Supabase client (initialized once)
_SUPABASE_CLIENT = None

def get_supabase_client():
    """Get or create a reusable Supabase client for state lookups."""
    global _SUPABASE_CLIENT
    if _SUPABASE_CLIENT is None:
        try:
            from supabase_client import SupabaseClient
            _SUPABASE_CLIENT = SupabaseClient(use_service_role=True)
        except Exception:
            pass
    return _SUPABASE_CLIENT

def preload_politician_states():
    """Pre-load all politician states from database to avoid per-trade queries."""
    global _POLITICIAN_STATE_CACHE, _POLITICIAN_CACHE_LOADED
    
    if _POLITICIAN_CACHE_LOADED:
        return  # Already loaded
    
    client = get_supabase_client()
    if not client:
        _POLITICIAN_CACHE_LOADED = True
        return
    
    try:
        result = client.supabase.table('politicians')\
            .select('name, state')\
            .execute()
        
        if result.data:
            for pol in result.data:
                name = pol.get('name', '').strip()
                state = pol.get('state')
                if name and state:
                    _POLITICIAN_STATE_CACHE[name] = state
                    # Also cache by first + last name variations
                    parts = name.split()
                    if len(parts) >= 2:
                        # "John Smith" -> cache as "John Smith"
                        _POLITICIAN_STATE_CACHE[f"{parts[0]} {parts[-1]}"] = state
            
            logger.info(f"Pre-loaded {len(_POLITICIAN_STATE_CACHE)} politician state mappings")
    except Exception as e:
        logger.debug(f"Could not pre-load politician states: {e}")
    
    _POLITICIAN_CACHE_LOADED = True


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
                # Get the politician cell - it contains "Name Party Chamber State" format
                politician_cell = politician_link.find_parent(['td', 'div'])
                politician_cell_text = ''
                if politician_cell:
                    # Get all text from the cell (includes party, chamber, state)
                    politician_cell_text = politician_cell.get_text(separator=' ', strip=True)
                
                # Extract just the name from the link
                politician_name = politician_link.get_text(strip=True)
                trade['politician']['firstName'] = politician_name.split()[0] if politician_name else ''
                trade['politician']['lastName'] = ' '.join(politician_name.split()[1:]) if politician_name else ''
                
                # Extract party from the cell text (format: "Name Party Chamber State")
                if politician_cell_text:
                    party = extract_party_from_text(politician_cell_text)
                    if party:
                        trade['politician']['party'] = party
                    
                    # Also try to extract chamber and state from the cell text
                    # Format is typically: "Name Party Chamber State"
                    # Chamber is usually "House" or "Senate"
                    chamber_match = re.search(r'\b(House|Senate)\b', politician_cell_text, re.IGNORECASE)
                    if chamber_match:
                        trade['politician']['chamber'] = chamber_match.group(1).title()
                    
                    # State is typically 2-letter code at the end
                    state_match = re.search(r'\b([A-Z]{2})\b(?:\s|$)', politician_cell_text)
                    if state_match:
                        trade['politician']['state'] = state_match.group(1).upper()
            
            if issuer_link:
                issuer_text = issuer_link.get_text(strip=True)
                # Try to extract ticker (usually shown as "COMPANY (TICKER)")
                ticker_match = re.search(r'\(([A-Z]+)\)', issuer_text)
                if ticker_match:
                    trade['issuer']['issuerTicker'] = ticker_match.group(1) + ':US'
                trade['issuer']['issuerName'] = re.sub(r'\s*\([A-Z]+\)\s*', '', issuer_text).strip()
            
            # Extract owner from the full row text (format: "... Owner Type Amount ...")
            # Get the full row text to extract owner
            if row:
                row_text = row.get_text(separator=' ', strip=True)
                if row_text:
                    owner = extract_owner_from_text(row_text)
                    if owner:
                        trade['owner'] = owner
            
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
    
    # Validation: Allow 1-10 chars, letters, numbers, and dots (for share classes like BRK.B)
    # This captures stocks, bonds (US10Y), share classes (BRK.B), and numbered tickers
    if not re.match(r'^[A-Z0-9\.]{1,10}$', ticker):
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
    """Normalize transaction types to Purchase/Sale/Exchange/Received"""
    if not tx_type:
        return None
    
    tx_lower = str(tx_type).lower().strip()
    if 'buy' in tx_lower or 'purchase' in tx_lower:
        return 'Purchase'
    elif 'sell' in tx_lower or 'sale' in tx_lower:
        return 'Sale'
    elif 'exchange' in tx_lower:
        return 'Exchange'
    elif 'receive' in tx_lower:
        return 'Received'
    else:
        return 'Purchase'


def extract_party_from_text(text: Optional[str]) -> Optional[str]:
    """Extract party from text like 'Richard Blumenthal Democrat Senate CT' or 'Jefferson Shreve Republican House IN'.
    
    Returns normalized party name: 'Democrat', 'Republican', or 'Independent', or None if not found.
    """
    if not text:
        return None
    
    text_lower = str(text).lower().strip()
    
    # Check for party names (check in order of specificity)
    if 'democrat' in text_lower or 'democratic' in text_lower:
        return 'Democrat'
    elif 'republican' in text_lower:
        return 'Republican'
    elif 'independent' in text_lower:
        return 'Independent'
    
    # Check for party codes in parentheses or as standalone: (D), (R), (I), D, R, I
    party_code_match = re.search(r'\(([DIR])\)|^([DIR])$|\b([DIR])\b', text_lower)
    if party_code_match:
        code = party_code_match.group(1) or party_code_match.group(2) or party_code_match.group(3)
        if code == 'd':
            return 'Democrat'
        elif code == 'r':
            return 'Republican'
        elif code == 'i':
            return 'Independent'
    
    return None


def extract_state_from_text(text: Optional[str]) -> Optional[str]:
    """Extract 2-letter state code from text like 'Richard Blumenthal Democrat Senate CT'.
    
    Returns uppercase 2-letter state code (e.g., 'CT', 'CA', 'NY') or None if not found.
    """
    if not text:
        return None
    
    # Look for 2-letter uppercase state codes (common US state abbreviations)
    # Pattern: word boundary, 2 uppercase letters, word boundary or end of string
    state_match = re.search(r'\b([A-Z]{2})\b(?:\s|$)', str(text))
    if state_match:
        state_code = state_match.group(1).upper()
        # Validate it's a valid US state code (basic check - 2 letters)
        if len(state_code) == 2 and state_code.isalpha():
            return state_code
    
    return None


def extract_owner_from_text(text: Optional[str]) -> Optional[str]:
    """Extract owner from text like '... Spouse sell ...' or '... Joint buy ...'.
    
    Returns normalized owner name: 'Self', 'Spouse', 'Joint', 'Child', 'Undisclosed', or None if not found.
    """
    if not text:
        return None
    
    text_lower = str(text).lower().strip()
    
    # Check for owner types (order matters - check more specific first)
    if 'spouse' in text_lower:
        return 'Spouse'
    elif 'joint' in text_lower:
        return 'Joint'
    elif 'child' in text_lower or 'dependent' in text_lower:
        return 'Child'  # Note: schema uses 'Child' but source might say 'Dependent'
    elif 'undisclosed' in text_lower or 'not-disclosed' in text_lower or 'not disclosed' in text_lower:
        return 'Undisclosed'
    elif 'self' in text_lower:
        return 'Self'
    
    return None


def map_trade_to_schema(trade_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Map scraped trade data to congress_trades schema"""
    try:
        # Extract politician info
        politician = trade_data.get('politician', {})
        if not politician:
            # Fallback: Treat trade_data as politician object (sometimes keys are at top level)
            politician = trade_data
            logger.debug(f"Politician object empty, falling back to top-level trade data. Keys: {list(trade_data.keys())}")
        
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
        
        # Extract party affiliation - try multiple sources
        party = None
        
        # 1. Try JSON fields in politician object (primary method)
        party = (politician.get('party') or 
                politician.get('partyAffiliation') or 
                politician.get('politicalParty') or
                politician.get('partyName') or
                politician.get('partyCode') or
                politician.get('partyLabel'))
        
        # 2. Try top-level fields in trade_data
        if not party:
            party = (trade_data.get('party') or
                    trade_data.get('partyAffiliation') or
                    trade_data.get('politicalParty'))
        
        # 3. Try extracting from chamber/office field (may contain "(D-CA)" pattern)
        if not party:
            chamber_text = politician.get('chamber') or politician.get('office') or trade_data.get('chamber') or trade_data.get('office')
            if chamber_text:
                # Look for patterns like "(D-CA)", "(R-TX)", "(I-VT)"
                party_code_match = re.search(r'\(([DIR])-', str(chamber_text), re.IGNORECASE)
                if party_code_match:
                    code = party_code_match.group(1).upper()
                    if code == 'D':
                        party = 'Democrat'
                    elif code == 'R':
                        party = 'Republican'
                    elif code == 'I':
                        party = 'Independent'
        
        # 4. Normalize party value if found in JSON
        if party:
            party = str(party).strip()
            # Normalize to standard values
            party_lower = party.lower()
            if 'republican' in party_lower or party_lower == 'r':
                party = 'Republican'
            elif 'democrat' in party_lower or party_lower == 'd':
                party = 'Democrat'
            elif 'independent' in party_lower or party_lower == 'i':
                party = 'Independent'
            elif party_lower in ('other', 'none', 'n/a', 'na', 'unknown', 'unaffiliated'):
                # Map "other" and similar values to Independent (e.g., Angus King)
                party = 'Independent'
            else:
                party = None  # Don't store if not standard value
        
        # 5. Fallback: Try extracting from text fields (politician name, chamber, state combined)
        if not party:
            # Try extracting from politician name field (may contain full info)
            politician_name_text = politician.get('name') or politician.get('fullName') or politician_name
            if politician_name_text:
                party = extract_party_from_text(politician_name_text)
            
            # Try extracting from chamber field (may contain "Democrat House" or "Republican Senate")
            if not party:
                chamber_text = politician.get('chamber') or trade_data.get('chamber')
                if chamber_text:
                    party = extract_party_from_text(str(chamber_text))
            
            # Try extracting from combined text (name + chamber + state)
            # Note: state may not be extracted yet, so we'll get it from politician object
            if not party:
                # Build combined text from available fields
                combined_text_parts = []
                if politician_name:
                    combined_text_parts.append(politician_name)
                if chamber:
                    combined_text_parts.append(chamber)
                # Get state from politician object (before it's extracted below)
                state_from_obj = politician.get('state') or politician.get('stateCode') or politician.get('stateAbbreviation')
                if state_from_obj:
                    combined_text_parts.append(str(state_from_obj).strip().upper()[:2])
                
                # Also check if there's a display field that might have the full string
                display_text = (politician.get('displayName') or 
                               politician.get('display') or
                               trade_data.get('politicianDisplay'))
                if display_text:
                    combined_text_parts.insert(0, str(display_text))
                
                if combined_text_parts:
                    combined_text = ' '.join(combined_text_parts)
                    party = extract_party_from_text(combined_text)
        
        # Extract state code
        state = (politician.get('_stateId') or              # ← FIX 1: Add _stateId (actual field name from source)
                 politician.get('state') or 
                 politician.get('stateCode') or 
                 politician.get('stateAbbreviation'))
        if state:
            state = str(state).strip().upper()[:2]  # Ensure 2-letter uppercase code
            # Validate it looks like a state code (2 letters)
            if not state or len(state) != 2 or not state.isalpha():
                state = None
        
        # Try extracting state from text fields if not found in JSON
        if not state:
            # Try from politician name/display fields (may contain "Name Party Chamber State")
            politician_name_text = politician.get('name') or politician.get('fullName') or politician_name
            if politician_name_text:
                state = extract_state_from_text(politician_name_text)
            
            # Try from chamber/display fields
            if not state:
                display_text = (politician.get('displayName') or 
                               politician.get('display') or
                               trade_data.get('politicianDisplay'))
                if display_text:
                    state = extract_state_from_text(str(display_text))
            
            # Try from combined text (name + chamber + state)
            if not state:
                combined_text_parts = []
                if politician_name:
                    combined_text_parts.append(politician_name)
                if chamber:
                    combined_text_parts.append(chamber)
                if combined_text_parts:
                    combined_text = ' '.join(combined_text_parts)
                    state = extract_state_from_text(combined_text)
        
        # If state not in scraped data, try to look it up from politicians table
        # (populated by seed_committees.py which has state from YAML data)
        if not state:
            # Ensure cache is pre-loaded (one-time bulk query)
            preload_politician_states()
            
            # Check cache
            if politician_name in _POLITICIAN_STATE_CACHE:
                state = _POLITICIAN_STATE_CACHE[politician_name]
                logger.debug(f"Found state '{state}' for {politician_name} in cache")
            else:
                # Cache miss - politician not in database
                try:
                    _POLITICIAN_STATE_CACHE[politician_name] = None  # Cache negative result
                    state = None
                except Exception as e:
                    logger.debug(f"Could not lookup state for {politician_name}: {e}")
                    state = None
        
        if not state:
            # logger.debug(f"STATE MISSING for {politician_name}. Politician keys: {list(politician.keys())}")
            if '_stateId' in politician:
                # logger.debug(f"   _stateId value: {politician.get('_stateId')}")
                pass # suppress debug

        # FIX 2: Also check top level for _stateId (sometimes not nested)
        if not state:
            state = trade_data.get('_stateId') or trade_data.get('state')
            if state:
                state = str(state).strip().upper()[:2]
                # Validate it looks like a state code (2 letters)
                if not state or len(state) != 2 or not state.isalpha():
                    state = None
        
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
        
        # Extract company name (cleaned)
        issuer_name = trade_data.get('issuer', {}).get('issuerName', '').strip()
        # Clean company name
        if issuer_name:
            issuer_name = re.sub(r'\s*\([A-Z]+\)\s*', '', issuer_name).strip()
            # Remove "N/A" or "Unknown"
            if issuer_name.upper() in ['N/A', 'UNKNOWN', '']:
                issuer_name = None
        else:
            issuer_name = None
        
        # Extract price
        price = trade_data.get('price')
        if price is not None:
            try:
                price = float(price)
            except (ValueError, TypeError):
                price = None
        
        # Asset type defaults to Stock
        asset_type = 'Stock'
        
        # Extract tooltip/description for notes
        # Source may have various description fields
        tooltip = None
        for field in ['tooltip', 'description', 'txDescription', 'comment']:
            if field in trade_data and trade_data[field]:
                tooltip = str(trade_data[field]).strip()
                if tooltip:
                    break
        
        # Build notes from available context
        if tooltip:
            notes = tooltip
        else:
            notes = f"Imported from public records (scraped)"
        
        # Extract owner (Self, Spouse, Dependent, Joint, Undisclosed)
        owner = trade_data.get('owner') or trade_data.get('assetOwner') or trade_data.get('ownerType')
        if owner:
            owner = str(owner).strip().title()  # Capitalize properly: "Self", "Spouse", etc.
        else:
            owner = None
        
        # Try extracting owner from text fields if not found in JSON
        if not owner:
            # Check if there's a display/description field that might contain owner info
            display_text = (trade_data.get('display') or 
                           trade_data.get('description') or
                           trade_data.get('tooltip') or
                           trade_data.get('txDescription'))
            if display_text:
                owner = extract_owner_from_text(str(display_text))
            
            # Try from notes/tooltip fields
            if not owner:
                tooltip = trade_data.get('tooltip') or trade_data.get('comment')
                if tooltip:
                    owner = extract_owner_from_text(str(tooltip))
        
        # Extract representative (may differ from politician for spousal trades)
        representative = trade_data.get('representative') or trade_data.get('repName') or trade_data.get('representativeName')
        if representative:
            representative = str(representative).strip()
        else:
            representative = None
        
        # Try extracting representative from text fields if not found in JSON
        # Note: Representative might not always be visible in main table view
        if not representative:
            # Check display/description fields
            display_text = (trade_data.get('display') or 
                           trade_data.get('description') or
                           trade_data.get('tooltip'))
            if display_text:
                # Representative name might be in format like "John Smith (Spouse of Jane Smith)"
                # or "Representative: John Smith"
                rep_match = re.search(r'(?:representative|rep)[:\s]+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)', 
                                     str(display_text), re.IGNORECASE)
                if rep_match:
                    representative = rep_match.group(1).strip()
                # Also check for pattern like "(Spouse of ...)" or "Spouse: ..."
                spouse_match = re.search(r'(?:spouse\s+of|spouse:)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)', 
                                        str(display_text), re.IGNORECASE)
                if spouse_match:
                    representative = spouse_match.group(1).strip()
        
        # Build record for congress_trades table
        return {
            'ticker': ticker,
            'company_name': issuer_name,  # Added for securities table upsert
            'politician': politician_name,
            'chamber': chamber,
            'party': party,
            'state': state,
            'owner': owner,
            'transaction_date': tx_date.isoformat(),
            'disclosure_date': disclosure_date.isoformat(),
            'type': tx_type,
            'amount': amount,
            'price': price,
            'asset_type': asset_type,
            'conflict_score': None,
            'notes': notes
        }
    
    except Exception as e:
        logger.debug(f"Error mapping trade data: {e}, data: {trade_data}")
        return None


def seed_congress_trades_staging(months_back: Optional[int] = None, page_size: int = 100, max_pages: Optional[int] = None, start_page: int = 1, skip_recent: bool = False) -> str:
    """Main seeder function - scrapes historical data into STAGING table
    
    Returns:
        batch_id: UUID of the import batch
    """
    # Generate batch ID for this import
    batch_id = str(uuid.uuid4())
    
    print("=" * 70)
    print("CONGRESS TRADES HISTORY SEEDER (STAGING)")
    print("=" * 70)
    print(f"📦 Batch ID: {batch_id}")
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
    
    # Check for most recent trade in database (only if skip_recent is enabled)
    most_recent_trade_date = None
    if skip_recent:
        try:
            result = client.supabase.table("congress_trades_staging")\
                .select("transaction_date")\
                .order("transaction_date", desc=True)\
                .limit(1)\
                .execute()
            
            if result.data and result.data[0].get('transaction_date'):
                most_recent_trade_date = datetime.strptime(result.data[0]['transaction_date'], "%Y-%m-%d").date()
                print(f"📊 Found existing trades in database. Most recent: {most_recent_trade_date}")
                print(f"   ⚠️  SKIP RECENT MODE: Will skip trades on or after this date (importing older trades only).")
        except Exception as e:
            logger.debug(f"Could not check existing trades: {e}")
            print(f"   (Could not check existing trades - will import all)")
    else:
        print(f"📊 Processing all trades (existing records will be updated via upsert if they match)")
    
    # Calculate cutoff date (only if months_back is specified)
    cutoff_date = None
    if months_back is not None:
        cutoff_date = datetime.now() - timedelta(days=months_back * 30)
        print(f"📉 Starting Data Scrape (Target: Trades after {cutoff_date.date()})...")
    else:
        print(f"📉 Starting Data Scrape (No date limit - importing all available trades)...")
    print(f"   Using page size: {page_size}")
    if start_page > 1:
        print(f"   ⚠️  Starting from page {start_page}")
    if max_pages:
        print(f"   ⚠️  TEST MODE: Limited to {max_pages} pages")
    print()
    
    page = start_page
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
            skipped_details = []  # Track what we skip for logging
            oldest_on_page = None
            newest_on_page = None
            
            for trade in trades:
                try:
                    # Map to schema
                    mapped_record = map_trade_to_schema(trade)
                    if not mapped_record:
                        total_skipped += 1
                        # Log why it was skipped
                        politician_name = trade.get('politician', {})
                        if isinstance(politician_name, dict):
                            pol = f"{politician_name.get('firstName', '')} {politician_name.get('lastName', '')}".strip()
                        else:
                            pol = str(politician_name)
                        
                        issuer = trade.get('issuer', {})
                        ticker_raw = issuer.get('issuerTicker', '') or issuer.get('ticker', '')
                        company = issuer.get('issuerName', 'Unknown')
                        
                        skip_reason = "No ticker" if not ticker_raw else "Failed validation"
                        skipped_details.append({
                            'politician': pol or 'Unknown',
                            'company': company,
                            'ticker_raw': ticker_raw,
                            'reason': skip_reason,
                            'tx_date': trade.get('txDate', 'Unknown')
                        })
                        continue
                    
                    # Add staging-specific fields
                    mapped_record['import_batch_id'] = batch_id
                    mapped_record['raw_data'] = trade  # Store original for debugging
                    
                    # Check transaction date
                    tx_date = datetime.strptime(mapped_record['transaction_date'], "%Y-%m-%d").date()
                    if oldest_on_page is None or tx_date < oldest_on_page:
                        oldest_on_page = tx_date
                    if newest_on_page is None or tx_date > newest_on_page:
                        newest_on_page = tx_date
                    
                    # Skip if skip_recent is enabled and this trade is on or after the most recent trade
                    # This allows continuing where we left off when importing historical data
                    if skip_recent and most_recent_trade_date and tx_date >= most_recent_trade_date:
                        total_skipped += 1
                        continue
                    
                    # Add ALL records regardless of date (no cutoff filter)
                    page_records.append(mapped_record)
                
                except Exception as e:
                    total_errors += 1
                    logger.debug(f"Error processing trade: {e}")
                    continue
            
            # Deduplicate records within the batch by unique key
            # (politician, ticker, transaction_date, amount)
            seen_keys = set()
            unique_records = []
            securities_to_upsert = {}  # Map ticker -> company_name
            
            for record in page_records:
                key = (record['politician'], record['ticker'], record['transaction_date'], record['amount'])
                if key not in seen_keys:
                    seen_keys.add(key)
                    unique_records.append(record)
                    
                    # Collect company info for securities table
                    ticker = record['ticker']
                    company_name = record.get('company_name')
                    if company_name and ticker not in securities_to_upsert:
                        securities_to_upsert[ticker] = company_name

            page_records = unique_records
            
            # Upsert securities (Company Names)
            if securities_to_upsert:
                try:
                    securities_data = [
                        {'ticker': t, 'company_name': n} 
                        for t, n in securities_to_upsert.items()
                    ]
                    # We only want to update company_name if it's currently null? 
                    # Or just overwrite? Since we cleaned it, overwrite is probably fine 
                    # and keeps it up to date with official records.
                    # Supabase upsert requires specifying the on_conflict column
                    client.supabase.table("securities").upsert(
                        securities_data,
                        on_conflict="ticker"
                    ).execute()
                    print(f"   ✓ Updated {len(securities_data)} securities metadata")
                except Exception as e:
                    logger.warning(f"   ⚠️  Error updating securities metadata: {e}")

            # Remove company_name from records before inserting to congress_trades
            # as the table doesn't have that column
            for record in page_records:
                if 'company_name' in record:
                    del record['company_name']

            # Insert records in batch to STAGING table
            if page_records:
                try:
                    result = client.supabase.table("congress_trades_staging")\
                        .insert(page_records)\
                        .execute()
                    
                    page_added = len(page_records)
                    total_added += page_added
                    
                    date_range = f"(Oldest: {oldest_on_page}"
                    if newest_on_page and newest_on_page != oldest_on_page:
                        date_range += f", Newest: {newest_on_page}"
                    date_range += ")"
                    print(f"   ✅ Saved {page_added} trades. {date_range}")
                    
                except Exception as e:
                    total_errors += len(page_records)
                    print(f"   ⚠️  Error inserting batch: {e}")
            else:
                # No new records on this page - might be all duplicates
                if newest_on_page and most_recent_trade_date and newest_on_page >= most_recent_trade_date:
                    print(f"   ⏭️  Page {page}: All trades already imported (newest: {newest_on_page} >= {most_recent_trade_date})")
            
            # Check if we should stop (reached cutoff date, if specified)
            if cutoff_date and oldest_on_page and oldest_on_page < cutoff_date.date():
                print(f"🛑 Reached cutoff date ({oldest_on_page}). Stopping.")
                break
            
            # Note: We don't stop when we reach older trades - we want to import historical data
            # The script will continue until it reaches the end of available data
            
            # Check if we've reached max pages (for testing)
            if max_pages and page >= max_pages:
                print(f"🛑 Reached max pages limit ({max_pages}). Stopping.")
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
    print("\n" + "=" * 70)
    print("✅ IMPORT TO STAGING COMPLETE")
    print("=" * 70)
    print(f"   Batch ID: {batch_id}")
    print(f"   Total Added To Staging: {total_added}")
    print(f"   Total Skipped (no ticker): {total_skipped}")
    if total_errors > 0:
        print(f"   Total Errors: {total_errors}")
    print()
    print(f"   Next steps:")
    print(f"   1. Review data in staging table")
    print(f"   2. Run validation: python validate_congress_staging.py --batch-id {batch_id}")
    print(f"   3. Promote to production: python promote_congress_trades.py --batch-id {batch_id}")
    print()
    
    return batch_id


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Import historical congressional trades')
    parser.add_argument(
        '--months-back',
        type=int,
        default=None,
        help='Number of months back to import (default: None = import all available trades)'
    )
    parser.add_argument(
        '--page-size',
        type=int,
        default=100,
        help='Number of trades per page (default: 100, max recommended: 200)'
    )
    parser.add_argument(
        '--max-pages',
        type=int,
        default=None,
        help='Maximum number of pages to process (for testing, default: unlimited)'
    )
    parser.add_argument(
        '--start-page',
        type=int,
        default=1,
        help='Page number to start from (default: 1)'
    )
    parser.add_argument(
        '--skip-recent',
        action='store_true',
        help='Skip trades on or after the most recent trade date (useful for continuing historical import where you left off)'
    )
    
    args = parser.parse_args()
    batch_id = seed_congress_trades_staging(months_back=args.months_back, page_size=args.page_size, max_pages=args.max_pages, start_page=args.start_page, skip_recent=args.skip_recent)
    print(f"\nBatch ID: {batch_id}")
