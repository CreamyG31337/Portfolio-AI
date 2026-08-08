"""Tests for sticky Ollama num_ctx, half-window budget, and heretic 65k config."""

from __future__ import annotations

import json
import logging
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


def test_heretic_num_ctx_is_65536_not_legacy() -> None:
    """Regression: 20k/32k left warm smaller runners and thrashed vs Goose 65k."""
    cfg_path = WEB_DASHBOARD / "model_config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    heretic = cfg["models"]["qwen3.6:27b-heretic"]
    assert heretic["num_ctx"] == 65536
    assert heretic["num_ctx"] not in (20000, 32768)
    assert heretic["num_predict"] <= 32768  # generation half of 65k
    agentic = cfg["models"]["qwen3.6:27b-heretic-agentic"]
    assert agentic["num_ctx"] == 65536
    # AMD IQ3 must not blindly copy 65536.
    iq3 = cfg["models"]["batiai/qwen3.6-27b:iq3"]
    assert iq3["num_ctx"] != 65536
    assert ollama_ctx.HERETIC_PREFERRED_NUM_CTX == 65536


def test_sticky_num_ctx_first_wins() -> None:
    assert ollama_ctx.resolve_sticky_num_ctx("qwen3.6:27b-heretic", 65536) == 65536
    assert ollama_ctx.resolve_sticky_num_ctx("qwen3.6:27b-heretic", 32768) == 65536
    assert ollama_ctx.get_sticky_num_ctx("qwen3.6:27b-heretic") == 65536


def test_clear_sticky_allows_new_ctx() -> None:
    ollama_ctx.resolve_sticky_num_ctx("m", 20000)
    ollama_ctx.clear_sticky_num_ctx("m")
    assert ollama_ctx.resolve_sticky_num_ctx("m", 65536) == 65536


def test_prompt_budget_uses_half_window_not_full_ctx() -> None:
    # Full 65k is NOT usable prompt space — half ≈ 32k, heretic soft-cap 28k.
    budget = ollama_ctx.compute_prompt_token_budget(
        65536,
        model_name="qwen3.6:27b-heretic",
    )
    assert budget == ollama_ctx.HERETIC_SOFT_PROMPT_BUDGET
    assert budget == 28000
    assert ollama_ctx.ollama_prompt_half_tokens(65536) == 32768
    assert ollama_ctx.ollama_generation_half_tokens(65536) == 32768


def test_compute_prompt_token_budget_uses_measured_ceiling() -> None:
    budget = ollama_ctx.compute_prompt_token_budget(
        65536,
        reserved_for_output=0,
        measured_ceiling=16000,
        soft_prompt_cap=28000,
    )
    assert budget == 16000


def test_compact_messages_drops_oldest_non_system() -> None:
    messages = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "a" * 4000},
        {"role": "assistant", "content": "b" * 4000},
        {"role": "user", "content": "short"},
    ]
    out = ollama_ctx.compact_messages_to_budget(messages, budget_tokens=50)
    assert out[0]["role"] == "system"
    assert any(m.get("content") == "short" for m in out)
    assert not any(m.get("content", "").startswith("aaa") for m in out)


def test_log_telemetry_warns_when_prompt_eval_below_estimate(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger="ollama_ctx"):
        ollama_ctx.log_ollama_ctx_telemetry(
            model="qwen3.6:27b-heretic",
            requested_num_ctx=65536,
            response_data={"prompt_eval_count": 8000, "eval_count": 10},
            prompt_tokens_est=20000,
        )
    assert any("silent front truncation" in r.message for r in caplog.records)


def test_apply_num_ctx_to_options_sets_sticky() -> None:
    options: dict[str, Any] = {"temperature": 0.2}
    n = ollama_ctx.apply_num_ctx_to_options(options, "qwen3.6:27b-heretic", 65536)
    assert n == 65536
    assert options["num_ctx"] == 65536


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

    ollama_ctx.resolve_sticky_num_ctx("qwen3.6:27b-heretic", 32768)
    ok = client.unload_model("qwen3.6:27b-heretic")
    assert ok is True
    assert posted and posted[0][0].endswith("/api/generate")
    assert posted[0][1].get("keep_alive") == 0
    assert ollama_ctx.get_sticky_num_ctx("qwen3.6:27b-heretic") is None
