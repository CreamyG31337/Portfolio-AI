from __future__ import annotations

import sys
from pathlib import Path

web_dashboard = Path(__file__).resolve().parent.parent / "web_dashboard"
if str(web_dashboard) not in sys.path:
    sys.path.insert(0, str(web_dashboard))

import user_preferences  # noqa: E402


def test_get_user_currency_uses_preference_lookup(monkeypatch):
    monkeypatch.setattr("user_preferences.get_user_preference", lambda *_args, **_kwargs: "USD")

    assert user_preferences.get_user_currency() == "USD"
