"""Tests for ``collect_with_summary_model_chain`` AI Audit integration.

Verifies the regression fix for the missing GLM rows in ``/admin/ai-audit``:
every chain-based caller now writes one audit entry per attempt with the
provider detected from the model name, so GLM fallback attempts are visible.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Iterator, List
from unittest.mock import Mock

web_dashboard = Path(__file__).resolve().parent.parent / "web_dashboard"
if str(web_dashboard) not in sys.path:
    sys.path.insert(0, str(web_dashboard))

import ollama_client  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_audit_recorder(monkeypatch) -> list[dict[str, Any]]:
    """Patch ``ai_audit.log_inference`` to capture calls in-memory."""
    captured: list[dict[str, Any]] = []
    import ai_audit

    def _fake_log_inference(**kwargs: Any) -> None:
        captured.append(kwargs)

    monkeypatch.setattr(ai_audit, "log_inference", _fake_log_inference)
    return captured


class _FakeOllama:
    """Stand-in for OllamaClient that drives ``query_ollama`` deterministically."""

    def __init__(self, scripted: List[Any]) -> None:
        # scripted: list of per-call responses. Each item is either a list of
        # str chunks (success) or an Exception instance (raised on iteration).
        self._scripted = list(scripted)
        self.calls: list[dict[str, Any]] = []

    def query_ollama(self, **kwargs: Any) -> Iterator[str]:
        self.calls.append(kwargs)
        if not self._scripted:
            raise AssertionError("FakeOllama: chain ran out of scripted responses")
        next_item = self._scripted.pop(0)
        if isinstance(next_item, BaseException):
            raise next_item
        for chunk in next_item:
            yield chunk


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_chain_audit_skipped_when_function_name_not_provided(monkeypatch):
    """Legacy callers that don't pass function_name must not get audit rows."""
    monkeypatch.setattr(
        ollama_client, "_get_summary_model_chain", lambda req: ["granite3.3:8b"]
    )
    captured = _make_audit_recorder(monkeypatch)
    fake = _FakeOllama([["hello"]])

    body, model = ollama_client.collect_with_summary_model_chain(
        fake,
        prompt="prompt",
        requested_model="granite3.3:8b",
        stream=False,
    )

    assert body == "hello"
    assert model == "granite3.3:8b"
    assert captured == []


def test_chain_audit_logs_one_row_per_attempt_with_glm_provider(monkeypatch):
    """When a GLM model is the successful candidate, audit provider must be 'glm'."""
    monkeypatch.setattr(
        ollama_client, "_get_summary_model_chain", lambda req: ["glm-5.1"]
    )
    captured = _make_audit_recorder(monkeypatch)
    fake = _FakeOllama([["{\"ok\": true}"]])

    body, model = ollama_client.collect_with_summary_model_chain(
        fake,
        prompt="prompt",
        requested_model="glm-5.1",
        stream=False,
        function_name="ticker_meta_analysis",
    )

    assert body == "{\"ok\": true}"
    assert model == "glm-5.1"
    assert len(captured) == 1, captured
    row = captured[0]
    assert row["function"] == "ticker_meta_analysis"
    assert row["model"] == "glm-5.1"
    assert row["provider"] == "glm"
    assert row["success"] is True
    assert row["error"] is None
    assert row["output_summary"].startswith("{")
    assert row["input_chars"] == len("prompt")


def test_chain_audit_records_failure_attempt_then_glm_success(monkeypatch):
    """Failed qwen attempt + successful GLM fallback must produce 2 distinct rows."""
    monkeypatch.setattr(
        ollama_client,
        "_get_summary_model_chain",
        lambda req: ["qwen3.6:27b", "glm-5.1"],
    )
    captured = _make_audit_recorder(monkeypatch)
    fake = _FakeOllama(
        [
            RuntimeError("ollama backend exploded"),
            ["{\"sentiment\": \"BULLISH\"}"],
        ]
    )

    body, model = ollama_client.collect_with_summary_model_chain(
        fake,
        prompt="prompt",
        requested_model="qwen3.6:27b",
        stream=False,
        function_name="ticker_analysis",
        audit_extra={"tickers_extracted": ["AMAT"]},
    )

    assert body == "{\"sentiment\": \"BULLISH\"}"
    assert model == "glm-5.1"
    assert len(captured) == 2, captured
    first, second = captured
    assert first["model"] == "qwen3.6:27b"
    assert first["provider"] == "ollama"
    assert first["success"] is False
    assert "ollama backend exploded" in (first["error"] or "")
    assert first["tickers_extracted"] == ["AMAT"]
    assert second["model"] == "glm-5.1"
    assert second["provider"] == "glm"
    assert second["success"] is True
    assert second["tickers_extracted"] == ["AMAT"]


