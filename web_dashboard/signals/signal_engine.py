"""
Signal Engine

Orchestrates all signal types (structure, timing, fear/risk) into unified analysis.
"""

import pandas as pd
from typing import Dict, Any, Optional
import logging
from .structure_signal import StructureSignal
from .timing_signal import TimingSignal
from .fear_risk_signal import FearRiskSignal

logger = logging.getLogger(__name__)


class SignalEngine:
    """
    Orchestrates all signal types into unified analysis.
    """
    
    def __init__(
        self,
        structure_signal: Optional[StructureSignal] = None,
        timing_signal: Optional[TimingSignal] = None,
        fear_risk_signal: Optional[FearRiskSignal] = None
    ):
        """
        Initialize SignalEngine.
        
        Args:
            structure_signal: Optional StructureSignal instance (creates default if None)
            timing_signal: Optional TimingSignal instance (creates default if None)
            fear_risk_signal: Optional FearRiskSignal instance (creates default if None)
        """
        self.structure_signal = structure_signal or StructureSignal()
        self.timing_signal = timing_signal or TimingSignal()
        self.fear_risk_signal = fear_risk_signal or FearRiskSignal()
    
    def evaluate(self, ticker: str, df: pd.DataFrame, price_col: str = 'Close') -> Dict[str, Any]:
        """
        Evaluate all signals for a ticker.
        
        Args:
            ticker: Ticker symbol
            df: DataFrame with OHLCV price data
            price_col: Column name for price (default 'Close')
        
        Returns:
            Dictionary with comprehensive signal analysis:
            {
                'ticker': str,
                'structure': dict,
                'timing': dict,
                'fear_risk': dict,
                'overall_signal': 'BUY' | 'SELL' | 'HOLD' | 'WATCH',
                'confidence': float (0-1),
                'analysis_date': str (ISO format)
            }
        """
        try:
            # Evaluate each signal type
            structure = self.structure_signal.evaluate(df, price_col=price_col)
            timing = self.timing_signal.evaluate(df, price_col=price_col)
            fear_risk = self.fear_risk_signal.evaluate(df, price_col=price_col)
            
            # Determine overall signal
            overall_signal, confidence = self._determine_overall_signal(
                structure, timing, fear_risk
            )
            
            from datetime import datetime, timezone
            analysis_date = datetime.now(timezone.utc).isoformat()
            
            return {
                'ticker': ticker.upper(),
                'structure': structure,
                'timing': timing,
                'fear_risk': fear_risk,
                'overall_signal': overall_signal,
                'confidence': round(confidence, 2),
                'analysis_date': analysis_date
            }
        
        except Exception as e:
            logger.error(f"Error evaluating signals for {ticker}: {e}", exc_info=True)
            return {
                'ticker': ticker.upper(),
                'structure': {'error': str(e)},
                'timing': {'error': str(e)},
                'fear_risk': {'error': str(e)},
                'overall_signal': 'HOLD',
                'confidence': 0.0,
                'error': str(e)
            }
    
    def _determine_overall_signal(
        self,
        structure: Dict[str, Any],
        timing: Dict[str, Any],
        fear_risk: Dict[str, Any]
    ) -> tuple[str, float]:
        """
        Determine overall signal and confidence from component signals.
        
        Args:
            structure: Structure signal dict
            timing: Timing signal dict
            fear_risk: Fear/risk signal dict
        
        Returns:
            Tuple of (overall_signal, confidence)
        """
        # Check for errors
        if 'error' in structure or 'error' in timing or 'error' in fear_risk:
            return ('HOLD', 0.0)
        
        # Extract key signals
        trend = structure.get('trend', 'NEUTRAL')
        pullback = structure.get('pullback', False)
        breakout = structure.get('breakout', False)
        timing_ok = timing.get('timing_ok', False)
        fear_level = fear_risk.get('fear_level', 'LOW')
        risk_score = fear_risk.get('risk_score', 0.0)
        recommendation = fear_risk.get('recommendation', 'SAFE')
        
        # High fear/risk overrides everything
        if fear_level in ['HIGH', 'EXTREME'] or recommendation in ['RISKY', 'AVOID']:
            if risk_score >= 70:
                return ('SELL', 0.8)
            elif risk_score >= 50:
                return ('WATCH', 0.6)
            else:
                return ('HOLD', 0.4)
        
        # Strong buy signals
        if (trend == 'UPTREND' and 
            (pullback or breakout) and 
            timing_ok and 
            fear_level == 'LOW'):
            confidence = 0.8 if breakout else 0.7
            return ('BUY', confidence)
        
        # Moderate buy signals
        if (trend == 'UPTREND' and timing_ok and fear_level in ['LOW', 'MODERATE']):
            return ('BUY', 0.6)
        
        # Weak buy/watch signals
        if trend == 'UPTREND' and fear_level in ['LOW', 'MODERATE']:
            return ('WATCH', 0.5)
        
        # Sell signals (downtrend with high risk)
        if trend == 'DOWNTREND' and risk_score >= 50:
            return ('SELL', 0.7)
        
        # Watch signals (downtrend but not extreme)
        if trend == 'DOWNTREND':
            return ('WATCH', 0.4)
        
        # Default to hold
        return ('HOLD', 0.5)
