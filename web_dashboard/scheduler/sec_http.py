"""Shared, throttled SEC EDGAR HTTP client.

Extracted/generalized from ``sec_form4_poc.py`` so every SEC call site — the
Form 4 POC, ``company_tickers.json`` (ticker→CIK map), and the
``data.sec.gov/submissions`` filing poll (G2) — shares ONE global rate limiter
and the SEC fair-access ``User-Agent``.

SEC fair-access policy (https://www.sec.gov/os/accessing-edgar-data): declare a
``User-Agent`` with contact info and stay under 10 requests/second. The limiter
targets ~9 req/s and is thread-safe so parallel fetchers can't collectively
exceed the cap. Override the UA via ``SEC_EDGAR_USER_AGENT``.
"""

from __future__ import annotations

import json as _json
import logging
import os
import threading
import time
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger(__name__)

# SEC requires "Company Name AdminContact@company.com"; override via env in prod.
DEFAULT_USER_AGENT = "LLM-Micro-Cap-Trading-Bot AdminContact@example.com"

# Target ~9 req/s to stay under SEC's 10/s. Global + thread-safe so every SEC
# call site (POC, CIK map, submissions poll) shares the SAME budget.
_REQUESTS_PER_SEC = 9.0
_rate_limit_lock = threading.Lock()
_last_request_time = 0.0

# Retry on transient server / rate-limit errors.
RETRYABLE_STATUS = (429, 502, 503)
SEC_FETCH_MAX_RETRIES = int(os.getenv("SEC_FETCH_MAX_RETRIES", "5"))
SEC_FETCH_BACKOFF_BASE = float(os.getenv("SEC_FETCH_BACKOFF_BASE", "2.0"))


def rate_limit_wait() -> None:
    """Block until another SEC request may start (thread-safe, ~9 req/s)."""
    global _last_request_time
    with _rate_limit_lock:
        now = time.monotonic()
        wait = (_last_request_time + (1.0 / _REQUESTS_PER_SEC)) - now
        if wait > 0:
            _rate_limit_lock.release()
            time.sleep(wait)
            _rate_limit_lock.acquire()
        _last_request_time = time.monotonic()


def headers() -> Dict[str, str]:
    """Fair-access headers; UA from ``SEC_EDGAR_USER_AGENT`` or the default."""
    ua = os.getenv("SEC_EDGAR_USER_AGENT", "").strip() or DEFAULT_USER_AGENT
    return {"User-Agent": ua, "Accept-Encoding": "gzip", "Accept": "*/*"}


def fetch_url(url: str, *, timeout: int = 60) -> Optional[str]:
    """GET a SEC URL with the shared throttle + retry/backoff. Returns text or None.

    Never raises on a fetch miss — callers (nightly jobs) must degrade, not
    crash, on a single bad ticker/endpoint.
    """
    last_error: Optional[Exception] = None
    for attempt in range(SEC_FETCH_MAX_RETRIES + 1):
        rate_limit_wait()
        try:
            r = requests.get(url, headers=headers(), timeout=timeout)
            if r.status_code in RETRYABLE_STATUS and attempt < SEC_FETCH_MAX_RETRIES:
                backoff = min(SEC_FETCH_BACKOFF_BASE ** attempt, 60.0)
                logger.warning(
                    "SEC %s for %s, retry %s/%s in %.1fs",
                    r.status_code, url[:60], attempt + 1, SEC_FETCH_MAX_RETRIES, backoff,
                )
                time.sleep(backoff)
                continue
            r.raise_for_status()
            return r.text
        except requests.exceptions.HTTPError as e:
            last_error = e
            resp = e.response
            if resp is not None and resp.status_code in RETRYABLE_STATUS and attempt < SEC_FETCH_MAX_RETRIES:
                backoff = min(SEC_FETCH_BACKOFF_BASE ** attempt, 60.0)
                logger.warning(
                    "SEC %s for %s, retry %s/%s in %.1fs",
                    resp.status_code, url[:60], attempt + 1, SEC_FETCH_MAX_RETRIES, backoff,
                )
                time.sleep(backoff)
                continue
            logger.error("SEC fetch failed for %s: %s", url[:80], e)
            return None
        except Exception as e:
            last_error = e
            if attempt < SEC_FETCH_MAX_RETRIES:
                backoff = min(SEC_FETCH_BACKOFF_BASE ** attempt, 60.0)
                logger.warning(
                    "SEC fetch error %s for %s, retry %s/%s in %.1fs",
                    e, url[:60], attempt + 1, SEC_FETCH_MAX_RETRIES, backoff,
                )
                time.sleep(backoff)
                continue
            logger.error("SEC fetch error for %s: %s", url[:80], e)
            return None
    logger.error("SEC fetch failed after %s retries: %s", SEC_FETCH_MAX_RETRIES + 1, last_error)
    return None


def fetch_json(url: str, *, timeout: int = 60) -> Optional[Any]:
    """GET + parse a SEC JSON endpoint. Returns parsed JSON or None on any miss."""
    body = fetch_url(url, timeout=timeout)
    if body is None:
        return None
    try:
        return _json.loads(body)
    except (ValueError, TypeError) as e:
        logger.warning("SEC JSON parse failed for %s: %s", url[:80], e)
        return None
