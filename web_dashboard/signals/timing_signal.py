"""
Timing Signal Analysis

Analyzes volume and momentum timing signals using RSI, CCI, and volume analysis.
Inspired by InvestAI but adapted to our data structures.
"""

import pandas as pd
from typing import Dict, Any
import logging
from .indicators import calculate_rsi, calculate_cci

logger = logging.getLogger(__name__)


class TimingSignal:
    """
    Analyzes timing signals based on volume, RSI, and CCI.
    """
    
    def __init__(
        self,
        volume_ma_window: int = 20,
        volume_min_ratio: float = 1.0,
        rsi_min: float = 40.0,
        rsi_max: float = 65.0,
        cci_min: float = -100.0,
        cci_max: float = 100.0
    ):
        """
        Initialize TimingSignal.
        
        Args:
            volume_ma_window: Window for volume moving average (default 20)
            volume_min_ratio: Minimum volume ratio vs average (default 1.0)
            rsi_min: Minimum RSI value (default 40)
            rsi_max: Maximum RSI value (default 65)
            cci_min: Minimum CCI value (default -100)
            cci_max: Maximum CCI value (default 100)
        """
        self.volume_ma_window = volume_ma_window
        self.volume_min_ratio = volume_min_ratio
        self.rsi_min = rsi_min
        self.rsi_max = rsi_max
        self.cci_min = cci_min
        self.cci_max = cci_max
    
    def evaluate(self, df: pd.DataFrame, price_col: str = 'Close') -> Dict[str, Any]:
        """
        Evaluate timing signal for given price data.
        
        Args:
            df: DataFrame with OHLCV data
            price_col: Column name for price (default 'Close')
        
        Returns:
            Dictionary with timing signal data:
            {
                'volume': float,
                'volume_ma': float,
                'volume_ok': bool,
                'rsi': float,
                'rsi_ok': bool,
                'cci': float,
                'cci_ok': bool,
                'timing_ok': bool
            }
        """
        try:
            if df.empty or len(df) < self.volume_ma_window:
                logger.warning(f"Insufficient data for timing signal (need at least {self.volume_ma_window} periods)")
                return {
                    'volume': 0.0,
                    'volume_ma': 0.0,
                    'volume_ok': False,
                    'rsi': 0.0,
                    'rsi_ok': False,
                    'cci': 0.0,
                    'cci_ok': False,
                    'timing_ok': False,
                    'error': 'Insufficient data'
                }
            
            required_cols = [price_col, 'Volume']
            missing_cols = [col for col in required_cols if col not in df.columns]
            if missing_cols:
                logger.warning(f"Columns {missing_cols} not found in DataFrame")
                return {
                    'volume': 0.0,
                    'volume_ma': 0.0,
                    'volume_ok': False,
                    'rsi': 0.0,
                    'rsi_ok': False,
                    'cci': 0.0,
                    'cci_ok': False,
                    'timing_ok': False,
                    'error': f'Missing columns: {missing_cols}'
                }
            
            df = df.copy()
            
            # Volume analysis
            df['vol_ma'] = df['Volume'].rolling(window=self.volume_ma_window).mean()
            volume = float(df['Volume'].iloc[-1])
            volume_ma = float(df['vol_ma'].iloc[-1])
            volume_ok = volume >= volume_ma * self.volume_min_ratio if volume_ma > 0 else False
            
            # RSI calculation
            rsi_series = calculate_rsi(df, price_col=price_col, period=self.volume_ma_window)
            rsi_val = float(rsi_series.iloc[-1]) if not rsi_series.empty and not pd.isna(rsi_series.iloc[-1]) else 50.0
            rsi_ok = self.rsi_min <= rsi_val <= self.rsi_max
            
            # CCI calculation
            cci_series = calculate_cci(
                df,
                high_col='High',
                low_col='Low',
                close_col=price_col,
                period=self.volume_ma_window
            )
            cci_val = float(cci_series.iloc[-1]) if not cci_series.empty and not pd.isna(cci_series.iloc[-1]) else 0.0
            cci_ok = self.cci_min <= cci_val <= self.cci_max
            
            # Overall timing signal
            timing_ok = volume_ok and rsi_ok and cci_ok
            
            return {
                'volume': round(volume, 2),
                'volume_ma': round(volume_ma, 2),
                'volume_ok': bool(volume_ok),
                'rsi': round(rsi_val, 2),
                'rsi_ok': bool(rsi_ok),
                'cci': round(cci_val, 2),
                'cci_ok': bool(cci_ok),
                'timing_ok': bool(timing_ok)
            }
        
        except Exception as e:
            logger.error(f"Error evaluating timing signal: {e}", exc_info=True)
            return {
                'volume': 0.0,
                'volume_ma': 0.0,
                'volume_ok': False,
                'rsi': 0.0,
                'rsi_ok': False,
                'cci': 0.0,
                'cci_ok': False,
                'timing_ok': False,
                'error': str(e)
            }
