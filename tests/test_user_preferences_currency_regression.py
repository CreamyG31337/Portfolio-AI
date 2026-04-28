from __future__ import annotations

import sys
from pathlib import Path

web_dashboard = Path(__file__).resolve().parent.parent / "web_dashboard"
if str(web_dashboard) not in sys.path:
    sys.path.insert(0, str(web_dashboard))

import user_preferences  # noqa: E402


def test_get_user_currency_falls_back_when_streamlit_import_raises(monkeypatch):
    original_import = __import__

    def _fake_import(name, *args, **kwargs):
        if name == "streamlit_utils":
            raise AttributeError("NoneType has no attribute cache_data")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", _fake_import)
    monkeypatch.setattr("user_preferences.get_user_preference", lambda *_args, **_kwargs: "USD")

    assert user_preferences.get_user_currency() == "USD"
