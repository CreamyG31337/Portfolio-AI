#!/usr/bin/env python3
"""
Exchange Rates Utilities for Web Dashboard
==========================================

Helper functions for loading and managing exchange rates from Supabase database.
Provides backward compatibility with utils.currency_converter functions.
"""

import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Dict, Optional, List
from decimal import Decimal
import logging

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from web_dashboard.supabase_client import SupabaseClient

logger = logging.getLogger(__name__)


def get_supabase_client(use_service_role: bool = False) -> Optional[SupabaseClient]:
    """Get Supabase client instance.
    
    Args:
        use_service_role: If True, use service role key (bypasses RLS)
        
    Returns:
        SupabaseClient instance or None if initialization fails
    """
    try:
        return SupabaseClient(use_service_role=use_service_role)
    except Exception as e:
        logger.error(f"Failed to initialize Supabase client: {e}")
        return None


def load_exchange_rates_from_db(
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    from_currency: str = 'USD',
    to_currency: str = 'CAD'
) -> Dict[str, Decimal]:
    """Load exchange rates from Supabase database.
    
    Returns a dictionary compatible with utils.currency_converter format:
    { 'YYYY-MM-DD': Decimal(rate), ... }
    
    Args:
        start_date: Optional start date for date range (default: None = all)
        end_date: Optional end date for date range (default: None = all)
        from_currency: Source currency (default: 'USD')
        to_currency: Target currency (default: 'CAD')
        
    Returns:
        Dictionary mapping date strings (YYYY-MM-DD) to Decimal exchange rates
    """
    client = get_supabase_client()
    if not client:
        logger.warning("Could not initialize Supabase client, returning empty rates")
        return {}
    
    try:
        # If no date range specified, get all rates
        if start_date is None and end_date is None:
            # Get rates from last 5 years to present (reasonable default)
            end_date = datetime.now(timezone.utc)
            start_date = end_date - timedelta(days=5 * 365)
        elif start_date is None:
            # Get all rates up to end_date
            start_date = datetime(2020, 1, 1, tzinfo=timezone.utc)  # Reasonable default
        elif end_date is None:
            # Get all rates from start_date to present
            end_date = datetime.now(timezone.utc)
        
        # Ensure dates are timezone-aware
        if start_date.tzinfo is None:
            start_date = start_date.replace(tzinfo=timezone.utc)
        if end_date.tzinfo is None:
            end_date = end_date.replace(tzinfo=timezone.utc)
        
        # Query database
        rates_data = client.get_exchange_rates(start_date, end_date, from_currency, to_currency)
        
        # Convert to dictionary format compatible with currency_converter
        exchange_rates = {}
        for rate_entry in rates_data:
            timestamp_str = rate_entry.get('timestamp')
            rate_value = rate_entry.get('rate')
            
            if timestamp_str and rate_value is not None:
                # Parse timestamp and extract date
                try:
                    if isinstance(timestamp_str, str):
                        dt = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                    else:
                        dt = timestamp_str
                    
                    # Convert to date string (YYYY-MM-DD)
                    date_key = dt.date().strftime('%Y-%m-%d')
                    exchange_rates[date_key] = Decimal(str(rate_value))
                except Exception as e:
                    logger.warning(f"Could not parse rate entry: {e}")
                    continue
        
        logger.info(f"Loaded {len(exchange_rates)} exchange rates from database")
        return exchange_rates
        
    except Exception as e:
        logger.error(f"Error loading exchange rates from database: {e}")
        return {}


