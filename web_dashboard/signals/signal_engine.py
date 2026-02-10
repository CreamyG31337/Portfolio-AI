"""
Signal Engine

Orchestrates all signal types (structure, timing, fear/risk, momentum,
fundamental) into unified analysis.
"""

import pandas as pd
from typing import Any, Dict, Optional
import logging
from .structure_signal import StructureSignal
from .timing_signal import TimingSignal
from .fear_risk_signal import FearRiskSignal
from .momentum_signal import MomentumSignal
from .fundamental_signal import FundamentalSignal

logger = logging.getLogger(__name__)


class SignalEngine:
    """
    Orchestrates all signal types into unified analysis.
    """
    
    def __init__(
        self,
        structure_signal: Optional[StructureSignal] = None,
        timing_signal: Optional[TimingSignal] = None,
        fear_risk_signal: Optional[FearRiskSignal] = None,
        momentum_signal: Optional[MomentumSignal] = None,
        fundamental_signal: Optional[FundamentalSignal] = None,
    ):
        """
        Initialize SignalEngine.
        
        Args:
            structure_signal: Optional StructureSignal instance (creates default if None)
            timing_signal: Optional TimingSignal instance (creates default if None)
            fear_risk_signal: Optional FearRiskSignal instance (creates default if None)
            momentum_signal: Optional MomentumSignal instance (creates default if None)
            fundamental_signal: Optional FundamentalSignal instance (creates default if None)
        """
        self.structure_signal = structure_signal or StructureSignal()
        self.timing_signal = timing_signal or TimingSignal()
        self.fear_risk_signal = fear_risk_signal or FearRiskSignal()
        self.momentum_signal = momentum_signal or MomentumSignal()
        self.fundamental_signal = fundamental_signal or FundamentalSignal()
    
    def evaluate(
        self,
        ticker: str,
        df: pd.DataFrame,
        price_col: str = 'Close',
        fundamentals: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Evaluate all signals for a ticker.
        
        Args:
            ticker: Ticker symbol
            df: DataFrame with OHLCV price data
            price_col: Column name for price (default 'Close')
            fundamentals: Optional dict of fundamental metrics from the
                          securities table. If None, the fundamental signal
                          is skipped (returns neutral).
        
        Returns:
            Dictionary with comprehensive signal analysis:
            {
                'ticker': str,
                'structure': dict,
                'timing': dict,
                'fear_risk': dict,
                'momentum': dict,
                'fundamental': dict,
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
            momentum = self.momentum_signal.evaluate(df, price_col=price_col)
            fundamental = self.fundamental_signal.evaluate(fundamentals)
            
            # Determine overall signal
            overall_signal, confidence = self._determine_overall_signal(
                structure, timing, fear_risk, momentum, fundamental
            )
            
            from datetime import datetime, timezone
            analysis_date = datetime.now(timezone.utc).isoformat()
            
            return {
                'ticker': ticker.upper(),
                'structure': structure,
                'timing': timing,
                'fear_risk': fear_risk,
                'momentum': momentum,
                'fundamental': fundamental,
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
                'momentum': {'error': str(e)},
                'fundamental': {'error': str(e)},
                'overall_signal': 'HOLD',
                'confidence': 0.0,
                'error': str(e)
            }
    
    def _determine_overall_signal(
        self,
        structure: Dict[str, Any],
        timing: Dict[str, Any],
        fear_risk: Dict[str, Any],
        momentum: Optional[Dict[str, Any]] = None,
        fundamental: Optional[Dict[str, Any]] = None,
    ) -> tuple[str, float]:
        """
        Determine overall signal and confidence from component signals.

        Uses a two-stage approach:
        1. Hard override: extreme fear/risk forces SELL or WATCH (safety first).
        2. Weighted composite: combines the original rule-based logic with
           momentum and fundamental scores for a richer picture.
        
        Args:
            structure: Structure signal dict
            timing: Timing signal dict
            fear_risk: Fear/risk signal dict
            momentum: Momentum signal dict (optional)
            fundamental: Fundamental signal dict (optional)
        
        Returns:
            Tuple of (overall_signal, confidence)
        """
        # Check for errors in the three core signals
        if 'error' in structure or 'error' in timing or 'error' in fear_risk:
            return ('HOLD', 0.0)
        
        # Extract key signals from original components
        trend = structure.get('trend', 'NEUTRAL')
        pullback = structure.get('pullback', False)
        breakout = structure.get('breakout', False)
        timing_ok = timing.get('timing_ok', False)
        fear_level = fear_risk.get('fear_level', 'LOW')
        risk_score = fear_risk.get('risk_score', 0.0)
        recommendation = fear_risk.get('recommendation', 'SAFE')
        
        # --- Stage 1: Hard override on extreme fear/risk ---
        if fear_level in ['HIGH', 'EXTREME'] or recommendation in ['RISKY', 'AVOID']:
            if risk_score >= 70:
                return ('SELL', 0.8)
            elif risk_score >= 50:
                return ('WATCH', 0.6)
            else:
                return ('HOLD', 0.4)
        
        # --- Stage 2: Rule-based base signal (original logic) ---
        if (trend == 'UPTREND' and 
            (pullback or breakout) and 
            timing_ok and 
            fear_level == 'LOW'):
            base_signal = 'BUY'
            base_conf = 0.8 if breakout else 0.7
        elif (trend == 'UPTREND' and timing_ok and fear_level in ['LOW', 'MODERATE']):
            base_signal = 'BUY'
            base_conf = 0.6
        elif trend == 'UPTREND' and fear_level in ['LOW', 'MODERATE']:
            base_signal = 'WATCH'
            base_conf = 0.5
        elif trend == 'DOWNTREND' and risk_score >= 50:
            base_signal = 'SELL'
            base_conf = 0.7
        elif trend == 'DOWNTREND':
            base_signal = 'WATCH'
            base_conf = 0.4
        else:
            base_signal = 'HOLD'
            base_conf = 0.5

        # --- Stage 3: Adjust confidence with momentum & fundamentals ---
        # Momentum composite: 0-1, where > 0.6 is bullish, < 0.4 is bearish
        mom_score = 0.5
        if momentum and 'error' not in momentum:
            mom_score = momentum.get('composite_score', 0.5)

        # Fundamental composite: 0-1, where > 0.6 is strong, < 0.4 is weak
        fund_score = 0.5
        if fundamental and 'error' not in fundamental:
            fund_score = fundamental.get('composite_score', 0.5)

        # Blend: base confidence is 60% weight, momentum 25%, fundamentals 15%
        blended_conf = (
            0.60 * base_conf
            + 0.25 * mom_score
            + 0.15 * fund_score
        )

        # If momentum strongly disagrees with base signal, moderate confidence
        if base_signal == 'BUY' and mom_score < 0.35:
            # Momentum is bearish but structure says buy -> downgrade
            blended_conf = min(blended_conf, 0.55)
        elif base_signal in ('SELL', 'WATCH') and mom_score > 0.65:
            # Momentum is bullish but structure says sell/watch -> moderate
            blended_conf = max(blended_conf, 0.45)

        # Signal upgrade/downgrade based on strong agreement
        if base_signal == 'WATCH' and mom_score > 0.65 and fund_score > 0.55:
            # Everything aligns bullish -> upgrade WATCH to BUY
            base_signal = 'BUY'
            blended_conf = max(blended_conf, 0.6)
        elif base_signal == 'HOLD' and mom_score < 0.3 and fund_score < 0.35:
            # Everything aligns bearish -> downgrade HOLD to WATCH
            base_signal = 'WATCH'
            blended_conf = min(blended_conf, 0.45)

        return (base_signal, round(max(0.0, min(1.0, blended_conf)), 2))
