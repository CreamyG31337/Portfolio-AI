#!/usr/bin/env python3
"""
Chat context types for the Flask AI assistant.

Streamlit-specific ChatContextManager was removed in the Flask migration;
this module keeps the shared ContextItemType enum used by ai_routes and
ai_chat_handler.
"""

from enum import Enum


class ContextItemType(Enum):
    """Types of context items that can be added to AI chat."""

    HOLDINGS = "holdings"
    THESIS = "thesis"
    TRADES = "trades"
    PERFORMANCE_CHART = "performance_chart"
    METRICS = "metrics"
    CASH_BALANCES = "cash_balances"
    INVESTOR_ALLOCATIONS = "investor_allocations"
    PNL_CHART = "pnl_chart"
    SECTOR_ALLOCATION = "sector_allocation"
    SEARCH_RESULTS = "search_results"
