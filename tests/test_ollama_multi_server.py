"""Multi-host Ollama routing (phase 1): mocks always run; live tests skip when unreachable or AI disabled."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import requests

web_dashboard = Path(__file__).resolve().parent.parent / "web_dashboard"
if str(web_dashboard) not in sys.path:
    sys.path.insert(0, str(web_dashboard))

import ollama_client  # noqa: E402
import settings as settings_module  # noqa: E402


def _reachable(url: str) -> bool:
    try:
        return bool(requests.get(f"{url.rstrip('/')}/api/tags", timeout=3).ok)
    except OSError:
        return False


def test_qwen_payload_includes_think_false_and_routes_to_env_second_host(monkeypatch: pytest.MonkeyPatch) -> None:
    """qwen3.8:27b-mtp-q4_K_M hits NVIDIA URL first; granite4.1:8b hits AMD URL first (semantic env aliases)."""
    monkeypatch.delenv("OLLAMA_BASE_URL_AMD", raising=False)
    monkeypatch.delenv("OLLAMA_BASE_URL_NVIDIA", raising=False)
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://amd-test:11434")
    monkeypatch.setenv("OLLAMA_BASE_URL_2", "http://rtx-test:11434")
    client = ollama_client.OllamaClient(base_url="http://amd-test:11434")
    captured: list[tuple[str, dict]] = []

    def fake_post(url: str, json: dict | None = None, **kwargs: object) -> MagicMock:
        captured.append((url, json or {}))
        resp = MagicMock()
        resp.json.return_value = {"response": "ok"}
        resp.raise_for_status = lambda: None
        return resp

    monkeypatch.setattr(client.session, "post", fake_post)
    out = client.generate_completion(prompt="x", model="qwen3.8:27b-mtp-q4_K_M", json_mode=False)
    assert out == "ok"
    assert captured
    first_url, payload = captured[0]
    assert "rtx-test" in first_url
    assert payload.get("think") is False

    captured.clear()
    client.generate_completion(prompt="x", model="granite4.1:8b", json_mode=False)
    assert captured
    g_url, g_payload = captured[0]
    assert "amd-test" in g_url
    assert g_payload.get("think") is False


def test_ollama_semantic_host_env_aliases_fallback_to_legacy_pair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OLLAMA_BASE_URL_AMD / _NVIDIA fall back to OLLAMA_BASE_URL / _2 when unset."""
    monkeypatch.delenv("OLLAMA_BASE_URL_AMD", raising=False)
    monkeypatch.delenv("OLLAMA_BASE_URL_NVIDIA", raising=False)
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://legacy-amd:11434")
    monkeypatch.setenv("OLLAMA_BASE_URL_2", "http://legacy-nv:11434")
    assert ollama_client._resolve_ollama_host_env("OLLAMA_BASE_URL_AMD") == "http://legacy-amd:11434"
    assert ollama_client._resolve_ollama_host_env("OLLAMA_BASE_URL_NVIDIA") == "http://legacy-nv:11434"


def test_ollama_semantic_host_env_explicit_overrides_legacy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://wrong-amd:11434")
    monkeypatch.setenv("OLLAMA_BASE_URL_2", "http://wrong-nv:11434")
    monkeypatch.setenv("OLLAMA_BASE_URL_AMD", "http://explicit-amd:11434")
    monkeypatch.setenv("OLLAMA_BASE_URL_NVIDIA", "http://explicit-nv:11434")
    assert ollama_client._resolve_ollama_host_env("OLLAMA_BASE_URL_AMD") == "http://explicit-amd:11434"
    assert ollama_client._resolve_ollama_host_env("OLLAMA_BASE_URL_NVIDIA") == "http://explicit-nv:11434"


