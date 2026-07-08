#!/usr/bin/env python3
"""Log into Reddit with username/password and save session cookies.

Use this on your dev machine (with Playwright installed), then copy the output
file to the server or set REDDIT_COOKIES_FILE in production.

Usage:
    set REDDIT_USERNAME=your_user
    set REDDIT_PASSWORD=your_pass
    python web_dashboard/scripts/reddit_login_export.py

    # Or prompt for password:
    python web_dashboard/scripts/reddit_login_export.py --username your_user
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

WEB_DASHBOARD = Path(__file__).resolve().parents[1]
PROJECT_ROOT = WEB_DASHBOARD.parent
if str(WEB_DASHBOARD) not in sys.path:
    sys.path.insert(0, str(WEB_DASHBOARD))

from env_loader import load_project_dotenv
from reddit_login import RedditLoginError, login_interactive, login_with_password

load_project_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(description="Reddit login → reddit_cookies.json")
    parser.add_argument("--username", help="Reddit username (or set REDDIT_USERNAME)")
    parser.add_argument("--password", help="Reddit password (or set REDDIT_PASSWORD; prompts if omitted)")
    parser.add_argument(
        "--output",
        default="reddit_cookies.json",
        help="Output path (default: reddit_cookies.json in project root)",
    )
    parser.add_argument(
        "--http-only",
        action="store_true",
        help="Skip Playwright and try HTTP login only (usually blocked)",
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Open a visible browser and log in manually (no password stored). "
        "This is the default when no username/password is provided.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=300,
        help="Interactive login wait time in seconds (default: 300)",
    )
    args = parser.parse_args()

    username = (args.username or os.getenv("REDDIT_USERNAME", "")).strip()
    password = args.password or os.getenv("REDDIT_PASSWORD", "").strip()

    use_interactive = args.interactive or not (username and password)

    try:
        if use_interactive:
            logger.info("Interactive login mode — a browser window will open.")
            cookies = login_interactive(timeout_seconds=args.timeout)
        else:
            cookies = login_with_password(
                username,
                password,
                prefer_playwright=not args.http_only,
            )
    except RedditLoginError as exc:
        logger.error("%s", exc)
        return 1

    output = Path(args.output)
    if not output.is_absolute():
        output = PROJECT_ROOT / output.name
    output.write_text(json.dumps(cookies, indent=2), encoding="utf-8")
    logger.info("Saved %s cookie(s) to %s", len(cookies), output)
    for name in cookies:
        logger.info("  - %s", name)
    print(f"\n[OK] Add to web_dashboard/.env:\nREDDIT_COOKIES_FILE={output}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nInterrupted")
        sys.exit(1)
