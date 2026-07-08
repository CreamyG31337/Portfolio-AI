#!/usr/bin/env python3
"""Load Reddit browser session cookies for authenticated .json access.

Sources (priority order):
1. Shared volume: ``/shared/cookies/reddit_cookies.json`` (production)
2. Environment: ``REDDIT_COOKIES_JSON``
3. Environment file path: ``REDDIT_COOKIES_FILE``
4. Project root: ``reddit_cookies.json`` (local dev, gitignored)
5. ``REDDIT_USERNAME`` + ``REDDIT_PASSWORD`` → programmatic login (Playwright)
"""

from __future__ import annotations

import json
import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SHARED_COOKIE_PATH = Path("/shared/cookies/reddit_cookies.json")
_LOCAL_COOKIE_PATH = _PROJECT_ROOT / "reddit_cookies.json"

# reddit_session is the authenticated login cookie. token_v2 alone is anonymous.
_REQUIRED_COOKIES = ("reddit_session",)
_OPTIONAL_COOKIES = ("token_v2", "csrf_token", "loid", "edgebucket", "csv")


def _parse_cookies_json(raw: str) -> dict[str, str]:
    data: Any = json.loads(raw.strip())
    if not isinstance(data, dict):
        raise ValueError("Reddit cookies JSON must be an object")
    cookies: dict[str, str] = {}
    for key, value in data.items():
        if isinstance(key, str) and isinstance(value, str) and value.strip():
            cookies[key] = value.strip()
    return cookies


def _normalize_cookies(cookies: dict[str, str]) -> dict[str, str] | None:
    if not any(key in cookies for key in _REQUIRED_COOKIES):
        return None
    keep = set(_REQUIRED_COOKIES) | set(_OPTIONAL_COOKIES)
    return {k: cookies[k] for k in keep if k in cookies}


def _load_static_reddit_cookies() -> dict[str, str] | None:
    sources: list[tuple[str, str | Path]] = []

    if _SHARED_COOKIE_PATH.exists():
        sources.append(("shared volume", _SHARED_COOKIE_PATH))

    env_json = os.getenv("REDDIT_COOKIES_JSON", "").strip()
    if env_json:
        sources.append(("REDDIT_COOKIES_JSON", env_json))

    env_file = os.getenv("REDDIT_COOKIES_FILE", "").strip()
    if env_file:
        sources.append(("REDDIT_COOKIES_FILE", Path(env_file)))

    if _LOCAL_COOKIE_PATH.exists():
        sources.append(("reddit_cookies.json", _LOCAL_COOKIE_PATH))

    for label, source in sources:
        try:
            raw = source.read_text(encoding="utf-8") if isinstance(source, Path) else source
            cookies = _normalize_cookies(_parse_cookies_json(raw))
            if cookies is None:
                logger.debug(
                    "Reddit cookies from %s missing %s — skipped",
                    label,
                    " or ".join(_REQUIRED_COOKIES),
                )
                continue
            logger.info(
                "Reddit session cookies loaded from %s (%s keys)",
                label,
                len(cookies),
            )
            return cookies
        except Exception as exc:
            logger.warning("Failed to load Reddit cookies from %s: %s", label, exc)

    return None


def _load_password_login_cookies() -> dict[str, str] | None:
    from reddit_login import RedditLoginError, login_with_password, reddit_password_configured

    if not reddit_password_configured():
        return None
    try:
        cookies = login_with_password()
    except RedditLoginError as exc:
        logger.error("Reddit username/password login failed: %s", exc)
        return None
    except Exception as exc:
        logger.error("Unexpected Reddit login error: %s", exc, exc_info=True)
        return None

    normalized = _normalize_cookies(cookies)
    if normalized:
        logger.info("Reddit session cookies obtained via username/password login")
    return normalized


def _load_reddit_cookies_uncached() -> dict[str, str] | None:
    static = _load_static_reddit_cookies()
    if static is not None:
        return static
    return _load_password_login_cookies()


@lru_cache(maxsize=1)
def load_reddit_cookies() -> dict[str, str] | None:
    """Return Reddit session cookies (cached per process)."""
    return _load_reddit_cookies_uncached()


def reddit_cookie_configured() -> bool:
    """Return True when cookies or username/password login is available."""
    if _load_static_reddit_cookies() is not None:
        return True
    from reddit_login import reddit_password_configured

    return reddit_password_configured()


def reset_reddit_cookie_cache() -> None:
    """Clear cached cookies (for tests)."""
    load_reddit_cookies.cache_clear()
