from __future__ import annotations

import sys
import types


class _FakeScheduler:
    def __init__(self):
        self.calls = []

    def add_job(self, *args, **kwargs):
        self.calls.append({"args": args, "kwargs": kwargs})


def test_schedule_startup_backfill_adds_safety_pass(monkeypatch):
    from web_dashboard.scheduler import scheduler_core

    backfill_module = types.ModuleType("scheduler.backfill")
    backfill_module.startup_backfill_check = lambda: None
    backfill_module.startup_performance_metrics_backfill = lambda: None
    monkeypatch.setitem(sys.modules, "scheduler.backfill", backfill_module)

    scheduler = _FakeScheduler()
    scheduler_core._schedule_startup_backfill_jobs(scheduler)

    job_ids = [call["kwargs"]["id"] for call in scheduler.calls]
    assert "startup_backfill" in job_ids
    assert "startup_performance_metrics_backfill" in job_ids
    assert "startup_performance_metrics_backfill_safety" in job_ids
