"""Tests for Advise v0 ranking (no LLM)."""

from web_dashboard.advise_service import (
    build_advise_recommendations,
    disposition_to_advise,
)


def test_disposition_to_advise_maps_axes() -> None:
    assert disposition_to_advise("bearish", "monitor") == "SELL"
    assert disposition_to_advise("bullish", "seek_entry") == "BUY"
    assert disposition_to_advise("neutral", "monitor") == "WATCH"
    assert disposition_to_advise("bullish", "seek_exit") == "SELL"


def test_build_advise_merges_queue_and_thesis_dual_tension() -> None:
    pack = build_advise_recommendations(
        action_queue=[
            {
                "ticker": "MSFT",
                "action": "BUY",
                "confidence": 0.8,
                "ai_review": {"verdict": "TENSION", "one_liner": "Conflicts"},
                "research_context": {"meta_conviction": "BEARISH"},
            }
        ],
        theses_attention=[
            {
                "id": "t1",
                "ticker": "MSFT",
                "disposition": "bearish",
                "intent": "seek_exit",
                "llm_verdict": "TENSION",
                "attention_reasons": ["tension"],
                "llm_metadata": {
                    "suggested_disposition": "bearish",
                    "suggested_intent": "seek_exit",
                },
            }
        ],
        limit=10,
    )
    assert len(pack) == 1
    row = pack[0]
    assert row["ticker"] == "MSFT"
    assert row["advise"] == "SELL"  # conflict prefers sell
    assert row["dual_tension"] is True
    assert "dual_tension" in row["reasons"]
    assert "meta_conflict" in row["reasons"]


def test_build_advise_ranks_sell_before_buy() -> None:
    pack = build_advise_recommendations(
        action_queue=[
            {"ticker": "AAA", "action": "BUY", "confidence": 0.9},
            {"ticker": "BBB", "action": "SELL", "confidence": 0.6},
        ],
        theses_attention=[],
        limit=10,
    )
    assert [r["ticker"] for r in pack] == ["BBB", "AAA"]


def test_build_advise_thesis_only() -> None:
    pack = build_advise_recommendations(
        action_queue=[],
        theses_attention=[
            {
                "id": "x",
                "ticker": "COST",
                "disposition": "bullish",
                "intent": "monitor",
                "llm_verdict": "STALE_THESIS",
                "attention_reasons": ["stale_thesis"],
            }
        ],
    )
    assert pack[0]["advise"] == "BUY"
    assert pack[0]["thesis_id"] == "x"
