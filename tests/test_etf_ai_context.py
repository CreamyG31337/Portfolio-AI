"""Tests for ETF and unrated fundamental handling across ticker_state and ai_explainer."""

from __future__ import annotations

import pytest

from web_dashboard.ticker_state import (
    _detect_conflicts,
    _standout_fundamentals,
    summarize_ticker_state,
)
from web_dashboard.signals.ai_explainer import build_signal_explanation_prompt


# ===================================================================
# Conflict detection tests
# ===================================================================

def test_conflict_detection_etf_not_flagged_as_speculative_run() -> None:
    """ETFs must NOT be flagged as speculative run even with UNKNOWN or WEAK fundamentals."""
    state = {
        "ticker": "SPY",
        "signals": {
            "momentum": {"bias": "BULLISH", "composite_score": 0.85},
            "fundamental": {
                "quality": "UNKNOWN",
                "composite_score": 0.5,
                "is_etf": True,
                "insufficient_data": True,
                "reason": "ETF: company fundamentals do not apply",
            },
        },
        "fundamentals": {"company_name": "SPDR S&P 500 ETF Trust"},
    }
    conflicts = _detect_conflicts(state)
    assert not any("speculative run" in c for c in conflicts)

    # Even if quality is WEAK on an ETF, speculative run should not fire
    state["signals"]["fundamental"]["quality"] = "WEAK"
    conflicts_weak = _detect_conflicts(state)
    assert not any("speculative run" in c for c in conflicts_weak)


def test_conflict_detection_insufficient_data_not_flagged() -> None:
    """Insufficient data on a regular stock must NOT be flagged as speculative run."""
    state = {
        "ticker": "TINY",
        "signals": {
            "momentum": {"bias": "BULLISH", "composite_score": 0.75},
            "fundamental": {
                "quality": "UNKNOWN",
                "composite_score": 0.5,
                "insufficient_data": True,
                "reason": "Only 1 metric available",
            },
        },
        "fundamentals": {"company_name": "Tiny Microcap Inc"},
    }
    conflicts = _detect_conflicts(state)
    assert not any("speculative run" in c for c in conflicts)


def test_conflict_detection_real_weak_still_flagged() -> None:
    """Real WEAK fundamental quality with BULLISH momentum MUST still be flagged."""
    state = {
        "ticker": "JUNK",
        "signals": {
            "momentum": {"bias": "BULLISH", "composite_score": 0.8},
            "fundamental": {
                "quality": "WEAK",
                "composite_score": 0.25,
                "metrics_available": 5,
                "insufficient_data": False,
                "is_etf": False,
            },
        },
        "fundamentals": {"company_name": "Junk Operating Corp"},
    }
    conflicts = _detect_conflicts(state)
    assert any("speculative run" in c for c in conflicts)
    assert "Bullish momentum with weak/unknown fundamentals — possible speculative run" in conflicts


def test_conflict_detection_legacy_unknown_still_flagged() -> None:
    """Old stored results without insufficient_data or is_etf keys retain legacy behavior."""
    state = {
        "ticker": "OLD",
        "signals": {
            "momentum": {"bias": "BULLISH", "composite_score": 0.8},
            "fundamental": {
                "quality": "UNKNOWN",
                "composite_score": 0.5,
            },
        },
        "fundamentals": {"company_name": "Old Legacy Corp"},
    }
    conflicts = _detect_conflicts(state)
    assert any("speculative run" in c for c in conflicts)


# ===================================================================
# Summary text tests (ticker_state)
# ===================================================================

