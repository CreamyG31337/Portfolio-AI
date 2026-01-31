#!/usr/bin/env python3
"""
Reset January congress trade sessions for re-analysis.
========================================================

Marks sessions that overlap January (by end_date) as needing re-analysis
and clears their scores so the batch analysis job will pick them up.

Run this once, then run the session analysis from the repo so it keeps
running even if you redeploy the app:

  .\\venv\\Scripts\\activate
  python web_dashboard\\scripts\\analyze_congress_trades_batch.py --sessions --batch-size 10

Usage:
  python web_dashboard/scripts/reset_january_sessions_for_reanalysis.py [--year 2026] [--month 1]
"""

import argparse
import sys
from pathlib import Path

# Add web_dashboard to path (script lives in web_dashboard/scripts)
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
env_path = project_root / ".env"
if env_path.exists():
    load_dotenv(env_path)
else:
    load_dotenv()

from postgres_client import PostgresClient


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Mark January congress trade sessions for re-analysis (clear scores so batch job re-runs them)."
    )
    parser.add_argument(
        "--year",
        type=int,
        default=2026,
        help="Year for January (default: 2026)",
    )
    parser.add_argument(
        "--month",
        type=int,
        default=1,
        help="Month to reset (default: 1 = January)",
    )
    args = parser.parse_args()

    year, month = args.year, args.month
    start_date = f"{year}-{month:02d}-01"
    if month == 12:
        end_date = f"{year + 1}-01-01"
    else:
        end_date = f"{year}-{month + 1:02d}-01"

    pg = PostgresClient()

    # Sessions that overlap the target month (end_date in [start_date, end_date) or start_date in that range)
    # We use end_date in month for simplicity: "sessions whose last trade was in January"
    update_sessions = """
        UPDATE congress_trade_sessions
        SET
            needs_reanalysis = TRUE,
            conflict_score = NULL,
            confidence_score = NULL,
            ai_summary = NULL,
            risk_pattern = NULL,
            model_used = NULL,
            last_analyzed_at = NULL,
            updated_at = NOW()
        WHERE end_date >= %s AND end_date < %s
    """
    n_sessions = pg.execute_update(update_sessions, (start_date, end_date)) or 0

    # Clear per-trade analysis for those sessions so UI doesn't show stale scores
    # (batch job will repopulate with ON CONFLICT DO UPDATE)
    n_analysis = 0
    try:
        clear_analysis = """
            UPDATE congress_trades_analysis
            SET conflict_score = NULL,
                confidence_score = NULL,
                reasoning = NULL,
                risk_pattern = NULL,
                analyzed_at = NULL
            WHERE session_id IN (
                SELECT id FROM congress_trade_sessions
                WHERE end_date >= %s AND end_date < %s
            )
        """
        n_analysis = pg.execute_update(clear_analysis, (start_date, end_date)) or 0
    except Exception as e:
        print(f"Note: could not clear per-trade analysis ({e}). Session-level reset still applied.")

    print(f"Reset {n_sessions} sessions (and {n_analysis} analysis rows) for {year}-{month:02d}.")
    print("Run re-analysis from repo so it survives redeploy:")
    print("  .\\venv\\Scripts\\activate")
    print("  python web_dashboard\\scripts\\analyze_congress_trades_batch.py --sessions --batch-size 10")


if __name__ == "__main__":
    main()
