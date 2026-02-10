"""
Momentum Signal Analysis

Combines multiple technical indicators into a weighted momentum assessment
inspired by ai-hedge-fund's category weighting system:

- Trend Following  (0.25): EMA alignment, ADX trend strength
- Momentum         (0.25): Multi-period returns, MACD histogram
- Mean Reversion   (0.20): Z-score vs 50d MA, Bollinger %B, RSI
- Volatility       (0.15): 20d vs 60d vol ratio, ATR-based regime
- Oscillators      (0.15): Stochastic, Williams %R, ROC
"""

import pandas as pd
import numpy as np
from typing import Any, Dict
import logging

from .indicators import (
    calculate_adx,
    calculate_bollinger_bands,
    calculate_ema,
    calculate_macd,
    calculate_momentum_returns,
    calculate_roc,
    calculate_rsi,
    calculate_stochastic,
    calculate_volatility,
    calculate_williams_r,
    calculate_z_score,
)

logger = logging.getLogger(__name__)

# Category weights (must sum to 1.0)
WEIGHT_TREND = 0.25
WEIGHT_MOMENTUM = 0.25
WEIGHT_MEAN_REVERSION = 0.20
WEIGHT_VOLATILITY = 0.15
WEIGHT_OSCILLATORS = 0.15

# Momentum return sub-weights (1m / 3m / 6m)
MOM_W_1M = 0.40
MOM_W_3M = 0.30
MOM_W_6M = 0.30


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    """Clamp a value between lo and hi."""
    return max(lo, min(hi, value))


