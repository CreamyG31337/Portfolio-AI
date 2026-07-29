"""Queue-mode path for analyze_congress_trades_job."""

from types import SimpleNamespace
from unittest.mock import MagicMock


def test_analyze_congress_trades_queue_mode_enqueues_without_inline_scoring(monkeypatch):
    from web_dashboard.scheduler import jobs_congress as job_module

    enqueue_calls = []

    def fake_enqueue(supabase, trade_ids, *, priority, enqueued_by, max_attempts):
        enqueue_calls.append(
            {
                "trade_ids": list(trade_ids),
                "priority": priority,
                "enqueued_by": enqueued_by,
                "max_attempts": max_attempts,
            }
        )
        return {"attempted": len(trade_ids), "enqueued": len(trade_ids), "failed": 0}

    class _Query:
        def select(self, *_a, **_k):
            return self

        def is_(self, *_a, **_k):
            return self

        def order(self, *_a, **_k):
            return self

        def limit(self, *_a, **_k):
            return self

        def execute(self):
            return SimpleNamespace(data=[{"id": 11}, {"id": 22}])

    fake_client = SimpleNamespace(supabase=SimpleNamespace(table=lambda _n: _Query()))

    monkeypatch.setenv("AI_QUEUE_ENABLED", "true")
    monkeypatch.setenv("AI_QUEUE_JOBS", "analyze_congress_trades")
    monkeypatch.setenv("AI_QUEUE_MAX_ATTEMPTS", "4")
    monkeypatch.setenv("AI_QUEUE_ENQUEUED_BY", "cron")

    import scheduler.ai_task_workers as workers
    import utils.job_tracking as tracking

    monkeypatch.setattr(workers, "enqueue_congress_trade_analysis_tasks", fake_enqueue)
    monkeypatch.setattr(job_module, "log_job_execution", MagicMock())
    monkeypatch.setattr(tracking, "mark_job_started", MagicMock())
    monkeypatch.setattr(tracking, "mark_job_completed", MagicMock())
    monkeypatch.setattr(tracking, "mark_job_failed", MagicMock())
    monkeypatch.setattr(tracking, "get_running_ai_job", MagicMock(side_effect=AssertionError))

    # SupabaseClient is imported inside enqueue helper path
    import supabase_client as sc

    monkeypatch.setattr(sc, "SupabaseClient", lambda use_service_role=True: fake_client)

    job_module.analyze_congress_trades_job()

    assert enqueue_calls
    assert enqueue_calls[0]["trade_ids"] == [11, 22]
    assert enqueue_calls[0]["priority"] == 10
    assert enqueue_calls[0]["max_attempts"] == 4
    tracking.mark_job_completed.assert_called_once()
    tracking.mark_job_failed.assert_not_called()
