"""
Structure Signal Analysis

Analyzes trend structure using moving averages, pullbacks, and breakouts.
Inspired by InvestAI but adapted to our data structures.
"""

import pandas as pd
from typing import Dict, Any
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class TrendType(Enum):
    """Trend classification"""
    UPTREND = "UPTREND"
    NEUTRAL = "NEUTRAL"
    DOWNTREND = "DOWNTREND"


class StructureSignal:
    """
    Analyzes price structure for trend, pullbacks, and breakouts.
    """
    
    def __init__(
        self,
        ma_short_period: int = 20,
        ma_long_period: int = 60,
        pullback_threshold: float = 0.03,
        pullback_enabled: bool = True,
        breakout_window: int = 20,
        breakout_buffer: float = 0.005
    ):
        """
        Initialize StructureSignal.
        
        Args:
            ma_short_period: Short moving average period (default 20)
            ma_long_period: Long moving average period (default 60)
            pullback_threshold: Maximum pullback percentage (default 0.03 = 3%)
            pullback_enabled: Whether to detect pullbacks (default True)
            breakout_window: Window for resistance calculation (default 20)
            breakout_buffer: Buffer for breakout confirmation (default 0.005 = 0.5%)
        """
        self.ma_short_period = ma_short_period
        self.ma_long_period = ma_long_period
        self.pullback_threshold = pullback_threshold
        self.pullback_enabled = pullback_enabled
        self.breakout_window = breakout_window
        self.breakout_buffer = breakout_buffer
    
    def evaluate(self, df: pd.DataFrame, price_col: str = 'Close') -> Dict[str, Any]:
        """
        Evaluate structure signal for given price data.
        
        Args:
            df: DataFrame with price data (must have Close column)
            price_col: Column name for price (default 'Close')
        
        Returns:
            Dictionary with structure signal data:
            {
                'price': float,
                'ma_short': float,
                'ma_long': float,
                'trend': TrendType,
                'pullback': bool,
                'breakout': bool
            }
        """
        try:
            if df.empty or len(df) < self.ma_long_period:
                logger.warning(f"Insufficient data for structure signal (need at least {self.ma_long_period} periods)")
                return {
                    'price': 0.0,
                    'ma_short': 0.0,
                    'ma_long': 0.0,
                    'trend': TrendType.NEUTRAL.value,
                    'pullback': False,
                    'breakout': False,
                    'error': 'Insufficient data'
                }
            
            if price_col not in df.columns:
                logger.warning(f"Column {price_col} not found in DataFrame")
                return {
                    'price': 0.0,
                    'ma_short': 0.0,
                    'ma_long': 0.0,
                    'trend': TrendType.NEUTRAL.value,
                    'pullback': False,
                    'breakout': False,
                    'error': 'Missing price column'
                }
            
            # Calculate moving averages
            df = df.copy()
            df['ma_short'] = df[price_col].rolling(window=self.ma_short_period).mean()
            df['ma_long'] = df[price_col].rolling(window=self.ma_long_period).mean()
            
            # Get current values
            price = float(df[price_col].iloc[-1])
            prev_price = float(df[price_col].iloc[-2]) if len(df) > 1 else price
            ma_short_val = float(df['ma_short'].iloc[-1])
            ma_long_val = float(df['ma_long'].iloc[-1])
            
            # Determine trend
            if price > ma_short_val > ma_long_val:
                trend = TrendType.UPTREND
            elif price > ma_long_val:
                trend = TrendType.NEUTRAL
            else:
                trend = TrendType.DOWNTREND
            
            # Detect pullback (price < MA20 but > MA60, within threshold)
            pullback = False
            if self.pullback_enabled:
                pullback = (
                    price < ma_short_val
                    and price > ma_long_val
                    and (ma_short_val - price) / ma_short_val <= self.pullback_threshold
                )
            
            # Detect breakout (price breaks prior resistance with buffer)
            prior_prices = df[price_col].iloc[:-1]
            if len(prior_prices) < self.breakout_window:
                resistance = float(prior_prices.max()) if len(prior_prices) else price
                breakout = False
            else:
                resistance = float(prior_prices.iloc[-self.breakout_window:].max())
                breakout = (
                    prev_price <= resistance
                    and price > resistance * (1 + self.breakout_buffer)
                )
            
            return {
                'price': round(price, 2),
                'ma_short': round(ma_short_val, 2),
                'ma_long': round(ma_long_val, 2),
                'trend': trend.value,
                'pullback': bool(pullback),
                'breakout': bool(breakout)
            }
        
        except Exception as e:
            logger.error(f"Error evaluating structure signal: {e}", exc_info=True)
            return {
                'price': 0.0,
                'ma_short': 0.0,
                'ma_long': 0.0,
                'trend': TrendType.NEUTRAL.value,
                'pullback': False,
                'breakout': False,
                'error': str(e)
            }
