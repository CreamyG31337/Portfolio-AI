"""Per-ticker article sentiment is stored and shown to the analysis prompts.

The summarizer returns ``ticker_sentiment`` ([{ticker, sentiment, reason}]) for every
symbol it names, but until 2026-11 no save path stored it: the column was empty on
every row, and a video trashing ASUS that also named NVDA reached NVDA's analysis as
one article-level label. These tests pin the round trip.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock

import pytest

from summary_common import sentiment_for_ticker, ticker_sentiment_for_tickers

_SUMMARY = {
    "sentiment": "BEARISH",
    "ticker_sentiment": [
        {"ticker": "MU", "sentiment": "VERY_BEARISH", "reason": "RMA refunds at 17% of retail"},
        {"ticker": "nvda", "sentiment": "neutral", "reason": "mentioned in passing"},
        {"ticker": "SHOP", "sentiment": "BULLISH", "reason": "beat on GMV"},
        {"ticker": "JUNK", "sentiment": "SIDEWAYS", "reason": "invalid enum is dropped"},
    ],
}


# --- helpers -------------------------------------------------------------------------


def test_keeps_only_saved_tickers_and_respells_listing_suffix() -> None:
    kept = ticker_sentiment_for_tickers(_SUMMARY, ["MU", "SHOP.TO"])
    assert kept == [
        {"ticker": "MU", "sentiment": "VERY_BEARISH", "reason": "RMA refunds at 17% of retail"},
        {"ticker": "SHOP.TO", "sentiment": "BULLISH", "reason": "beat on GMV"},
    ]


def test_returns_none_without_tickers_or_entries() -> None:
    assert ticker_sentiment_for_tickers(_SUMMARY, None) is None
    assert ticker_sentiment_for_tickers(_SUMMARY, []) is None
    assert ticker_sentiment_for_tickers({"sentiment": "BEARISH"}, ["MU"]) is None
    assert ticker_sentiment_for_tickers(None, ["MU"]) is None
    assert ticker_sentiment_for_tickers(_SUMMARY, ["AAPL"]) is None
    assert ticker_sentiment_for_tickers(_SUMMARY, [None]) is None


def test_sentiment_for_ticker_reads_list_or_json_string() -> None:
    stored = [
        {"ticker": "MU", "sentiment": "BEARISH", "reason": "r"},
        {"ticker": "NVDA", "sentiment": "NEUTRAL", "reason": ""},
    ]
    assert sentiment_for_ticker(stored, "nvda")["sentiment"] == "NEUTRAL"
    assert sentiment_for_ticker(json.dumps(stored), "MU")["sentiment"] == "BEARISH"
    assert sentiment_for_ticker(stored, "MU.TO")["sentiment"] == "BEARISH"
    assert sentiment_for_ticker(stored, "AMD") is None
    assert sentiment_for_ticker(None, "MU") is None
    assert sentiment_for_ticker("not json", "MU") is None


# --- write path ----------------------------------------------------------------------


def _repo_capturing_sql() -> tuple[Any, MagicMock]:
    from research_repository import ResearchRepository

    repo = object.__new__(ResearchRepository)  # bypass __init__ DB checks
    repo._has_tickers_column = True
    repo._has_source_metadata_column = False
    repo._has_available_at_column = False
    repo.client = MagicMock()
    cursor = MagicMock()
    cursor.fetchone.return_value = ["11111111-1111-1111-1111-111111111111"]
    conn = MagicMock()
    conn.cursor.return_value = cursor
    repo.client.get_connection.return_value.__enter__.return_value = conn
    repo.client.get_connection.return_value.__exit__.return_value = None
    return repo, cursor


@pytest.mark.parametrize("embedding", [None, [0.1, 0.2]])
def test_save_article_writes_ticker_sentiment(embedding: list[float] | None) -> None:
    repo, cursor = _repo_capturing_sql()
    entries = [{"ticker": "MU", "sentiment": "BEARISH", "reason": "r"}]
    repo.save_article(
        title="t",
        url="https://example.com/a",
        tickers=["MU"],
        published_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
        embedding=embedding,
        ticker_sentiment=entries,
    )
    sql, params = cursor.execute.call_args[0]
    assert "ticker_sentiment," in sql
    assert sql.count("%s") == len(params)
    assert json.dumps(entries) in params
    # A later re-save without per-ticker data must not wipe it.
    conflict = sql.split("ON CONFLICT (url) DO UPDATE SET", 1)[1]
    assert "COALESCE(EXCLUDED.ticker_sentiment, research_articles.ticker_sentiment)" in conflict


def test_save_article_without_ticker_sentiment_leaves_column_out() -> None:
    repo, cursor = _repo_capturing_sql()
    repo.save_article(title="t", url="https://example.com/b", tickers=["MU"])
    sql, params = cursor.execute.call_args[0]
    assert "ticker_sentiment" not in sql
    assert sql.count("%s") == len(params)


# --- read paths ----------------------------------------------------------------------


def test_ticker_analysis_prompt_uses_this_tickers_view() -> None:
    from ticker_analysis_service import TickerAnalysisService

    svc = object.__new__(TickerAnalysisService)
    articles = [
        {
            "title": "The ASUS + NVDA nightmare",
            "source": "youtube:GN",
            "published_at": "2026-10-23",
            "sentiment": "BEARISH",
            "summary": "s",
            "ticker_view": {"ticker": "NVDA", "sentiment": "NEUTRAL", "reason": "named, not criticised"},
        },
        {"title": "Plain", "source": "x", "published_at": "2026-10-24", "sentiment": "BULLISH", "summary": ""},
    ]
    text = svc._format_articles(articles)
    assert "The ASUS + NVDA nightmare | youtube:GN | 2026-10-23 | NEUTRAL" in text
    assert "On this ticker: named, not criticised" in text
    assert "Plain | x | 2026-10-24 | BULLISH" in text


def test_meta_bundle_shows_per_ticker_sentiment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("META_ANALYSIS_PHASE3_SECTOR", "false")
    monkeypatch.setenv("META_ANALYSIS_HUMAN_THESIS", "false")
    monkeypatch.setenv("META_ANALYSIS_PHASE_H2", "false")
    monkeypatch.setenv("ARTICLE_EVIDENCE_MAX_PUBLISH_AGE_DAYS", "0")
    import pit_time

    pit_time._column_cache["research_articles"] = (False, None)
    from meta_analysis_service import TickerMetaAnalysisService

    std_row = {
        "id": "550e8400-e29b-41d4-a716-446655440000",
        "updated_at": datetime(2026, 10, 1, tzinfo=timezone.utc),
        "analysis_date": None,
        "summary": "s",
        "analysis_text": "t",
        "stance": "HOLD",
        "sentiment": "NEUTRAL",
        "sentiment_score": 0.0,
        "confidence_score": 0.5,
        "reasoning": "r",
    }
    articles = [
        {
            "id": "11111111-1111-1111-1111-111111111111",
            "title": "Micron Robs Customer",
            "conclusion": "c",
            "sentiment": "NEUTRAL",
            "sentiment_score": 0.0,
            "published_at": None,
            "fetched_at": None,
            "ticker_sentiment": [{"ticker": "MU", "sentiment": "VERY_BEARISH", "reason": "RMA refunds"}],
        },
        {
            "id": "22222222-2222-2222-2222-222222222222",
            "title": "Old row",
            "conclusion": None,
            "sentiment": "BULLISH",
            "sentiment_score": 0.5,
            "published_at": None,
            "fetched_at": None,
            "ticker_sentiment": None,
        },
    ]
    pg = MagicMock()
    pg.execute_query.side_effect = [[std_row], [], [], articles]
    sb = MagicMock()
    sb.supabase.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(
        data=[]
    )
    svc = TickerMetaAnalysisService(ollama=None, supabase=sb, postgres=pg)
    bundle, _, evidence = svc.build_artifact_bundle_with_evidence("MU")
    assert "sentiment_for_MU=VERY_BEARISH (article overall=NEUTRAL)" in bundle
    assert "why: RMA refunds" in bundle
    assert "sentiment=BULLISH score=0.5" in bundle  # old rows fall back unchanged
    assert len(evidence["article_ids"]) == 2