def test_fallback_retry_on_http_404_for_default_base_models(monkeypatch: pytest.MonkeyPatch) -> None:
    """Models using only OLLAMA_BASE_URL (e.g. mistral-nemo) retry on OLLAMA_BASE_URL_2 after 404."""
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://host-a:11434")
    monkeypatch.setenv("OLLAMA_BASE_URL_2", "http://host-b:11434")
    monkeypatch.setattr(
        settings_module,
        "get_system_setting",
        lambda _key, default=None: default,
    )
    client = ollama_client.OllamaClient(base_url="http://host-a:11434")
    posts: list[str] = []

    def fake_post(url: str, json: dict | None = None, **kwargs: object) -> MagicMock:
        posts.append(url)
        if "host-a" in url:
            r = MagicMock()
            r.raise_for_status.side_effect = requests.HTTPError(response=MagicMock(status_code=404))
            return r
        r = MagicMock()
        r.raise_for_status = lambda: None
        r.json.return_value = {"response": "ok"}
        return r

    monkeypatch.setattr(client.session, "post", fake_post)
    out = client._post_ollama(
        "mistral-nemo:12b",
        "/api/generate",
        {"model": "mistral-nemo:12b", "prompt": "x"},
        stream=False,
    )
    assert len(posts) == 2
    assert "host-a" in posts[0]
    assert "host-b" in posts[1]
    assert out.json()["response"] == "ok"


def test_fallback_retry_on_http_404_for_qwen(monkeypatch: pytest.MonkeyPatch) -> None:
    """Primary host may answer /api/tags but return 404 on /api/generate — try fallback."""
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://good-fallback:11434")
    monkeypatch.setenv("OLLAMA_BASE_URL_2", "http://bad-primary:11434")
    monkeypatch.setattr(
        settings_module,
        "get_system_setting",
        lambda _key, default=None: default,
    )
    client = ollama_client.OllamaClient(base_url="http://good-fallback:11434")
    posts: list[str] = []

    def fake_post(url: str, json: dict | None = None, **kwargs: object) -> MagicMock:
        posts.append(url)
        if "bad-primary" in url:
            r = MagicMock()
            r.raise_for_status.side_effect = requests.HTTPError(response=MagicMock(status_code=404))
            return r
        r = MagicMock()
        r.raise_for_status = lambda: None
        r.json.return_value = {"response": "ok"}
        return r

    monkeypatch.setattr(client.session, "post", fake_post)
    out = client._post_ollama(
        "qwen3.8:27b-mtp-q4_K_M",
        "/api/generate",
        {"model": "qwen3.8:27b-mtp-q4_K_M", "prompt": "x"},
        stream=False,
    )
    assert "good-fallback" in posts[-1]
    assert out.json()["response"] == "ok"


def test_fallback_retry_on_connection_error_for_qwen(monkeypatch: pytest.MonkeyPatch) -> None:
    """ConnectionError on primary OLLAMA_BASE_URL_2 host triggers one retry on OLLAMA_BASE_URL."""
    monkeypatch.setenv("OLLAMA_BASE_URL_2", "http://rtx-fail:11434")
    client = ollama_client.OllamaClient(base_url="http://amd-ok:11434")
    calls: list[str] = []

    def fake_post(url: str, **kwargs: object) -> MagicMock:
        calls.append(url)
        if "rtx-fail" in url:
            raise requests.exceptions.ConnectionError("primary down")
        resp = MagicMock()
        resp.json.return_value = {"response": "recovered"}
        resp.raise_for_status = lambda: None
        return resp

    monkeypatch.setattr(client.session, "post", fake_post)
    out = client.generate_completion(prompt="x", model="qwen3.8:27b-mtp-q4_K_M")
    assert out == "recovered"
    assert any("rtx-fail" in u for u in calls)
    assert len(calls) == 2


def test_live_health_skips_when_no_ollama() -> None:
    """Quick GET /api/tags against default and per-model resolved hosts (no completion — avoids long GPU runs)."""
    base = ollama_client.OLLAMA_BASE_URL.rstrip("/")
    if not _reachable(base):
        pytest.skip(f"Ollama not reachable at {base}")
    client = ollama_client.OllamaClient()
    if not client.enabled:
        pytest.skip("OLLAMA_ENABLED is false")
    assert client.check_health() is True
    assert client.check_health_for_model("granite4.1:8b") is True
    if not client.check_health_for_model("qwen3.8:27b-mtp-q4_K_M"):
        pytest.skip("qwen3.8:27b-mtp-q4_K_M not installed on resolved Ollama host (ollama pull qwen3.8:27b-mtp-q4_K_M)")


