"""Regression tests for bounded article pipeline execution."""

import time

from web_dashboard.scheduler.article_pipeline import (
    ArticleCounters,
    run_article_pipeline_parallel,
)


def test_single_worker_pipeline_returns_at_deadline() -> None:
    """The default one-worker path must still honor the job deadline."""

    def slow_worker(_item: int) -> ArticleCounters:
        time.sleep(0.25)
        return ArticleCounters(processed=1)

    started = time.time()
    agg = run_article_pipeline_parallel(
        slow_worker,
        [1],
        max_workers=1,
        job_start_time=started,
        max_job_duration_sec=0.05,
    )

    assert time.time() - started < 0.2
    assert agg.processed == 0
