"""Unit tests for sector_meta_normalization (Phase 3b contract)."""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

web_dashboard = Path(__file__).resolve().parent.parent / "web_dashboard"
if str(web_dashboard) not in sys.path:
    sys.path.insert(0, str(web_dashboard))

from sector_meta_normalization import (  # noqa: E402
    invalid_sector_meta_enum_fields,
    normalize_sector_meta_payload,
)


def test_invalid_sector_meta_enum_fields_detects_drift() -> None:
    raw = {"sector_stance": "BULL", "momentum_state": "FAST", "news_pressure": "GOOD"}
    bad = invalid_sector_meta_enum_fields(raw)
    joined = "".join(bad)
    assert "sector_stance=" in joined
    assert "momentum_state=" in joined
    assert "news_pressure=" in joined


def test_normalize_sector_meta_payload_clamps_enums() -> None:
    now = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
    out = normalize_sector_meta_payload(
        {
            "sector_stance": "BULL",
            "momentum_state": "unknownish",
            "news_pressure": "NEGATIVE",
            "rotation_rank": "3",
            "confidence": "0.5",
            "key_drivers": ["a"],
            "risk_flags": "x",
            "as_of": "2026-05-01T12:00:00Z",
        },
        sector_label="Technology",
        as_of_fallback=now,
    )
    assert out["sector_stance"] == "INSUFFICIENT_DATA"
    assert out["momentum_state"] == "UNKNOWN"
    assert out["news_pressure"] == "NEGATIVE"
    assert out["rotation_rank"] == 3
    assert out["confidence"] == 0.5
    assert out["key_drivers"] == ["a"]
    assert out["risk_flags"] == ["x"]
    assert out["sector"] == "Technology"


def test_normalize_sector_meta_payload_empty_lists() -> None:
    now = datetime(2026, 5, 1, tzinfo=UTC)
    out = normalize_sector_meta_payload(None, sector_label="X", as_of_fallback=now)
    assert out["sector_stance"] == "INSUFFICIENT_DATA"
    assert out["key_drivers"] == []
    assert out["risk_flags"] == []


def test_phase3_sector_feature_flag_env(monkeypatch: pytest.MonkeyPatch) -> None:
    import settings as settings_mod

    monkeypatch.delenv("META_ANALYSIS_PHASE3_SECTOR", raising=False)
    assert settings_mod.is_meta_analysis_phase3_sector_enabled() is False
    monkeypatch.setenv("META_ANALYSIS_PHASE3_SECTOR", "true")
    assert settings_mod.is_meta_analysis_phase3_sector_enabled() is True