def test_check_health_for_model_resolves_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLLAMA_BASE_URL_2", "http://resolved-ollama:11434")
    client = ollama_client.OllamaClient(base_url="http://default-ollama:11434")
    ok = False

    def fake_get(url: str, timeout: object = 5) -> MagicMock:
        nonlocal ok
        if "resolved-ollama" in url:
            ok = True
            r = MagicMock()
            r.status_code = 200
            r.json.return_value = {"models": [{"name": "qwen3.8:27b-mtp-q4_K_M"}]}
            return r
        r = MagicMock()
        r.status_code = 500
        return r

    monkeypatch.setattr(client.session, "get", fake_get)
    assert client.check_health_for_model("qwen3.8:27b-mtp-q4_K_M") is True
    assert ok is True


def test_check_health_for_model_false_when_model_not_in_tags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = ollama_client.OllamaClient(base_url="http://solo-ollama:11434")

    def fake_get(url: str, timeout: object = 5) -> MagicMock:
        r = MagicMock()
        r.status_code = 200
        r.json.return_value = {"models": [{"name": "granite3.3:8b"}]}
        return r

    monkeypatch.setattr(client.session, "get", fake_get)
    assert client.check_health_for_model("qwen3.8:27b-mtp-q4_K_M") is False


def test_ollama_tags_list_contains_model_exact_and_tag_suffix() -> None:
    assert ollama_client.ollama_tags_list_contains_model(["qwen3.8:27b-mtp-q4_K_M"], "qwen3.8:27b-mtp-q4_K_M")
    assert ollama_client.ollama_tags_list_contains_model(
        ["qwen3.8:27b-mtp-q4_K_M:extra"],
        "qwen3.8:27b-mtp-q4_K_M",
    )
    assert not ollama_client.ollama_tags_list_contains_model(
        ["granite3.3:8b"],
        "qwen3.8:27b-mtp-q4_K_M",
    )


def test_coalesce_ollama_generate_prefers_response_over_thinking() -> None:
    assert (
        ollama_client.coalesce_ollama_generate_response_text(
            {"response": "hello", "thinking": "zzz"}
        )
        == "hello"
    )


def test_coalesce_ollama_generate_falls_back_to_thinking_or_think() -> None:
    assert ollama_client.coalesce_ollama_generate_response_text(
        {"response": "", "thinking": '{"a": 1}'}
    ) == '{"a": 1}'
    assert ollama_client.coalesce_ollama_generate_response_text(
        {"response": "  ", "think": "x"}
    ) == "x"


def test_coalesce_ollama_generate_skips_thinking_when_disallowed() -> None:
    assert (
        ollama_client.coalesce_ollama_generate_response_text(
            {"response": "", "thinking": '{"a": 1}'},
            allow_thinking_fallback=False,
        )
        == ""
    )


def test_inference_slot_busy_skips_to_second_host(monkeypatch: pytest.MonkeyPatch) -> None:
    """When the primary URL's slot is taken, POST goes to the fallback base without failing."""
    monkeypatch.setenv("OLLAMA_MAX_CONCURRENT_PER_HOST", "1")
    monkeypatch.setenv("OLLAMA_HOST_SLOT_WAIT_SEC", "0")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://slot-b-fallback:11434")
    monkeypatch.setenv("OLLAMA_BASE_URL_2", "http://slot-a-primary:11434")
    monkeypatch.setattr(
        settings_module,
        "get_system_setting",
        lambda _key, default=None: default,
    )
    client = ollama_client.OllamaClient(base_url="http://slot-b-fallback:11434")
    sem = ollama_client._host_semaphore("http://slot-a-primary:11434")
    assert sem.acquire(blocking=False) is True
    posts: list[str] = []

    def fake_post(url: str, json: dict | None = None, **kwargs: object) -> MagicMock:
        posts.append(url)
        resp = MagicMock()
        resp.raise_for_status = lambda: None
        resp.json.return_value = {"response": "ok"}
        return resp

    try:
        monkeypatch.setattr(client.session, "post", fake_post)
        out = client._post_ollama(
            "qwen3.8:27b-mtp-q4_K_M",
            "/api/generate",
            {"model": "qwen3.8:27b-mtp-q4_K_M", "prompt": "x"},
            stream=False,
        )
        assert out.json()["response"] == "ok"
    finally:
        sem.release()
    assert any("slot-b-fallback" in p for p in posts)
    assert not any("slot-a-primary" in p for p in posts)


