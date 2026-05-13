"""Pure unit tests for market regime normalization (Phase 2a)."""

from datetime import date, datetime, UTC
from pathlib import Path
import sys

web_dashboard = Path(__file__).resolve().parent.parent / "web_dashboard"
if str(web_dashboard) not in sys.path:
    sys.path.insert(0, str(web_dashboard))

from market_regime_normalization import invalid_regime_enum_fields, merge_regime_for_storage, normalize_market_regime  # noqa: E402


def test_normalize_legacy_risk_tone_aliases_to_risk_regime():
    canon = normalize_market_regime(
        {"risk_tone": "RISK_OFF", "leadership_note": "Small caps lag", "caveats": ["thin vol"]},
        brief_date=date(2026, 5, 1),
        updated_at=datetime(2026, 5, 2, 1, 0, tzinfo=UTC),
    )
    assert canon["risk_regime"] == "RISK_OFF"
    assert canon["breadth_proxy"] == "UNCLEAR"
    assert canon["volatility_state"] == "UNKNOWN"
    assert canon["macro_themes"] == []
    assert canon["leadership_note"] == "Small caps lag"
    assert canon["caveats"] == ["thin vol"]
    assert canon["as_of"].startswith("2026-05-02")
    assert 0.0 <= canon["regime_confidence"] <= 1.0


def test_normalize_prefers_updated_at_iso_string():
    canon = normalize_market_regime(
        {"risk_regime": "NEUTRAL"},
        brief_date=date(2026, 1, 15),
        updated_at="2026-01-16T15:30:45Z",
    )
    assert "2026-01-16" in canon["as_of"]
    assert canon["risk_regime"] == "NEUTRAL"


def test_normalize_fallback_as_of_when_no_updated():
    canon = normalize_market_regime(
        {},
        brief_date=date(2026, 3, 10),
        updated_at=None,
    )
    assert canon["as_of"].startswith("2026-03-10")
    assert canon["risk_regime"] == "NEUTRAL"


def test_normalize_full_contract():
    canon = normalize_market_regime(
        {
            "risk_regime": "MIXED",
            "regime_confidence": 0.71,
            "breadth_proxy": "LEADERSHIP_NARROW",
            "volatility_state": "ELEVATED",
            "macro_themes": ["rates", "earnings breadth", "", "ignored empty"],
            "leadership_note": "QQQ-led",
            "caveats": ["one"],
        },
        brief_date="2026-06-01",
        updated_at=None,
    )
    assert canon["risk_regime"] == "MIXED"
    assert abs(canon["regime_confidence"] - 0.71) < 1e-6
    assert canon["breadth_proxy"] == "LEADERSHIP_NARROW"
    assert canon["volatility_state"] == "ELEVATED"
    assert canon["macro_themes"] == ["rates", "earnings breadth", "ignored empty"]


def test_merge_regime_keeps_unknown_llm_keys():
    merged = merge_regime_for_storage(
        {"risk_tone": "RISK_ON", "custom_note_from_model": "x"},
        brief_date=date(2026, 7, 1),
    )
    assert merged["custom_note_from_model"] == "x"
    assert merged["risk_regime"] == "RISK_ON"
    assert "as_of" in merged


def test_invalid_regime_enum_fields_detects_drift():
    issues = invalid_regime_enum_fields(
        {"risk_regime": "BANANA", "breadth_proxy": "LEADERSHIP_BROAD", "volatility_state": "ZZZ"}
    )
    assert any("risk_regime" in x for x in issues)
    assert any("volatility_state" in x for x in issues)
    assert not any("breadth_proxy" in x for x in issues)


def test_invalid_regime_enum_fields_empty_when_clean():
    assert invalid_regime_enum_fields({"risk_regime": "NEUTRAL", "breadth_proxy": "UNCLEAR"}) == []

