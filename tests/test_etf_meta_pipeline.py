"""Unit tests for ETF meta pipeline gap/progress helpers."""

from __future__ import annotations

from etf_meta_pipeline import measure_backfill_progress


def test_measure_backfill_progress_filled_and_new_gaps() -> None:
    before = {("SPY", "2026-05-10"), ("QQQ", "2026-05-11"), ("IWM", "2026-05-12")}
    after = {("IWM", "2026-05-12"), ("ARKK", "2026-05-19")}

    progress = measure_backfill_progress(before, after)

    assert progress.filled == 2
    assert progress.new_gaps == 1
    assert progress.net_delta == -1
    assert progress.filled_pairs == frozenset({("SPY", "2026-05-10"), ("QQQ", "2026-05-11")})
    assert progress.new_pairs == frozenset({("ARKK", "2026-05-19")})


def test_measure_backfill_progress_net_increase_from_watchtower() -> None:
    """New same-day holdings should not be treated as zero progress."""
    before = {("SPY", "2026-05-18")}
    after = {("SPY", "2026-05-18"), ("QQQ", "2026-05-19"), ("IWM", "2026-05-19")}

    progress = measure_backfill_progress(before, after)

    assert progress.filled == 0
    assert progress.new_gaps == 2
    assert progress.net_delta == 2


def test_measure_backfill_progress_all_filled() -> None:
    before = {("SPY", "2026-05-07")}
    after: set[tuple[str, str]] = set()

    progress = measure_backfill_progress(before, after)

    assert progress.filled == 1
    assert progress.new_gaps == 0
    assert progress.net_delta == -1
