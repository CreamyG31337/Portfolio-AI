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


@pytest.fixture(autouse=True)
def _no_local_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """Z.AI behaviour tests must not reach the local Ollama or OpenRouter fallbacks; their own tests opt back in."""
    monkeypatch.setenv("GLM_FALLBACK_TO_LOCAL", "false")
    monkeypatch.setenv("GLM_FALLBACK_TO_OPENROUTER", "false")
    monkeypatch.setattr(glm_transport, "_glm_cooldown_until", 0.0)


def test_get_glm_models_refresh_false_skips_live_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("glm_config.get_zhipu_api_key", lambda: "test-key")
    monkeypatch.setattr("glm_config._read_glm_models_cache", lambda: [])
    monkeypatch.setattr(
        "glm_config.fetch_zhipu_models",
        lambda: (_ for _ in ()).throw(AssertionError("live fetch should not run")),
    )
    models = glm_config.get_glm_models(refresh=False)
    assert "glm-5.3" in models
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


def test_streaming_length_cutoff_is_logged(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Reasoning spends max_tokens and the JSON is cut off; the log must say so by name."""
    monkeypatch.setattr("glm_config.get_zhipu_api_key", lambda: "k")
    monkeypatch.setattr("model_registry.get_glm_base_urls", lambda: ["https://only/v4"])
    usage = {"completion_tokens": 4096, "completion_tokens_details": {"reasoning_tokens": 3042}}

    def fake_post(url: str, **kwargs: object) -> MagicMock:
        r = MagicMock()
        r.status_code = 200
        r.raise_for_status = lambda: None

        first = {"choices": [{"delta": {"content": '{"a": '}}]}
        last = {"choices": [{"delta": {}, "finish_reason": "length"}], "usage": usage}

        def iter_lines(decode_unicode: bool = True):
            yield f"data: {json.dumps(first)}"
            yield f"data: {json.dumps(last)}"
            yield "data: [DONE]"

        r.iter_lines = iter_lines
        return r

    monkeypatch.setattr("glm_transport.requests.post", fake_post)

    with caplog.at_level("WARNING", logger="glm_transport"):
        parts = list(
            glm_transport.glm_chat_completion(
                [{"role": "user", "content": "x"}],
                model="glm-5.2",
                stream=True,
                json_mode=True,
                temperature=0.1,
                max_tokens=4096,
                timeout=30.0,
                allow_cheap_fallback=False,
            )
        )
    assert "".join(parts) == '{"a": '
    assert "truncated at max_tokens=4096" in caplog.text
    assert "reasoning_tokens=3042" in caplog.text


def test_live_glm_models_have_room_to_reason() -> None:
    """GLM-5.x reasoning alone used ~3k tokens on a real ticker prompt; 4096 truncated 60% of calls."""
    cfg = json.loads((web_dashboard / "model_config.json").read_text(encoding="utf-8"))
    for model in ("glm-5.3", "glm-5.2", "glm-5.1", "glm-5-turbo"):
        assert cfg["models"][model]["max_tokens"] >= 16384, model


def test_glm_raw_indicates_transport_failure_known_messages() -> None:
    assert glm_transport.glm_raw_indicates_transport_failure(
        "GLM request timed out. Please try again."
    )
    assert glm_transport.glm_raw_indicates_transport_failure("GLM API error: 429 boom")
    assert glm_transport.glm_raw_indicates_transport_failure("GLM error: connection reset")
    assert not glm_transport.glm_raw_indicates_transport_failure('{"summary": "ok"}')
    assert not glm_transport.glm_raw_indicates_transport_failure("")


def _enable_local_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GLM_FALLBACK_TO_LOCAL", "true")
    monkeypatch.delenv("GLM_LOCAL_FALLBACK_BASE_URL", raising=False)
    monkeypatch.delenv("GLM_LOCAL_FALLBACK_MODEL", raising=False)
    monkeypatch.delenv("OLLAMA_BASE_URL_2", raising=False)
    monkeypatch.setenv("OLLAMA_BASE_URL_NVIDIA", "http://laptop:11434")
    monkeypatch.setattr("glm_config.get_zhipu_api_key", lambda: "k")
    monkeypatch.setattr("model_registry.get_glm_base_urls", lambda: ["https://only/v4"])


def test_local_fallback_when_zai_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    import requests

    from model_registry import OLLAMA_NVIDIA_DEFAULT

    _enable_local_fallback(monkeypatch)
    calls: list[tuple[str, dict]] = []

    def fake_post(url: str, **kwargs: object) -> MagicMock:
        calls.append((url, kwargs["json"]))  # type: ignore[arg-type]
        if url.startswith("https://only"):
            raise requests.exceptions.ConnectionError("down")
        r = MagicMock()
        r.raise_for_status = lambda: None
        r.json.return_value = {"choices": [{"message": {"content": '{"ok": true}'}}]}
        return r

    monkeypatch.setattr("glm_transport.requests.post", fake_post)

    out = glm_transport.glm_chat_completion_text(
        [{"role": "user", "content": "x"}],
        model="glm-5.2",
        json_mode=True,
        temperature=0.1,
        max_tokens=64,
        timeout=30.0,
        allow_cheap_fallback=False,
    )
    assert out == '{"ok": true}'
    url, body = calls[-1]
    assert url == "http://laptop:11434/v1/chat/completions"
    assert body["model"] == OLLAMA_NVIDIA_DEFAULT
    assert body["reasoning_effort"] == "none"
    assert body["response_format"] == {"type": "json_object"}
    assert body["stream"] is False


def test_local_fallback_failure_keeps_glm_error(monkeypatch: pytest.MonkeyPatch) -> None:
    import requests

    _enable_local_fallback(monkeypatch)

    def fake_post(url: str, **kwargs: object) -> MagicMock:
        raise requests.exceptions.ConnectionError("down")

    monkeypatch.setattr("glm_transport.requests.post", fake_post)

    out = glm_transport.glm_chat_completion_text(
        [{"role": "user", "content": "x"}],
        model="glm-5.2",
        temperature=0.1,
        max_tokens=64,
        timeout=30.0,
        allow_cheap_fallback=False,
    )
    assert out == "Cannot connect to GLM API."


def test_local_fallback_skipped_without_local_host(monkeypatch: pytest.MonkeyPatch) -> None:
    import requests

    _enable_local_fallback(monkeypatch)
    monkeypatch.delenv("OLLAMA_BASE_URL_NVIDIA", raising=False)
    urls: list[str] = []

    def fake_post(url: str, **kwargs: object) -> MagicMock:
        urls.append(url)
        raise requests.exceptions.ConnectionError("down")

    monkeypatch.setattr("glm_transport.requests.post", fake_post)

    glm_transport.glm_chat_completion_text(
        [{"role": "user", "content": "x"}],
        model="glm-5.2",
        temperature=0.1,
        max_tokens=64,
        timeout=30.0,
        allow_cheap_fallback=False,
    )
    assert urls == ["https://only/v4/chat/completions"]


def test_local_fallback_not_used_after_partial_stream(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_local_fallback(monkeypatch)
    urls: list[str] = []

    def fake_post(url: str, **kwargs: object) -> MagicMock:
        urls.append(url)
        r = MagicMock()
        r.status_code = 200
        r.raise_for_status = lambda: None

        def iter_lines(decode_unicode: bool = True):
            yield f'data: {json.dumps({"choices": [{"delta": {"content": "a"}, "finish_reason": None}]})}'
            raise RuntimeError("stream cut")

        r.iter_lines = iter_lines
        return r

    monkeypatch.setattr("glm_transport.requests.post", fake_post)

    parts = list(
        glm_transport.glm_chat_completion(
            [{"role": "user", "content": "x"}],
            model="glm-5.2",
            stream=True,
            temperature=0.1,
            max_tokens=64,
            timeout=30.0,
            allow_cheap_fallback=False,
        )
    )
    assert parts[0] == "a"
    assert parts[1].startswith("GLM error:")
    assert urls == ["https://only/v4/chat/completions"]


def test_local_fallback_message_returns_tool_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    import requests

    _enable_local_fallback(monkeypatch)

    def fake_post(url: str, **kwargs: object) -> MagicMock:
        if url.startswith("https://only"):
            raise requests.exceptions.Timeout("slow")
        assert kwargs["json"]["tools"]  # type: ignore[index]
        r = MagicMock()
        r.raise_for_status = lambda: None
        r.json.return_value = {
            "choices": [
                {
                    "finish_reason": "tool_calls",
                    "message": {
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "c1",
                                "type": "function",
                                "function": {"name": "get_quote", "arguments": '{"ticker":"AAPL"}'},
                            }
                        ],
                    },
                }
            ]
        }
        return r

    monkeypatch.setattr("glm_transport.requests.post", fake_post)

    res = glm_transport.glm_chat_completion_message(
        [{"role": "user", "content": "price?"}],
        model="glm-5.2",
        temperature=0.1,
        max_tokens=64,
        tools=[{"type": "function", "function": {"name": "get_quote", "parameters": {}}}],
        timeout=30.0,
        allow_cheap_fallback=False,
    )
    assert res.error is None
    assert res.has_tool_calls
    assert res.tool_calls[0]["function"]["name"] == "get_quote"


# --- OpenRouter (DeepSeek) fallback + quota cooldown --------------------------------


def _enable_openrouter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GLM_FALLBACK_TO_OPENROUTER", "true")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test")
    monkeypatch.delenv("OPENROUTER_FALLBACK_MODEL", raising=False)
    monkeypatch.delenv("OPENROUTER_BASE_URL", raising=False)
    monkeypatch.setattr("glm_config.get_zhipu_api_key", lambda: "k")
    monkeypatch.setattr("model_registry.get_glm_base_urls", lambda: ["https://only/v4"])


def _http_error(status: int):
    import requests

    resp = MagicMock()
    resp.status_code = status
    err = requests.exceptions.HTTPError(f"{status} Client Error: Too Many Requests", response=resp)
    r = MagicMock()
    r.status_code = status
    r.raise_for_status.side_effect = err
    return r


def _ok(message: dict) -> MagicMock:
    r = MagicMock()
    r.status_code = 200
    r.raise_for_status = lambda: None
    r.json.return_value = {"choices": [{"message": message, "finish_reason": "stop"}]}
    return r


def test_openrouter_used_before_local_when_glm_quota_exhausted(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_openrouter(monkeypatch)
    _enable_local_fallback(monkeypatch)
    calls: list[tuple[str, dict, dict]] = []

    def fake_post(url: str, **kwargs: object) -> MagicMock:
        calls.append((url, kwargs.get("json") or {}, kwargs.get("headers") or {}))  # type: ignore[arg-type]
        if url.startswith("https://only"):
            return _http_error(429)
        return _ok({"content": "", "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "search_web", "arguments": "{}"}}]})

    monkeypatch.setattr("glm_transport.requests.post", fake_post)
    tools = [{"type": "function", "function": {"name": "search_web", "parameters": {}}}]
    res = glm_transport.glm_chat_completion_message(
        [{"role": "user", "content": "x"}], model="glm-5.3", temperature=0.1, max_tokens=64,
        tools=tools, tool_choice="auto", allow_cheap_fallback=False,
    )
    assert not res.error
    assert res.tool_calls and res.tool_calls[0]["function"]["name"] == "search_web"
    assert res.model_used == "openrouter:deepseek/deepseek-v4-pro"
    url, body, headers = calls[-1]
    assert url == "https://openrouter.ai/api/v1/chat/completions"
    assert body["model"] == "deepseek/deepseek-v4-pro" and body["tools"] == tools
    assert headers["Authorization"] == "Bearer or-test"
    assert not any(u.startswith("http://laptop") for u, _, _ in calls)
    # 429 started the cooldown: the next call skips Z.AI entirely.
    assert glm_transport.glm_cooldown_active()
    calls.clear()
    glm_transport.glm_chat_completion_message(
        [{"role": "user", "content": "y"}], model="glm-5.3", temperature=0.1, max_tokens=64,
        allow_cheap_fallback=False,
    )
    assert [u for u, _, _ in calls] == ["https://openrouter.ai/api/v1/chat/completions"]


def test_connection_error_falls_back_without_cooldown(monkeypatch: pytest.MonkeyPatch) -> None:
    import requests

    _enable_openrouter(monkeypatch)

    def fake_post(url: str, **kwargs: object) -> MagicMock:
        if url.startswith("https://only"):
            raise requests.exceptions.ConnectionError("down")
        return _ok({"content": "deepseek answer"})

    monkeypatch.setattr("glm_transport.requests.post", fake_post)
    out = glm_transport.glm_chat_completion_text(
        [{"role": "user", "content": "x"}], model="glm-5.3", temperature=0.1, max_tokens=64,
        allow_cheap_fallback=False,
    )
    assert out == "deepseek answer"
    assert not glm_transport.glm_cooldown_active()  # a blip is not quota exhaustion


def test_openrouter_failure_falls_through_to_local(monkeypatch: pytest.MonkeyPatch) -> None:
    import requests

    _enable_openrouter(monkeypatch)
    _enable_local_fallback(monkeypatch)

    def fake_post(url: str, **kwargs: object) -> MagicMock:
        if url.startswith("https://only"):
            raise requests.exceptions.ConnectionError("down")
        if "openrouter" in url:
            return _http_error(402)
        return _ok({"content": "local answer"})

    monkeypatch.setattr("glm_transport.requests.post", fake_post)
    out = glm_transport.glm_chat_completion_text(
        [{"role": "user", "content": "x"}], model="glm-5.3", temperature=0.1, max_tokens=64,
        allow_cheap_fallback=False,
    )
    assert out == "local answer"


def test_openrouter_skipped_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_openrouter(monkeypatch)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert glm_transport._openrouter_fallback_target() is None
    glm_transport._note_glm_failure("GLM API error: 429 Client Error")
    assert not glm_transport.glm_cooldown_active()  # no fallback => never skip GLM
