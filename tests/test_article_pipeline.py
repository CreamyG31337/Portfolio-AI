"""Tests for ``web_dashboard.scheduler.article_pipeline`` parallel runner."""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from web_dashboard.ollama_client import OllamaHostBusyError
from web_dashboard.scheduler.article_pipeline import (
    ArticleCounters,
    get_research_article_worker_count,
    run_article_pipeline_parallel,
)


def test_article_counters_add() -> None:
    a = ArticleCounters(processed=1, saved=2, skipped=3, blacklisted=1, irrelevant=1, failed=1)
    b = ArticleCounters(processed=2, saved=1, skipped=0, blacklisted=0, irrelevant=2, failed=0)
    c = a + b
    assert c == ArticleCounters(processed=3, saved=3, skipped=3, blacklisted=1, irrelevant=3, failed=1)


def test_get_research_article_worker_count_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RESEARCH_ARTICLE_WORKERS", "5")
    with patch("web_dashboard.settings.get_system_setting", side_effect=RuntimeError("no settings")):
        assert get_research_article_worker_count() == 5


def test_get_research_article_worker_count_clamped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RESEARCH_ARTICLE_WORKERS", "999")
    with patch("web_dashboard.settings.get_system_setting", side_effect=RuntimeError("no settings")):
        assert get_research_article_worker_count() == 32


def test_run_article_pipeline_parallel_serial() -> None:
    calls: list[int] = []

    def worker(x: int) -> ArticleCounters:
        calls.append(x)
        return ArticleCounters(saved=1, processed=1)

    start = time.time()
    agg = run_article_pipeline_parallel(
        worker,
        [1, 2, 3],
        max_workers=1,
        job_start_time=start,
        max_job_duration_sec=3600.0,
    )
    assert calls == [1, 2, 3]
    assert agg.saved == 3
    assert agg.processed == 3


def test_run_article_pipeline_parallel_bounded() -> None:
    def worker(_: int) -> ArticleCounters:
        return ArticleCounters(skipped=1)

    start = time.time()
    agg = run_article_pipeline_parallel(
        worker,
        list(range(10)),
        max_workers=3,
        job_start_time=start,
        max_job_duration_sec=3600.0,
    )
    assert agg.skipped == 10


def test_run_article_pipeline_parallel_host_busy_error_does_not_abort_others() -> None:
    def worker(i: int) -> ArticleCounters:
        if i == 0:
            raise OllamaHostBusyError("slot busy")
        return ArticleCounters(saved=1)

    start = time.time()
    agg = run_article_pipeline_parallel(
        worker,
        [0, 1, 2],
        max_workers=3,
        job_start_time=start,
        max_job_duration_sec=3600.0,
    )
    assert agg.failed == 1
    assert agg.saved == 2


def test_run_article_pipeline_respects_job_deadline() -> None:
    def worker(_: int) -> ArticleCounters:
        time.sleep(0.05)
        return ArticleCounters(saved=1)

    start = time.time() - 10.0
    agg = run_article_pipeline_parallel(
        worker,
        [1, 2, 3, 4, 5],
        max_workers=2,
        job_start_time=start,
        max_job_duration_sec=0.01,
    )
    assert agg.saved < 5


def test_run_article_pipeline_returns_when_a_worker_hangs() -> None:
    """Regression: a single hung worker must not block the runner past its deadline.

    A prior bug (root cause of the 1h ``alpha_research`` watchdog kills on
    2026-05-20 and 2026-05-22) was that ``wait(pending, ...)`` had no timeout, so
    one stuck article worker pinned the entire job until the global stale-AI-lock
    watchdog fired at 1h. The runner now caps its wait by the remaining job
    deadline and returns even when in-flight work is abandoned.
    """

    started = []
    finished = []

    def worker(i: int) -> ArticleCounters:
        started.append(i)
        if i == 0:
            # Simulate a hung HTTP call / slow upstream: never returns within the test budget.
            time.sleep(60)
            finished.append(i)
            return ArticleCounters(saved=1)
        finished.append(i)
        return ArticleCounters(saved=1)

    start = time.time()
    agg = run_article_pipeline_parallel(
        worker,
        [0, 1, 2],
        max_workers=2,
        job_start_time=start,
        max_job_duration_sec=0.5,
    )
    elapsed = time.time() - start

    assert elapsed < 5.0, (
        f"Runner blocked for {elapsed:.2f}s; expected to return within job deadline "
        "even when a worker hangs."
    )
    # Item 1 (or 2) should have completed; item 0 is the hung one and may be abandoned.
    assert agg.saved >= 1
    assert 0 in started
