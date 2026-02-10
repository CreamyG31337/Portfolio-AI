from web_dashboard import settings


def test_normalize_fund_type_aliases() -> None:
    assert settings.normalize_fund_type("tfsa") == "TFSA"
    assert settings.normalize_fund_type("rrsp") == "RRSP"
    assert settings.normalize_fund_type("short_term") == "TFSA"
    assert settings.normalize_fund_type("long_term") == "RRSP"
    assert settings.normalize_fund_type(None) == "DEFAULT"


def test_get_signal_alert_policy_uses_profile_defaults() -> None:
    policy = settings.get_signal_alert_policy("RRSP")
    assert policy["profile_key"] == "RRSP"
    assert policy["min_confidence"] == 0.78
    assert policy["fear_levels"] == ["EXTREME"]
    rebalance = settings.get_rebalance_policy("RRSP")
    assert rebalance["max_position_pct"] == 8.0


def test_get_fund_profile_settings_applies_system_override(monkeypatch) -> None:
    def _mock_get_system_setting(key: str, default=None):
        if key == "fund_profile_settings":
            return {
                "DEFAULT": {"signal_alert_min_confidence": 0.71},
                "TFSA": {"signal_alert_min_confidence": 0.83},
            }
        return default

    monkeypatch.setattr(settings, "get_system_setting", _mock_get_system_setting)
    profile = settings.get_fund_profile_settings("TFSA")
    assert profile["signal_alert_min_confidence"] == 0.83


def test_get_rebalance_policy_returns_typed_values(monkeypatch) -> None:
    def _mock_get_system_setting(key: str, default=None):
        if key == "fund_profile_settings":
            return {
                "TFSA": {
                    "rebalance_max_position_pct": "11.5",
                    "rebalance_review_days": "9",
                }
            }
        return default

    monkeypatch.setattr(settings, "get_system_setting", _mock_get_system_setting)
    policy = settings.get_rebalance_policy("TFSA")
    assert policy["max_position_pct"] == 11.5
    assert policy["review_days"] == 9