class MomentumSignal:
    """
    Evaluates a weighted momentum composite from multiple indicator categories.
    """

    def __init__(
        self,
        ema_periods: tuple[int, ...] = (8, 21, 55),
        adx_period: int = 14,
        macd_fast: int = 12,
        macd_slow: int = 26,
        macd_signal: int = 9,
        bb_period: int = 20,
        bb_std: float = 2.0,
        rsi_period: int = 14,
        z_score_period: int = 50,
        stoch_k: int = 14,
        stoch_d: int = 3,
        stoch_smooth: int = 3,
        williams_period: int = 14,
        roc_period: int = 10,
        vol_short: int = 20,
        vol_long: int = 60,
    ):
        self.ema_periods = ema_periods
        self.adx_period = adx_period
        self.macd_fast = macd_fast
        self.macd_slow = macd_slow
        self.macd_signal = macd_signal
        self.bb_period = bb_period
        self.bb_std = bb_std
        self.rsi_period = rsi_period
        self.z_score_period = z_score_period
        self.stoch_k = stoch_k
        self.stoch_d = stoch_d
        self.stoch_smooth = stoch_smooth
        self.williams_period = williams_period
        self.roc_period = roc_period
        self.vol_short = vol_short
        self.vol_long = vol_long

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate(self, df: pd.DataFrame, price_col: str = "Close") -> Dict[str, Any]:
        """
        Evaluate momentum signal for given OHLCV data.

        Args:
            df: DataFrame with at least Close (and ideally High/Low/Volume).
            price_col: Column name for close price.

        Returns:
            Dictionary with per-category details, composite_score, and bias.
        """
        try:
            min_rows = max(self.ema_periods[-1], self.vol_long, self.z_score_period) + 10
            if df.empty or len(df) < min_rows:
                return self._empty_result("Insufficient data")

            if price_col not in df.columns:
                return self._empty_result(f"Missing column {price_col}")

            trend = self._score_trend_following(df, price_col)
            momentum = self._score_momentum(df, price_col)
            mean_rev = self._score_mean_reversion(df, price_col)
            vol = self._score_volatility(df, price_col)
            osc = self._score_oscillators(df, price_col)

            composite = (
                WEIGHT_TREND * trend["score"]
                + WEIGHT_MOMENTUM * momentum["score"]
                + WEIGHT_MEAN_REVERSION * mean_rev["score"]
                + WEIGHT_VOLATILITY * vol["score"]
                + WEIGHT_OSCILLATORS * osc["score"]
            )

            if composite >= 0.6:
                bias = "BULLISH"
            elif composite <= 0.4:
                bias = "BEARISH"
            else:
                bias = "NEUTRAL"

            return {
                "trend_following": trend,
                "momentum": momentum,
                "mean_reversion": mean_rev,
                "volatility": vol,
                "oscillators": osc,
                "composite_score": round(composite, 3),
                "bias": bias,
            }

        except Exception as e:
            logger.error(f"Error evaluating momentum signal: {e}", exc_info=True)
            return self._empty_result(str(e))

    # ------------------------------------------------------------------
    # Category scorers (each returns dict with 'score' in [0, 1])
    # ------------------------------------------------------------------

    def _score_trend_following(self, df: pd.DataFrame, price_col: str) -> Dict[str, Any]:
        """EMA alignment + ADX trend strength -> score 0-1."""
        price = float(df[price_col].iloc[-1])
        emas: Dict[str, float] = {}
        for p in self.ema_periods:
            series = calculate_ema(df, price_col=price_col, period=p)
            val = float(series.iloc[-1]) if not series.empty and not pd.isna(series.iloc[-1]) else 0.0
            emas[f"ema_{p}"] = round(val, 4)

        ema_vals = list(emas.values())

        # Check alignment: price > EMA_short > EMA_mid > EMA_long = bullish
        if len(ema_vals) == 3 and all(v > 0 for v in ema_vals):
            if price > ema_vals[0] > ema_vals[1] > ema_vals[2]:
                alignment = "BULLISH"
                align_score = 1.0
            elif price < ema_vals[0] < ema_vals[1] < ema_vals[2]:
                alignment = "BEARISH"
                align_score = 0.0
            else:
                alignment = "MIXED"
                align_score = 0.5
        else:
            alignment = "UNKNOWN"
            align_score = 0.5

        # ADX: 0-100, where 25+ = trending
        adx_series = calculate_adx(df, period=self.adx_period)
        adx_val = float(adx_series.iloc[-1]) if not adx_series.empty and not pd.isna(adx_series.iloc[-1]) else 0.0
        # Normalize: ADX 0->0, 25->0.5, 50+->1.0
        adx_norm = _clamp(adx_val / 50.0)

        # Combine: alignment determines direction, ADX determines confidence
        # If bearish alignment, high ADX means strong downtrend -> low score
        if alignment == "BULLISH":
            score = 0.5 + 0.5 * adx_norm  # strong bull trend = higher
        elif alignment == "BEARISH":
            score = 0.5 - 0.5 * adx_norm  # strong bear trend = lower
        else:
            score = 0.5

        return {
            "score": round(_clamp(score), 3),
            **emas,
            "ema_alignment": alignment,
            "adx": round(adx_val, 2),
        }

    def _score_momentum(self, df: pd.DataFrame, price_col: str) -> Dict[str, Any]:
        """Multi-period returns + MACD histogram -> score 0-1."""
        mom = calculate_momentum_returns(df, price_col=price_col)

        r1m = mom.get("returns_21d", 0.0)
        r3m = mom.get("returns_63d", 0.0)
        r6m = mom.get("returns_126d", 0.0)

        # Convert returns to 0-1 scores: +20% -> 1.0, -20% -> 0.0
        def ret_score(r: float) -> float:
            return _clamp((r + 0.20) / 0.40)

        weighted_ret = (
            MOM_W_1M * ret_score(r1m)
            + MOM_W_3M * ret_score(r3m)
            + MOM_W_6M * ret_score(r6m)
        )

        # MACD histogram direction
        macd = calculate_macd(
            df, price_col=price_col,
            fast_period=self.macd_fast, slow_period=self.macd_slow,
            signal_period=self.macd_signal
        )
        hist = macd["histogram"]
        if not hist.empty and not pd.isna(hist.iloc[-1]):
            hist_val = float(hist.iloc[-1])
            macd_val = float(macd["macd"].iloc[-1]) if not pd.isna(macd["macd"].iloc[-1]) else 0.0
            signal_val = float(macd["signal"].iloc[-1]) if not pd.isna(macd["signal"].iloc[-1]) else 0.0
            # Positive histogram + rising = bullish
            if hist_val > 0:
                macd_score = _clamp(0.5 + hist_val * 10)  # scale small values up
            else:
                macd_score = _clamp(0.5 + hist_val * 10)
        else:
            hist_val = 0.0
            macd_val = 0.0
            signal_val = 0.0
            macd_score = 0.5

        score = 0.6 * weighted_ret + 0.4 * macd_score

        return {
            "score": round(_clamp(score), 3),
            "returns_1m": round(r1m, 4),
            "returns_3m": round(r3m, 4),
            "returns_6m": round(r6m, 4),
            "macd_value": round(macd_val, 4),
            "macd_signal": round(signal_val, 4),
            "macd_histogram": round(hist_val, 4),
        }

    def _score_mean_reversion(self, df: pd.DataFrame, price_col: str) -> Dict[str, Any]:
        """Z-score + Bollinger %B + RSI -> score 0-1.

        For mean-reversion, *oversold* conditions are bullish (higher score),
        *overbought* conditions are bearish (lower score).
        """
        # Z-score: negative = below mean = potential buy
        z = calculate_z_score(df, price_col=price_col, period=self.z_score_period)
        z_val = float(z.iloc[-1]) if not z.empty and not pd.isna(z.iloc[-1]) else 0.0
        # Map Z: -2 -> 1.0 (oversold), 0 -> 0.5, +2 -> 0.0 (overbought)
        z_score_norm = _clamp((-z_val + 2.0) / 4.0)

        # Bollinger %B: 0 = at lower band (oversold), 1 = at upper (overbought)
        bb = calculate_bollinger_bands(
            df, price_col=price_col, period=self.bb_period, num_std=self.bb_std
        )
        pct_b = bb["pct_b"]
        bb_val = float(pct_b.iloc[-1]) if not pct_b.empty and not pd.isna(pct_b.iloc[-1]) else 0.5
        # Invert: low %B (oversold) = higher score
        bb_score = _clamp(1.0 - bb_val)

        # RSI: < 30 oversold (bullish), > 70 overbought (bearish)
        rsi = calculate_rsi(df, price_col=price_col, period=self.rsi_period)
        rsi_val = float(rsi.iloc[-1]) if not rsi.empty and not pd.isna(rsi.iloc[-1]) else 50.0
        # Map: RSI 20 -> 1.0, 50 -> 0.5, 80 -> 0.0
        rsi_score = _clamp((80.0 - rsi_val) / 60.0)

        score = 0.35 * z_score_norm + 0.35 * bb_score + 0.30 * rsi_score

        return {
            "score": round(_clamp(score), 3),
            "z_score": round(z_val, 3),
            "bb_pct_b": round(bb_val, 3),
            "rsi": round(rsi_val, 2),
        }

    def _score_volatility(self, df: pd.DataFrame, price_col: str) -> Dict[str, Any]:
        """20d vs 60d volatility ratio -> score 0-1.

        Low volatility expansion = stable (higher score for trend followers).
        High spike = risky (lower score).
        """
        vol_20 = calculate_volatility(df, price_col=price_col, period=self.vol_short)
        vol_60 = calculate_volatility(df, price_col=price_col, period=self.vol_long)

        v20 = float(vol_20.iloc[-1]) if not vol_20.empty and not pd.isna(vol_20.iloc[-1]) else 0.0
        v60 = float(vol_60.iloc[-1]) if not vol_60.empty and not pd.isna(vol_60.iloc[-1]) else 0.0

        vol_ratio = v20 / v60 if v60 > 0 else 1.0
        # Annualized vol approximation
        annualized_vol = v20 * np.sqrt(252) if v20 > 0 else 0.0

        # Score: ratio near 1.0 = calm (0.7), < 0.8 = contracting (0.9),
        # > 1.5 = spiking (0.2), > 2.0 = extreme (0.1)
        if vol_ratio < 0.8:
            score = 0.9  # vol contracting = good for momentum
        elif vol_ratio < 1.2:
            score = 0.7  # normal
        elif vol_ratio < 1.5:
            score = 0.4  # expanding
        elif vol_ratio < 2.0:
            score = 0.2  # spiking
        else:
            score = 0.1  # extreme

        return {
            "score": round(score, 3),
            "vol_20d": round(v20, 6),
            "vol_60d": round(v60, 6),
            "vol_ratio": round(vol_ratio, 3),
            "annualized_vol": round(annualized_vol, 4),
        }

    def _score_oscillators(self, df: pd.DataFrame, price_col: str) -> Dict[str, Any]:
        """Stochastic %K, Williams %R, ROC -> score 0-1."""
        # Stochastic %K (0-100): < 20 oversold (bullish), > 80 overbought (bearish)
        stoch = calculate_stochastic(
            df, k_period=self.stoch_k, d_period=self.stoch_d, smooth_k=self.stoch_smooth
        )
        k_val = float(stoch["k"].iloc[-1]) if not stoch["k"].empty and not pd.isna(stoch["k"].iloc[-1]) else 50.0
        d_val = float(stoch["d"].iloc[-1]) if not stoch["d"].empty and not pd.isna(stoch["d"].iloc[-1]) else 50.0
        # Neutral zone 20-80 scores 0.3-0.7, extremes amplified
        stoch_score = _clamp((80.0 - k_val) / 60.0)

        # Williams %R (-100 to 0): < -80 oversold (bullish), > -20 overbought
        wr = calculate_williams_r(df, period=self.williams_period)
        wr_val = float(wr.iloc[-1]) if not wr.empty and not pd.isna(wr.iloc[-1]) else -50.0
        # Map: -100 -> 1.0, -50 -> 0.5, 0 -> 0.0
        wr_score = _clamp(-wr_val / 100.0)

        # ROC (unbounded %): positive = bullish momentum
        roc = calculate_roc(df, price_col=price_col, period=self.roc_period)
        roc_val = float(roc.iloc[-1]) if not roc.empty and not pd.isna(roc.iloc[-1]) else 0.0
        # Map: -10% -> 0.0, 0% -> 0.5, +10% -> 1.0
        roc_score = _clamp((roc_val + 10.0) / 20.0)

        score = 0.40 * stoch_score + 0.30 * wr_score + 0.30 * roc_score

        return {
            "score": round(_clamp(score), 3),
            "stochastic_k": round(k_val, 2),
            "stochastic_d": round(d_val, 2),
            "williams_r": round(wr_val, 2),
            "roc": round(roc_val, 2),
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _empty_result(reason: str = "") -> Dict[str, Any]:
        empty_cat: Dict[str, Any] = {"score": 0.5}
        result: Dict[str, Any] = {
            "trend_following": {**empty_cat},
            "momentum": {**empty_cat},
            "mean_reversion": {**empty_cat},
            "volatility": {**empty_cat},
            "oscillators": {**empty_cat},
            "composite_score": 0.5,
            "bias": "NEUTRAL",
        }
        if reason:
            result["error"] = reason
        return result
