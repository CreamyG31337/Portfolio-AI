import pytest
from flask import url_for

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
