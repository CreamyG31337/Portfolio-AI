"""Tests for Alpha Hunter pure helpers in ``jobs_common``."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

web_dashboard = Path(__file__).resolve().parent.parent / "web_dashboard"
if str(web_dashboard) not in sys.path:
    sys.path.insert(0, str(web_dashboard))

from scheduler.jobs_common import (  # noqa: E402
    is_low_value_alpha_result,
    low_value_alpha_reason,
    relevance_for_logic_check,
    select_alpha_queries,
)

QUERIES_16 = [f"query-{i}" for i in range(16)]


def test_select_alpha_queries_day_zero_first_batch() -> None:
    assert select_alpha_queries(QUERIES_16, 4, 0) == [
        "query-0",
        "query-1",
        "query-2",
        "query-3",
    ]


def test_select_alpha_queries_rotates_by_day() -> None:
    assert select_alpha_queries(QUERIES_16, 4, 1) == [
        "query-4",
        "query-5",
        "query-6",
        "query-7",
    ]
    assert select_alpha_queries(QUERIES_16, 4, 3) == [
        "query-12",
        "query-13",
        "query-14",
        "query-15",
    ]


def test_select_alpha_queries_wraps_after_full_cycle() -> None:
    assert select_alpha_queries(QUERIES_16, 4, 4) == [
        "query-0",
        "query-1",
        "query-2",
        "query-3",
    ]


def test_select_alpha_queries_covers_all_over_four_days() -> None:
    seen: set[str] = set()
    for day in range(4):
        for q in select_alpha_queries(QUERIES_16, 4, day):
            seen.add(q)
    assert seen == set(QUERIES_16)


def test_select_alpha_queries_empty_input() -> None:
    assert select_alpha_queries([], 4, date.today().toordinal()) == []


def test_select_alpha_queries_clamps_n_to_list_length() -> None:
    assert select_alpha_queries(["only"], 99, 0) == ["only"]


def test_relevance_for_logic_check_buckets() -> None:
    assert relevance_for_logic_check("DATA_BACKED") == 0.9
    assert relevance_for_logic_check("HYPE_DETECTED") == 0.1
    assert relevance_for_logic_check("NEUTRAL") == 0.7
    assert relevance_for_logic_check(None) == 0.7
    assert relevance_for_logic_check("something_else") == 0.7


def test_is_low_value_alpha_result_detects_boilerplate() -> None:
    assert is_low_value_alpha_result("Innoviva (INVA) Stock Price & Overview")
    assert is_low_value_alpha_result("AAPL stock quote")
    assert is_low_value_alpha_result("MSFT stock price history")
    assert is_low_value_alpha_result(
        "Perimeter Medical Imaging AI (PYNKF) Stock Price & Overview"
    )


def test_low_value_quote_overview_reason() -> None:
    assert low_value_alpha_reason("Innoviva (INVA) Stock Price & Overview") == "quote_overview"
    assert low_value_alpha_reason("AAPL stock quote") == "quote_overview"
    assert low_value_alpha_reason("MSFT stock price history") == "price_history"


def test_low_value_listing_index_reason() -> None:
    # Real-world index/aggregator pages observed in prod that should be dropped.
    assert (
        low_value_alpha_reason("Latest Azitra Stock News | AMEX:AZTR | Benzinga")
        == "listing_index"
    )
    assert (
        low_value_alpha_reason(
            "Latest Communication Services Stock Analysis Articles | Seeking Alpha"
        )
        == "listing_index"
    )
    assert (
        low_value_alpha_reason("Latest Financial Stocks and REIT Investing Analysis")
        == "listing_index"
    )


def test_is_low_value_alpha_result_allows_real_analysis() -> None:
    # Verified-real saves from prod runs must NOT be filtered.
    legit = [
        "Replimune: Modeling The Coin Flip Of FDA Approval",
        "Milestone Pharmaceuticals: Here Comes The Revenue Ramp",
        "Kyverna Therapeutics vs. Vertex Pharmaceuticals: Which Drug Stock Wins",
        "Artificial Heart Maker Picard Medical's Stock Surges 15% After Earnings",
        "Trevi Therapeutics Is Up 100%, Pivotal bioVenture Adds Anyway",
        "Can Medtronic Finally Challenge Intuitive Surgical's Robotic Dominance",
        "5 Best Infrastructure Stocks for 2026 and How to Invest",
        # Starts with a word other than "Latest" -> not a listing match.
        "Analysis: Why This Microcap Could Double",
    ]
    for title in legit:
        assert not is_low_value_alpha_result(title), title
        assert low_value_alpha_reason(title) is None, title
