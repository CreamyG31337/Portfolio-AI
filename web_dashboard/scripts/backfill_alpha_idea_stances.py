#!/usr/bin/env python3
"""Backfill ``alpha_idea`` stances from past Alpha/Opportunity articles (ROADMAP §2.8 Z1).

The nightly ``alpha_idea_ledger`` job only looks back a few days. Running this once
over the article history means ideas get scored at the 7d/30d horizons straight
away instead of a month from now. Entry dates come from each article's own fetch
time (next weekday), so backfilled rows are scored exactly as if the job had been
running all along.

Idempotent: dedupe is per (ticker, alpha_idea, article id), so re-running or
overlapping the nightly window writes nothing twice.

SCORING BACKLOG: the nightly outcome scorer takes 200 rows per horizon, oldest
first. Backfilled rows are old, so a large backfill would hold up scoring of every
other source for days. ``--score-rounds N`` runs the scorer N times right after
writing to drain the backlog (it fetches prices from yfinance, so it takes a while).

Undo (stance_outcomes rows cascade on delete):
    DELETE FROM stance_history WHERE source = 'alpha_idea';

Run from project root:
  python web_dashboard/scripts/backfill_alpha_idea_stances.py               # dry run
  python web_dashboard/scripts/backfill_alpha_idea_stances.py --execute
  python web_dashboard/scripts/backfill_alpha_idea_stances.py --execute --score-rounds 20
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

_SCRIPT_DIR = Path(__file__).resolve().parent
_WEB_DASHBOARD = _SCRIPT_DIR.parent
_REPO_ROOT = _WEB_DASHBOARD.parent
for p in (str(_WEB_DASHBOARD), str(_REPO_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true", help="write the stances")
    parser.add_argument("--days", type=int, default=180, help="article lookback (default 180)")
    parser.add_argument(
        "--score-rounds", type=int, default=0,
        help="after writing, run the outcome scorer up to N times to drain the backlog",
    )
    args = parser.parse_args()

    from idea_stance_service import record_alpha_idea_stances
    from postgres_client import PostgresClient

    stats = record_alpha_idea_stances(
        PostgresClient(), days=args.days, dry_run=not args.execute
    )
    mode = "WROTE" if args.execute else "DRY RUN (pass --execute to write)"
    print(f"{mode}: {stats}")

    if args.execute and args.score_rounds > 0:
        from scheduler.jobs_stance_outcomes import stance_outcomes_job

        pg = PostgresClient()
        for i in range(1, args.score_rounds + 1):
            before = _unscored_alpha_idea_count(pg)
            if before == 0:
                break
            print(f"score round {i}: {before} matured alpha_idea (row, horizon) pairs unscored")
            stance_outcomes_job()
            if _unscored_alpha_idea_count(pg) >= before:
                print("no progress this round (dead-letters / missing prices); stopping")
                break
        print(f"remaining unscored: {_unscored_alpha_idea_count(pg)}")
    return 0


def _unscored_alpha_idea_count(pg: Any) -> int:
    """Matured alpha_idea (stance, horizon) pairs with no outcome and not dead-lettered."""
    from scheduler.jobs_stance_outcomes import HORIZONS, MAX_SCORING_ATTEMPTS

    total = 0
    for horizon in HORIZONS:
        rows = pg.execute_query(
            """
            SELECT COUNT(*) AS n
            FROM stance_history sh
            LEFT JOIN stance_outcomes so
              ON so.stance_id = sh.id AND so.horizon_days = %s
            LEFT JOIN stance_outcome_attempts sa
              ON sa.stance_id = sh.id AND sa.horizon_days = %s
            WHERE sh.source = 'alpha_idea'
              AND sh.as_of <= NOW() - (%s || ' days')::interval
              AND so.id IS NULL
              AND COALESCE(sa.attempts, 0) < %s
            """,
            (horizon, horizon, str(horizon), MAX_SCORING_ATTEMPTS),
        )
        total += int((rows or [{}])[0].get("n") or 0)
    return total


if __name__ == "__main__":
    raise SystemExit(main())
