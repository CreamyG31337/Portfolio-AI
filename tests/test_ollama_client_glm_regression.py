from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import Mock

import requests

web_dashboard = Path(__file__).resolve().parent.parent / "web_dashboard"
if str(web_dashboard) not in sys.path:
    sys.path.insert(0, str(web_dashboard))

import ollama_client  # noqa: E402


def test_get_summary_model_chain_glm_primary_only(monkeypatch):
    """No implicit glm-* tail; fallbacks come only from summarizer settings."""
    import settings as settings_module

    monkeypatch.setattr(settings_module, "get_summarizing_fallback_models", lambda: [])
    chain = ollama_client._get_summary_model_chain("glm-5.1")
    assert chain == ["glm-5.1"]


def test_get_summary_model_chain_skip_glm_fallback_strips_tail_glms(monkeypatch):
    """SUMMARY_SKIP_GLM_FALLBACK removes glm-* from chain tail (defaults append glm fallbacks)."""
    monkeypatch.setenv("SUMMARY_SKIP_GLM_FALLBACK", "1")
    chain = ollama_client._get_summary_model_chain("qwen3.6:27b-heretic")
    assert chain
    assert chain[0] == "qwen3.6:27b-heretic"
    assert not any(str(m).startswith("glm-") for m in chain[1:]), chain


def test_get_summary_model_chain_skip_glm_fallback_keeps_primary_glm(monkeypatch):
    monkeypatch.setenv("SUMMARY_SKIP_GLM_FALLBACK", "1")
    chain = ollama_client._get_summary_model_chain("glm-4.5-air")
    assert chain[0] == "glm-4.5-air"
    assert not any(str(m).startswith("glm-") for m in chain[1:])


def test_generate_summary_via_zhipu_uses_glm_timeout(monkeypatch):
    monkeypatch.setattr("glm_config.get_zhipu_api_key", lambda: "test-key")

    call_args = {}

    def _fake_post(*args, **kwargs):
        call_args.update(kwargs)
        raise requests.exceptions.Timeout("timeout")

    monkeypatch.setattr("glm_transport.requests.post", _fake_post)

    result = ollama_client._generate_summary_via_zhipu(
        text="hello world",
        model="glm-5.1",
        article_type="Market News",
        stream=False,
    )

    assert result == {}
    assert call_args["timeout"] == ollama_client.GLM_TIMEOUT
