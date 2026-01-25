import pytest
from unittest.mock import patch, MagicMock
import time
from web_dashboard.flask_cache_utils import SimpleCache

def test_rate_limiter_login(client):
    """Test that login endpoint is rate limited."""

    # Create a fresh cache for this test
    test_cache = SimpleCache()

    # We need to patch _get_cache in rate_limiter module specifically
    # And patch requests.post in app module to avoid external calls

    # We try patching 'rate_limiter._get_cache' because app.py imports it as 'from rate_limiter import ...'
    # and app.py is loaded with web_dashboard in sys.path.

    with patch('rate_limiter._get_cache', return_value=test_cache) as mock_cache_getter, \
         patch('web_dashboard.app.requests.post') as mock_post:

        # Mock 401 response from Supabase
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.text = '{"error": "Invalid credentials"}'
        mock_response.json.return_value = {"error": "Invalid credentials"}
        mock_post.return_value = mock_response

        headers = {'X-Forwarded-For': '10.0.0.1'}

        # 5 allowed requests
        for i in range(5):
            response = client.post('/api/auth/login',
                                 json={'email': 'test@test.com', 'password': 'pass'},
                                 headers=headers)
            assert response.status_code == 401

        # 6th request should be blocked
        response = client.post('/api/auth/login',
                             json={'email': 'test@test.com', 'password': 'pass'},
                             headers=headers)
        assert response.status_code == 429
        data = response.get_json()
        assert "Too many requests" in data.get('error', '')

        # Verify different IP is not blocked
        headers2 = {'X-Forwarded-For': '10.0.0.2'}
        response = client.post('/api/auth/login',
                             json={'email': 'test@test.com', 'password': 'pass'},
                             headers=headers2)
        assert response.status_code == 401

def test_rate_limiter_window_expiry(client):
    """Test that rate limit resets after window expires."""

    test_cache = SimpleCache()

    with patch('rate_limiter._get_cache', return_value=test_cache), \
         patch('web_dashboard.app.requests.post') as mock_post, \
         patch('rate_limiter.time.time') as mock_time:

        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.json.return_value = {"error": "Invalid credentials"}
        mock_post.return_value = mock_response

        # Set initial time
        start_time = 1000000.0
        mock_time.return_value = start_time

        headers = {'X-Forwarded-For': '10.0.0.3'}

        # Hit limit (5 requests)
        for i in range(5):
            client.post('/api/auth/login',
                      json={'email': 'test@test.com', 'password': 'pass'},
                      headers=headers)

        # Verify blocked
        response = client.post('/api/auth/login',
                             json={'email': 'test@test.com', 'password': 'pass'},
                             headers=headers)
        assert response.status_code == 429

        # Advance time by 61 seconds (window is 60s)
        # Note: Fixed window logic uses int(time / period).
        # start_time = 1000000.0. window = 1000000 // 60 = 16666
        # next_time = 1000061.0. window = 1000061 // 60 = 16667
        # So the key changes.
        mock_time.return_value = start_time + 61.0

        # Should be allowed again
        response = client.post('/api/auth/login',
                             json={'email': 'test@test.com', 'password': 'pass'},
                             headers=headers)
        assert response.status_code == 401
