#!/usr/bin/env python3
"""One-time backfill: set ``research_articles.sector`` for ETF Analysis rows from holding sectors.

Uses ``etf_article_sector_infer`` (research ``securities`` first, then Supabase ``securities``).

Examples (repo root, venv activated)::

    python web_dashboard/scripts/backfill_etf_analysis_article_sectors.py --dry-run
    python web_dashboard/scripts/backfill_etf_analysis_article_sectors.py --limit 50
    python web_dashboard/scripts/backfill_etf_analysis_article_sectors.py

PowerShell::

    .\\venv\\Scripts\\Activate.ps1
    python web_dashboard\\scripts\\backfill_etf_analysis_article_sectors.py --dry-run
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path


def _configure_paths() -> Path:
    script = Path(__file__).resolve()
    web_dashboard_root = script.parent.parent
    project_root = web_dashboard_root.parent
    if str(web_dashboard_root) not in sys.path:
        sys.path.insert(0, str(web_dashboard_root))
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    return web_dashboard_root


def _load_env(web_dashboard_root: Path) -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    env_path = web_dashboard_root / ".env"
    if env_path.is_file():
        load_dotenv(env_path)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Backfill sector on ETF Analysis research_articles from holding tickers."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Log actions only; do not UPDATE the database.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Max articles to process (0 = no limit).",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    log = logging.getLogger("backfill_etf_analysis_article_sectors")

    web_root = _configure_paths()
    _load_env(web_root)

    from etf_article_sector_infer import article_row_tickers, dominant_sector_for_holdings
    from postgres_client import PostgresClient
    from supabase_client import SupabaseClient

    pg = PostgresClient()
    if not pg.test_connection():
        log.error("Research DB connection failed (RESEARCH_DATABASE_URL).")
        return 1

    supabase: SupabaseClient | None = None
    try:
        supabase = SupabaseClient(use_service_role=True)
    except Exception as exc:
        log.warning("Supabase client unavailable; using research securities only: %s", exc)

    base_q = """
        SELECT id, ticker, tickers, title, sector
        FROM research_articles
        WHERE article_type = 'ETF Analysis'
          AND (sector IS NULL OR TRIM(sector) = '')
        ORDER BY fetched_at DESC NULLS LAST
    """
    if args.limit and args.limit > 0:
        rows = pg.execute_query(base_q + " LIMIT %s", (int(args.limit),))
    else:
        rows = pg.execute_query(base_q)
    articles = list(rows or [])
    log.info("Found %s ETF Analysis article(s) with empty sector.", len(articles))

    updated = 0
    skipped_no_tickers = 0
    skipped_no_sector = 0
    errors = 0

    for row in articles:
        aid = row.get("id")
        tickers = article_row_tickers(row)
        if not tickers:
            skipped_no_tickers += 1
            log.debug("skip %s: no tickers", aid)
            continue
        sector = dominant_sector_for_holdings(pg, supabase, tickers)
        if not sector:
            skipped_no_sector += 1
            log.info("skip %s (%s): no sector in securities for tickers %s", aid, row.get("title"), tickers[:5])
            continue
        if args.dry_run:
            log.info("[dry-run] would set sector=%r for %s (%s)", sector, aid, row.get("title"))
            updated += 1
            continue
        try:
            pg.execute_update(
                "UPDATE research_articles SET sector = %s WHERE id = %s",
                (sector, aid),
            )
            updated += 1
            log.info("updated %s -> sector=%r", aid, sector)
        except Exception as exc:
            errors += 1
            log.error("failed to update %s: %s", aid, exc)

    log.info(
        "Done. updated=%s skipped_no_tickers=%s skipped_no_sector=%s errors=%s dry_run=%s",
        updated,
        skipped_no_tickers,
        skipped_no_sector,
        errors,
        args.dry_run,
    )
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
