"""Tests for contradiction drill-down job gating."""

from unittest.mock import MagicMock, patch

from web_dashboard.scheduler.jobs_contradiction_drilldown import contradiction_drilldown_job


@patch("web_dashboard.scheduler.jobs_contradiction_drilldown.log_job_execution")
@patch("utils.job_tracking.mark_job_completed")
@patch("utils.job_tracking.mark_job_started")
@patch("postgres_client.PostgresClient")
def test_contradiction_job_skips_low_supply(mock_pg_cls, _start, _done, _log):
    pg = MagicMock()
    mock_pg_cls.return_value = pg
    pg.execute_query.side_effect = [
        [{"cnt": 14}],  # 1/day << 10/day gate
        [{"ticker": "AAA", "confidence_adjusted": 0.3, "c_count": 3}],
    ]

    contradiction_drilldown_job()

    _log.assert_called()
    assert "skipped" in str(_log.call_args[0][2]).lower()


@patch("web_dashboard.scheduler.jobs_contradiction_drilldown.log_job_execution")
@patch("utils.job_tracking.mark_job_completed")
@patch("utils.job_tracking.mark_job_started")
@patch("supabase_client.SupabaseClient")
@patch("scheduler.ai_task_workers.enqueue_ticker_analysis_tasks")
@patch("postgres_client.PostgresClient")
def test_contradiction_job_enqueues_when_supply_healthy(
    mock_pg_cls, mock_enqueue, _sb, _start, _done, _log
):
    pg = MagicMock()
    mock_pg_cls.return_value = pg
    # The gate must use the unbounded COUNT, not the LIMITed candidate rows —
    # otherwise daily_avg caps at 50/14 and the job can never enqueue.
    pg.execute_query.side_effect = [
        [{"cnt": 200}],  # 14.3/day >= 10/day gate
        [{"ticker": "AAA", "confidence_adjusted": 0.3, "c_count": 3}],
    ]
    mock_enqueue.return_value = {"enqueued": 1, "attempted": 1, "failed": 0}

    contradiction_drilldown_job()

    mock_enqueue.assert_called_once()
    assert "enqueued" in str(_log.call_args[0][2]).lower()