def test_summarize_ticker_state_insufficient_data() -> None:
    """For insufficient data show 'Fundamentals: not rated (<reason>)' without 50% score."""
    state = {
        "ticker": "SPY",
        "signals": {
            "overall_signal": "HOLD",
            "confidence": 0.6,
            "structure": {"trend": "NEUTRAL"},
            "momentum": {"bias": "NEUTRAL", "composite_score": 0.5},
            "fundamental": {
                "quality": "UNKNOWN",
                "composite_score": 0.5,
                "metrics_available": 1,
                "insufficient_data": True,
                "is_etf": True,
                "reason": "ETF: company fundamentals do not apply",
            },
            "fear_risk": {"fear_level": "LOW", "risk_score": 25.0},
        },
    }
    summary = summarize_ticker_state(state)
    assert "Fundamentals: not rated (ETF: company fundamentals do not apply)" in summary
    assert "50%" not in summary.split("Fundamentals:")[1]


def test_summarize_ticker_state_lookthrough_rated() -> None:
    """For look-through ETF, append holdings-weighted coverage note to rated fundamentals."""
    state = {
        "ticker": "QQQ",
        "signals": {
            "overall_signal": "BUY",
            "confidence": 0.8,
            "structure": {"trend": "BULLISH"},
            "momentum": {"bias": "BULLISH", "composite_score": 0.75},
            "fundamental": {
                "quality": "GOOD",
                "composite_score": 0.65,
                "metrics_available": 8,
                "method": "lookthrough",
                "lookthrough": {
                    "etf_ticker": "QQQ",
                    "holdings_total": 100,
                    "holdings_with_fundamentals": 95,
                    "weight_with_fundamentals": 0.85,
                },
            },
            "fear_risk": {"fear_level": "LOW", "risk_score": 20.0},
        },
    }
    summary = summarize_ticker_state(state)
    assert "Fundamentals: GOOD 65% (8 metrics), holdings-weighted, 85% of weight covered" in summary


def test_summarize_ticker_state_lookthrough_insufficient() -> None:
    """For look-through with insufficient data, append coverage to not-rated line."""
    state = {
        "ticker": "EMGF",
        "signals": {
            "overall_signal": "HOLD",
            "confidence": 0.5,
            "structure": {"trend": "NEUTRAL"},
            "momentum": {"bias": "NEUTRAL", "composite_score": 0.5},
            "fundamental": {
                "quality": "UNKNOWN",
                "composite_score": 0.5,
                "insufficient_data": True,
                "reason": "Not enough holdings data",
                "method": "lookthrough",
                "lookthrough": {
                    "weight_with_fundamentals": 0.25,
                },
            },
            "fear_risk": {"fear_level": "LOW", "risk_score": 30.0},
        },
    }
    summary = summarize_ticker_state(state)
    assert "Fundamentals: not rated (Not enough holdings data), holdings-weighted, 25% of weight covered" in summary


# ===================================================================
# Standout fundamentals tests
# ===================================================================

def test_standout_fundamentals_etf_labeled_fund_level() -> None:
    """ETF with a lone P/E must be labeled fund-level and not presented as company data."""
    raw_securities_etf = {
        "company_name": "Vanguard Total Stock Market ETF",
        "trailing_pe": 24.5,
        "return_on_equity": 0.20,  # ETF shouldn't show company ROE
    }
    res = _standout_fundamentals(raw_securities_etf)
    assert "fund-level P/E 24.5" in res
    assert "ROE" not in res


def test_standout_fundamentals_handles_fundamental_signal_dict() -> None:
    """Works when fed the fundamental signal dict instead of raw securities row."""
    signal_fund = {
        "is_etf": True,
        "valuation": {"trailing_pe": 26.2},
    }
    res = _standout_fundamentals(signal_fund)
    assert "fund-level P/E 26.2" in res


def test_standout_fundamentals_operating_company_standard() -> None:
    """Regular operating company shows standard metric names and abbreviations."""
    raw_company = {
        "company_name": "Acme Widgets Inc",
        "forward_pe": 18.0,
        "return_on_equity": 0.22,
        "revenue_growth": 0.15,
        "debt_to_equity": 0.4,
    }
    res = _standout_fundamentals(raw_company)
    assert "P/E 18.0" in res
    assert "ROE 22%" in res
    assert "RevGrowth 15%" in res
    assert "D/E 0.4" in res
    assert "fund-level" not in res


