from web_dashboard.routes import dashboard_routes


def test_build_global_dashboard_alert_policy_uses_strictest_confidence() -> None:
    policy = dashboard_routes._build_global_dashboard_alert_policy(
        [
            {"min_confidence": 0.70, "fear_levels": ["HIGH", "EXTREME"]},
            {"min_confidence": 0.82, "fear_levels": ["EXTREME"]},
        ]
    )
    assert policy["min_confidence"] == 0.82
    assert policy["fear_levels"] == ["EXTREME"]


def test_resolve_dashboard_alert_policy_for_specific_fund(monkeypatch) -> None:
    class _Query:
        def __init__(self, data):
            self._data = data

        def select(self, *_args, **_kwargs):
            return self

        def eq(self, *_args, **_kwargs):
            return self

        def limit(self, *_args, **_kwargs):
            return self

        def execute(self):
            return type("Result", (), {"data": self._data})()

    class _Supabase:
        def table(self, name):
            if name == "funds":
                return _Query([{"fund_type": "RRSP", "is_production": True}])
            raise AssertionError(f"Unexpected table: {name}")

    class _Client:
        supabase = _Supabase()

    policy = dashboard_routes._resolve_dashboard_alert_policy(_Client(), "Some Fund")
    assert policy["profile_key"] == "RRSP"
    assert policy["min_confidence"] == 0.78
