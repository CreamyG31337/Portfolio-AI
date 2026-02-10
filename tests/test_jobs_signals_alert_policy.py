from web_dashboard.scheduler.jobs_signals import _build_global_alert_policy, _should_alert


def test_build_global_alert_policy_uses_strictest_confidence_and_common_fear_levels() -> None:
    policy = _build_global_alert_policy(
        [
            {"min_confidence": 0.70, "fear_levels": ["HIGH", "EXTREME"], "cooldown_minutes": 180},
            {"min_confidence": 0.82, "fear_levels": ["EXTREME"], "cooldown_minutes": 720},
        ]
    )

    assert policy["min_confidence"] == 0.82
    assert policy["fear_levels"] == ["EXTREME"]
    assert policy["cooldown_minutes"] == 720


def test_should_alert_respects_min_confidence() -> None:
    signals = {
        "overall_signal": "BUY",
        "confidence": 0.75,
        "fear_risk": {"fear_level": "LOW"},
    }
    policy = {"min_confidence": 0.80, "fear_levels": ["EXTREME"]}

    assert _should_alert(signals, policy=policy) is False


def test_should_alert_on_allowed_fear_level_even_without_signal() -> None:
    signals = {
        "overall_signal": "HOLD",
        "confidence": 0.10,
        "fear_risk": {"fear_level": "high"},
    }
    policy = {"min_confidence": 0.90, "fear_levels": ["HIGH"]}

    assert _should_alert(signals, policy=policy) is True