# ===================================================================
# AI Explainer prompt tests
# ===================================================================

def test_ai_explainer_prompt_not_asking_fundamentals_when_insufficient() -> None:
    """When insufficient_data is true on a stock, do not ask to comment on fundamental quality."""
    signals = {
        "overall_signal": "BUY",
        "confidence": 0.7,
        "structure": {"trend": "BULLISH"},
        "timing": {"timing": "EARLY"},
        "fear_risk": {"fear_level": "LOW"},
        "momentum": {"bias": "BULLISH", "composite_score": 0.8},
        "fundamental": {
            "quality": "UNKNOWN",
            "composite_score": 0.5,
            "insufficient_data": True,
            "reason": "Only 1 metric available",
        },
    }
    prompt = build_signal_explanation_prompt("TINY", signals)
    assert "Comment on fundamental quality" not in prompt
    assert "Comment on momentum bias" in prompt


def test_ai_explainer_prompt_etf_notes_fund() -> None:
    """For an ETF with insufficient data, prompt asks to note that it's a fund instead of rating."""
    signals = {
        "overall_signal": "HOLD",
        "confidence": 0.5,
        "structure": {"trend": "NEUTRAL"},
        "timing": {"timing": "NEUTRAL"},
        "fear_risk": {"fear_level": "LOW"},
        "momentum": {"bias": "NEUTRAL", "composite_score": 0.5},
        "fundamental": {
            "quality": "UNKNOWN",
            "composite_score": 0.5,
            "insufficient_data": True,
            "is_etf": True,
            "reason": "ETF: company fundamentals do not apply",
        },
    }
    prompt = build_signal_explanation_prompt("SPY", signals)
    assert "Comment on fundamental quality" not in prompt
    assert "Note that this is a fund" in prompt


def test_ai_explainer_prompt_etf_lookthrough() -> None:
    """For an ETF with look-through, prompt asks to note that metrics are holdings-weighted."""
    signals = {
        "overall_signal": "BUY",
        "confidence": 0.8,
        "structure": {"trend": "BULLISH"},
        "timing": {"timing": "EARLY"},
        "fear_risk": {"fear_level": "LOW"},
        "momentum": {"bias": "BULLISH", "composite_score": 0.75},
        "fundamental": {
            "quality": "GOOD",
            "composite_score": 0.65,
            "is_etf": True,
            "method": "lookthrough",
            "lookthrough": {"weight_with_fundamentals": 0.85},
        },
    }
    prompt = build_signal_explanation_prompt("QQQ", signals)
    assert "Note that this is a fund" in prompt
    assert "holdings-weighted" in prompt
    assert "Comment on fundamental quality" not in prompt


def test_ai_explainer_prompt_normal_company_asks_quality() -> None:
    """Standard operating company with rated fundamentals asks to comment on fundamental quality."""
    signals = {
        "overall_signal": "BUY",
        "confidence": 0.85,
        "structure": {"trend": "BULLISH"},
        "timing": {"timing": "EARLY"},
        "fear_risk": {"fear_level": "LOW"},
        "momentum": {"bias": "BULLISH", "composite_score": 0.75},
        "fundamental": {
            "quality": "STRONG",
            "composite_score": 0.88,
        },
    }
    prompt = build_signal_explanation_prompt("AAPL", signals)
    assert "Comment on fundamental quality and any standout metrics" in prompt


def test_standout_fundamentals_etf_yield_is_already_percent() -> None:
    # securities.dividend_yield is stored as a percent (2.05 means 2.05%)
    res = _standout_fundamentals({"company_name": "Some Dividend ETF", "dividend_yield": 2.05})
    assert "Yield 2.05%" in res
    assert "205" not in res


def test_explainer_tolerates_null_fundamental() -> None:
    prompt = build_signal_explanation_prompt("XYZ", {"fundamental": None})
    assert "Comment on fundamental quality" not in prompt
