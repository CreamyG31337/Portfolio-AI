"""
Technical Signals Module

Provides technical analysis signals including:
- Structure signals (trend, pullback, breakout)
- Timing signals (volume, momentum)
- Fear/risk signals (volatility, drawdown, risk scoring)
- Momentum signals (EMA alignment, MACD, Bollinger Bands, oscillators)
- Fundamental signals (profitability, growth, health, valuation scoring)
"""

from .indicators import (
    calculate_rsi,
    calculate_cci,
    calculate_ma,
    calculate_volatility,
    calculate_ema,
    calculate_macd,
    calculate_bollinger_bands,
    calculate_adx,
    calculate_stochastic,
    calculate_williams_r,
    calculate_roc,
    calculate_z_score,
    calculate_momentum_returns,
)
from .structure_signal import StructureSignal
from .timing_signal import TimingSignal
from .fear_risk_signal import FearRiskSignal
from .momentum_signal import MomentumSignal
from .fundamental_signal import FundamentalSignal
from .signal_engine import SignalEngine
from .ai_explainer import generate_signal_explanation

__all__ = [
    # Indicators
    'calculate_rsi',
    'calculate_cci',
    'calculate_ma',
    'calculate_volatility',
    'calculate_ema',
    'calculate_macd',
    'calculate_bollinger_bands',
    'calculate_adx',
    'calculate_stochastic',
    'calculate_williams_r',
    'calculate_roc',
    'calculate_z_score',
    'calculate_momentum_returns',
    # Signal types
    'StructureSignal',
    'TimingSignal',
    'FearRiskSignal',
    'MomentumSignal',
    'FundamentalSignal',
    # Engine & utilities
    'SignalEngine',
    'generate_signal_explanation',
]
