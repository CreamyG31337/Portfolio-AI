import pytest
import sys
import os
import importlib.util
from unittest.mock import MagicMock, patch

# Add web_dashboard to path so we can import app (ensure highest priority)
web_dashboard_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'web_dashboard'))
if web_dashboard_path not in sys.path:
    sys.path.insert(0, web_dashboard_path)

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
         patch('log_handler.setup_logging'):

        app_path = os.path.join(web_dashboard_path, "app.py")
        spec = importlib.util.spec_from_file_location("web_dashboard_app", app_path)
        if not spec or not spec.loader:
            raise RuntimeError("Failed to load Flask app module for tests")
        app_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(app_module)
        app = app_module.app
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
