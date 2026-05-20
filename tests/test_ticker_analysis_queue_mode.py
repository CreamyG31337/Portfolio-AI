from types import SimpleNamespace
from unittest.mock import MagicMock


def test_ticker_analysis_queue_mode_enqueues_without_global_ai_lock(monkeypatch):
    from web_dashboard.scheduler import jobs_ticker_analysis as job_module

    fake_service = MagicMock()
    fake_service.get_tickers_to_analyze.return_value = [("AAPL", 100), ("MSFT", 10)]
    fake_service.last_selection_stats = {"selected": 2}

    enqueue_calls = []

    def fake_enqueue(supabase, tickers, *, enqueued_by, max_attempts):
        enqueue_calls.append((supabase, tickers, enqueued_by, max_attempts))
        return {"attempted": 2, "enqueued": 2, "failed": 0}

    monkeypatch.setenv("AI_QUEUE_ENABLED", "true")
    monkeypatch.setenv("AI_QUEUE_JOBS", "ticker_analysis")
    monkeypatch.setenv("AI_QUEUE_MAX_ATTEMPTS", "5")
    monkeypatch.setattr(job_module, "SupabaseClient", lambda use_service_role=True: SimpleNamespace())
    monkeypatch.setattr(job_module, "PostgresClient", lambda: SimpleNamespace())
    monkeypatch.setattr(job_module, "AISkipListManager", lambda supabase: SimpleNamespace())
    monkeypatch.setattr(job_module, "get_ollama_client", lambda: SimpleNamespace())
    monkeypatch.setattr(job_module, "TickerAnalysisService", lambda *args: fake_service)
    monkeypatch.setattr(job_module, "log_job_execution", MagicMock())

    import scheduler.ai_task_workers as workers
    import utils.job_tracking as tracking

    monkeypatch.setattr(workers, "enqueue_ticker_analysis_tasks", fake_enqueue)
    monkeypatch.setattr(tracking, "mark_job_started", MagicMock())
    monkeypatch.setattr(tracking, "mark_job_completed", MagicMock())
    monkeypatch.setattr(tracking, "mark_job_failed", MagicMock())
    monkeypatch.setattr(tracking, "get_running_ai_job", MagicMock(side_effect=AssertionError))

    job_module.ticker_analysis_job()

    assert enqueue_calls
    assert enqueue_calls[0][1] == [("AAPL", 100), ("MSFT", 10)]
    assert enqueue_calls[0][2] == "cron"
    assert enqueue_calls[0][3] == 5
    tracking.mark_job_completed.assert_called_once()
    tracking.mark_job_failed.assert_not_called()
