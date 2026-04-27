"""Unit tests for UI AI summary digest stability (no Flask, no DB)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

web_dashboard = Path(__file__).resolve().parent.parent / "web_dashboard"
if str(web_dashboard) not in sys.path:
    sys.path.insert(0, str(web_dashboard))

from dashboard_portfolio_digest import digest_fingerprint  # noqa: E402
from ui_ai_summary_scopes import (  # noqa: E402
    make_global_scope_key,
    make_portfolio_scope_key,
    scope_dashboard_portfolio,
)
from ui_ai_phase2_digests import build_research_feed_digest, build_signals_overview_digest  # noqa: E402
from ui_ai_summary_service import sha256_hex  # noqa: E402


def test_digest_fingerprint_stable_key_order() -> None:
    a = {"z": 1, "a": 2, "m": {"nested": True}}
    b = {"a": 2, "m": {"nested": True}, "z": 1}
    assert digest_fingerprint(a) == digest_fingerprint(b)


def test_sha256_hex_deterministic() -> None:
    assert sha256_hex("hello") == sha256_hex("hello")
    assert sha256_hex("a") != sha256_hex("b")


def test_make_portfolio_scope_key() -> None:
    assert make_portfolio_scope_key("TEST", "cad", "all") == "TEST|CAD|ALL"


def test_scope_dashboard_portfolio() -> None:
    assert scope_dashboard_portfolio() == "dashboard.portfolio_overview"


def test_make_global_scope_key() -> None:
    assert make_global_scope_key("7d") == "global|7D"


def test_json_roundtrip_summary_shape() -> None:
    payload = {"headline": "H", "narrative": "N", "bullets": ["a", "b"]}
    s = json.dumps(payload, sort_keys=True)
    assert json.loads(s)["headline"] == "H"


def test_build_research_feed_digest_shape() -> None:
    class _PG:
        def execute_query(self, _query: str, _params: tuple[object, ...]):
            return [
                {
                    "title": "A",
                    "source": "Src1",
                    "sentiment": "bullish",
                    "conclusion": "Conclusion A",
                    "tickers": ["ABC"],
                },
                {
                    "title": "B",
                    "source": "Src2",
                    "sentiment": "neutral",
                    "summary": "Summary B",
                    "tickers": [],
                },
            ]

    digest = build_research_feed_digest(_PG(), days=7, limit=5)
    assert digest["article_count"] == 2
    assert "highlights" in digest
    assert digest["sentiment_counts"]["bullish"] == 1


def test_build_signals_overview_digest_shape(monkeypatch) -> None:
    monkeypatch.setattr(
        "ui_ai_phase2_digests.get_active_watchlist_rows",
        lambda _client: [{"ticker": "ABC"}, {"ticker": "XYZ"}],
    )

    class _Result:
        def __init__(self, data):
            self.data = data

    class _Table:
        def __init__(self):
            self._data = [
                {
                    "ticker": "ABC",
                    "overall_signal": "BUY",
                    "confidence_score": 0.8,
                    "fear_risk_signal": {"fear_level": "LOW", "risk_score": 11},
                    "analysis_date": "2026-04-26T10:00:00Z",
                }
            ]

        def select(self, _x):
            return self

        def in_(self, _k, _v):
            return self

        def order(self, _k, desc=False):
            return self

        def execute(self):
            return _Result(self._data)

    class _Client:
        def __init__(self):
            self.supabase = self

        def table(self, _name):
            return _Table()

    digest = build_signals_overview_digest(_Client())
    assert digest["watchlist_count"] == 2
    assert digest["signal_counts"]["BUY"] == 1
