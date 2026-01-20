"""
Fear and Risk Signal Analysis

Analyzes fear and risk indicators including:
- Volatility spikes
- Drawdowns
- Volume anomalies
- Price action risk
- Composite risk scoring

This is new functionality not present in InvestAI.
"""

import pandas as pd
from typing import Dict, Any
import logging
from .indicators import calculate_volatility

logger = logging.getLogger(__name__)


class FearRiskSignal:
    """
    Analyzes fear and risk indicators for a ticker.
    """
    
    def __init__(
        self,
        volatility_spike_threshold: float = 1.5,
        drawdown_alert_threshold: float = -10.0,
        volume_spike_threshold: float = 2.0,
        volume_drop_threshold: float = 0.5,
        price_drop_alert: float = -5.0,
        lookback_period: int = 60
    ):
        """
        Initialize FearRiskSignal.
        
        Args:
            volatility_spike_threshold: Ratio for volatility spike (default 1.5 = 150%)
            drawdown_alert_threshold: Drawdown percentage to alert (default -10%)
            volume_spike_threshold: Volume spike ratio (default 2.0 = 200%)
            volume_drop_threshold: Volume drop ratio (default 0.5 = 50%)
            price_drop_alert: Daily price drop to alert (default -5%)
            lookback_period: Period for calculating highs/drawdowns (default 60)
        """
        self.volatility_spike_threshold = volatility_spike_threshold
        self.drawdown_alert_threshold = drawdown_alert_threshold
        self.volume_spike_threshold = volume_spike_threshold
        self.volume_drop_threshold = volume_drop_threshold
        self.price_drop_alert = price_drop_alert
        self.lookback_period = lookback_period
    
    def evaluate(self, df: pd.DataFrame, price_col: str = 'Close') -> Dict[str, Any]:
        """
        Evaluate fear and risk signals for given price data.
        
        Args:
            df: DataFrame with OHLCV data
            price_col: Column name for price (default 'Close')
        
        Returns:
            Dictionary with fear/risk signal data:
            {
                'fear_level': 'LOW' | 'MODERATE' | 'HIGH' | 'EXTREME',
                'risk_score': float (0-100),
                'volatility_spike': bool,
                'volatility_ratio': float,
                'drawdown_pct': float,
                'volume_anomaly': bool,
                'volume_ratio': float,
                'price_action_risk': bool,
                'daily_change_pct': float,
                'recommendation': 'SAFE' | 'CAUTION' | 'RISKY' | 'AVOID'
            }
        """
        try:
            if df.empty or len(df) < 60:
                logger.warning("Insufficient data for fear/risk signal (need at least 60 periods)")
                return {
                    'fear_level': 'LOW',
                    'risk_score': 0.0,
                    'volatility_spike': False,
                    'volatility_ratio': 1.0,
                    'drawdown_pct': 0.0,
                    'volume_anomaly': False,
                    'volume_ratio': 1.0,
                    'price_action_risk': False,
                    'daily_change_pct': 0.0,
                    'recommendation': 'SAFE',
                    'error': 'Insufficient data'
                }
            
            if price_col not in df.columns:
                logger.warning(f"Column {price_col} not found in DataFrame")
                return {
                    'fear_level': 'LOW',
                    'risk_score': 0.0,
                    'volatility_spike': False,
                    'volatility_ratio': 1.0,
                    'drawdown_pct': 0.0,
                    'volume_anomaly': False,
                    'volume_ratio': 1.0,
                    'price_action_risk': False,
                    'daily_change_pct': 0.0,
                    'recommendation': 'SAFE',
                    'error': 'Missing price column'
                }
            
            df = df.copy()
            
            # Volatility analysis (20-day vs 60-day)
            vol_20 = calculate_volatility(df, price_col=price_col, period=20)
            vol_60 = calculate_volatility(df, price_col=price_col, period=60)
            
            vol_20_val = float(vol_20.iloc[-1]) if not vol_20.empty and not pd.isna(vol_20.iloc[-1]) else 0.0
            vol_60_val = float(vol_60.iloc[-1]) if not vol_60.empty and not pd.isna(vol_60.iloc[-1]) else 0.0
            
            vol_ratio = vol_20_val / vol_60_val if vol_60_val > 0 else 1.0
            volatility_spike = vol_ratio > self.volatility_spike_threshold
            
            # Drawdown calculation (from recent high)
            high_60 = float(df[price_col].rolling(self.lookback_period).max().iloc[-1])
            current_price = float(df[price_col].iloc[-1])
            drawdown_pct = ((current_price - high_60) / high_60) * 100 if high_60 > 0 else 0.0
            
            # Volume anomaly detection
            if 'Volume' in df.columns:
                vol_ma_20 = float(df['Volume'].rolling(20).mean().iloc[-1])
                current_vol = float(df['Volume'].iloc[-1])
                vol_ratio_vol = current_vol / vol_ma_20 if vol_ma_20 > 0 else 1.0
                volume_anomaly = vol_ratio_vol > self.volume_spike_threshold or vol_ratio_vol < self.volume_drop_threshold
            else:
                vol_ratio_vol = 1.0
                volume_anomaly = False
            
            # Price action risk (rapid declines)
            if len(df) > 1:
                daily_change = ((df[price_col].iloc[-1] - df[price_col].iloc[-2]) / df[price_col].iloc[-2]) * 100
                daily_change_pct = float(daily_change)
                price_action_risk = daily_change_pct < self.price_drop_alert
            else:
                daily_change_pct = 0.0
                price_action_risk = False
            
            # Calculate risk score (0-100)
            risk_score = 0.0
            if volatility_spike:
                risk_score += 25.0
            if drawdown_pct < self.drawdown_alert_threshold:
                risk_score += 30.0
            if volume_anomaly and vol_ratio_vol < self.volume_drop_threshold:  # Low volume is risky
                risk_score += 15.0
            if price_action_risk:
                risk_score += 30.0
            
            # Determine fear level
            if risk_score >= 70.0:
                fear_level = 'EXTREME'
            elif risk_score >= 50.0:
                fear_level = 'HIGH'
            elif risk_score >= 30.0:
                fear_level = 'MODERATE'
            else:
                fear_level = 'LOW'
            
            # Recommendation
            if risk_score >= 70.0:
                recommendation = 'AVOID'
            elif risk_score >= 50.0:
                recommendation = 'RISKY'
            elif risk_score >= 30.0:
                recommendation = 'CAUTION'
            else:
                recommendation = 'SAFE'
            
            return {
                'fear_level': fear_level,
                'risk_score': round(risk_score, 1),
                'volatility_spike': bool(volatility_spike),
                'volatility_ratio': round(vol_ratio, 2),
                'drawdown_pct': round(drawdown_pct, 2),
                'volume_anomaly': bool(volume_anomaly),
                'volume_ratio': round(vol_ratio_vol, 2),
                'price_action_risk': bool(price_action_risk),
                'daily_change_pct': round(daily_change_pct, 2),
                'recommendation': recommendation
            }
        
        except Exception as e:
            logger.error(f"Error evaluating fear/risk signal: {e}", exc_info=True)
            return {
                'fear_level': 'LOW',
                'risk_score': 0.0,
                'volatility_spike': False,
                'volatility_ratio': 1.0,
                'drawdown_pct': 0.0,
                'volume_anomaly': False,
                'volume_ratio': 1.0,
                'price_action_risk': False,
                'daily_change_pct': 0.0,
                'recommendation': 'SAFE',
                'error': str(e)
            }
