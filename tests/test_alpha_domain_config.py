"""Tests for configurable alpha-research domain enable/disable.

Covers ``settings.get_alpha_research_domains`` /
``settings.get_alpha_research_domain_config`` /
``settings._normalize_alpha_domain_entries``:

* backwards compatibility with the legacy flat ``list[str]`` shape,
* the preferred structured ``list[dict]`` shape with per-domain ``enabled``
  flags so operators can temporarily disable a noisy/blocked domain without
  losing the entry,
* env-var override precedence,
* robustness against malformed config.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

web_dashboard = Path(__file__).resolve().parent.parent / "web_dashboard"
if str(web_dashboard) not in sys.path:
    sys.path.insert(0, str(web_dashboard))

import settings as settings_mod  # noqa: E402


@pytest.fixture(autouse=True)
def _no_env_domains(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure ALPHA_RESEARCH_DOMAINS does not leak in from the real environment."""
    monkeypatch.delenv("ALPHA_RESEARCH_DOMAINS", raising=False)


def _patch_setting(monkeypatch: pytest.MonkeyPatch, value: object) -> None:
    def fake_get(key: str, default: object = None) -> object:
        if key == "alpha_research_domains":
            return value
        return default

    monkeypatch.setattr(settings_mod, "get_system_setting", fake_get)


# --------------------------------------------------------------------------- #
# Legacy flat list[str]
# --------------------------------------------------------------------------- #


def test_legacy_flat_list_all_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_setting(monkeypatch, ["fool.com", "benzinga.com"])
    assert settings_mod.get_alpha_research_domains() == ["fool.com", "benzinga.com"]


def test_legacy_flat_list_strips_blanks(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_setting(monkeypatch, ["  fool.com  ", "", "   "])
    assert settings_mod.get_alpha_research_domains() == ["fool.com"]


# --------------------------------------------------------------------------- #
# Structured list[dict] with enabled flags
# --------------------------------------------------------------------------- #


def test_structured_filters_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_setting(
        monkeypatch,
        [
            {"domain": "fool.com", "enabled": True, "note": "reliable"},
            {"domain": "seekingalpha.com", "enabled": False, "note": "paywalled"},
            {"domain": "benzinga.com", "enabled": True},
        ],
    )
    # Only enabled domains drive the site: dorks.
    assert settings_mod.get_alpha_research_domains() == ["fool.com", "benzinga.com"]


def test_structured_enabled_defaults_true_when_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_setting(monkeypatch, [{"domain": "fool.com"}])
    assert settings_mod.get_alpha_research_domains() == ["fool.com"]


def test_config_view_preserves_disabled_and_notes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_setting(
        monkeypatch,
        [
            {"domain": "fool.com", "enabled": True, "note": "reliable"},
            {"domain": "investorplace.com", "enabled": False, "note": "advertorials"},
        ],
    )
    config = settings_mod.get_alpha_research_domain_config()
    assert config == [
        {"domain": "fool.com", "enabled": True, "note": "reliable"},
        {"domain": "investorplace.com", "enabled": False, "note": "advertorials"},
    ]
    # The enabled-only getter hides the disabled one but the config keeps it.
    assert settings_mod.get_alpha_research_domains() == ["fool.com"]


def test_mixed_string_and_dict_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_setting(
        monkeypatch,
        ["fool.com", {"domain": "benzinga.com", "enabled": False}],
    )
    assert settings_mod.get_alpha_research_domains() == ["fool.com"]


# --------------------------------------------------------------------------- #
# Robustness
# --------------------------------------------------------------------------- #


def test_none_setting_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_setting(monkeypatch, None)
    assert settings_mod.get_alpha_research_domains() == []
    assert settings_mod.get_alpha_research_domain_config() == []


def test_non_list_setting_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_setting(monkeypatch, {"domain": "fool.com"})  # dict, not list
    assert settings_mod.get_alpha_research_domains() == []


def test_malformed_entries_are_dropped(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_setting(
        monkeypatch,
        [
            None,
            123,
            {"note": "no domain key"},
            {"domain": "   "},
            ["nested", "list"],
            {"domain": "fool.com", "enabled": True},
        ],
    )
    assert settings_mod.get_alpha_research_domains() == ["fool.com"]


def test_truthy_enabled_values_are_coerced(monkeypatch: pytest.MonkeyPatch) -> None:
    # Operators editing JSON by hand may use 1/0 rather than true/false.
    _patch_setting(
        monkeypatch,
        [
            {"domain": "fool.com", "enabled": 1},
            {"domain": "benzinga.com", "enabled": 0},
        ],
    )
    assert settings_mod.get_alpha_research_domains() == ["fool.com"]


# --------------------------------------------------------------------------- #
# Env var precedence
# --------------------------------------------------------------------------- #


def test_env_var_overrides_system_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPHA_RESEARCH_DOMAINS", "envone.com, envtwo.com")
    # system_setting should be ignored when env var is present.
    _patch_setting(monkeypatch, [{"domain": "dbonly.com", "enabled": True}])
    assert settings_mod.get_alpha_research_domains() == ["envone.com", "envtwo.com"]
    config = settings_mod.get_alpha_research_domain_config()
    assert config == [
        {"domain": "envone.com", "enabled": True},
        {"domain": "envtwo.com", "enabled": True},
    ]


# --------------------------------------------------------------------------- #
# Alpha search time range
# --------------------------------------------------------------------------- #


def _patch_time_range_setting(monkeypatch: pytest.MonkeyPatch, value: object) -> None:
    def fake_get(key: str, default: object = None) -> object:
        if key == "alpha_search_time_range":
            return value
        return default

    monkeypatch.setattr(settings_mod, "get_system_setting", fake_get)
    monkeypatch.delenv("ALPHA_SEARCH_TIME_RANGE", raising=False)


def test_time_range_defaults_to_week(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_time_range_setting(monkeypatch, None)
    assert settings_mod.get_alpha_search_time_range() == "week"


def test_time_range_valid_values_pass_through(monkeypatch: pytest.MonkeyPatch) -> None:
    for v in ("day", "week", "month", "year"):
        _patch_time_range_setting(monkeypatch, v)
        assert settings_mod.get_alpha_search_time_range() == v


def test_time_range_normalizes_case_and_whitespace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_time_range_setting(monkeypatch, "  Month ")
    assert settings_mod.get_alpha_search_time_range() == "month"


def test_time_range_all_time_sentinels_return_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for v in ("none", "all", "any", "", "  "):
        _patch_time_range_setting(monkeypatch, v)
        assert settings_mod.get_alpha_search_time_range() is None


def test_time_range_invalid_falls_back_to_week(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_time_range_setting(monkeypatch, "fortnight")
    assert settings_mod.get_alpha_search_time_range() == "week"


def test_time_range_env_var_used_when_no_setting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_get(key: str, default: object = None) -> object:
        return default  # no system_setting configured

    monkeypatch.setattr(settings_mod, "get_system_setting", fake_get)
    monkeypatch.setenv("ALPHA_SEARCH_TIME_RANGE", "month")
    assert settings_mod.get_alpha_search_time_range() == "month"


def test_time_range_setting_overrides_env(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get(key: str, default: object = None) -> object:
        if key == "alpha_search_time_range":
            return "day"
        return default

    monkeypatch.setattr(settings_mod, "get_system_setting", fake_get)
    monkeypatch.setenv("ALPHA_SEARCH_TIME_RANGE", "year")
    assert settings_mod.get_alpha_search_time_range() == "day"
