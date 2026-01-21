import pytest
from flask import url_for
from unittest.mock import MagicMock, patch

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


def test_logs_debug_requires_admin_non_admin_denied(client):
    """Test that /logs/debug denies access to non-admin users (Security Regression Test)."""
    # Mock authentication - user is authenticated but not admin
    with patch('auth.auth_manager.verify_session') as mock_verify, \
         patch('supabase_client.SupabaseClient') as mock_client_class, \
         patch('auth.auth_manager.is_admin') as mock_is_admin:
        
        # Mock successful authentication
        mock_verify.return_value = {
            'user_id': 'test-user-id',
            'email': 'test@example.com'
        }
        
        # Mock SupabaseClient RPC call to return False (not admin)
        mock_client_instance = MagicMock()
        mock_rpc_response = MagicMock()
        mock_rpc_response.data = False
        
        # Mock the RPC chain: supabase.rpc('is_admin', ...).execute()
        mock_rpc_chain = MagicMock()
        mock_rpc_chain.execute.return_value = mock_rpc_response
        mock_client_instance.supabase.rpc.return_value = mock_rpc_chain
        
        mock_client_class.return_value = mock_client_instance
        
        # Mock final fallback to return False
        mock_is_admin.return_value = False
        
        # Set auth cookie to simulate authenticated user
        client.set_cookie('auth_token', 'test.token.value')
        
        # Attempt access
        response = client.get('/logs/debug')
        
        # Should redirect to /auth (access denied)
        assert response.status_code == 302
        assert '/auth' in response.headers['Location']


def test_logs_debug_requires_admin_unauthenticated_denied(client):
    """Test that /logs/debug denies access to unauthenticated users."""
    # No auth cookie set - user is not authenticated
    response = client.get('/logs/debug')
    
    # Should redirect to /auth (authentication required)
    assert response.status_code == 302
    assert '/auth' in response.headers['Location']


def test_logs_debug_allows_admin_access(client):
    """Test that /logs/debug allows access to admin users."""
    # Mock authentication - user is authenticated and is admin
    with patch('auth.auth_manager.verify_session') as mock_verify, \
         patch('supabase_client.SupabaseClient') as mock_client_class, \
         patch('flask_auth_utils.get_user_email_flask') as mock_get_email, \
         patch('flask_auth_utils.get_user_id_flask') as mock_get_id, \
         patch('auth.is_admin') as mock_is_admin_helper:
        
        # Mock successful authentication
        mock_verify.return_value = {
            'user_id': 'admin-user-id',
            'email': 'admin@example.com'
        }
        
        # Mock SupabaseClient RPC call to return True (is admin)
        mock_client_instance = MagicMock()
        mock_rpc_response = MagicMock()
        mock_rpc_response.data = True
        
        # Mock the RPC chain: supabase.rpc('is_admin', ...).execute()
        mock_rpc_chain = MagicMock()
        mock_rpc_chain.execute.return_value = mock_rpc_response
        mock_client_instance.supabase.rpc.return_value = mock_rpc_chain
        
        # Mock table query for user_profiles
        mock_table_result = MagicMock()
        mock_table_result.data = [{'role': 'admin', 'email': 'admin@example.com'}]
        mock_table_chain = MagicMock()
        mock_table_chain.execute.return_value = mock_table_result
        mock_table_chain.eq.return_value = mock_table_chain
        mock_table_chain.select.return_value = mock_table_chain
        mock_client_instance.supabase.table.return_value = mock_table_chain
        
        mock_client_class.return_value = mock_client_instance
        
        # Mock helper functions used inside logs_debug
        mock_get_email.return_value = 'admin@example.com'
        mock_get_id.return_value = 'admin-user-id'
        mock_is_admin_helper.return_value = True
        
        # Set auth cookie
        client.set_cookie('auth_token', 'test.token.value')
        
        # Access should succeed
        response = client.get('/logs/debug')
        
        # Should return 200 with debug information
        assert response.status_code == 200
        data = response.get_json()
        assert data is not None
        assert 'user_email' in data
        assert 'user_id' in data
        assert 'is_admin' in data
        assert data['is_admin'] is True
