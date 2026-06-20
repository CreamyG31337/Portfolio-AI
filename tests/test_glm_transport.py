from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

web_dashboard = Path(__file__).resolve().parent.parent / "web_dashboard"
if str(web_dashboard) not in sys.path:
    sys.path.insert(0, str(web_dashboard))

import glm_transport  # noqa: E402
import glm_config  # noqa: E402


def test_get_glm_models_refresh_false_skips_live_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("glm_config.get_zhipu_api_key", lambda: "test-key")
    monkeypatch.setattr("glm_config._read_glm_models_cache", lambda: [])
    monkeypatch.setattr(
        "glm_config.fetch_zhipu_models",
        lambda: (_ for _ in ()).throw(AssertionError("live fetch should not run")),
    )
    models = glm_config.get_glm_models(refresh=False)
    assert "glm-5.2" in models


def test_glm_chat_completion_text_failover_second_base_on_500(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("glm_config.get_zhipu_api_key", lambda: "k")
    monkeypatch.setattr("model_registry.get_glm_base_urls", lambda: ["https://a/v4", "https://b/v4"])

    posts: list[str] = []

    def fake_post(url: str, **kwargs: object) -> MagicMock:
        posts.append(url)
        r = MagicMock()
        if len(posts) == 1:
            r.status_code = 500
        else:
            r.status_code = 200
            r.json.return_value = {"choices": [{"message": {"content": "ok"}}]}
        r.raise_for_status = lambda: None
        return r

    monkeypatch.setattr("glm_transport.requests.post", fake_post)

    out = glm_transport.glm_chat_completion_text(
        [{"role": "user", "content": "x"}],
        model="glm-5.1",
        stream=False,
        json_mode=False,
        temperature=0.1,
        max_tokens=64,
        timeout=30.0,
        allow_cheap_fallback=False,
    )
    assert out == "ok"
    assert len(posts) == 2


def test_glm_chat_completion_text_cheap_fallback_on_empty_primary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("glm_config.get_zhipu_api_key", lambda: "k")
    monkeypatch.setattr("model_registry.get_glm_base_urls", lambda: ["https://only/v4"])
    monkeypatch.setattr("model_registry.get_cheap_model", lambda: "glm-5-turbo")
    monkeypatch.delenv("GLM_FALLBACK_TO_CHEAP_MODEL", raising=False)

    models: list[str] = []

    def fake_post(url: str, **kwargs: object) -> MagicMock:
        payload = kwargs.get("json") or {}
        models.append(str(payload.get("model", "")))
        r = MagicMock()
        r.status_code = 200
        r.raise_for_status = lambda: None
        if payload.get("model") == "glm-5.1":
            r.json.return_value = {"choices": [{"message": {"content": ""}}]}
        else:
            r.json.return_value = {"choices": [{"message": {"content": "cheap-ok"}}]}
        return r

    monkeypatch.setattr("glm_transport.requests.post", fake_post)

    out = glm_transport.glm_chat_completion_text(
        [{"role": "user", "content": "x"}],
        model="glm-5.1",
        stream=False,
        json_mode=False,
        temperature=0.1,
        max_tokens=64,
        timeout=30.0,
        allow_cheap_fallback=True,
    )
    assert out == "cheap-ok"
    assert models == ["glm-5.1", "glm-5-turbo"]


def test_glm_fallback_disabled_no_second_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GLM_FALLBACK_TO_CHEAP_MODEL", "false")
    monkeypatch.setattr("glm_config.get_zhipu_api_key", lambda: "k")
    monkeypatch.setattr("model_registry.get_glm_base_urls", lambda: ["https://only/v4"])
    monkeypatch.setattr("model_registry.get_cheap_model", lambda: "glm-5-turbo")

    models: list[str] = []

    def fake_post(url: str, **kwargs: object) -> MagicMock:
        payload = kwargs.get("json") or {}
        models.append(str(payload.get("model", "")))
        r = MagicMock()
        r.status_code = 200
        r.raise_for_status = lambda: None
        r.json.return_value = {"choices": [{"message": {"content": ""}}]}
        return r

    monkeypatch.setattr("glm_transport.requests.post", fake_post)

    out = glm_transport.glm_chat_completion_text(
        [{"role": "user", "content": "x"}],
        model="glm-5.1",
        stream=False,
        json_mode=False,
        temperature=0.1,
        max_tokens=64,
        timeout=30.0,
        allow_cheap_fallback=True,
    )
    assert "GLM returned an empty response" in out
    assert models == ["glm-5.1"]


def test_json_mode_sets_response_format(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("glm_config.get_zhipu_api_key", lambda: "k")
    monkeypatch.setattr("model_registry.get_glm_base_urls", lambda: ["https://only/v4"])

    captured: dict[str, object] = {}

    def fake_post(url: str, **kwargs: object) -> MagicMock:
        captured.update(kwargs.get("json") or {})
        r = MagicMock()
        r.status_code = 200
        r.raise_for_status = lambda: None
        r.json.return_value = {"choices": [{"message": {"content": "{}"}}]}
        return r

    monkeypatch.setattr("glm_transport.requests.post", fake_post)

    glm_transport.glm_chat_completion_text(
        [{"role": "user", "content": "x"}],
        model="glm-5.1",
        stream=False,
        json_mode=True,
        temperature=0.0,
        max_tokens=256,
        timeout=60.0,
        allow_cheap_fallback=False,
    )
    assert captured.get("response_format") == {"type": "json_object"}


def test_streaming_yields_chunks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("glm_config.get_zhipu_api_key", lambda: "k")
    monkeypatch.setattr("model_registry.get_glm_base_urls", lambda: ["https://only/v4"])

    def fake_post(url: str, **kwargs: object) -> MagicMock:
        r = MagicMock()
        r.status_code = 200
        r.raise_for_status = lambda: None

        def iter_lines(decode_unicode: bool = True):
            yield f'data: {json.dumps({"choices": [{"delta": {"content": "a"}, "finish_reason": None}]})}'
            yield f'data: {json.dumps({"choices": [{"delta": {"content": "b"}, "finish_reason": "stop"}]})}'

        r.iter_lines = iter_lines
        return r

    monkeypatch.setattr("glm_transport.requests.post", fake_post)

    parts = list(
        glm_transport.glm_chat_completion(
            [{"role": "user", "content": "x"}],
            model="glm-5.1",
            stream=True,
            json_mode=False,
            temperature=0.1,
            max_tokens=64,
            timeout=30.0,
            allow_cheap_fallback=False,
        )
    )
    assert "".join(parts) == "ab"


def test_glm_raw_indicates_transport_failure_known_messages() -> None:
    assert glm_transport.glm_raw_indicates_transport_failure(
        "GLM request timed out. Please try again."
    )
    assert glm_transport.glm_raw_indicates_transport_failure("GLM API error: 429 boom")
    assert glm_transport.glm_raw_indicates_transport_failure("GLM error: connection reset")
    assert not glm_transport.glm_raw_indicates_transport_failure('{"summary": "ok"}')
    assert not glm_transport.glm_raw_indicates_transport_failure("")
