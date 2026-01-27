import sys
import os
import unittest
from unittest.mock import patch, MagicMock
import json

# Add web_dashboard to path so we can import app
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'web_dashboard'))

# Mock dependencies that might be missing in the test environment
sys.modules['flask_cache_utils'] = MagicMock()
sys.modules['rate_limiter'] = MagicMock()
# Mock the rate_limit decorator to just return the function
def rate_limit_mock(*args, **kwargs):
    def decorator(f):
        return f
    return decorator
sys.modules['rate_limiter'].rate_limit = rate_limit_mock

from app import app

class TestSecurity(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.client.testing = True

    def test_hsts_header(self):
        """Test HSTS header presence on secure requests"""
        # Simulate HTTPS request via base_url
        response = self.client.get('/auth', base_url='https://example.com')
        self.assertIn('Strict-Transport-Security', response.headers)
        self.assertEqual(response.headers['Strict-Transport-Security'], 'max-age=31536000; includeSubDomains')

    def test_no_hsts_on_http(self):
        """Test HSTS header absence on insecure requests"""
        response = self.client.get('/auth', base_url='http://example.com')
        self.assertNotIn('Strict-Transport-Security', response.headers)

if __name__ == '__main__':
    unittest.main()
