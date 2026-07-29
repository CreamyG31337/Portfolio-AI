"""Tests for Advise ranking (no LLM)."""

from web_dashboard.advise_service import (
    build_advise_recommendations,
    disposition_to_advise,
    learn_weight_multiplier,
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


def test_learn_weight_multiplier_boosts_and_penalizes() -> None:
    up, reasons = learn_weight_multiplier(
        source_hit_rate=0.70, source_scored=24, verdict_hit_rate=1.0, verdict_scored=8
    )
    assert up > 1.0
    assert any("learn_src+" in r for r in reasons)

    down, reasons2 = learn_weight_multiplier(
        source_hit_rate=0.40, source_scored=50
    )
    assert down < 1.0
    assert any("learn_src-" in r for r in reasons2)

    neutral, _ = learn_weight_multiplier(source_hit_rate=0.70, source_scored=3)
    assert neutral == 1.0


def test_build_advise_v1_learn_and_confluence() -> None:
    base = build_advise_recommendations(
        action_queue=[
            {
                "ticker": "MSFT",
                "action": "BUY",
                "confidence": 0.8,
                "ai_review": {"verdict": "ALIGNED"},
            }
        ],
        theses_attention=[],
    )
    base_score = float(base[0]["score"])

    boosted = build_advise_recommendations(
        action_queue=[
            {
                "ticker": "MSFT",
                "action": "BUY",
                "confidence": 0.8,
                "ai_review": {"verdict": "ALIGNED"},
            }
        ],
        theses_attention=[],
        track_record={
            "hit_rate_by_source": {"action_queue_ai_review": 0.70},
            "counts_by_source": {
                "action_queue_ai_review": {"scored": 24, "hits": 17, "misses": 7}
            },
            "hit_rate_by_verdict": {"ALIGNED": 1.0},
            "counts_by_verdict": {"ALIGNED": {"scored": 8, "hits": 8, "misses": 0}},
        },
        confluence_events=[{"ticker": "MSFT", "direction": "bullish", "score": 4}],
    )
    assert float(boosted[0]["score"]) > base_score
    assert any("learn_src+" in r for r in boosted[0]["reasons"])
    assert "confluence:bullish" in boosted[0]["reasons"]


def test_confluence_risk_downgrades_buy() -> None:
    pack = build_advise_recommendations(
        action_queue=[{"ticker": "XYZ", "action": "BUY", "confidence": 0.9}],
        confluence_events=[{"ticker": "XYZ", "direction": "risk", "score": 3}],
    )
    assert pack[0]["advise"] == "RISK"
    assert "confluence:risk→RISK" in pack[0]["reasons"]
