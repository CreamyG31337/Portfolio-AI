"""Tests for sticky Ollama num_ctx, budget scaffold, and heretic 32k config."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

WEB_DASHBOARD = Path(__file__).resolve().parent.parent / "web_dashboard"
if str(WEB_DASHBOARD) not in sys.path:
    sys.path.insert(0, str(WEB_DASHBOARD))

import ollama_ctx  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_sticky() -> None:
    ollama_ctx.clear_sticky_num_ctx()
    yield
    ollama_ctx.clear_sticky_num_ctx()


def test_heretic_num_ctx_is_32768_not_20000() -> None:
    """Regression: 20000 left warm -c 20000 runners on the shared 3090."""
    cfg_path = WEB_DASHBOARD / "model_config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    heretic = cfg["models"]["qwen3.6:27b-heretic"]
    assert heretic["num_ctx"] == 32768
    assert heretic["num_ctx"] != 20000
    # Failover twin should not re-pin 20k on NVIDIA either.
    iq3 = cfg["models"]["batiai/qwen3.6-27b:iq3"]
    assert iq3["num_ctx"] == 32768


def test_sticky_num_ctx_first_wins() -> None:
    assert ollama_ctx.resolve_sticky_num_ctx("qwen3.6:27b-heretic", 32768) == 32768
    assert ollama_ctx.resolve_sticky_num_ctx("qwen3.6:27b-heretic", 16384) == 32768
    assert ollama_ctx.get_sticky_num_ctx("qwen3.6:27b-heretic") == 32768


def test_clear_sticky_allows_new_ctx() -> None:
    ollama_ctx.resolve_sticky_num_ctx("m", 20000)
    ollama_ctx.clear_sticky_num_ctx("m")
    assert ollama_ctx.resolve_sticky_num_ctx("m", 32768) == 32768


def test_compute_prompt_token_budget_uses_measured_ceiling() -> None:
    budget = ollama_ctx.compute_prompt_token_budget(
        32768,
        reserved_for_output=4096,
        measured_ceiling=16000,
    )
    assert budget == 16000 - 4096


def test_compact_messages_drops_oldest_non_system() -> None:
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "a" * 4000},
        {"role": "assistant", "content": "b" * 4000},
        {"role": "user", "content": "short"},
    ]
    # Very small budget forces drops.
    out = ollama_ctx.compact_messages_to_budget(messages, budget_tokens=50)
    assert out[0]["role"] == "system"
    assert any(m.get("content") == "short" for m in out)
    assert not any(m.get("content", "").startswith("aaa") for m in out)


def test_log_telemetry_warns_when_prompt_eval_far_below(
    caplog: pytest.LogCaptureFixture,
) -> None:
    import logging

    with caplog.at_level(logging.WARNING, logger="ollama_ctx"):
        ollama_ctx.log_ollama_ctx_telemetry(
            model="qwen3.6:27b-heretic",
            requested_num_ctx=32768,
            response_data={"prompt_eval_count": 8000, "eval_count": 10},
        )
    assert any("far below requested_num_ctx" in r.message for r in caplog.records)


def test_apply_num_ctx_to_options_sets_sticky() -> None:
    options: dict[str, Any] = {"temperature": 0.2}
    n = ollama_ctx.apply_num_ctx_to_options(options, "qwen3.6:27b-heretic", 32768)
    assert n == 32768
    assert options["num_ctx"] == 32768


def test_unload_model_posts_keep_alive_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    import ollama_client

    posted: list[tuple[str, dict[str, Any]]] = []

    class _Resp:
        def raise_for_status(self) -> None:
            return None

    class _Session:
        def post(self, url: str, json: dict[str, Any] | None = None, timeout: int = 0) -> _Resp:
            posted.append((url, json or {}))
            return _Resp()

    client = ollama_client.OllamaClient.__new__(ollama_client.OllamaClient)
    client.enabled = True
    client.timeout = 30
    client.session = _Session()  # type: ignore[assignment]
    client.model_config = {"models": {}}
    monkeypatch.setattr(client, "_resolve_urls", lambda _m: ("http://nvidia:11434", None))

    ollama_ctx.resolve_sticky_num_ctx("qwen3.6:27b-heretic", 20000)
    ok = client.unload_model("qwen3.6:27b-heretic")
    assert ok is True
    assert posted and posted[0][0].endswith("/api/generate")
    assert posted[0][1].get("keep_alive") == 0
    assert ollama_ctx.get_sticky_num_ctx("qwen3.6:27b-heretic") is None
