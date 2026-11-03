"""Newsletters reach ticker / meta analysis, with their sentiment saved.

Until 2026-11 newsletters were summarized and ticker-tagged but only shown in the
newsletter UI, and only ``summary`` + ``tickers`` were saved (sentiment, claims,
conclusion and per-ticker sentiment were thrown away).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock

import pytest

_NL = {
    "id": "aaaaaaaa-0000-0000-0000-000000000001",
    "sender_name": "Phil Rosen",
    "subject": "Opening Bell: Micron's margin problem",
    "summary": "• Memory pricing is rolling over.",
    "sentiment": "BEARISH",
    "conclusion": "Memory makers face a cyclical top.",
    "ticker_sentiment": [{"ticker": "MU", "sentiment": "VERY_BEARISH", "reason": "DRAM contract prices down 8%"}],
    "received_at": datetime(2026, 11, 2, tzinfo=timezone.utc),
}


def test_persist_saves_analysis_fields_for_saved_tickers() -> None:
    from newsletter_service import _persist_newsletter_analysis_fields

    repo = MagicMock()
    summary_data = {
        "sentiment": "BEARISH",
        "sentiment_score": -0.6,
        "claims": ["DRAM down 8%"],
        "fact_check": "f",
        "conclusion": "c",
        "logic_check": "l",
        "ticker_sentiment": [
            {"ticker": "MU", "sentiment": "BEARISH", "reason": "r"},
            {"ticker": "NVDA", "sentiment": "NEUTRAL", "reason": "dropped by validator"},
        ],
    }
    _persist_newsletter_analysis_fields(repo, "nl-1", summary_data, ["MU"])
    sql, params = repo.client.execute_update.call_args[0]
    assert "UPDATE newsletters" in sql and "ticker_sentiment" in sql
    assert sql.count("%s") == len(params)
    assert params[0] == "BEARISH" and params[1] == -0.6
    assert json.loads(params[2]) == ["DRAM down 8%"]
    assert json.loads(params[6]) == [{"ticker": "MU", "sentiment": "BEARISH", "reason": "r"}]
    assert params[-1] == "nl-1"


def test_persist_never_raises_and_skips_non_dict() -> None:
    from newsletter_service import _persist_newsletter_analysis_fields

    repo = MagicMock()
    _persist_newsletter_analysis_fields(repo, "nl-1", "plain summary", ["MU"])
    repo.client.execute_update.assert_not_called()
    repo.client.execute_update.side_effect = RuntimeError("db down")
    _persist_newsletter_analysis_fields(repo, "nl-1", {"sentiment": "BULLISH"}, None)  # no raise


def test_fetch_filters_by_ticker_and_attaches_view() -> None:
    from newsletter_repository import fetch_newsletters_for_ticker

    pg = MagicMock()
    pg.execute_query.return_value = [dict(_NL)]
    rows = fetch_newsletters_for_ticker(pg, "mu", limit=3)
    sql, params = pg.execute_query.call_args[0]
    assert "tickers @> ARRAY[%s]::text[]" in sql and "processed_at IS NOT NULL" in sql
    assert params == ("MU", 30, 3)
    assert rows[0]["ticker_view"]["sentiment"] == "VERY_BEARISH"


def test_fetch_returns_empty_on_error_or_blank_ticker() -> None:
    from newsletter_repository import fetch_newsletters_for_ticker

    pg = MagicMock()
    pg.execute_query.side_effect = RuntimeError("no table")
    assert fetch_newsletters_for_ticker(pg, "MU") == []
    assert fetch_newsletters_for_ticker(pg, "  ") == []


def test_ticker_analysis_prompt_includes_newsletters() -> None:
    from ticker_analysis_service import TickerAnalysisService

    svc = object.__new__(TickerAnalysisService)
    nl = {**_NL, "ticker_view": _NL["ticker_sentiment"][0]}
    text = svc._format_newsletters([nl, {**_NL, "ticker_view": None, "conclusion": None}])
    assert "Phil Rosen | Opening Bell: Micron's margin problem | 2026-11-02 | VERY_BEARISH" in text
    assert "On this ticker: DRAM contract prices down 8%" in text
    assert "Summary: Memory makers face a cyclical top." in text
    assert "| BEARISH" in text  # falls back to newsletter-level sentiment
    assert "Summary: • Memory pricing is rolling over." in text  # falls back to summary
    assert svc._format_newsletters([]) == ""


def test_meta_bundle_includes_newsletters_with_own_evidence_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("META_ANALYSIS_PHASE3_SECTOR", "false")
    monkeypatch.setenv("META_ANALYSIS_HUMAN_THESIS", "false")
    monkeypatch.setenv("META_ANALYSIS_PHASE_H2", "false")
    monkeypatch.setenv("ARTICLE_EVIDENCE_MAX_PUBLISH_AGE_DAYS", "0")
    import pit_time

    pit_time._column_cache["research_articles"] = (False, None)
    import newsletter_repository

    from summary_common import sentiment_for_ticker

    monkeypatch.setattr(
        newsletter_repository,
        "fetch_newsletters_for_ticker",
        lambda pg, t, **k: [{**_NL, "ticker_view": sentiment_for_ticker(_NL["ticker_sentiment"], t)}],
    )
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
    article = {
        "id": "11111111-1111-1111-1111-111111111111",
        "title": "A",
        "conclusion": None,
        "sentiment": "NEUTRAL",
        "sentiment_score": 0.0,
        "published_at": None,
        "fetched_at": None,
        "ticker_sentiment": None,
    }
    pg = MagicMock()
    pg.execute_query.side_effect = [[std_row], [], [], [article]]
    sb = MagicMock()
    sb.supabase.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(
        data=[]
    )
    svc = TickerMetaAnalysisService(ollama=None, supabase=sb, postgres=pg)
    bundle, _, evidence = svc.build_artifact_bundle_with_evidence("MU")
    assert "### Newsletters (user subscriptions, last 30 days)" in bundle
    assert "sentiment_for_MU=VERY_BEARISH" in bundle
    assert "why: DRAM contract prices down 8%" in bundle
    assert "newsletters" in evidence["artifact_types"]
    assert evidence["newsletter_ids"] == [_NL["id"]]
    # Newsletter ids never leak into article_ids (other code joins those to research_articles).
    assert evidence["article_ids"] == ["11111111-1111-1111-1111-111111111111"]
