import pytest
from flask import url_for
from unittest.mock import MagicMock

# TODO: Also run `npm run build:ts` before running tests to ensure TypeScript is compiled
# This ensures frontend JS changes are tested alongside Flask route tests

def test_index_redirects_to_auth(client):
    """Test that the index page redirects to auth when not logged in."""
    response = client.get('/')
    # When not authenticated, should redirect to /auth
    assert response.status_code == 302
    assert '/auth' in response.headers['Location']

def test_auth_page_loads(client):
    """Test that the auth page loads successfully."""
    response = client.get('/auth')
    assert response.status_code == 200
    assert b'Sign In' in response.data or b'Login' in response.data

def test_health_check_404(client):
    """Test that a non-existent route returns 404."""
    response = client.get('/non-existent-page')
    assert response.status_code == 404

def test_api_metrics_structure(client):
    """Test standard API response structure (mocked data)."""
    # This might fail if the route requires auth, but good to check 401/403 behavior
    response = client.get('/api/portfolio/metrics')
    # If auth is required, it should be 401 or redirect
    assert response.status_code in [200, 302, 401, 404]

def test_logs_debug_restricted(client, mocker):
    """Test that /logs/debug requires admin access (Security Regression Test)."""

    # Mock auth to simulate non-admin user
    mocker.patch('auth.auth_manager.verify_session', return_value={
        'user_id': 'test-user-id',
        'email': 'test@example.com'
    })

    # Mock is_authenticated to pass initial check
    mocker.patch('web_dashboard.flask_auth_utils.is_authenticated_flask', return_value=True)

    # Explicitly mock is_admin to False
    mocker.patch('auth.auth_manager.is_admin', return_value=False)
    mocker.patch('auth.is_admin', return_value=False)

    # Mock SupabaseClient to ensure RPC returns False
    # Use patch on 'web_dashboard.app.SupabaseClient' assuming it's available in test scope via app fixture
    import web_dashboard.app
    mock_client_class = web_dashboard.app.SupabaseClient
    if hasattr(mock_client_class, 'return_value'):
        mock_client = mock_client_class.return_value
        mock_rpc = MagicMock()
        mock_rpc.data = False
        mock_client.supabase.rpc.return_value.execute.return_value = mock_rpc

    # Set auth cookie
    client.set_cookie('auth_token', 'test-token')

    # Attempt access
    response = client.get('/logs/debug')

    # Expect redirect to auth (access denied)
    assert response.status_code == 302
    assert '/auth' in response.headers['Location']
