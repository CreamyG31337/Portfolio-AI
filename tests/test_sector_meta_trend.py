"""Phase H4: sector meta rotation-rank trend memory."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import pytest

from sector_meta_analysis_service import SectorMetaAnalysisService


def _svc(pg: MagicMock | None = None) -> SectorMetaAnalysisService:
    return SectorMetaAnalysisService(
        ollama=MagicMock(),
        supabase=MagicMock(),
        postgres=pg or MagicMock(),
    )


def test_format_rotation_history_block_empty() -> None:
    svc = _svc()
    assert svc._format_rotation_history_block([]) == ""


def test_format_rotation_history_block_delta_note() -> None:
    svc = _svc()
    # Newest-first (as fetched).
    rows = [
        {
            "run_date": date(2026, 7, 15),
            "sector_stance": "BULLISH",
            "rotation_rank": 5,
            "news_pressure": "POSITIVE",
            "momentum_state": "ACCELERATING",
        },
        {
            "run_date": date(2026, 7, 8),
            "sector_stance": "NEUTRAL",
            "rotation_rank": 2,
            "news_pressure": "MIXED",
            "momentum_state": "STABLE",
        },
    ]
    block = svc._format_rotation_history_block(rows)
    assert "### Rotation rank - recent runs (oldest to newest)" in block
    assert "2026-07-08: stance=NEUTRAL | rotation_rank=2" in block
    assert "2026-07-15: stance=BULLISH | rotation_rank=5" in block
    assert block.index("2026-07-08") < block.index("2026-07-15")
    assert "climbed" in block
    assert "Δ=+3" in block


def test_run_sector_meta_appends_rotation_history_when_flag_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("META_ANALYSIS_TREND_MEMORY", "true")
    monkeypatch.setenv("META_ANALYSIS_PHASE3_SECTOR", "true")
    captured: dict[str, str] = {}

    def _fake_collect(*_a, prompt: str = "", **_kw):
        captured["prompt"] = prompt
        return (
            '{"sector":"Energy","sector_stance":"BULLISH","momentum_state":"STABLE",'
            '"news_pressure":"POSITIVE","rotation_rank":3,"confidence":0.5,'
            '"key_drivers":[],"risk_flags":[],"as_of":"2026-07-15T00:00:00Z"}',
            "test-model",
        )

    monkeypatch.setattr(
        "sector_meta_analysis_service.collect_with_summary_model_chain",
        _fake_collect,
    )
    monkeypatch.setattr(
        "sector_meta_analysis_service.get_summarizing_model", lambda _k: "m"
    )

    svc = _svc()
    svc.fetch_etf_articles_for_sector = lambda _s: [  # type: ignore[method-assign]
        {
            "title": "ETF flow note",
            "summary": "Energy inflows",
            "conclusion": None,
            "tickers": ["XLE"],
            "fetched_at": "2026-07-14",
            "sentiment": "POSITIVE",
            "sentiment_score": 0.6,
        }
    ]
    svc._fetch_rotation_history = lambda *_a, **_k: [  # type: ignore[method-assign]
        {
            "run_date": date(2026, 7, 8),
            "sector_stance": "NEUTRAL",
            "rotation_rank": 1,
            "news_pressure": "MIXED",
            "momentum_state": "STABLE",
        }
    ]
    svc._save_row = MagicMock()  # type: ignore[method-assign]

    result = svc.run_sector_meta("Energy")
    assert result is not None
    assert "Rotation rank - recent runs" in captured["prompt"]
    assert "rotation_rank=1" in captured["prompt"]


def test_run_sector_meta_omits_rotation_history_when_flag_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("META_ANALYSIS_TREND_MEMORY", "false")
    monkeypatch.setenv("META_ANALYSIS_PHASE3_SECTOR", "true")
    captured: dict[str, str] = {}

    def _fake_collect(*_a, prompt: str = "", **_kw):
        captured["prompt"] = prompt
        return (
            '{"sector":"Energy","sector_stance":"NEUTRAL","momentum_state":"UNKNOWN",'
            '"news_pressure":"UNKNOWN","rotation_rank":0,"confidence":0.4,'
            '"key_drivers":[],"risk_flags":[],"as_of":"2026-07-15T00:00:00Z"}',
            "test-model",
        )

    monkeypatch.setattr(
        "sector_meta_analysis_service.collect_with_summary_model_chain",
        _fake_collect,
    )
    monkeypatch.setattr(
        "sector_meta_analysis_service.get_summarizing_model", lambda _k: "m"
    )

    svc = _svc()
    svc.fetch_etf_articles_for_sector = lambda _s: [  # type: ignore[method-assign]
        {
            "title": "ETF flow note",
            "summary": "Energy inflows",
            "conclusion": None,
            "tickers": ["XLE"],
            "fetched_at": "2026-07-14",
            "sentiment": "POSITIVE",
            "sentiment_score": 0.6,
        }
    ]

    def _should_not_fetch(*_a, **_k):
        raise AssertionError("_fetch_rotation_history should not run when flag off")

    svc._fetch_rotation_history = _should_not_fetch  # type: ignore[method-assign]
    svc._save_row = MagicMock()  # type: ignore[method-assign]

    svc.run_sector_meta("Energy")
    # Prompt task rule may mention the section name; the injected markdown header must not appear.
    assert "### Rotation rank - recent runs" not in captured["prompt"]