def test_streaming_slot_released_on_retryable_http_after_post(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If stream=True attaches the slot to ``r`` then ``raise_for_status`` fails with retryable
    HTTP, the slot must be released (otherwise per-host semaphores leak until exhausted).
    """
    monkeypatch.setenv("OLLAMA_MAX_CONCURRENT_PER_HOST", "1")
    monkeypatch.setenv("OLLAMA_HOST_SLOT_WAIT_SEC", "0.01")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://fallback-good:11434")
    monkeypatch.setenv("OLLAMA_BASE_URL_2", "http://primary-bad:11434")
    monkeypatch.setattr(
        settings_module,
        "get_system_setting",
        lambda _key, default=None: default,
    )
    client = ollama_client.OllamaClient(base_url="http://fallback-good:11434")
    sem_primary = ollama_client._host_semaphore("http://primary-bad:11434")

    def fake_post(url: str, json: dict | None = None, stream: bool = False, **kwargs: object) -> MagicMock:
        resp = MagicMock()
        resp.close = MagicMock()
        if "primary-bad" in url:
            resp.raise_for_status.side_effect = requests.HTTPError(
                response=MagicMock(status_code=503)
            )
            return resp
        resp.raise_for_status = lambda: None
        return resp

    monkeypatch.setattr(client.session, "post", fake_post)
    out = client._post_ollama(
        "qwen3.8:27b-mtp-q4_K_M",
        "/api/generate",
        {"model": "qwen3.8:27b-mtp-q4_K_M", "prompt": "x"},
        stream=True,
    )
    assert out is not None
    assert sem_primary.acquire(blocking=False) is True
    sem_primary.release()


def test_all_hosts_busy_raises_ollama_host_busy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLLAMA_MAX_CONCURRENT_PER_HOST", "1")
    monkeypatch.setenv("OLLAMA_HOST_SLOT_WAIT_SEC", "0")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://only-b:11434")
    monkeypatch.setenv("OLLAMA_BASE_URL_2", "http://only-a:11434")
    monkeypatch.setattr(
        settings_module,
        "get_system_setting",
        lambda _key, default=None: default,
    )
    client = ollama_client.OllamaClient(base_url="http://only-b:11434")
    s1 = ollama_client._host_semaphore("http://only-a:11434")
    s2 = ollama_client._host_semaphore("http://only-b:11434")
    assert s1.acquire(blocking=False) is True
    assert s2.acquire(blocking=False) is True
    try:
        with pytest.raises(ollama_client.OllamaHostBusyError):
            client._post_ollama(
                "qwen3.8:27b-mtp-q4_K_M",
                "/api/generate",
                {"model": "qwen3.8:27b-mtp-q4_K_M"},
                stream=False,
            )
    finally:
        s1.release()
        s2.release()


def test_default_summarizer_and_fallbacks_when_settings_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        settings_module,
        "get_system_setting",
        lambda _key, default=None: default,
    )
    monkeypatch.delenv("OLLAMA_SUMMARIZING_MODEL", raising=False)
    monkeypatch.delenv("OLLAMA_SUMMARIZING_FALLBACK_MODELS", raising=False)
    assert settings_module.get_summarizing_model() == "qwen3.8:27b-mtp-q4_K_M"
    assert settings_module.get_summarizing_fallback_models() == [
        "granite4.1:8b",
        "qwen3.8:27b-mtp-q4_K_M",
        "glm-5.2",
    ]
    chain = ollama_client._get_summary_model_chain(None)
    assert chain[0] == "qwen3.8:27b-mtp-q4_K_M"
    assert chain[1] == "granite4.1:8b"
    assert chain[2] == "glm-5.2"
    assert len(chain) == 3
    assert chain[-1].startswith("glm-")
