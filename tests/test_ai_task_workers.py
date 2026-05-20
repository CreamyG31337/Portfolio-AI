from types import SimpleNamespace

from web_dashboard.scheduler.ai_task_workers import (
    AIQueueConfig,
    AIQueueWorkerPool,
    QUEUE_JOB_TICKER_ANALYSIS,
    ERROR_HOST_BUSY,
    ERROR_RATE_LIMITED,
    ERROR_TIMEOUT_GLM,
    ERROR_UNSUPPORTED_TASK,
    UnsupportedTaskError,
    build_task_handlers,
    classify_error,
    enqueue_ticker_analysis_tasks,
    model_for_backend,
    ollama_base_url_for_backend,
    retry_delay_seconds,
    should_increment_attempts,
)


class FakeSupabase:
    def __init__(self):
        self.calls = []

    def rpc(self, function_name, payload):
        self.calls.append((function_name, payload))
        return self

    def execute(self):
        return SimpleNamespace(data=[])


def test_ai_queue_config_from_env_parses_worker_counts_and_jobs():
    config = AIQueueConfig.from_env(
        {
            "AI_QUEUE_ENABLED": "true",
            "AI_QUEUE_JOBS": "ticker_analysis, ticker_meta_analysis",
            "AI_QUEUE_WORKERS_OLLAMA_PRIMARY": "2",
            "AI_QUEUE_WORKERS_OLLAMA_SECONDARY": "0",
            "AI_QUEUE_WORKERS_GLM": "4",
            "AI_QUEUE_LEASE_TTL_SEC": "120",
            "AI_QUEUE_HEARTBEAT_SEC": "15",
        }
    )

    assert config.enabled is True
    assert config.enabled_jobs == ("ticker_analysis", "ticker_meta_analysis")
    assert config.worker_counts["ollama_primary"] == 2
    assert config.worker_counts["ollama_secondary"] == 0
    assert config.worker_counts["glm"] == 4
    assert config.lease_ttl_sec == 120
    assert config.heartbeat_sec == 15


def test_worker_pool_does_not_start_without_registered_handlers():
    config = AIQueueConfig.from_env(
        {
            "AI_QUEUE_ENABLED": "true",
            "AI_QUEUE_JOBS": "ticker_analysis",
            "AI_QUEUE_WORKERS_OLLAMA_PRIMARY": "1",
            "AI_QUEUE_WORKERS_OLLAMA_SECONDARY": "0",
            "AI_QUEUE_WORKERS_GLM": "0",
        }
    )
    pool = AIQueueWorkerPool(config, handlers={})

    assert pool.start() is False
    assert pool.running is False


def test_lease_one_uses_backend_and_enabled_analysis_types():
    fake = SimpleNamespace(supabase=FakeSupabase())
    config = AIQueueConfig.from_env(
        {
            "AI_QUEUE_ENABLED": "true",
            "AI_QUEUE_JOBS": "ticker_analysis",
        }
    )
    pool = AIQueueWorkerPool(config)

    task = pool._lease_one(fake, "worker-1", "glm", ["ticker_analysis"])

    assert task is None
    assert fake.supabase.calls == [
        (
            "lease_ai_task",
            {
                "p_worker_id": "worker-1",
                "p_backend": "glm",
                "p_analysis_types": ["ticker_analysis"],
                "p_lease_seconds": 90,
            },
        )
    ]


def test_classify_error_matches_fallback_taxonomy():
    assert classify_error(UnsupportedTaskError("missing")) == ERROR_UNSUPPORTED_TASK
    assert classify_error(RuntimeError("hosts busy for model")) == ERROR_HOST_BUSY
    assert classify_error(RuntimeError("HTTP 429 rate limit")) == ERROR_RATE_LIMITED
    assert classify_error(TimeoutError("Z.AI timed out"), backend="glm") == ERROR_TIMEOUT_GLM


def test_host_busy_does_not_increment_attempts_but_rate_limit_backs_off():
    assert should_increment_attempts(ERROR_HOST_BUSY) is False
    assert should_increment_attempts(ERROR_RATE_LIMITED) is True
    assert retry_delay_seconds(ERROR_RATE_LIMITED, attempts=2, base_delay_sec=30) == 120


def test_build_task_handlers_registers_ticker_analysis_only_when_enabled():
    assert build_task_handlers([]) == {}
    handlers = build_task_handlers([QUEUE_JOB_TICKER_ANALYSIS])

    assert list(handlers) == [QUEUE_JOB_TICKER_ANALYSIS]


def test_enqueue_ticker_analysis_tasks_uses_enqueue_rpc_payload():
    fake = SimpleNamespace(supabase=FakeSupabase())

    stats = enqueue_ticker_analysis_tasks(
        fake,
        [("aapl", 1000), ("msft", 100)],
        enqueued_by="manual",
        max_attempts=4,
    )

    assert stats == {"attempted": 2, "enqueued": 2, "failed": 0}
    assert [call[0] for call in fake.supabase.calls] == ["enqueue_ai_task", "enqueue_ai_task"]
    assert fake.supabase.calls[0][1] == {
        "p_analysis_type": "ticker_analysis",
        "p_target_key": "AAPL",
        "p_payload": {"ticker": "AAPL", "priority": 1000, "manual_request": True},
        "p_priority": 1000,
        "p_enqueued_by": "manual",
        "p_max_attempts": 4,
    }


def test_backend_model_and_host_mapping(monkeypatch):
    monkeypatch.setenv("AI_QUEUE_MODEL_GLM", "glm-5.1")
    monkeypatch.setenv("AI_QUEUE_OLLAMA_PRIMARY_BASE_URL", "http://amd:11434")
    monkeypatch.setenv("AI_QUEUE_OLLAMA_SECONDARY_BASE_URL", "http://nvidia:11434")

    assert model_for_backend("glm") == "glm-5.1"
    assert ollama_base_url_for_backend("ollama_primary") == "http://amd:11434"
    assert ollama_base_url_for_backend("ollama_secondary") == "http://nvidia:11434"
