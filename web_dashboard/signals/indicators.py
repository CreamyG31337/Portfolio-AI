"""
Core Technical Indicator Calculations

Provides functions for calculating common technical indicators:
- RSI (Relative Strength Index)
- CCI (Commodity Channel Index)
- Moving Averages
- Volatility (standard deviation of returns)
"""

import pandas as pd
import numpy as np
from typing import Optional
import logging

logger = logging.getLogger(__name__)


def calculate_rsi(df: pd.DataFrame, price_col: str = 'Close', period: int = 14) -> pd.Series:
    """
    Calculate Relative Strength Index (RSI).
    
    Args:
        df: DataFrame with price data
        price_col: Column name for price (default 'Close')
        period: Period for RSI calculation (default 14)
    
    Returns:
        Series with RSI values
    """
    try:
        if price_col not in df.columns:
            logger.warning(f"Column {price_col} not found in DataFrame")
            return pd.Series(dtype=float)
        
        delta = df[price_col].diff()
        gain = delta.where(delta > 0, 0)
        loss = -delta.where(delta < 0, 0)
        
        avg_gain = gain.rolling(window=period).mean()
        avg_loss = loss.rolling(window=period).mean()
        
        # Avoid division by zero
        rs = avg_gain / avg_loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))
        
        return rsi
    except Exception as e:
        logger.error(f"Error calculating RSI: {e}", exc_info=True)
        return pd.Series(dtype=float)


def calculate_cci(
    df: pd.DataFrame,
    high_col: str = 'High',
    low_col: str = 'Low',
    close_col: str = 'Close',
    period: int = 20
) -> pd.Series:
    """
    Calculate Commodity Channel Index (CCI).
    
    Args:
        df: DataFrame with OHLC data
        high_col: Column name for high prices (default 'High')
        low_col: Column name for low prices (default 'Low')
        close_col: Column name for close prices (default 'Close')
        period: Period for CCI calculation (default 20)
    
    Returns:
        Series with CCI values
    """
    try:
        required_cols = [high_col, low_col, close_col]
        missing_cols = [col for col in required_cols if col not in df.columns]
        if missing_cols:
            logger.warning(f"Columns {missing_cols} not found in DataFrame")
            return pd.Series(dtype=float)
        
        # Typical Price
        tp = (df[high_col] + df[low_col] + df[close_col]) / 3
        
        # Simple Moving Average of TP
        tp_sma = tp.rolling(window=period).mean()
        
        # Mean Deviation
        mean_dev = tp.rolling(window=period).apply(
            lambda x: np.mean(np.abs(x - x.mean())),
            raw=True
        )
        
        # CCI calculation
        cci = (tp - tp_sma) / (0.015 * mean_dev.replace(0, np.nan))
        
        return cci
    except Exception as e:
        logger.error(f"Error calculating CCI: {e}", exc_info=True)
        return pd.Series(dtype=float)


def calculate_ma(df: pd.DataFrame, price_col: str = 'Close', period: int = 20) -> pd.Series:
    """
    Calculate Moving Average.
    
    Args:
        df: DataFrame with price data
        price_col: Column name for price (default 'Close')
        period: Period for moving average (default 20)
    
    Returns:
        Series with moving average values
    """
    try:
        if price_col not in df.columns:
            logger.warning(f"Column {price_col} not found in DataFrame")
            return pd.Series(dtype=float)
        
        return df[price_col].rolling(window=period).mean()
    except Exception as e:
        logger.error(f"Error calculating MA: {e}", exc_info=True)
        return pd.Series(dtype=float)


def calculate_volatility(df: pd.DataFrame, price_col: str = 'Close', period: int = 20) -> pd.Series:
    """
    Calculate volatility as standard deviation of returns.
    
    Args:
        df: DataFrame with price data
        price_col: Column name for price (default 'Close')
        period: Period for volatility calculation (default 20)
    
    Returns:
        Series with volatility values (as standard deviation of returns)
    """
    try:
        if price_col not in df.columns:
            logger.warning(f"Column {price_col} not found in DataFrame")
            return pd.Series(dtype=float)
        
        # Calculate returns
        returns = df[price_col].pct_change()
        
        # Calculate rolling standard deviation of returns
        volatility = returns.rolling(window=period).std()
        
        return volatility
    except Exception as e:
        logger.error(f"Error calculating volatility: {e}", exc_info=True)
        return pd.Series(dtype=float)
