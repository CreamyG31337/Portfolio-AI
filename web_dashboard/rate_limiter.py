from functools import wraps
from flask import request, jsonify
import time
import logging
from flask_cache_utils import _get_cache

logger = logging.getLogger(__name__)

def rate_limit(limit=5, period=60):
    """
    Rate limiting decorator using the shared cache.
    Uses a fixed window algorithm.

    Args:
        limit (int): Number of allowed requests per period.
        period (int): Time window in seconds.
    """
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            try:
                cache = _get_cache()

                # Get IP address
                # Prioritize X-Forwarded-For if available (behind proxy)
                # ProxyFix in app.py should handle this, but checking explicitly is safer
                ip = request.headers.get('X-Forwarded-For', request.remote_addr)
                if ip:
                    ip = ip.split(',')[0].strip()
                else:
                    ip = 'unknown'

                # Create a key based on IP, endpoint, and time window
                # Fixed window: current_time // period gives a unique bucket index
                window = int(time.time() // period)
                key = f"rate_limit:{ip}:{request.endpoint}:{window}"

                # Get current count
                current_count = cache.get(key)

                if current_count is not None and current_count >= limit:
                    logger.warning(f"Rate limit exceeded for {ip} on {request.endpoint}")
                    return jsonify({
                        "error": "Too many requests. Please try again later.",
                        "retry_after": period
                    }), 429

                # Increment count
                new_count = (current_count or 0) + 1

                # Set with timeout slightly larger than period to ensure it persists for the full window
                # Note: SimpleCache.set resets the timeout, which is fine for fixed window keys
                # because the key changes when the window changes.
                try:
                    cache.set(key, new_count, timeout=period + 10)
                except Exception as cache_error:
                    logger.warning(f"Failed to set rate limit cache: {cache_error}")

            except Exception as e:
                # Fail open if rate limiting logic fails
                logger.error(f"Rate limiting error: {e}", exc_info=True)

            return f(*args, **kwargs)
        return wrapped
    return decorator
