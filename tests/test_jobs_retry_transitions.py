from __future__ import annotations

import sys
import types


def _install_retry_job_stubs(
    monkeypatch,
    retry_count: int,
    raise_error: Exception,
    job_name: str = "update_portfolio_prices",
) -> dict[str, list]:
    calls: dict[str, list] = {
        "mark_retrying": [],
        "mark_resolved": [],
        "mark_abandoned": [],
        "mark_pending_retry": [],
        "populate_performance_metrics_job": [],
    }

    job_tracking = types.ModuleType("utils.job_tracking")

    def get_pending_retries(max_retries=3, max_age_days=7, limit=5):
        return [{
            "job_name": job_name,
            "target_date": "2026-04-27",
            "entity_id": "",
            "entity_type": "all_funds",
            "retry_count": retry_count,
            "failure_reason": "test_failure",
        }]

    def mark_retrying(*args, **kwargs):
        calls["mark_retrying"].append((args, kwargs))

    def mark_resolved(*args, **kwargs):
        calls["mark_resolved"].append((args, kwargs))

    def mark_abandoned(*args, **kwargs):
        calls["mark_abandoned"].append((args, kwargs))

    def mark_pending_retry(*args, **kwargs):
        calls["mark_pending_retry"].append((args, kwargs))

    job_tracking.get_pending_retries = get_pending_retries
    job_tracking.mark_retrying = mark_retrying
    job_tracking.mark_resolved = mark_resolved
    job_tracking.mark_abandoned = mark_abandoned
    job_tracking.mark_pending_retry = mark_pending_retry

    jobs_portfolio = types.ModuleType("scheduler.jobs_portfolio")

    def backfill_portfolio_prices_range(*args, **kwargs):
        raise raise_error

    jobs_portfolio.backfill_portfolio_prices_range = backfill_portfolio_prices_range

    jobs_metrics = types.ModuleType("scheduler.jobs_metrics")

    def populate_performance_metrics_job(*args, **kwargs):
        calls["populate_performance_metrics_job"].append((args, kwargs))
        if raise_error:
            raise raise_error

    jobs_metrics.populate_performance_metrics_job = populate_performance_metrics_job

    supabase_module = types.ModuleType("supabase_client")

    class _Query:
        def select(self, *args, **kwargs):
            return self

        def eq(self, *args, **kwargs):
            return self

        def in_(self, *args, **kwargs):
            return self

        def execute(self):
            return types.SimpleNamespace(data=[])

    class SupabaseClient:
        def __init__(self, use_service_role=True):
            self.supabase = self

        def table(self, _name):
            return _Query()

    supabase_module.SupabaseClient = SupabaseClient

    monkeypatch.setitem(sys.modules, "utils.job_tracking", job_tracking)
    monkeypatch.setitem(sys.modules, "scheduler.jobs_portfolio", jobs_portfolio)
    monkeypatch.setitem(sys.modules, "scheduler.jobs_metrics", jobs_metrics)
    monkeypatch.setitem(sys.modules, "supabase_client", supabase_module)

    return calls


def test_retry_failure_returns_to_pending(monkeypatch):
    from web_dashboard.scheduler import jobs_retry

    calls = _install_retry_job_stubs(monkeypatch, retry_count=0, raise_error=RuntimeError("boom"))
    monkeypatch.setattr(jobs_retry, "log_job_execution", lambda *args, **kwargs: None)

    jobs_retry.process_retry_queue_job()

    assert len(calls["mark_retrying"]) == 1
    assert len(calls["mark_pending_retry"]) == 1
    assert len(calls["mark_abandoned"]) == 0


def test_retry_failure_at_max_is_abandoned(monkeypatch):
    from web_dashboard.scheduler import jobs_retry

    calls = _install_retry_job_stubs(monkeypatch, retry_count=2, raise_error=RuntimeError("boom"))
    monkeypatch.setattr(jobs_retry, "log_job_execution", lambda *args, **kwargs: None)

    jobs_retry.process_retry_queue_job()

    assert len(calls["mark_retrying"]) == 1
    assert len(calls["mark_abandoned"]) == 1
    assert len(calls["mark_pending_retry"]) == 0


def test_retry_performance_metrics_resolves(monkeypatch):
    from web_dashboard.scheduler import jobs_retry

    calls = _install_retry_job_stubs(
        monkeypatch,
        retry_count=0,
        raise_error=None,
        job_name="performance_metrics",
    )
    monkeypatch.setattr(jobs_retry, "log_job_execution", lambda *args, **kwargs: None)

    jobs_retry.process_retry_queue_job()

    assert len(calls["mark_retrying"]) == 1
    assert len(calls["populate_performance_metrics_job"]) == 1
    assert len(calls["mark_resolved"]) == 1
    assert len(calls["mark_pending_retry"]) == 0
    assert len(calls["mark_abandoned"]) == 0
