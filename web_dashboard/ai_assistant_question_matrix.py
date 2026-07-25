#!/usr/bin/env python3
"""Acceptance question matrix for AI Assistant pulse + tool wiring.

Each family documents which tools (or pulse fields) must be available so the
chat path can answer intelligently without dumping the full research corpus.
"""

from __future__ import annotations

from typing import Any, TypedDict


class QuestionFamily(TypedDict):
    id: int
    family: str
    example: str
    expected_tools: list[str]
    pulse_fields: list[str]
    notes: str


QUESTION_MATRIX: list[QuestionFamily] = [
    {
        "id": 1,
        "family": "discovery_timing",
        "example": "What stock has a good entry point right now?",
        "expected_tools": ["list_entry_candidates"],
        "pulse_fields": ["candidates", "market"],
        "notes": "Pulse may answer; tool refreshes/filters candidates.",
    },
    {
        "id": 2,
        "family": "market",
        "example": "What's the market doing today?",
        "expected_tools": ["get_market_brief"],
        "pulse_fields": ["market"],
        "notes": "Pulse has headline/regime; tool adds narrative.",
    },
    {
        "id": 3,
        "family": "sector",
        "example": "How is Healthcare / biotech rotating?",
        "expected_tools": ["get_sector_rotation"],
        "pulse_fields": [],
        "notes": "Sector meta only via tool.",
    },
    {
        "id": 4,
        "family": "sector_discovery",
        "example": "Best setups in Energy right now?",
        "expected_tools": ["list_entry_candidates", "get_ticker_setup"],
        "pulse_fields": [],
        "notes": "list_entry_candidates must accept sector=.",
    },
    {
        "id": 5,
        "family": "holdings_advice",
        "example": "Should I add more XYZ / trim XYZ?",
        "expected_tools": ["get_ticker_setup", "get_holdings_snapshot"],
        "pulse_fields": [],
        "notes": "Combine portfolio facts with ticker setup.",
    },
    {
        "id": 6,
        "family": "holdings_risk",
        "example": "Any of my holdings look risky?",
        "expected_tools": ["list_entry_candidates", "get_signals_overview"],
        "pulse_fields": ["candidates"],
        "notes": "held_only / action=RISK|SELL filters.",
    },
    {
        "id": 7,
        "family": "specific_ticker",
        "example": "Tell me about ABC / Is ABC a buy?",
        "expected_tools": ["get_ticker_setup"],
        "pulse_fields": [],
        "notes": "Never invent entry zones.",
    },
    {
        "id": 8,
        "family": "news",
        "example": "Any news on ABC?",
        "expected_tools": ["search_web", "search_research"],
        "pulse_fields": [],
        "notes": "GLM path uses tools; not always-on prefetch.",
    },
    {
        "id": 9,
        "family": "multi_ticker",
        "example": "Compare DEF vs GHI for an entry",
        "expected_tools": ["get_ticker_setup"],
        "pulse_fields": [],
        "notes": "Expect two get_ticker_setup calls in one round.",
    },
    {
        "id": 10,
        "family": "overview",
        "example": "What should I focus on today?",
        "expected_tools": ["get_signals_overview", "list_entry_candidates"],
        "pulse_fields": ["market", "candidates"],
        "notes": "Pulse + optional signals overview.",
    },
    {
        "id": 11,
        "family": "portfolio_performance",
        "example": "How has the fund done over the last year / since inception?",
        "expected_tools": ["get_portfolio_performance", "get_trade_history"],
        "pulse_fields": [],
        "notes": "Windowed performance/curve; window='all' for inception.",
    },
    {
        "id": 12,
        "family": "event_investigation",
        "example": "Why did ABC drop last month? What moved it?",
        "expected_tools": ["get_price_history", "search_web"],
        "pulse_fields": [],
        "notes": "price_history biggest_moves -> search_web(time_range) for the cause.",
    },
    {
        "id": 13,
        "family": "track_record",
        "example": "Which of our signals/sources have actually been right lately?",
        "expected_tools": ["get_track_record"],
        "pulse_fields": [],
        "notes": "Learn-layer hit rate / excess return by source/verdict/domain; not a live signal.",
    },
    {
        "id": 14,
        "family": "thesis_attention",
        "example": "Which of my thesis threads need a review / look stale or in tension?",
        "expected_tools": ["get_theses_attention"],
        "pulse_fields": [],
        "notes": "Advisory human threads flagged due/stale/weak or LLM TENSION/STALE_THESIS.",
    },
    {
        "id": 15,
        "family": "confluence",
        "example": "Any tickers where multiple signals are stacking up right now?",
        "expected_tools": ["get_confluence"],
        "pulse_fields": [],
        "notes": "Independent signal families aligning; score = how many, direction bullish/risk.",
    },
    {
        "id": 16,
        "family": "ideas_triage",
        "example": "What new ideas came in this week that I haven't looked at?",
        "expected_tools": ["get_ideas_triage"],
        "pulse_fields": [],
        "notes": "Untriaged Alpha Research/Opportunity Discovery; confirm with get_ticker_setup.",
    },
    {
        "id": 17,
        "family": "earnings",
        "example": "Do any of my holdings report earnings soon?",
        "expected_tools": ["get_earnings_calendar", "get_holdings_snapshot"],
        "pulse_fields": [],
        "notes": "get_holdings_snapshot tickers -> get_earnings_calendar(tickers=...).",
    },
]

# Tools that must exist in the v1 catalog (union of matrix expectations).
REQUIRED_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "list_entry_candidates",
        "get_ticker_setup",
        "get_market_brief",
        "get_sector_rotation",
        "get_signals_overview",
        "get_holdings_snapshot",
        "get_portfolio_performance",
        "get_trade_history",
        "get_price_history",
        "get_track_record",
        "get_theses_attention",
        "get_confluence",
        "get_ideas_triage",
        "get_earnings_calendar",
        "search_web",
        "search_research",
    }
)


def matrix_by_family() -> dict[str, QuestionFamily]:
    return {row["family"]: row for row in QUESTION_MATRIX}


def expected_tools_for_family(family: str) -> list[str]:
    row = matrix_by_family().get(family)
    return list(row["expected_tools"]) if row else []


def matrix_as_dict() -> list[dict[str, Any]]:
    return [dict(row) for row in QUESTION_MATRIX]
