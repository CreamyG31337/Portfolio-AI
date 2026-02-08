import json
import threading
from datetime import date, timedelta
from pathlib import Path

import pytest

import ai_audit


@pytest.fixture(autouse=True)
def isolate_audit_logs(tmp_path, monkeypatch):
    log_dir = tmp_path / "ai_audit"
    monkeypatch.setattr(ai_audit, "_AUDIT_DIR", log_dir)
    monkeypatch.setattr(ai_audit, "_last_cleanup_date", None)
    ai_audit.clear_audit_context()
    yield log_dir
    ai_audit.clear_audit_context()


def _today_log_file(log_dir: Path) -> Path:
    return log_dir / f"{date.today().isoformat()}.jsonl"


def test_log_inference_creates_file(isolate_audit_logs):
    ai_audit.log_inference(
        function="generate_summary",
        model="granite3.3:8b",
        input_chars=123,
        input_hash=ai_audit._compute_input_hash("hello"),
        success=True,
    )

    assert _today_log_file(isolate_audit_logs).exists()


def test_log_entry_structure(isolate_audit_logs):
    ai_audit.log_inference(
        function="generate_summary",
        model="granite3.3:8b",
        provider="ollama",
        input_chars=10,
        input_hash=ai_audit._compute_input_hash("sample"),
        output_summary="ok",
        duration_ms=12,
        success=True,
        error=None,
    )

    data = _today_log_file(isolate_audit_logs).read_text(encoding="utf-8").strip().splitlines()
    entry = json.loads(data[0])

    expected_keys = {
        "timestamp",
        "function",
        "model",
        "provider",
        "input_chars",
        "input_hash",
        "output_summary",
        "duration_ms",
        "success",
        "error",
        "tickers_extracted",
        "sentiment",
        "logic_check",
        "market_relevance",
        "caller",
        "article_url",
        "article_title",
    }
    assert expected_keys.issubset(entry.keys())


def test_input_hash_deterministic():
    assert ai_audit._compute_input_hash("same input") == ai_audit._compute_input_hash("same input")


def test_input_hash_different():
    assert ai_audit._compute_input_hash("a") != ai_audit._compute_input_hash("b")


def test_thread_safety(isolate_audit_logs):
    def worker(worker_id: int):
        for i in range(10):
            payload = f"w{worker_id}-{i}"
            ai_audit.log_inference(
                function="thread_test",
                model="granite3.3:8b",
                input_chars=len(payload),
                input_hash=ai_audit._compute_input_hash(payload),
                success=True,
            )

    threads = [threading.Thread(target=worker, args=(idx,)) for idx in range(10)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    lines = _today_log_file(isolate_audit_logs).read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 100


def test_never_raises(isolate_audit_logs):
    class BadString:
        def __str__(self):
            raise RuntimeError("boom")

    ai_audit.log_inference(function="bad_case", model=None, success=None, weird=BadString())
    ai_audit.log_inference(function=None, model="granite3.3:8b", input_chars=None, input_hash=None)


def test_cleanup_old_logs(isolate_audit_logs):
    isolate_audit_logs.mkdir(parents=True, exist_ok=True)
    old_date = (date.today() - timedelta(days=31)).isoformat()
    recent_date = (date.today() - timedelta(days=5)).isoformat()

    old_file = isolate_audit_logs / f"{old_date}.jsonl"
    recent_file = isolate_audit_logs / f"{recent_date}.jsonl"
    old_file.write_text("{}\n", encoding="utf-8")
    recent_file.write_text("{}\n", encoding="utf-8")

    ai_audit._cleanup_old_logs(max_age_days=30)

    assert not old_file.exists()
    assert recent_file.exists()


def test_cleanup_preserves_recent(isolate_audit_logs):
    isolate_audit_logs.mkdir(parents=True, exist_ok=True)
    for days_ago in [0, 5, 15, 30]:
        file_path = isolate_audit_logs / f"{(date.today() - timedelta(days=days_ago)).isoformat()}.jsonl"
        file_path.write_text("{}\n", encoding="utf-8")

    ai_audit._cleanup_old_logs(max_age_days=30)

    remaining = list(isolate_audit_logs.glob("*.jsonl"))
    assert len(remaining) == 4


def test_audit_context_thread_local():
    ai_audit.set_audit_context(article_url="https://example.com", article_title="Main")
    main_context = ai_audit.get_audit_context()
    from_thread = {}

    def worker():
        from_thread.update(ai_audit.get_audit_context())

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join()

    assert main_context.get("article_url") == "https://example.com"
    assert from_thread == {}


def test_detect_provider():
    assert ai_audit._detect_provider("granite3.3:8b") == "ollama"
    assert ai_audit._detect_provider("glm-4") == "glm"


def test_detect_caller():
    def call_detect():
        return ai_audit._detect_caller()

    caller = call_detect()
    assert caller != "unknown"
    assert "." in caller

