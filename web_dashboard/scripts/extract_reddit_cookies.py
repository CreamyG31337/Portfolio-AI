#!/usr/bin/env python3
"""Extract Reddit session cookies from Brave/Chrome or DevTools.

Reddit requires a logged-in session for .json and RSS access. This script exports
``reddit_session`` (and ``token_v2`` when present) for the trading bot.

Usage:
    # Close Brave first, then:
    python web_dashboard/scripts/extract_reddit_cookies.py --browser brave

    # Or print manual DevTools steps:
    python web_dashboard/scripts/extract_reddit_cookies.py --browser manual

Output defaults to ``reddit_cookies.json`` in the project root (gitignored).
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Any

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

REDDIT_DOMAIN = "reddit.com"
PROJECT_ROOT = Path(__file__).resolve().parents[2]

BROWSER_PATHS: dict[str, tuple[Path, Path]] = {
    "brave": (
        Path.home() / "AppData/Local/BraveSoftware/Brave-Browser/User Data",
        Path.home() / "AppData/Local/BraveSoftware/Brave-Browser/User Data/Default/Network/Cookies",
    ),
    "chrome": (
        Path.home() / "AppData/Local/Google/Chrome/User Data",
        Path.home() / "AppData/Local/Google/Chrome/User Data/Default/Network/Cookies",
    ),
    "edge": (
        Path.home() / "AppData/Local/Microsoft/Edge/User Data",
        Path.home() / "AppData/Local/Microsoft/Edge/User Data/Default/Network/Cookies",
    ),
}

WANTED_COOKIES = ("reddit_session", "token_v2", "csrf_token", "loid")


def _decrypt_chrome_value(encrypted_value: bytes, key: bytes | None) -> str | None:
    """Decrypt a Chromium cookie value (v10/v11 AES-GCM or legacy DPAPI)."""
    if not encrypted_value:
        return None

    if encrypted_value[:3] in (b"v10", b"v11") and key is not None:
        try:
            from Cryptodome.Cipher import AES  # type: ignore[import-untyped]
        except ImportError:
            try:
                from Crypto.Cipher import AES  # type: ignore[import-untyped]
            except ImportError:
                logger.debug("pycryptodome not installed — cannot decrypt v10 cookies")
                return None
        nonce = encrypted_value[3:15]
        ciphertext = encrypted_value[15:-16]
        tag = encrypted_value[-16:]
        cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
        try:
            return cipher.decrypt_and_verify(ciphertext, tag).decode("utf-8")
        except Exception:
            return None

    if sys.platform == "win32":
        try:
            import win32crypt  # type: ignore[import-untyped]

            return win32crypt.CryptUnprotectData(encrypted_value, None, None, None, 0)[1].decode("utf-8")
        except Exception:
            return None
    return None


def _chrome_aes_key(user_data_dir: Path) -> bytes | None:
    local_state = user_data_dir / "Local State"
    if not local_state.exists():
        return None
    try:
        from base64 import b64decode

        import win32crypt  # type: ignore[import-untyped]

        state = json.loads(local_state.read_text(encoding="utf-8"))
        encrypted_key = b64decode(state["os_crypt"]["encrypted_key"])
        return win32crypt.CryptUnprotectData(encrypted_key[5:], None, None, None, 0)[1]
    except Exception as exc:
        logger.debug("Could not read Chrome AES key: %s", exc)
        return None


def extract_chromium_cookies(browser: str) -> dict[str, str]:
    """Read Reddit cookies from a Chromium-based browser profile."""
    if browser not in BROWSER_PATHS:
        return {}
    user_data_dir, cookie_db = BROWSER_PATHS[browser]
    if not cookie_db.exists():
        legacy = user_data_dir / "Default/Cookies"
        cookie_db = legacy if legacy.exists() else cookie_db
    if not cookie_db.exists():
        logger.error("%s cookie database not found at %s", browser, cookie_db)
        logger.info("Close the browser completely and try again.")
        return {}

    aes_key = _chrome_aes_key(user_data_dir)
    temp_path = Path(tempfile.mkstemp(suffix=".db")[1])
    conn: sqlite3.Connection | None = None
    try:
        shutil.copy2(cookie_db, temp_path)
        conn = sqlite3.connect(temp_path)
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT name, encrypted_value, value
            FROM cookies
            WHERE host_key LIKE ?
            """,
            (f"%{REDDIT_DOMAIN}%",),
        )
        found: dict[str, str] = {}
        for name, encrypted_value, plain_value in cursor.fetchall():
            if name not in WANTED_COOKIES:
                continue
            value = plain_value
            if not value and encrypted_value:
                if isinstance(encrypted_value, str):
                    encrypted_value = encrypted_value.encode("latin-1")
                value = _decrypt_chrome_value(encrypted_value, aes_key)
            if value:
                found[name] = value
        return found
    except OSError as exc:
        logger.error(
            "Could not read %s cookies (is the browser closed?): %s",
            browser,
            exc,
        )
        return {}
    except Exception as exc:
        logger.error("Failed to read %s cookies: %s", browser, exc)
        return {}
    finally:
        if conn is not None:
            conn.close()
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass


def manual_instructions() -> None:
    print("\n" + "=" * 60)
    print("MANUAL REDDIT COOKIE EXPORT")
    print("=" * 60)
    print("\n1. Open Brave (or any browser) and log into reddit.com")
    print("2. Press F12 → Application tab → Cookies → https://www.reddit.com")
    print("3. Copy these values into reddit_cookies.json:")
    print('   {')
    print('     "reddit_session": "<paste value>",')
    print('     "token_v2": "<paste if present>"')
    print("   }")
    print("\n4. Save to project root as reddit_cookies.json (gitignored)")
    print("   Or set REDDIT_COOKIES_FILE / REDDIT_COOKIES_JSON in web_dashboard/.env")
    print("\n5. Test: python web_dashboard/scripts/test_reddit_search.py")
    print("\nCookies expire after a few days — re-export when jobs fail with 403.")
    print("=" * 60 + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Export Reddit session cookies for the trading bot")
    parser.add_argument(
        "--browser",
        choices=["brave", "chrome", "edge", "manual"],
        default="brave",
        help="Browser profile to read (default: brave)",
    )
    parser.add_argument(
        "--output",
        default="reddit_cookies.json",
        help="Output JSON file (default: reddit_cookies.json in project root)",
    )
    args = parser.parse_args()

    if args.browser == "manual":
        manual_instructions()
        return 0

    logger.info("Extracting Reddit cookies from %s (close the browser first)...", args.browser)
    cookies = extract_chromium_cookies(args.browser)
    if "reddit_session" not in cookies:
        logger.warning("reddit_session not found — are you logged into Reddit in %s?", args.browser)
        manual_instructions()
        return 1

    output = Path(args.output)
    if not output.is_absolute():
        output = PROJECT_ROOT / output.name
    output.write_text(json.dumps(cookies, indent=2), encoding="utf-8")
    logger.info("Saved %s cookie(s) to %s", len(cookies), output)
    for name in cookies:
        logger.info("  - %s", name)
    print(f"\n[OK] Cookies saved to: {output}")
    print("Test with: python web_dashboard/scripts/test_reddit_search.py")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nInterrupted")
        sys.exit(1)
