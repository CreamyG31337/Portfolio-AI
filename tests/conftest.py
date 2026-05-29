import pytest
import sys
import os
from unittest.mock import patch

# Add web_dashboard to path so we can import app (ensure highest priority)
web_dashboard_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'web_dashboard'))
if web_dashboard_path not in sys.path:
    sys.path.insert(0, web_dashboard_path)

# Also add root to path for utils import
root_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if root_path not in sys.path:
    sys.path.insert(0, root_path)

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