def test_chain_audit_records_all_failures_when_chain_exhausted(monkeypatch):
    """Every failed attempt must be audited so ops can see the GLM rejection too."""
    monkeypatch.setattr(
        ollama_client,
        "_get_summary_model_chain",
        lambda req: ["qwen3.6:27b", "glm-5.1"],
    )
    captured = _make_audit_recorder(monkeypatch)
    fake = _FakeOllama(
        [
            RuntimeError("backend down"),
            ollama_client.OllamaHostBusyError("all hosts busy"),
        ]
    )

    body, model = ollama_client.collect_with_summary_model_chain(
        fake,
        prompt="prompt",
        requested_model="qwen3.6:27b",
        stream=False,
        function_name="sector_meta_analysis",
    )

    assert body is None
    assert model == "glm-5.1"
    providers = [row["provider"] for row in captured]
    successes = [row["success"] for row in captured]
    assert providers == ["ollama", "glm"]
    assert successes == [False, False]


def test_chain_audit_extract_audit_fields_runs_only_on_success(monkeypatch):
    """``extract_audit_fields`` should enrich the success row but never the failure row."""
    monkeypatch.setattr(
        ollama_client,
        "_get_summary_model_chain",
        lambda req: ["qwen3.6:27b", "glm-5.1"],
    )
    captured = _make_audit_recorder(monkeypatch)
    fake = _FakeOllama(
        [
            RuntimeError("nope"),
            ["{\"sentiment\": \"BULLISH\"}"],
        ]
    )

    extractor_calls: list[str] = []

    def _extract(raw: str) -> dict[str, Any]:
        extractor_calls.append(raw)
        return {"sentiment": "BULLISH"}

    body, model = ollama_client.collect_with_summary_model_chain(
        fake,
        prompt="prompt",
        requested_model="qwen3.6:27b",
        stream=False,
        function_name="ticker_analysis",
        extract_audit_fields=_extract,
    )

    assert body == "{\"sentiment\": \"BULLISH\"}"
    assert model == "glm-5.1"
    assert len(extractor_calls) == 1  # only invoked on success
    first, second = captured
    assert first["success"] is False
    assert "sentiment" not in first
    assert second["success"] is True
    assert second["sentiment"] == "BULLISH"


def test_chain_audit_extract_audit_fields_exception_does_not_break_chain(monkeypatch):
    """A buggy extractor must not blow up the chain or skip the audit row."""
    monkeypatch.setattr(
        ollama_client, "_get_summary_model_chain", lambda req: ["glm-5.1"]
    )
    captured = _make_audit_recorder(monkeypatch)
    fake = _FakeOllama([["{\"sentiment\": \"BULLISH\"}"]])

    def _bad_extract(raw: str) -> dict[str, Any]:
        raise RuntimeError("extractor blew up")

    body, model = ollama_client.collect_with_summary_model_chain(
        fake,
        prompt="prompt",
        requested_model="glm-5.1",
        stream=False,
        function_name="ticker_analysis",
        extract_audit_fields=_bad_extract,
    )

    assert body == "{\"sentiment\": \"BULLISH\"}"
    assert model == "glm-5.1"
    assert len(captured) == 1
    assert captured[0]["success"] is True
    assert captured[0]["provider"] == "glm"
    assert "sentiment" not in captured[0]


def test_chain_audit_records_response_ok_rejection_as_failure(monkeypatch):
    """If response_ok rejects the body, the attempt is failure-audited."""
    monkeypatch.setattr(
        ollama_client, "_get_summary_model_chain", lambda req: ["granite3.3:8b"]
    )
    captured = _make_audit_recorder(monkeypatch)
    fake = _FakeOllama([["plain text not json"]])

    body, model = ollama_client.collect_with_summary_model_chain(
        fake,
        prompt="prompt",
        requested_model="granite3.3:8b",
        stream=False,
        function_name="market_daily_brief",
        response_ok=lambda body: body.startswith("{"),
    )

    assert body is None
    assert model == "granite3.3:8b"
    assert len(captured) == 1
    row = captured[0]
    assert row["success"] is False
    assert "response not acceptable" in (row["error"] or "")
    assert row["provider"] == "ollama"
