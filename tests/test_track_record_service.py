"""Tests for track_record_service NaN handling."""

from decimal import Decimal

from web_dashboard.track_record_service import _hit_from_row, build_track_record_summary


def test_hit_from_row_rejects_nan_excess() -> None:
    assert _hit_from_row({"stance": "BULLISH", "excess_return": Decimal("NaN")}) is None
    assert _hit_from_row({"stance": "BULLISH", "excess_return": Decimal("1.5")}) is True


def test_build_track_record_summary_skips_nan_rows() -> None:
    class FakePg:
        def execute_query(self, query: str, params: tuple[int, ...] | None = None) -> list[dict]:
            return [
                {
                    "source": "ticker_meta_analysis",
                    "stance": "BULLISH",
                    "confidence": 0.7,
                    "metadata": {},
                    "excess_return": Decimal("NaN"),
                    "ticker_return": Decimal("NaN"),
                    "benchmark_return": Decimal("1.0"),
                    "ticker": "BAD",
                    "as_of": "2026-06-11",
                },
                {
                    "source": "ticker_meta_analysis",
                    "stance": "BULLISH",
                    "confidence": 0.7,
                    "metadata": {},
                    "excess_return": Decimal("2.0"),
                    "ticker_return": Decimal("3.0"),
                    "benchmark_return": Decimal("1.0"),
                    "ticker": "GOOD",
                    "as_of": "2026-06-11",
                },
            ]

    summary = build_track_record_summary(FakePg(), horizon_days=7)
    assert summary["total_scored"] == 2
    counts = summary["counts_by_source"]["ticker_meta_analysis"]
    assert counts["unscoreable"] == 1
    assert counts["hits"] == 1
    assert counts["scored"] == 1
