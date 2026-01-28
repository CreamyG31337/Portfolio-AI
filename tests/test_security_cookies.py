import pytest
from unittest.mock import MagicMock, patch
import json

def test_debug_cookies_masks_sensitive_data(client):
    """Test that /api/debug/cookies masks sensitive cookies even for admins."""

    # Mock authentication - user is authenticated and is admin
    with patch('auth.auth_manager.verify_session') as mock_verify, \
         patch('auth.auth_manager.is_admin') as mock_is_admin_method:

        # Mock successful authentication
        mock_verify.return_value = {
            'user_id': 'admin-user-id',
            'email': 'admin@example.com'
        }

        # Mock is_admin to return True
        mock_is_admin_method.return_value = True

        # Set sensitive cookies
        client.set_cookie('auth_token', 'sensitive_auth_token_value')
        client.set_cookie('session_token', 'sensitive_session_token_value')
        client.set_cookie('refresh_token', 'sensitive_refresh_token_value')
        client.set_cookie('other_cookie', 'safe_value')

        # Attempt access
        response = client.get('/api/debug/cookies')

        # Should return 200
        assert response.status_code == 200

        data = response.get_json()
        cookies = data.get('cookies', {})

        # Check that sensitive cookies are masked
        # This assertions will FAIL if the code leaks them
        assert cookies['auth_token'] == '***MASKED***', f"Expected masked auth_token, got {cookies.get('auth_token')}"
        assert cookies['session_token'] == '***MASKED***', f"Expected masked session_token, got {cookies.get('session_token')}"
        assert cookies['refresh_token'] == '***MASKED***', f"Expected masked refresh_token, got {cookies.get('refresh_token')}"

        # Check that non-sensitive cookies are present
        assert cookies['other_cookie'] == 'safe_value'
