"""ai_model must never be served from the Flask session cache.

The session cookie has no expiry: a browser that cached ai_model=glm-5.2 kept
showing (and running) it after the preference was changed to glm-5.3.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

from flask import Flask

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "web_dashboard"))

import user_preferences as up  # noqa: E402


def _app() -> Flask:
    app = Flask(__name__)
    app.secret_key = "test"
    return app


def test_stale_session_ai_model_is_not_returned() -> None:
    with _app().test_request_context("/"):
        from flask import session

        session[up._preference_cache_key("ai_model")] = "glm-5.2"
        # Not authenticated -> DB path returns the default; the stale cache must not win.
        with patch.object(up, "_is_authenticated", return_value=False):
            assert up.get_user_preference("ai_model", default="fresh") == "fresh"


def test_ordinary_keys_still_use_session_cache() -> None:
    with _app().test_request_context("/"):
        from flask import session

        session[up._preference_cache_key("theme")] = "dark"
        with patch.object(up, "_is_authenticated", return_value=False):
            assert up.get_user_preference("theme", default="light") == "dark"
