"""
Core Technical Indicator Calculations

Provides functions for calculating common technical indicators:
- RSI (Relative Strength Index)
- CCI (Commodity Channel Index)
- Moving Averages (SMA & EMA)
- Volatility (standard deviation of returns)
- MACD (Moving Average Convergence Divergence)
- Bollinger Bands
- ADX (Average Directional Index)
- Stochastic Oscillator
- Williams %R
- ROC (Rate of Change)
- Z-Score vs N-day MA
- Multi-period Momentum Returns
"""

import pandas as pd
import numpy as np
from typing import Dict, Optional, Tuple
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
        
        high = pd.to_numeric(df[high_col], errors="coerce")
        low = pd.to_numeric(df[low_col], errors="coerce")
        close = pd.to_numeric(df[close_col], errors="coerce")

        # Typical Price
        tp = (high + low + close) / 3
        
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


def calculate_ema(df: pd.DataFrame, price_col: str = 'Close', period: int = 20) -> pd.Series:
    """
    Calculate Exponential Moving Average (EMA).

    Args:
        df: DataFrame with price data
        price_col: Column name for price (default 'Close')
        period: Period for EMA calculation (default 20)

    Returns:
        Series with EMA values
    """
    try:
        if price_col not in df.columns:
            logger.warning(f"Column {price_col} not found in DataFrame")
            return pd.Series(dtype=float)

        return df[price_col].ewm(span=period, adjust=False).mean()
    except Exception as e:
        logger.error(f"Error calculating EMA: {e}", exc_info=True)
        return pd.Series(dtype=float)


def calculate_macd(
    df: pd.DataFrame,
    price_col: str = 'Close',
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9
) -> Dict[str, pd.Series]:
    """
    Calculate MACD (Moving Average Convergence Divergence).

    Args:
        df: DataFrame with price data
        price_col: Column name for price (default 'Close')
        fast_period: Fast EMA period (default 12)
        slow_period: Slow EMA period (default 26)
        signal_period: Signal line EMA period (default 9)

    Returns:
        Dictionary with 'macd', 'signal', and 'histogram' Series
    """
    empty = {
        'macd': pd.Series(dtype=float),
        'signal': pd.Series(dtype=float),
        'histogram': pd.Series(dtype=float),
    }
    try:
        if price_col not in df.columns:
            logger.warning(f"Column {price_col} not found in DataFrame")
            return empty

        fast_ema = df[price_col].ewm(span=fast_period, adjust=False).mean()
        slow_ema = df[price_col].ewm(span=slow_period, adjust=False).mean()

        macd_line = fast_ema - slow_ema
        signal_line = macd_line.ewm(span=signal_period, adjust=False).mean()
        histogram = macd_line - signal_line

        return {
            'macd': macd_line,
            'signal': signal_line,
            'histogram': histogram,
        }
    except Exception as e:
        logger.error(f"Error calculating MACD: {e}", exc_info=True)
        return empty


def calculate_bollinger_bands(
    df: pd.DataFrame,
    price_col: str = 'Close',
    period: int = 20,
    num_std: float = 2.0
) -> Dict[str, pd.Series]:
    """
    Calculate Bollinger Bands.

    Args:
        df: DataFrame with price data
        price_col: Column name for price (default 'Close')
        period: Period for middle band SMA (default 20)
        num_std: Number of standard deviations for bands (default 2.0)

    Returns:
        Dictionary with 'upper', 'middle', 'lower', and 'pct_b' Series.
        pct_b = (price - lower) / (upper - lower), where 0 = at lower band,
        1 = at upper band.
    """
    empty = {
        'upper': pd.Series(dtype=float),
        'middle': pd.Series(dtype=float),
        'lower': pd.Series(dtype=float),
        'pct_b': pd.Series(dtype=float),
    }
    try:
        if price_col not in df.columns:
            logger.warning(f"Column {price_col} not found in DataFrame")
            return empty

        middle = df[price_col].rolling(window=period).mean()
        rolling_std = df[price_col].rolling(window=period).std()
        upper = middle + (rolling_std * num_std)
        lower = middle - (rolling_std * num_std)

        band_width = upper - lower
        pct_b = (df[price_col] - lower) / band_width.replace(0, np.nan)

        return {
            'upper': upper,
            'middle': middle,
            'lower': lower,
            'pct_b': pct_b,
        }
    except Exception as e:
        logger.error(f"Error calculating Bollinger Bands: {e}", exc_info=True)
        return empty


