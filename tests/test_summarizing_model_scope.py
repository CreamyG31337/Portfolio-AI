"""Scoped ``get_summarizing_model(scope)`` via ``ai_summarizing_model_<scope>`` keys."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

web_dashboard = Path(__file__).resolve().parent.parent / "web_dashboard"
if str(web_dashboard) not in sys.path:
    sys.path.insert(0, str(web_dashboard))

import settings as settings_mod  # noqa: E402


def test_summarizing_model_scoped_key_overrides_global(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get(key: str, default: object = None) -> object:
        if key == "ai_summarizing_model_meta_analysis":
            return "meta-llm"
        if key == "ai_summarizing_model":
            return "global-llm"
        return default

    monkeypatch.setattr(settings_mod, "get_system_setting", fake_get)
    assert settings_mod.get_summarizing_model("meta_analysis") == "meta-llm"
    assert settings_mod.get_summarizing_model() == "global-llm"


def test_summarizing_model_scope_normalizes_to_setting_suffix(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get(key: str, default: object = None) -> object:
        if key == "ai_summarizing_model_market_brief":
            return "brief-model"
        if key == "ai_summarizing_model":
            return "fallback-model"
        return default

    monkeypatch.setattr(settings_mod, "get_system_setting", fake_get)
    assert settings_mod.get_summarizing_model("Market Brief") == "brief-model"


def test_summarizing_model_scoped_missing_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get(key: str, default: object = None) -> object:
        if key == "ai_summarizing_model":
            return "only-global"
        return default

    monkeypatch.setattr(settings_mod, "get_system_setting", fake_get)
    assert settings_mod.get_summarizing_model("ticker_meta") == "only-global"
