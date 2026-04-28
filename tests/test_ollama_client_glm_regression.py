from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import Mock

import requests

web_dashboard = Path(__file__).resolve().parent.parent / "web_dashboard"
if str(web_dashboard) not in sys.path:
    sys.path.insert(0, str(web_dashboard))

import ollama_client  # noqa: E402


def test_get_summary_model_chain_includes_glm_air_fallback():
    chain = ollama_client._get_summary_model_chain("glm-4.7")
    assert chain[0] == "glm-4.7"
    assert "glm-4.5-air" in chain


def test_generate_summary_via_zhipu_uses_glm_timeout(monkeypatch):
    monkeypatch.setattr("glm_config.get_zhipu_api_key", lambda: "test-key")

    call_args = {}

    def _fake_post(*args, **kwargs):
        call_args.update(kwargs)
        raise requests.exceptions.Timeout("timeout")

    monkeypatch.setattr("ollama_client.requests.post", _fake_post)

    result = ollama_client._generate_summary_via_zhipu(
        text="hello world",
        model="glm-4.7",
        article_type="Market News",
        stream=False,
    )

    assert result == {}
    assert call_args["timeout"] == ollama_client.GLM_TIMEOUT