def calculate_adx(
    df: pd.DataFrame,
    high_col: str = 'High',
    low_col: str = 'Low',
    close_col: str = 'Close',
    period: int = 14
) -> pd.Series:
    """
    Calculate Average Directional Index (ADX) -- measures trend strength.

    Values:  0-20 weak/absent trend, 20-40 strong trend, 40-60 very strong,
             60-80 extremely strong.

    Args:
        df: DataFrame with OHLC data
        high_col: Column for high prices (default 'High')
        low_col: Column for low prices (default 'Low')
        close_col: Column for close prices (default 'Close')
        period: Smoothing period (default 14)

    Returns:
        Series with ADX values
    """
    try:
        required_cols = [high_col, low_col, close_col]
        missing_cols = [c for c in required_cols if c not in df.columns]
        if missing_cols:
            logger.warning(f"Columns {missing_cols} not found in DataFrame")
            return pd.Series(dtype=float)

        high = pd.to_numeric(df[high_col], errors="coerce")
        low = pd.to_numeric(df[low_col], errors="coerce")
        close = pd.to_numeric(df[close_col], errors="coerce")

        # True Range
        prev_close = close.shift(1)
        tr = pd.concat([
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ], axis=1).max(axis=1)

        # Directional Movement
        up_move = high - high.shift(1)
        down_move = low.shift(1) - low
        plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
        minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)

        # Smoothed averages (Wilder's smoothing = EMA with alpha = 1/period)
        atr = tr.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
        plus_di = 100 * (
            plus_dm.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
            / atr.replace(0, np.nan)
        )
        minus_di = 100 * (
            minus_dm.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
            / atr.replace(0, np.nan)
        )

        dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
        adx = dx.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()

        return adx
    except Exception as e:
        logger.error(f"Error calculating ADX: {e}", exc_info=True)
        return pd.Series(dtype=float)


def calculate_stochastic(
    df: pd.DataFrame,
    high_col: str = 'High',
    low_col: str = 'Low',
    close_col: str = 'Close',
    k_period: int = 14,
    d_period: int = 3,
    smooth_k: int = 3
) -> Dict[str, pd.Series]:
    """
    Calculate Stochastic Oscillator (%K and %D).

    %K = 100 * (Close - Lowest Low) / (Highest High - Lowest Low)
    %D = SMA of %K

    Args:
        df: DataFrame with OHLC data
        high_col: Column for high prices (default 'High')
        low_col: Column for low prices (default 'Low')
        close_col: Column for close prices (default 'Close')
        k_period: Lookback period for %K (default 14)
        d_period: SMA period for %D (default 3)
        smooth_k: Smoothing period for %K (default 3)

    Returns:
        Dictionary with 'k' and 'd' Series
    """
    empty = {'k': pd.Series(dtype=float), 'd': pd.Series(dtype=float)}
    try:
        required_cols = [high_col, low_col, close_col]
        missing_cols = [c for c in required_cols if c not in df.columns]
        if missing_cols:
            logger.warning(f"Columns {missing_cols} not found in DataFrame")
            return empty

        high = pd.to_numeric(df[high_col], errors="coerce")
        low = pd.to_numeric(df[low_col], errors="coerce")
        close = pd.to_numeric(df[close_col], errors="coerce")

        lowest_low = low.rolling(window=k_period).min()
        highest_high = high.rolling(window=k_period).max()

        range_hl = highest_high - lowest_low
        fast_k = 100 * (close - lowest_low) / range_hl.replace(0, np.nan)
        k = fast_k.rolling(window=smooth_k).mean()
        d = k.rolling(window=d_period).mean()

        return {'k': k, 'd': d}
    except Exception as e:
        logger.error(f"Error calculating Stochastic: {e}", exc_info=True)
        return empty


