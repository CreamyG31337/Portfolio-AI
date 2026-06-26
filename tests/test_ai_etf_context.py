#!/usr/bin/env python3
"""Tests for richer ETF context on the AI assistant."""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "web_dashboard"))

from web_dashboard.ai_context_builder import (
    aggregate_etf_changes,
    format_etf_context,
    parse_etf_ticker_from_article_url,
)
from web_dashboard.routes.ai_routes import _filter_etf_analysis_articles


def _sample_changes() -> list[dict]:
    return [
        {
            "date": "2026-06-25",
            "etf_ticker": "SMH",
            "holding_ticker": "AMD",
            "share_change": -60534,
            "action": "SELL",
            "shares_after": 7289632,
        },
        {
            "date": "2026-06-25",
            "etf_ticker": "SMH",
            "holding_ticker": "TSM",
            "share_change": -121505,
            "action": "SELL",
            "shares_after": 14631893,
        },
        {
            "date": "2026-06-25",
            "etf_ticker": "ARKK",
            "holding_ticker": "AMD",
            "share_change": -15224,
            "action": "SELL",
            "shares_after": 562946,
        },
        {
            "date": "2026-06-24",
            "etf_ticker": "SMH",
            "holding_ticker": "MU",
            "share_change": 5000,
            "action": "BUY",
            "shares_after": 3700000,
        },
    ]


def test_aggregate_etf_changes_smh_net_selling() -> None:
    result = aggregate_etf_changes(_sample_changes())
    etf_by_ticker = {row["etf_ticker"]: row for row in result["etf_summary"]}

    assert etf_by_ticker["SMH"]["sell_events"] == 2
    assert etf_by_ticker["SMH"]["buy_events"] == 1
    assert etf_by_ticker["SMH"]["net_shares"] == -177039
    assert etf_by_ticker["SMH"]["tickers_touched"] == 3
    assert "net selling" in etf_by_ticker["SMH"]["direction"].lower()

    amd = next(r for r in result["ticker_summary"] if r["holding_ticker"] == "AMD")
    assert amd["etfs_selling"] == ["ARKK", "SMH"]
    assert amd["net_shares"] == -75758


def test_format_etf_context_empty() -> None:
    text = format_etf_context({"days": 7})
    assert "No ETF activity found" in text


def test_format_etf_context_with_summaries_and_articles() -> None:
    aggregates = aggregate_etf_changes(_sample_changes())
    text = format_etf_context({
        "days": 7,
        "etf_summary": aggregates["etf_summary"],
        "ticker_summary": aggregates["ticker_summary"],
        "recent_trades": [
            {
                "trade_date": "2026-06-25",
                "holding_ticker": "TSM",
                "etf_ticker": "SMH",
                "trade_type": "SELL",
                "shares_change": -121505,
                "shares_after": 14631893,
            }
        ],
        "etf_articles": [
            {
                "etf_ticker": "SMH",
                "title": "SMH Holdings Analysis - 2026-06-25",
                "sentiment": "bearish",
                "summary": "VanEck trimmed semiconductor exposure across holdings.",
                "matched_holdings": ["AMD", "TSM"],
            }
        ],
    })

    assert "ETF Activity Summary" in text
    assert "SMH" in text
    assert "Portfolio tickers — ETF flow" in text
    assert "ETF Analysis Summaries" in text
    assert "Notable ETF Holding Trades" in text
    assert "VanEck trimmed" in text


def test_parse_etf_ticker_from_article_url() -> None:
    assert parse_etf_ticker_from_article_url("etf-analysis://SMH/2026-06-25") == "SMH"
    assert parse_etf_ticker_from_article_url("https://example.com") is None


def test_filter_etf_analysis_articles_overlap_and_dedupe() -> None:
    articles = [
        {
            "id": 1,
            "title": "SMH Holdings Analysis - 2026-06-25",
            "url": "etf-analysis://SMH/2026-06-25",
            "tickers": ["AMD", "TSM"],
            "summary": "older",
            "sentiment": "bearish",
            "fetched_at": "2026-06-24T00:00:00+00:00",
        },
        {
            "id": 2,
            "title": "SMH Holdings Analysis - 2026-06-26",
            "url": "etf-analysis://SMH/2026-06-26",
            "tickers": ["AMD"],
            "summary": "newer",
            "sentiment": "bearish",
            "fetched_at": "2026-06-26T00:00:00+00:00",
        },
        {
            "id": 3,
            "title": "IVV Holdings Analysis - 2026-06-25",
            "url": "etf-analysis://IVV/2026-06-25",
            "tickers": ["AAPL"],
            "summary": "unrelated",
            "sentiment": "neutral",
            "fetched_at": "2026-06-25T00:00:00+00:00",
        },
    ]

    matched = _filter_etf_analysis_articles(
        articles,
        portfolio_tickers=["AMD", "MU"],
        active_etfs={"SMH", "ARKK"},
        max_articles=8,
    )

    assert len(matched) == 1
    assert matched[0]["etf_ticker"] == "SMH"
    assert matched[0]["summary"] == "newer"
    assert matched[0]["matched_holdings"] == ["AMD"]
