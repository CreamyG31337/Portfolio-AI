"""rss_feed_ingest must actually be scheduled.

It sat in AVAILABLE_JOBS with enabled_by_default=True from early 2026 but was never
passed to scheduler.add_job, so the RSS feeds were only ever fetched by hand.
"""

from __future__ import annotations

from typing import Any


class _RecordingScheduler:
    def __init__(self) -> None:
        self.jobs: dict[str, dict[str, Any]] = {}

    def add_job(self, func: Any, *args: Any, **kwargs: Any) -> None:
        self.jobs[kwargs.get("id") or getattr(func, "__name__", repr(func))] = {"func": func, **kwargs}

    def __getattr__(self, _name: str) -> Any:
        # register_default_jobs may call other scheduler helpers; they are irrelevant here.
        return lambda *a, **k: None


def test_rss_feed_ingest_is_registered_every_three_hours() -> None:
    from scheduler.jobs import AVAILABLE_JOBS, register_default_jobs, rss_feed_ingest_job

    sched = _RecordingScheduler()
    register_default_jobs(sched)

    assert AVAILABLE_JOBS["rss_feed_ingest"]["enabled_by_default"] is True
    job = sched.jobs.get("rss_feed_ingest")
    assert job is not None, "rss_feed_ingest is enabled but was never scheduled"
    assert job["func"] is rss_feed_ingest_job
    assert job["trigger"].interval.total_seconds() == 180 * 60
    assert job["max_instances"] == 1
