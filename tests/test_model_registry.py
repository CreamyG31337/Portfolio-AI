"""Tests for AI model preference resolution and deprecated GLM migration."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

WEB_DASHBOARD_ROOT = Path(__file__).resolve().parent.parent / "web_dashboard"
if str(WEB_DASHBOARD_ROOT) not in sys.path:
    sys.path.insert(0, str(WEB_DASHBOARD_ROOT))

from model_registry import (  # noqa: E402
    OLLAMA_QWEN38_STOCK,
    PRIMARY_MODEL_DEFAULT,
    remap_deprecated_model,
    resolve_ai_model_preference,
)


@pytest.mark.parametrize(
    "stored,available,expected",
    [
        ("glm-4.7", None, PRIMARY_MODEL_DEFAULT),
        ("glm-4.6", ["glm-5.2", "glm-5.1"], PRIMARY_MODEL_DEFAULT),
        ("glm-4.7", ["granite4.1:8b"], "granite4.1:8b"),
        ("glm-5.2", ["glm-5.2", "glm-5.1"], "glm-5.2"),
        (None, ["granite4.1:8b"], "granite4.1:8b"),
        ("qwen3.6:27b-heretic", None, OLLAMA_QWEN38_STOCK),
        ("qwen3.6:27b-heretic-agentic", ["qwen3.8:27b-mtp-q4_K_M"], OLLAMA_QWEN38_STOCK),
    ],
)
def test_resolve_ai_model_preference(
    stored: str | None,
    available: list[str] | None,
    expected: str,
) -> None:
    assert resolve_ai_model_preference(stored, available) == expected


def test_remap_deprecated_qwen36_tags() -> None:
    assert remap_deprecated_model("qwen3.6:27b-heretic") == OLLAMA_QWEN38_STOCK
    assert remap_deprecated_model("qwen3.6:27b-heretic-agentic") == OLLAMA_QWEN38_STOCK
    assert remap_deprecated_model("qwen3.8:27b-heretic") == OLLAMA_QWEN38_STOCK
    assert remap_deprecated_model(OLLAMA_QWEN38_STOCK) == OLLAMA_QWEN38_STOCK


def test_get_user_ai_model_migrates_deprecated_preference() -> None:
    import user_preferences  # noqa: E402

    with patch.object(
        user_preferences,
        "get_user_preference",
        return_value="glm-4.7",
    ), patch.object(
        user_preferences,
        "set_user_preference",
        return_value=True,
    ) as mock_set, patch(
        "ollama_client.list_available_models",
        return_value=["glm-5.2", "glm-5.1", "granite4.1:8b"],
    ):
        result = user_preferences.get_user_ai_model()

    assert result == PRIMARY_MODEL_DEFAULT
    mock_set.assert_called_once_with("ai_model", PRIMARY_MODEL_DEFAULT)