def reload_exchange_rate_for_date(
    date: datetime,
    from_currency: str = 'USD',
    to_currency: str = 'CAD',
    use_service_role: bool = True
) -> Optional[Decimal]:
    """Fetch and update exchange rate for a specific date using API.
    
    Args:
        date: Date to fetch rate for
        from_currency: Source currency (default: 'USD')
        to_currency: Target currency (default: 'CAD')
        use_service_role: Use service role for database write (default: True)
        
    Returns:
        Exchange rate as Decimal if successful, None otherwise
    """
    try:
        import requests
        
        # Fetch live rate from API
        rate = None
        
        # Try Bank of Canada API first (most accurate for CAD rates)
        if from_currency == 'USD' and to_currency == 'CAD':
            try:
                # Format date for BoC Valet API (YYYY-MM-DD)
                date_str = date.strftime('%Y-%m-%d')
                url = f"https://www.bankofcanada.ca/valet/observations/FXUSDCAD/json?start_date={date_str}&end_date={date_str}"
                response = requests.get(url, timeout=5)
                
                if response.status_code == 200:
                    data = response.json()
                    if 'observations' in data and data['observations']:
                        # Get the specific observation for this date
                        obs = data['observations'][0]
                        if 'FXUSDCAD' in obs and 'v' in obs['FXUSDCAD']:
                            rate = float(obs['FXUSDCAD']['v'])
                            logger.debug(f"Using Bank of Canada historical rate for {date_str}: {rate}")
                elif response.status_code == 404:
                    # If date not found (e.g., weekend or holiday), BoC returns 404
                    # This is expected for some dates
                    pass
            except Exception as e:
                logger.debug(f"Bank of Canada API failed for {date.date()}: {e}")
        
        # Fallback to exchangerate-api.com
        if rate is None:
            url = f"https://api.exchangerate-api.com/v4/latest/{from_currency}"
            response = requests.get(url, timeout=5)
            
            if response.status_code == 200:
                data = response.json()
                rate = data['rates'].get(to_currency)
                if rate:
                    logger.debug(f"Using exchangerate-api.com rate: {rate}")
        
        if rate is None:
            logger.warning("Could not fetch live exchange rate from API")
            return None
        
        # Save to database
        client = get_supabase_client(use_service_role=use_service_role)
        if not client:
            logger.error("Could not initialize Supabase client for saving rate")
            return None
        
        # Ensure date is timezone-aware
        if date.tzinfo is None:
            date = date.replace(tzinfo=timezone.utc)
        
        success = client.upsert_exchange_rate(date, Decimal(str(rate)), from_currency, to_currency)
        
        if success:
            logger.info(f"✅ Reloaded exchange rate for {date.date()}: {rate}")
            return Decimal(str(rate))
        else:
            logger.error(f"Failed to save exchange rate to database")
            return None
            
    except ImportError:
        logger.error("requests library not available for fetching exchange rates")
        return None
    except Exception as e:
        logger.error(f"Error reloading exchange rate: {e}")
        return None


def reload_exchange_rates_for_range(
    start_date: datetime,
    end_date: datetime,
    from_currency: str = 'USD',
    to_currency: str = 'CAD',
    use_service_role: bool = True
) -> int:
    """Fetch and update exchange rates for a date range using actual historical data.
    
    Args:
        start_date: Start date (inclusive)
        end_date: End date (inclusive)
        from_currency: Source currency (default: 'USD')
        to_currency: Target currency (default: 'CAD')
        use_service_role: Use service role for database write (default: True)
        
    Returns:
        Number of rates successfully updated
    """
    try:
        import requests
        
        # BoC Valet API handles ranges
        if from_currency == 'USD' and to_currency == 'CAD':
            client = get_supabase_client(use_service_role=use_service_role)
            if not client:
                return 0
                
            start_str = start_date.strftime('%Y-%m-%d')
            end_str = end_date.strftime('%Y-%m-%d')
            url = f"https://www.bankofcanada.ca/valet/observations/FXUSDCAD/json?start_date={start_str}&end_date={end_str}"
            
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if 'observations' in data and data['observations']:
                    rates_to_upsert = []
                    for obs in data['observations']:
                        if 'FXUSDCAD' in obs and 'v' in obs['FXUSDCAD']:
                            obs_date = obs['d']
                            rate = float(obs['FXUSDCAD']['v'])
                            
                            # Create timezone-aware datetime for the observation
                            dt = datetime.strptime(obs_date, '%Y-%m-%d').replace(tzinfo=timezone.utc)
                            
                            rates_to_upsert.append({
                                'timestamp': dt.isoformat(),
                                'rate': rate,
                                'from_currency': from_currency,
                                'to_currency': to_currency
                            })
                    
                    if rates_to_upsert:
                        if client.upsert_exchange_rates(rates_to_upsert):
                            logger.info(f"✅ Reloaded {len(rates_to_upsert)} actual historical rates from Bank of Canada")
                            return len(rates_to_upsert)
            
        # Fallback to daily fetch for each date if BoC range fails or for other currencies
        logger.info(f"Falling back to daily fetch for range {start_date.date()} to {end_date.date()}")
        current = start_date
        count = 0
        while current <= end_date:
            rate = reload_exchange_rate_for_date(current, from_currency, to_currency, use_service_role)
            if rate:
                count += 1
            current += timedelta(days=1)
        
        return count
        
    except Exception as e:
        logger.error(f"Error reloading exchange rates for range: {e}")
        return 0


