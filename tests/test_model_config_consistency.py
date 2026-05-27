"""Static consistency between hardcoded model-name defaults and ``model_config.json``.

These tests do **not** touch a live Ollama. They guard against a class of bugs
that nothing else in the suite catches: a typo or stale name in a default
constant (e.g. renaming ``qwen3.6:27b`` -> ``qwen3.6:27b-heretic`` in code but
forgetting to update ``model_config.json``, or vice versa). Mocked unit tests
happily echo whatever default string we hand them, so the rename "passes"
even when the model would 404 in production.

Scope: only Ollama-style names (the ``provider`` field is absent). GLM/Z.AI
and webai models are excluded because they are routed differently and may
intentionally not appear in ``model_config.json`` for every code path.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

WEB_DASHBOARD = Path(__file__).resolve().parent.parent / "web_dashboard"
if str(WEB_DASHBOARD) not in sys.path:
    sys.path.insert(0, str(WEB_DASHBOARD))


@pytest.fixture(scope="module")
def model_config() -> dict:
    cfg_path = WEB_DASHBOARD / "model_config.json"
    assert cfg_path.exists(), f"model_config.json missing at {cfg_path}"
    return json.loads(cfg_path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def ollama_model_names(model_config: dict) -> set[str]:
    """Set of Ollama-style model keys in model_config.json (no ``provider`` field)."""
    return {
        name
        for name, spec in model_config.get("models", {}).items()
        if isinstance(spec, dict) and "provider" not in spec
    }


def _is_ollama_style(name: str) -> bool:
    """Heuristic: Ollama tags use ``name:tag`` and we want to exclude GLM/webai/embed.

    Excludes:
    - empty / falsy
    - GLM family (``glm-*``) — routed via Z.AI
    - Gemini (``gemini-*``) — webai
    - Pure model families without a colon (rare; treated as non-Ollama)
    """
    if not name:
        return False
    s = name.strip()
    if not s or s.startswith("glm-") or s.startswith("gemini-"):
        return False
    return ":" in s


def test_summarizing_model_default_exists_in_config(ollama_model_names: set[str]) -> None:
    """``settings.get_summarizing_model()`` default must be a real model_config key."""
    import settings as settings_module

    model = settings_module.get_summarizing_model()
    assert _is_ollama_style(model), f"Default summarizing model {model!r} is not Ollama-style"
    assert model in ollama_model_names, (
        f"Default summarizing model {model!r} not found in model_config.json. "
        f"Known Ollama models: {sorted(ollama_model_names)}"
    )


def test_summarizing_fallback_models_all_exist_in_config(ollama_model_names: set[str]) -> None:
    """Every Ollama-style entry in the fallback chain must exist in model_config."""
    import settings as settings_module

    fallbacks = settings_module.get_summarizing_fallback_models()
    assert fallbacks, "Fallback model list should not be empty"
    missing = [m for m in fallbacks if _is_ollama_style(m) and m not in ollama_model_names]
    assert not missing, (
        f"Fallback models {missing!r} not in model_config.json. "
        f"Known: {sorted(ollama_model_names)}"
    )


def test_ai_task_workers_secondary_default_exists(ollama_model_names: set[str]) -> None:
    """The Ollama-secondary worker model resolves to a known config entry."""
    from scheduler import ai_task_workers

    model = ai_task_workers.model_for_backend(ai_task_workers.BACKEND_OLLAMA_SECONDARY)
    assert model in ollama_model_names, (
        f"AI queue secondary model {model!r} not in model_config.json. "
        f"Known: {sorted(ollama_model_names)}"
    )


def test_ai_task_workers_primary_default_exists(ollama_model_names: set[str]) -> None:
    """The Ollama-primary worker model resolves to a known config entry."""
    from scheduler import ai_task_workers

    model = ai_task_workers.model_for_backend(ai_task_workers.BACKEND_OLLAMA_PRIMARY)
    assert model in ollama_model_names, (
        f"AI queue primary model {model!r} not in model_config.json. "
        f"Known: {sorted(ollama_model_names)}"
    )


def test_admin_probe_models_all_exist(ollama_model_names: set[str]) -> None:
    """Models in the admin probe set must exist (otherwise the admin page shows phantom rows)."""
    from routes import admin_routes

    probes = admin_routes._ollama_models_to_probe()
    missing = [m for m in probes if _is_ollama_style(m) and m not in ollama_model_names]
    assert not missing, (
        f"Admin probe models {missing!r} not in model_config.json. "
        f"Known: {sorted(ollama_model_names)}"
    )


def test_summary_model_chain_resolves_to_known_models(ollama_model_names: set[str]) -> None:
    """``ollama_client._get_summary_model_chain`` for a known primary stays in config."""
    import ollama_client

    chain = ollama_client._get_summary_model_chain(None)
    assert chain, "Expected a non-empty summary model chain"
    missing = [m for m in chain if _is_ollama_style(m) and m not in ollama_model_names]
    assert not missing, (
        f"Summary model chain contains unknown Ollama models {missing!r}. "
        f"Known: {sorted(ollama_model_names)}"
    )
