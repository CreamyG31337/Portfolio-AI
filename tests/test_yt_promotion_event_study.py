"""Unit tests for the YouTube promotion event study (no network).

Locks in the guardrails that prevent manufacturing a fake result: entry after
the publish date, dedupe to (ticker, day), company-name matching, and fixed
view buckets from §22.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS = _ROOT / "web_dashboard" / "scripts"
_DISC = _ROOT / "scripts"
for p in (str(_SCRIPTS), str(_ROOT / "web_dashboard"), str(_DISC), str(_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

from yt_discover_channels import TickerTarget  # noqa: E402
from yt_promotion_event_study import (  # noqa: E402
    RawEvent,
    VIEW_HIGH_MIN,
    VIEW_LOW_MAX,
    _close_after,
    classify_match,
    dedupe_events,
    format_attrition_row,
    honesty_label,
    matching_tickers,
    parse_upload_date,
    report_tradeability,
    title_match_candidates,
    view_bucket,
)


class TestParseUploadDate:
    def test_yyyymmdd(self) -> None:
        assert parse_upload_date("20260722") == date(2026, 7, 22)

    def test_rejects_missing(self) -> None:
        assert parse_upload_date(None) is None
        assert parse_upload_date("") is None
        assert parse_upload_date("  ") is None

    def test_rejects_malformed(self) -> None:
        assert parse_upload_date("2026-07-22") is None
        assert parse_upload_date("20261301") is None  # invalid month
        assert parse_upload_date("2026072") is None


class TestCloseAfter:
    def test_skips_same_day_close(self) -> None:
        series = [
            {"date": date(2026, 7, 21), "close": 10.0},
            {"date": date(2026, 7, 22), "close": 11.0},
            {"date": date(2026, 7, 23), "close": 12.0},
        ]
        got = _close_after(series, date(2026, 7, 22))
        assert got == (date(2026, 7, 23), 12.0)

    def test_none_when_no_later_session(self) -> None:
        series = [{"date": date(2026, 7, 22), "close": 11.0}]
        assert _close_after(series, date(2026, 7, 22)) is None


class TestDedupe:
    def test_collapses_same_ticker_day_keeps_highest_views(self) -> None:
        events = [
            RawEvent("aaa", "DNN", date(2026, 7, 1), 5_000, "@A", "t1", "low"),
            RawEvent("bbb", "DNN", date(2026, 7, 1), 80_000, "@B", "t2", "high"),
            RawEvent("ccc", "DNN", date(2026, 7, 2), 3_000, "@A", "t3", "low"),
            RawEvent("ddd", "CCO.TO", date(2026, 7, 1), 12_000, "@A", "t4", "mid"),
        ]
        out = dedupe_events(events)
        assert len(out) == 3
        dnn_day1 = next(e for e in out if e.ticker == "DNN" and e.event_date.day == 1)
        assert dnn_day1.video_id == "bbb"
        assert dnn_day1.view_count == 80_000


class TestTickerMatching:
    def test_company_name_match_not_symbol_alone(self) -> None:
        # The §17 bug: matching symbols alone reports ~0% coverage.
        target = TickerTarget.parse("DNN:Denison")
        assert target.matches("Denison Mines CEO Interview")
        assert matching_tickers("Denison Mines CEO Interview", [target]) == ["DNN"]

    def test_symbol_in_title_still_works(self) -> None:
        target = TickerTarget.parse("DNN:Denison")
        assert target.matches("DNN update with management")

    def test_multi_company_title_classified(self) -> None:
        targets = [
            TickerTarget.parse("DNN:Denison"),
            TickerTarget.parse("NXE.TO:NexGen:Nexgen"),
        ]
        hits = matching_tickers("Denison and NexGen compared", targets)
        assert classify_match(hits) == "multi"

    def test_single_and_none(self) -> None:
        targets = [TickerTarget.parse("GLO.TO:Global Atomic")]
        assert classify_match(matching_tickers("Global Atomic drill update", targets)) == "single"
        assert classify_match(matching_tickers("macro uranium outlook", targets)) == "none"


class TestViewBuckets:
    def test_boundaries_from_section_22(self) -> None:
        assert view_bucket(None) is None
        assert view_bucket(2_350) == "low"
        assert view_bucket(VIEW_LOW_MAX - 1) == "low"
        assert view_bucket(VIEW_LOW_MAX) == "mid"
        assert view_bucket(49_999) == "mid"
        assert view_bucket(VIEW_HIGH_MIN) == "high"
        assert view_bucket(252_000) == "high"


class TestHonestyLabel:
    def test_tiers(self) -> None:
        assert "n<5" in honesty_label(4)
        assert "directional" in honesty_label(15)
        assert "interpretable" in honesty_label(30)


class TestAttritionHelpers:
    def test_format_attrition_row(self) -> None:
        row = format_attrition_row(
            "curated-42",
            {
                "listed": 500,
                "title_matched": 16,
                "title_multi": 1,
                "title_none": 483,
                "desc_demoted_multi": 7,
                "dates_resolved": 9,
                "after_dedupe": 9,
            },
            priced=8,
        )
        assert row.startswith("curated-42:")
        assert "title_single=16" in row
        assert "priced=8" in row

    def test_title_match_candidates_counts(self) -> None:
        target = TickerTarget.parse("DNN:Denison")
        videos = [
            {"video_id": "a", "title": "Denison Mines CEO Interview", "view_count": 1},
            {"video_id": "b", "title": "macro uranium outlook", "view_count": 2},
        ]
        cands, attr = title_match_candidates(videos, [target])
        assert attr["title_matched"] == 1
        assert attr["title_none"] == 1
        assert cands[0]["ticker"] == "DNN"

    def test_tradeability_flags_cse_majority(self, capsys: pytest.CaptureFixture[str]) -> None:
        from canadian_issuer_universe import IssuerTarget
        import re

        targets = [
            IssuerTarget(
                ticker="PHOS.CN",
                exchange="CSE",
                name="First Phosphate",
                patterns=(re.compile(r"PHOS"),),
            )
        ]
        events = [
            RawEvent("v1", "PHOS.CN", date(2026, 7, 1), 200_000, "@X", "t", "high"),
            RawEvent("v2", "PHOS.CN", date(2026, 7, 2), 5_000, "@X", "t", "low"),
        ]
        summary = report_tradeability(events, targets)
        assert summary["counts"]["CSE"] == 2
        assert summary["high_cse_frac"] == 1.0
        captured = capsys.readouterr().out
        assert "TRADEABILITY" in captured
        assert "CSE" in captured