def sync_exchange_rates_from_csv(csv_path: Path, use_service_role: bool = True) -> bool:
    """Sync exchange rates from CSV file to database.
    
    This is a convenience wrapper around the migration script functionality.
    
    Args:
        csv_path: Path to exchange_rates.csv file
        use_service_role: Use service role for database write (default: True)
        
    Returns:
        True if successful, False otherwise
    """
    try:
        import pandas as pd
        import pytz
        
        if not csv_path.exists():
            logger.error(f"CSV file not found: {csv_path}")
            return False
        
        # Load CSV
        df = pd.read_csv(csv_path)
        
        if 'Date' not in df.columns or 'USD_CAD_Rate' not in df.columns:
            logger.error("Invalid CSV format. Expected columns: Date, USD_CAD_Rate")
            return False
        
        # Parse dates (similar to migration script)
        def parse_date(date_str: str) -> Optional[datetime]:
            try:
                date_str = str(date_str).strip()
                if " PDT" in date_str:
                    clean_timestamp = date_str.replace(" PDT", "")
                    dt = datetime.strptime(clean_timestamp, "%Y-%m-%d %H:%M:%S")
                    tz = pytz.timezone('America/Los_Angeles')
                    dt = tz.localize(dt)
                elif " PST" in date_str:
                    clean_timestamp = date_str.replace(" PST", "")
                    dt = datetime.strptime(clean_timestamp, "%Y-%m-%d %H:%M:%S")
                    tz = pytz.timezone('America/Los_Angeles')
                    dt = tz.localize(dt)
                else:
                    dt = pd.to_datetime(date_str)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                
                if dt.tzinfo is not None:
                    dt = dt.astimezone(timezone.utc)
                else:
                    dt = dt.replace(tzinfo=timezone.utc)
                
                return dt
            except Exception as e:
                logger.warning(f"Could not parse date '{date_str}': {e}")
                return None
        
        df['parsed_date'] = df['Date'].apply(parse_date)
        df = df[df['parsed_date'].notna()]
        df['rate_decimal'] = df['USD_CAD_Rate'].apply(
            lambda x: Decimal(str(x)) if pd.notna(x) else None
        )
        df = df[df['rate_decimal'].notna()]
        
        # Prepare for upsert
        client = get_supabase_client(use_service_role=use_service_role)
        if not client:
            return False
        
        rates = []
        # to_dict("records") keeps the object-dtype columns intact, so parsed_date
        # stays a datetime/Timestamp and rate_decimal stays a Decimal (no float coercion).
        for record in df.to_dict('records'):
            rates.append({
                'timestamp': record['parsed_date'].isoformat(),
                'rate': float(record['rate_decimal']),
                'from_currency': 'USD',
                'to_currency': 'CAD'
            })
        
        # Bulk upsert
        success = client.upsert_exchange_rates(rates)
        
        if success:
            logger.info(f"✅ Synced {len(rates)} exchange rates from CSV to database")
        else:
            logger.error("Failed to sync exchange rates to database")
        
        return success
        
    except Exception as e:
        logger.error(f"Error syncing exchange rates from CSV: {e}")
        return False


def get_exchange_rate_for_date_from_db(
    target_date: Optional[datetime] = None,
    from_currency: str = 'USD',
    to_currency: str = 'CAD'
) -> Decimal:
    """Get exchange rate for a specific date from database.
    
    Compatible with utils.currency_converter.get_exchange_rate_for_date()
    
    Args:
        target_date: Target date (uses latest if None)
        from_currency: Source currency (default: 'USD')
        to_currency: Target currency (default: 'CAD')
        
    Returns:
        Exchange rate as Decimal
    """
    client = get_supabase_client()
    if not client:
        logger.warning("Could not initialize Supabase client, using default rate")
        return Decimal('1.35')
    
    if target_date is None:
        rate = client.get_latest_exchange_rate(from_currency, to_currency)
    else:
        rate = client.get_exchange_rate(target_date, from_currency, to_currency)
    
    if rate is None:
        logger.warning(f"No exchange rate found, using default: 1.35")
        return Decimal('1.35')
    
    return rate

