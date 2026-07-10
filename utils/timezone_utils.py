"""Timezone utilities for the trading system.

This module provides timezone handling functions for CSV parsing, timestamp formatting,
and market time calculations. It supports both current CSV-based storage and future
database timestamp requirements.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional, Union
import pandas as pd


def get_trading_timezone() -> timezone:
    """Get the configured trading timezone object.
    
    Returns:
        timezone: The configured trading timezone
    """
    try:
        from market_config import get_timezone_offset
        offset_hours = get_timezone_offset()
    except ImportError:
        # Fallback to settings if market_config is not available
        try:
            from config.settings import Settings
            settings = Settings()
            offset_hours = settings.get('timezone.offset_hours', -8)
        except:
            # Final fallback to PST if all else fails
            offset_hours = -8
    
    return timezone(timedelta(hours=offset_hours))


def get_timezone_name() -> str:
    """Get the configured timezone name.
    
    Returns:
        str: The timezone name (e.g., 'PST', 'PDT')
    """
    try:
        from market_config import get_timezone_name
        return get_timezone_name()
    except ImportError:
        # Fallback to PST if market_config is not available
        return "PST"


def get_current_trading_time() -> datetime:
    """Get current time in the configured trading timezone.
    
    Returns:
        datetime: Current time in trading timezone
    """
    tz = get_trading_timezone()
    return datetime.now(tz)


def get_market_open_time(date: Optional[Union[str, datetime]] = None) -> datetime:
    """Get market open time (6:30 AM) in the configured timezone for the given date.
    
    Args:
        date: The date to get market open time for. If None, uses current date.
              Can be a string in 'YYYY-MM-DD' format or datetime object.
    
    Returns:
        datetime: Market open time for the specified date
    """
    tz = get_trading_timezone()
    if date is None:
        date = datetime.now(tz).date()
    elif isinstance(date, str):
        date = datetime.strptime(date, "%Y-%m-%d").date()
    elif isinstance(date, datetime):
        date = date.date()
    
    market_open_time = datetime.combine(date, datetime.min.time().replace(hour=6, minute=30), tz)
    return market_open_time


def is_market_open() -> bool:
    """Check if the market is currently open.
    
    Market hours: 6:30 AM to 1:00 PM PST (9:30 AM to 4:00 PM EST)
    Only open on weekdays (Monday-Friday).
    
    Returns:
        bool: True if market is open, False if closed
    """
    tz = get_trading_timezone()
    now = datetime.now(tz)
    
    # Check if it's a weekday (Monday = 0, Friday = 4)
    if now.weekday() >= 5:  # Saturday or Sunday
        return False
    
    # Market hours: 6:30 AM to 1:00 PM PST (9:30 AM to 4:00 PM EST)
    market_open = now.replace(hour=6, minute=30, second=0, microsecond=0)
    market_close = now.replace(hour=13, minute=0, second=0, microsecond=0)
    
    return market_open <= now <= market_close


def format_timestamp_for_csv(dt: Optional[datetime] = None) -> str:
    """Format timestamps for CSV storage with user-readable timezone names.

    CRITICAL FUNCTION: This function MUST use PST/PDT for CSV files to maintain user readability.
    The parse_csv_timestamp() function depends on this format for proper timezone conversion.
    Changing this to UTC offsets will break CSV parsing and cause pandas FutureWarnings!

    NEVER change this to use UTC offsets like "-07:00" - keep PST/PDT for CSV display!
    The parsing function handles the conversion to pandas-compatible formats internally.

    Args:
        dt: The datetime to format. If None, uses current trading time.

    Returns:
        str: Formatted timestamp string for CSV storage
    """
    if dt is None:
        dt = get_current_trading_time()

    # Determine the appropriate timezone name based on the date
    # This ensures historical dates use the correct timezone for that time period
    try:
        from market_config import _is_dst
        tz_name = "PDT" if _is_dst(dt) else "PST"
    except ImportError:
        # Fallback if market_config is not available
        tz_name = "PST"

    return dt.strftime(f"%Y-%m-%d %H:%M:%S {tz_name}")


def parse_csv_timestamp(timestamp_str: Union[str, pd.Timestamp]) -> Optional[pd.Timestamp]:
    """Parse timestamps from CSV files with comprehensive timezone handling.

    CRITICAL FUNCTION: This function is CRITICAL for avoiding pandas FutureWarnings!
    It converts common timezone abbreviations from CSV files into pandas-compatible
    UTC offset formats before parsing.

    SUPPORTED TIMEZONE CONVERSIONS:
    - PST (Pacific Standard Time): UTC-8 → "-08:00"
    - PDT (Pacific Daylight Time): UTC-7 → "-07:00"
    - MST (Mountain Standard Time): UTC-7 → "-07:00"
    - MDT (Mountain Daylight Time): UTC-6 → "-06:00"
    - CST (Central Standard Time): UTC-6 → "-06:00"
    - CDT (Central Daylight Time): UTC-5 → "-05:00"
    - EST (Eastern Standard Time): UTC-5 → "-05:00"
    - EDT (Eastern Daylight Time): UTC-4 → "-04:00"
    - UTC/GMT: Already pandas-compatible

    WORKFLOW:
    1. CSV files store: "2025-09-10 06:30:00 EST" (user-readable)
    2. This function converts to: "2025-09-10 06:30:00-05:00" (pandas-compatible)
    3. Pandas parses without warnings

    NEVER remove or modify this conversion logic! Timezone abbreviations in CSVs will always
    cause pandas FutureWarnings if not converted to UTC offsets first.
    
    Args:
        timestamp_str: The timestamp string to parse
    
    Returns:
        pd.Timestamp: Parsed timestamp with timezone information, or None if invalid
    """
    if pd.isna(timestamp_str):
        return None

    timestamp_str = str(timestamp_str).strip()

    # CRITICAL: Handle common timezone abbreviations to prevent pandas FutureWarnings
    # Each timezone gets converted to its pandas-compatible UTC offset format

    # Pacific Time (West Coast)
    if " PST" in timestamp_str:
        clean_timestamp = timestamp_str.replace(" PST", "")
        timestamp_with_offset = f"{clean_timestamp}-08:00"
        return pd.to_datetime(timestamp_with_offset)
    elif " PDT" in timestamp_str:
        clean_timestamp = timestamp_str.replace(" PDT", "")
        timestamp_with_offset = f"{clean_timestamp}-07:00"
        return pd.to_datetime(timestamp_with_offset)

    # Mountain Time (Rockies)
    elif " MST" in timestamp_str:
        clean_timestamp = timestamp_str.replace(" MST", "")
        timestamp_with_offset = f"{clean_timestamp}-07:00"
        return pd.to_datetime(timestamp_with_offset)
    elif " MDT" in timestamp_str:
        clean_timestamp = timestamp_str.replace(" MDT", "")
        timestamp_with_offset = f"{clean_timestamp}-06:00"
        return pd.to_datetime(timestamp_with_offset)

    # Central Time (Midwest)
    elif " CST" in timestamp_str:
        clean_timestamp = timestamp_str.replace(" CST", "")
        timestamp_with_offset = f"{clean_timestamp}-06:00"
        return pd.to_datetime(timestamp_with_offset)
    elif " CDT" in timestamp_str:
        clean_timestamp = timestamp_str.replace(" CDT", "")
        timestamp_with_offset = f"{clean_timestamp}-05:00"
        return pd.to_datetime(timestamp_with_offset)

    # Eastern Time (East Coast)
    elif " EST" in timestamp_str:
        clean_timestamp = timestamp_str.replace(" EST", "")
        timestamp_with_offset = f"{clean_timestamp}-05:00"
        return pd.to_datetime(timestamp_with_offset)
    elif " EDT" in timestamp_str:
        clean_timestamp = timestamp_str.replace(" EDT", "")
        timestamp_with_offset = f"{clean_timestamp}-04:00"
        return pd.to_datetime(timestamp_with_offset)

    # Already pandas-compatible formats
    elif " UTC" in timestamp_str or " GMT" in timestamp_str:
        return pd.to_datetime(timestamp_str)

    # UTC offset format already present (e.g., "2025-09-10 06:30:00-05:00")
    elif ("+" in timestamp_str or ("-" in timestamp_str and timestamp_str[-6:-3].isdigit())):
        # Handle already timezone-aware timestamps
        try:
            return pd.to_datetime(timestamp_str)
        except Exception:
            # If it fails, try without timezone conversion
            dt = pd.to_datetime(timestamp_str, utc=True)
            return dt

    else:
        # No timezone info, assume it's in the configured timezone
        tz = get_trading_timezone()
        dt = pd.to_datetime(timestamp_str)
        # Localize to the configured timezone
        return dt.tz_localize(tz)


def safe_parse_datetime_column(series_or_str: Union[str, pd.Series], column_name: str = "datetime") -> Union[pd.Timestamp, pd.Series]:
    """Safely parse datetime columns that may contain timezone information.
    
    Handles PST timezone strings and other common formats.
    
    Args:
        series_or_str: Either a single string or pandas Series to parse
        column_name: Name of the column being parsed (for error reporting)
    
    Returns:
        Union[pd.Timestamp, pd.Series]: Parsed datetime(s)
    """
    if isinstance(series_or_str, str):
        # Single string - use existing timezone-aware function
        return parse_csv_timestamp(series_or_str)
    elif hasattr(series_or_str, 'apply'):
        # Pandas Series - apply timezone-aware parsing to each element
        return series_or_str.apply(lambda x: parse_csv_timestamp(x) if pd.notna(x) else x)
    else:
        # Fallback for other types
        return pd.to_datetime(series_or_str)


def get_market_close_time_local() -> int:
    """Get market close hour in user's local timezone.
    
    Market closes at 4:00 PM EST, which varies by user timezone:
    - EST user: 4:00 PM local
    - PST user: 1:00 PM local  
    - MST user: 2:00 PM local
    - CST user: 3:00 PM local
    
    Returns:
        int: Market close hour in user's local timezone
    """
    try:
        from market_config import get_timezone_offset
        user_offset = get_timezone_offset()  # e.g., -8 for PST
    except ImportError:
        # Fallback to settings if market_config is not available
        try:
            from config.settings import Settings
            settings = Settings()
            user_offset = settings.get('timezone.user_display.offset_hours', -8)
        except:
            # Final fallback to PST if all else fails
            user_offset = -8
    
    market_offset = -5  # EST is UTC-5 (standard time)
    # Market closes at 16:00 EST
    # Convert to user's timezone
    return 16 + (user_offset - market_offset)
    # For PST: 16 + (-8 - (-5)) = 16 + (-3) = 13 (1 PM PST)


def get_timezone_config() -> dict:
    """Get timezone configuration for database storage.
    
    This function provides timezone configuration that can be used for
    future database timestamp storage while maintaining compatibility
    with current CSV-based storage.
    
    Returns:
        dict: Timezone configuration with name, offset_hours, and utc_offset
    """
    try:
        from market_config import get_timezone_config as get_config
        return get_config()
    except ImportError:
        # Fallback configuration
        return {
            "name": "PST",
            "offset_hours": -8,
            "utc_offset": "-08:00"
        }


def convert_to_database_timestamp(dt: datetime) -> datetime:
    """Convert a datetime to UTC for database storage.
    
    This function prepares timestamps for future database storage by
    converting them to UTC while preserving the original timezone information.
    
    Args:
        dt: The datetime to convert
    
    Returns:
        datetime: UTC datetime for database storage
    """
    if dt.tzinfo is None:
        # Assume it's in trading timezone if no timezone info
        tz = get_trading_timezone()
        dt = dt.replace(tzinfo=tz)
    
    return dt.astimezone(timezone.utc)


def convert_from_database_timestamp(dt: datetime) -> datetime:
    """Convert a UTC datetime from database to trading timezone.
    
    This function converts UTC timestamps from database storage back to
    the configured trading timezone for display and calculations.
    
    Args:
        dt: The UTC datetime from database
    
    Returns:
        datetime: Datetime in trading timezone
    """
    if dt.tzinfo is None:
        # Assume it's UTC if no timezone info
        dt = dt.replace(tzinfo=timezone.utc)
    
    tz = get_trading_timezone()
    return dt.astimezone(tz)


def format_timestamp_for_display(dt: Optional[datetime] = None) -> str:
    """Format timestamps for display with timezone information.
    
    Args:
        dt: The datetime to format. If None, uses current trading time.
    
    Returns:
        str: Formatted timestamp string for display
    """
    if dt is None:
        dt = get_current_trading_time()
    
    # Get timezone name for display
    tz_name = get_timezone_name()
    
    return dt.strftime(f"%Y-%m-%d %H:%M:%S {tz_name}")