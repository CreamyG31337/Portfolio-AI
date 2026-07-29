#!/usr/bin/env python3
"""Apply Phase K sources migrations to the Research DB.

Runs:
  - migrations/008_create_youtube_sources.sql
  - migrations/009_add_rss_feeds_health_columns.sql

Usage (from repo root, venv active)::

    python web_dashboard/scripts/apply_sources_migrations.py
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

_WEB = Path(__file__).resolve().parent.parent
_ROOT = _WEB.parent
if str(_WEB) not in sys.path:
    sys.path.insert(0, str(_WEB))

from postgres_client import PostgresClient  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

MIGRATIONS = [
    _ROOT / "migrations" / "008_create_youtube_sources.sql",
    _ROOT / "migrations" / "009_add_rss_feeds_health_columns.sql",
]


def main() -> int:
    client = PostgresClient()
    for path in MIGRATIONS:
        if not path.exists():
            logger.error("Missing migration: %s", path)
            return 1
        sql = path.read_text(encoding="utf-8")
        logger.info("Applying %s ...", path.name)
        client.execute_update(sql)
        logger.info("  OK %s", path.name)

    # Sanity: youtube_sources exists; rss_feeds still has core columns + new ones.
    yt = client.execute_query(
        "SELECT COUNT(*) AS n FROM information_schema.tables "
        "WHERE table_name = 'youtube_sources'"
    )
    cols = client.execute_query(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = 'rss_feeds' ORDER BY column_name"
    )
    col_names = {row["column_name"] for row in cols}
    required = {"id", "name", "url", "enabled", "last_fetched_at", "notes", "consecutive_failures"}
    missing = required - col_names
    if not yt or int(yt[0]["n"]) < 1:
        logger.error("youtube_sources table missing after migrate")
        return 1
    if missing:
        logger.error("rss_feeds missing columns: %s", sorted(missing))
        return 1

    feeds = client.execute_query("SELECT id, name, url FROM rss_feeds WHERE enabled = true LIMIT 5")
    logger.info("RSS contract probe OK (%d enabled sample rows)", len(feeds))
    logger.info("Sources migrations applied successfully")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
