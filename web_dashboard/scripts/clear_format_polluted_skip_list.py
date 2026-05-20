#!/usr/bin/env python3
"""Clear polluted ``ai_analysis_skip_list`` rows from the May 2026 format-bug.

A bug somewhere in the ticker-analysis save path raised
``unsupported format string passed to NoneType.__format__`` for every ticker
the cron tried to analyze. Under the *old* skip policy
(``skip_until = NULL`` after 3 failures), 95 tickers got permanently banned,
which silently stopped the entire ``ticker_analysis`` → ``ticker_meta_analysis``
pipeline for 12+ days.

The skip-list policy is now fixed (see
``web_dashboard/ai_skip_list_manager.py`` — transient errors get a finite
``skip_until``). This script cleans up the historical pollution so the next
nightly run actually has tickers to process.

Usage (from repo root, with the venv activated)::

    python web_dashboard/scripts/clear_format_polluted_skip_list.py --dry-run
    python web_dashboard/scripts/clear_format_polluted_skip_list.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_script = Path(__file__).resolve()
_web_root = _script.parent.parent
_project_root = _web_root.parent
sys.path.insert(0, str(_project_root))
sys.path.insert(0, str(_web_root))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(_web_root / ".env")

from ai_skip_list_manager import AISkipListManager  # noqa: E402
from supabase_client import SupabaseClient  # noqa: E402

DEFAULT_MARKER = "unsupported format string passed to NoneType.__format__"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--marker",
        default=DEFAULT_MARKER,
        help="Substring to match in the skip_list reason column "
        f"(default: {DEFAULT_MARKER!r})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List matching tickers without deleting.",
    )
    args = parser.parse_args()

    sb = SupabaseClient(use_service_role=True)
    manager = AISkipListManager(sb)

    matching = (
        sb.supabase.table("ai_analysis_skip_list")
        .select("ticker, reason, failure_count, last_failed_at")
        .ilike("reason", f"%{args.marker}%")
        .execute()
    )
    rows = matching.data or []
    print(f"Found {len(rows)} skip-list rows matching marker {args.marker!r}:")
    for r in rows[:15]:
        last_fail = r.get("last_failed_at") or ""
        print(
            f"  {r['ticker']:<10} failure_count={r.get('failure_count')} "
            f"last_failed_at={last_fail}"
        )
    if len(rows) > 15:
        print(f"  ... and {len(rows) - 15} more")

    if not rows:
        return 0
    if args.dry_run:
        print("\n--dry-run: not deleting anything.")
        return 0

    deleted = manager.clear_entries_matching(args.marker)
    print(f"\nDeleted {deleted} skip-list rows.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
