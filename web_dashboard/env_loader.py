#!/usr/bin/env python3
"""Load `.env` files from the standard locations for this repo.

Primarily for local/dev: finds root and ``web_dashboard/.env`` regardless of cwd.

Production (e.g. Woodpecker, Docker) should inject secrets as real environment
variables. ``load_dotenv`` uses ``override=False`` by default, so existing env
vars are never overwritten by a file.

Files are loaded in order: repository root, then ``web_dashboard/.env``. If both
define the same key, the first file wins for that key; keys only in the second
file are still applied.
"""

from pathlib import Path

from dotenv import load_dotenv

_WEB_DASHBOARD = Path(__file__).resolve().parent
_ROOT = _WEB_DASHBOARD.parent


def load_project_dotenv() -> None:
    """Load ``<repo>/.env`` then ``web_dashboard/.env`` if they exist."""
    load_dotenv(_ROOT / ".env")
    load_dotenv(_WEB_DASHBOARD / ".env")