def calculate_williams_r(
    df: pd.DataFrame,
    high_col: str = 'High',
    low_col: str = 'Low',
    close_col: str = 'Close',
    period: int = 14
) -> pd.Series:
    """
    Calculate Williams %R.

    Williams %R = -100 * (Highest High - Close) / (Highest High - Lowest Low)
    Range: -100 (oversold) to 0 (overbought).

    Args:
        df: DataFrame with OHLC data
        high_col: Column for high prices (default 'High')
        low_col: Column for low prices (default 'Low')
        close_col: Column for close prices (default 'Close')
        period: Lookback period (default 14)

    Returns:
        Series with Williams %R values
    """
    try:
        required_cols = [high_col, low_col, close_col]
        missing_cols = [c for c in required_cols if c not in df.columns]
        if missing_cols:
            logger.warning(f"Columns {missing_cols} not found in DataFrame")
            return pd.Series(dtype=float)

        high = pd.to_numeric(df[high_col], errors="coerce")
        low = pd.to_numeric(df[low_col], errors="coerce")
        close = pd.to_numeric(df[close_col], errors="coerce")

        highest_high = high.rolling(window=period).max()
        lowest_low = low.rolling(window=period).min()

        range_hl = highest_high - lowest_low
        williams_r = -100 * (highest_high - close) / range_hl.replace(0, np.nan)

        return williams_r
    except Exception as e:
        logger.error(f"Error calculating Williams %%R: {e}", exc_info=True)
        return pd.Series(dtype=float)


def calculate_roc(df: pd.DataFrame, price_col: str = 'Close', period: int = 10) -> pd.Series:
    """
    Calculate Rate of Change (ROC).

    ROC = 100 * (Price - Price_n_periods_ago) / Price_n_periods_ago

    Args:
        df: DataFrame with price data
        price_col: Column name for price (default 'Close')
        period: Lookback period (default 10)

    Returns:
        Series with ROC values (percentage)
    """
    try:
        if price_col not in df.columns:
            logger.warning(f"Column {price_col} not found in DataFrame")
            return pd.Series(dtype=float)

        prev = df[price_col].shift(period)
        roc = 100 * (df[price_col] - prev) / prev.replace(0, np.nan)
        return roc
    except Exception as e:
        logger.error(f"Error calculating ROC: {e}", exc_info=True)
        return pd.Series(dtype=float)


def calculate_z_score(
    df: pd.DataFrame, price_col: str = 'Close', period: int = 50
) -> pd.Series:
    """
    Calculate Z-Score of price relative to its N-day moving average.

    Z = (Price - SMA) / StdDev

    Positive values: price above average; negative: below.
    Useful for mean-reversion signals (|Z| > 2 is extreme).

    Args:
        df: DataFrame with price data
        price_col: Column name for price (default 'Close')
        period: Lookback period for SMA and StdDev (default 50)

    Returns:
        Series with Z-Score values
    """
    try:
        if price_col not in df.columns:
            logger.warning(f"Column {price_col} not found in DataFrame")
            return pd.Series(dtype=float)

        sma = df[price_col].rolling(window=period).mean()
        std = df[price_col].rolling(window=period).std()
        z_score = (df[price_col] - sma) / std.replace(0, np.nan)
        return z_score
    except Exception as e:
        logger.error(f"Error calculating Z-Score: {e}", exc_info=True)
        return pd.Series(dtype=float)


def calculate_momentum_returns(
    df: pd.DataFrame,
    price_col: str = 'Close',
    periods: Optional[Tuple[int, ...]] = None
) -> Dict[str, float]:
    """
    Calculate multi-period momentum returns (percentage price change).

    Default periods are ~1 month (21 trading days), ~3 months (63),
    and ~6 months (126).

    Args:
        df: DataFrame with price data
        price_col: Column name for price (default 'Close')
        periods: Tuple of lookback periods in trading days
                 (default (21, 63, 126))

    Returns:
        Dictionary mapping period labels to return percentages, e.g.
        {"returns_21d": 0.054, "returns_63d": 0.12, "returns_126d": -0.03}
    """
    if periods is None:
        periods = (21, 63, 126)

    result: Dict[str, float] = {}
    try:
        if price_col not in df.columns:
            logger.warning(f"Column {price_col} not found in DataFrame")
            return result

        current_price = float(df[price_col].iloc[-1])
        for p in periods:
            label = f"returns_{p}d"
            if len(df) > p:
                past_price = float(df[price_col].iloc[-(p + 1)])
                if past_price != 0:
                    result[label] = round((current_price - past_price) / past_price, 6)
                else:
                    result[label] = 0.0
            else:
                result[label] = 0.0
        return result
    except Exception as e:
        logger.error(f"Error calculating momentum returns: {e}", exc_info=True)
        return result
