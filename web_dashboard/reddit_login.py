#!/usr/bin/env python3
"""Reddit username/password login → browser session cookies.

Reddit closed self-service API apps and blocks most programmatic login HTTP
endpoints. When ``REDDIT_USERNAME`` and ``REDDIT_PASSWORD`` are set (without a
legacy OAuth app), we obtain ``reddit_session`` via a headless browser login.

Playwright is optional at runtime — install with:
    pip install playwright && playwright install chromium

For production servers without Playwright, run ``scripts/reddit_login_export.py``
locally and deploy ``reddit_cookies.json`` to the server.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import requests

from reddit_rss import BROWSER_USER_AGENT

logger = logging.getLogger(__name__)

LOGIN_URL = "https://www.reddit.com/login"
HOME_URL = "https://www.reddit.com/"
WANTED_COOKIES = ("reddit_session", "token_v2", "csrf_token", "loid", "edgebucket", "csv")


class RedditLoginError(Exception):
    """Raised when Reddit username/password login fails."""


def reddit_password_configured() -> bool:
    """True when username + password env vars are set (no OAuth app required)."""
    if reddit_oauth_app_configured():
        return False
    username = os.getenv("REDDIT_USERNAME", "").strip()
    password = os.getenv("REDDIT_PASSWORD", "").strip()
    return bool(username and password)


def reddit_oauth_app_configured() -> bool:
    """True when legacy OAuth app credentials are present."""
    client_id = os.getenv("REDDIT_CLIENT_ID", "").strip()
    client_secret = os.getenv("REDDIT_CLIENT_SECRET", "").strip()
    username = os.getenv("REDDIT_USERNAME", "").strip()
    password = os.getenv("REDDIT_PASSWORD", "").strip()
    return bool(client_id and client_secret and username and password)


def _otp_code() -> str:
    one_time = os.getenv("REDDIT_OTP", "").strip()
    if one_time:
        return one_time
    secret = os.getenv("REDDIT_TOTP_SECRET", "").strip()
    if not secret:
        return ""
    try:
        import pyotp  # type: ignore[import-untyped]
    except ImportError:
        logger.warning(
            "REDDIT_TOTP_SECRET is set but pyotp is not installed — "
            "set REDDIT_OTP or pip install pyotp"
        )
        return ""
    return pyotp.TOTP(secret).now()


def _is_anonymous_token(token_v2: str) -> bool:
    """True when a token_v2 JWT is a logged-out/guest token (sub == 'loid')."""
    if not token_v2:
        return True
    try:
        import base64
        import json as _json

        payload_b64 = token_v2.split(".")[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)
        payload = _json.loads(base64.urlsafe_b64decode(payload_b64))
        return str(payload.get("sub", "")).lower() == "loid"
    except Exception:
        # Can't decode — fall back to requiring reddit_session (handled by caller).
        return True


def _filter_cookies(raw: dict[str, str]) -> dict[str, str]:
    # reddit_session is the only reliable proof of an authenticated login.
    # A token_v2 with sub="loid" is an anonymous guest token, not a real session.
    if "reddit_session" not in raw:
        return {}
    return {k: raw[k] for k in WANTED_COOKIES if k in raw and raw[k]}


def login_with_password_http(username: str, password: str, *, otp: str = "") -> dict[str, str]:
    """Attempt classic Reddit login HTTP flow (often blocked; prefer Playwright)."""
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": BROWSER_USER_AGENT,
            "Accept": "application/json, text/html, */*",
            "Origin": "https://www.reddit.com",
            "Referer": LOGIN_URL,
        }
    )
    session.get(HOME_URL, timeout=20)
    csrf = session.cookies.get("csrf_token")
    if not csrf:
        # old.reddit sometimes sets csrf when www does not
        try:
            session.get("https://old.reddit.com/login", timeout=20)
            csrf = session.cookies.get("csrf_token")
        except requests.RequestException:
            pass

    payload: dict[str, str] = {
        "op": "login",
        "username": username,
        "user": username,
        "passwd": password,
        "password": password,
        "otp": otp,
        "dest": HOME_URL,
    }
    if csrf:
        payload["csrf_token"] = csrf

    endpoints = [
        f"https://www.reddit.com/api/login/{username}",
        LOGIN_URL,
    ]
    last_status: int | None = None
    for url in endpoints:
        try:
            response = session.post(url, data=payload, timeout=20)
        except requests.RequestException as exc:
            logger.debug("Reddit HTTP login POST %s failed: %s", url, exc)
            continue
        last_status = response.status_code
        if response.status_code == 429:
            raise RedditLoginError("Reddit rate limited login (429) — try again later")
        cookies = _filter_cookies({c.name: c.value for c in session.cookies})
        if cookies:
            return cookies
        if response.headers.get("content-type", "").startswith("application/json"):
            try:
                body: Any = response.json()
                if isinstance(body, dict) and body.get("json", {}).get("errors"):
                    errors = body["json"]["errors"]
                    raise RedditLoginError(f"Reddit login rejected: {errors}")
            except ValueError:
                pass

    raise RedditLoginError(
        f"Reddit HTTP login failed (last status={last_status}) — "
        "use Playwright export or browser cookie export"
    )


def login_with_password_playwright(username: str, password: str, *, otp: str = "") -> dict[str, str]:
    """Log into Reddit via headless Chromium and return session cookies."""
    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeout
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RedditLoginError(
            "Playwright is required for username/password login. "
            "Install with: pip install playwright && playwright install chromium. "
            "Or export cookies via scripts/reddit_login_export.py / DevTools."
        ) from exc

    otp_value = otp or _otp_code()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(user_agent=BROWSER_USER_AGENT)
        page = context.new_page()
        try:
            page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60_000)

            user_input = page.locator('input[name="username"]').first
            pass_input = page.locator('input[name="password"]').first
            user_input.wait_for(state="visible", timeout=30_000)
            user_input.fill(username)
            pass_input.fill(password)

            if otp_value:
                otp_input = page.locator('input[name="otp"]').first
                if otp_input.count() > 0:
                    otp_input.fill(otp_value)

            submit = page.locator('button[type="submit"]').first
            submit.click()

            try:
                page.wait_for_function(
                    "() => document.cookie.includes('reddit_session=')",
                    timeout=45_000,
                )
            except PlaywrightTimeout:
                if page.locator("text=incorrect password").count() > 0:
                    raise RedditLoginError("Reddit login failed: incorrect username or password")
                if page.locator("text=one-time code").count() > 0 or page.locator("text=6-digit").count() > 0:
                    raise RedditLoginError(
                        "Reddit 2FA required — set REDDIT_OTP or REDDIT_TOTP_SECRET"
                    )
                raise RedditLoginError("Reddit login timed out waiting for session cookie")

            raw_cookies = {c["name"]: c["value"] for c in context.cookies()}
            cookies = _filter_cookies(raw_cookies)
            if not cookies:
                raise RedditLoginError("Login appeared to succeed but reddit_session cookie missing")
            return cookies
        finally:
            browser.close()


def login_interactive(*, timeout_seconds: int = 300) -> dict[str, str]:
    """Open a visible browser, let the user log in, then capture session cookies.

    No password is stored. Handles 2FA/CAPTCHA naturally since the user completes
    the login manually. Polls the browser context until ``reddit_session`` appears.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RedditLoginError(
            "Playwright is required for interactive login. "
            "Install with: pip install playwright && playwright install chromium."
        ) from exc

    import time as _time

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False)
        context = browser.new_context(user_agent=BROWSER_USER_AGENT)
        page = context.new_page()
        try:
            # Open the homepage (NOT /login) to avoid Reddit's js_challenge refresh
            # loop. The user can click "Log In" themselves from here.
            page.goto(HOME_URL, wait_until="domcontentloaded", timeout=60_000)
            logger.info(
                "Log into Reddit in the opened window (click Log In). "
                "Waiting up to %ss for a session...",
                timeout_seconds,
            )
            deadline = _time.time() + timeout_seconds
            last_log = 0.0
            reddit_urls = ["https://www.reddit.com", "https://old.reddit.com"]
            while _time.time() < deadline:
                if page.is_closed():
                    raise RedditLoginError("Browser window was closed before login completed.")

                current_url = page.url or ""
                # Do NOT navigate the page here — that would interrupt the user's
                # login. Just read cookies from the browsing context.
                all_cookies = context.cookies(reddit_urls)
                raw_cookies = {c["name"]: c["value"] for c in all_cookies}
                cookies = _filter_cookies(raw_cookies)
                if cookies:
                    logger.info(
                        "Reddit session detected (%s) — capturing cookies",
                        ", ".join(sorted(cookies)),
                    )
                    return cookies

                now = _time.time()
                if now - last_log >= 30:
                    reddit_names = sorted(
                        c["name"] for c in all_cookies if "reddit" in c.get("domain", "")
                    )
                    logger.info(
                        "Still waiting for login… url=%s reddit_cookies=%s",
                        current_url[:80],
                        reddit_names or "(none yet)",
                    )
                    last_log = now
                _time.sleep(2)
            raise RedditLoginError(
                "Timed out waiting for login. Re-run and complete the Reddit login in the window."
            )
        finally:
            browser.close()


def login_with_password(
    username: str | None = None,
    password: str | None = None,
    *,
    prefer_playwright: bool | None = None,
) -> dict[str, str]:
    """Log in with username/password; Playwright preferred when available."""
    user = (username or os.getenv("REDDIT_USERNAME", "")).strip()
    passwd = (password or os.getenv("REDDIT_PASSWORD", "")).strip()
    if not user or not passwd:
        raise RedditLoginError("REDDIT_USERNAME and REDDIT_PASSWORD are required")

    otp = _otp_code()
    use_playwright = prefer_playwright
    if use_playwright is None:
        use_playwright = os.getenv("REDDIT_LOGIN_USE_PLAYWRIGHT", "1").strip().lower() not in {
            "0",
            "false",
            "no",
            "off",
        }

    if use_playwright:
        try:
            return login_with_password_playwright(user, passwd, otp=otp)
        except RedditLoginError:
            raise
        except Exception as exc:
            logger.warning("Playwright Reddit login failed (%s) — trying HTTP fallback", exc)

    return login_with_password_http(user, passwd, otp=otp)
