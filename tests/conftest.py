import pytest
import sys
import os
from unittest.mock import patch

# Force-disable the background scheduler for the entire test session.
#
# `web_dashboard/app.py` auto-starts a real APScheduler at import time (unless
# DISABLE_SCHEDULER is set), which spawns a non-daemon init thread and runs
# startup-backfill jobs on concurrent.futures worker threads. pytest imports
# every test module during collection, so if any module imports the app before
# the `app` fixture's narrower patch runs, the scheduler starts and its still
# running (non-daemon) worker threads keep the pytest process alive long after
# the test summary prints. Setting this here -- before collection imports any
# test module -- guarantees the autostart guard is in effect for all tests.
os.environ["DISABLE_SCHEDULER"] = "true"

# Add web_dashboard to path so we can import app (ensure highest priority)
web_dashboard_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'web_dashboard'))
root_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

# Always pin root first, web_dashboard second. Pytest often pre-seeds root on
# sys.path, so a naive insert(0) after web_dashboard would leave web_dashboard
# ahead and shadow the project `utils` package with web_dashboard/utils.
for _path in (web_dashboard_path, root_path):
    while _path in sys.path:
        sys.path.remove(_path)
sys.path.insert(0, root_path)
sys.path.insert(1, web_dashboard_path)

# Pin project-root `utils` before collection. Some tests prepend web_dashboard to
# sys.path[0], which would otherwise register web_dashboard/utils as `utils` and
# break imports of root modules (fund_manager, trade_reason.is_trade_sell, etc.).
import utils as _root_utils  # noqa: F401
assert "web_dashboard" not in str(getattr(_root_utils, "__file__", "") or "")

@pytest.fixture
def app():
    """Create and configure a new app instance for each test."""
    # Ensure Flask is a real module (not shadowed by mocks)
    if 'flask' in sys.modules:
        del sys.modules['flask']
    import importlib
    flask = importlib.import_module('flask')
    from flask import Flask as FlaskClass
    flask.Flask = FlaskClass

    # Mock Supabase dependencies before importing app to prevent connection attempts
    with patch('supabase_client.SupabaseClient'), \
         patch('flask_caching.Cache'), \
         patch('log_handler.setup_logging'), \
         patch.dict(os.environ, {'DISABLE_SCHEDULER': 'true'}):

        from web_dashboard.app import app
        from jinja2 import FileSystemLoader
        app.jinja_loader = FileSystemLoader(os.path.join(web_dashboard_path, "templates"))
        
        app.config.update({
            "TESTING": True,
            "WTF_CSRF_ENABLED": False,  # Disable CSRF for testing
            "DEBUG": False
        })

        yield app

@pytest.fixture
def client(app):
    """A test client for the app."""
    return app.test_client()

@pytest.fixture
def runner(app):
    """A test runner for the app's CLI commands."""
    return app.test_cli_runner()
