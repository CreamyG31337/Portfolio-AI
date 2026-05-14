from __future__ import annotations

import importlib
import logging
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_root = Path(__file__).resolve().parent.parent
_web = _root / "web_dashboard"
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))
if str(_web) not in sys.path:
    sys.path.insert(1, str(_web))

from newsletter_service import NewsletterService  # noqa: E402


def test_log_step_formats_line_and_truncates(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    NewsletterService.log_step(
        "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        "my_step",
        "start",
        duration_ms=12,
        note="x" * 200,
    )
    msg = caplog.records[0].getMessage()
    assert "[nl=aaaaaaaa]" in msg
    assert "step=my_step" in msg
    assert "status=start" in msg
    assert "duration_ms=12" in msg
    assert "note=" in msg
    assert "..." in msg or len(msg.split("note=")[-1]) <= 130


def test_log_step_fail_is_error(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.ERROR)
    NewsletterService.log_step("id-here-00", "s", "fail", err="bad")
    assert caplog.records[-1].levelno == logging.ERROR


def test_log_step_skip_is_warning(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING)
    NewsletterService.log_step("id-here-00", "s", "skip", reason="x")
    assert caplog.records[-1].levelno == logging.WARNING


@pytest.fixture
def jobs_newsletter_module(monkeypatch: pytest.MonkeyPatch):
    # Import job module first — its top-level path setup must run before we resolve
    # ``utils.job_tracking`` so patches apply to the same module the job imports.
    jn = importlib.import_module("scheduler.jobs_newsletter")
    ut = importlib.import_module("utils.job_tracking")
    monkeypatch.setattr(ut, "get_running_ai_job", lambda exclude_job_name=None: None)
    monkeypatch.setattr(ut, "mark_job_started", lambda *a, **k: None)
    monkeypatch.setattr(ut, "mark_job_completed", lambda *a, **k: None)
    monkeypatch.setattr(ut, "mark_job_failed", lambda *a, **k: None)
    sched_core = importlib.import_module("scheduler.scheduler_core")
    monkeypatch.setattr(sched_core, "log_job_execution", lambda *a, **k: None)

    _settings = importlib.import_module("settings")
    monkeypatch.setattr(_settings, "get_summarizing_model", lambda scope=None: "test-summarizer")
    ti = importlib.import_module("ticker_inference")
    monkeypatch.setattr(ti, "infer_tickers_from_companies", lambda companies: [])
    monkeypatch.setattr(ti, "infer_tickers_from_text", lambda text: [])
    tv = importlib.import_module("ticker_validator")
    monkeypatch.setattr(tv, "validate_extracted_tickers", lambda tickers, **kwargs: tickers)
    monkeypatch.setattr(
        NewsletterService,
        "generate_embedding_for_newsletter",
        lambda self, nl_id, text: [0.0] * 768,
    )

    return jn


def test_newsletter_ai_processing_job_logs_steps(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    jobs_newsletter_module,
) -> None:
    caplog.set_level(logging.INFO)
    jn = jobs_newsletter_module

    row = {
        "id": "11111111-1111-1111-1111-111111111111",
        "subject": "Hello",
        "body_plain": "Some newsletter body text for testing.",
        "body_html": None,
        "received_at": None,
        "summary": None,
        "embedding_is_null": True,
    }

    class FakeRepo:
        def __init__(self) -> None:
            self.client = MagicMock()
            self.client.execute_query = MagicMock(return_value=[row])
            self.client.execute_update = MagicMock()

        def update_embedding(self, _nid: str, _emb: list) -> bool:
            return True

    monkeypatch.setattr("newsletter_repository.NewsletterRepository", FakeRepo)

    def _fake_summary(_text: str, article_type: str = "") -> dict:
        return {"summary": "Short summary.", "tickers": ["AAPL"], "companies": []}

    monkeypatch.setattr("ollama_client.generate_summary", _fake_summary)

    jn.newsletter_ai_processing_job()

    joined = " ".join(r.getMessage() for r in caplog.records)
    # Batch line uses scheduler.jobs_newsletter logger; after log_handler.setup_logging(),
    # parent scheduler.jobs has propagate=False so that line may not reach caplog.
    assert "step=ai_summary" in joined
    assert "step=persist" in joined
    assert "[nl=11111111]" in joined


def test_newsletter_ai_processing_job_ai_summary_fail_logs(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    jobs_newsletter_module,
) -> None:
    caplog.set_level(logging.ERROR)
    jn = jobs_newsletter_module

    row = {
        "id": "22222222-2222-2222-2222-222222222222",
        "subject": "Hello",
        "body_plain": "Body.",
        "body_html": None,
        "received_at": None,
        "summary": None,
        "embedding_is_null": True,
    }

    class FakeRepo:
        def __init__(self) -> None:
            self.client = MagicMock()
            self.client.execute_query = MagicMock(return_value=[row])
            self.client.execute_update = MagicMock()

        def update_embedding(self, _nid: str, _emb: list) -> bool:
            return True

    monkeypatch.setattr("newsletter_repository.NewsletterRepository", FakeRepo)
    monkeypatch.setattr(
        "ollama_client.generate_summary",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("summarizer down")),
    )

    jn.newsletter_ai_processing_job()

    joined = " ".join(r.getMessage() for r in caplog.records)
    assert "step=ai_summary" in joined
    assert "status=fail" in joined
