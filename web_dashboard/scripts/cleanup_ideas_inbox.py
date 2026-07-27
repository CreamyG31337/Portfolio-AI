#!/usr/bin/env python3
"""Auto-dismiss boilerplate from the Ideas inbox (Ideas quality P2).

The inbox pool is a rolling 14 days, so tightening the pre-extraction filter only
helps NEW articles -- the existing junk would sit at the top of /ideas for another
two weeks. This clears it now.

MECHANISM -- deliberately the least destructive one available
-------------------------------------------------------------
The inbox query already excludes any article with an `idea_triage` row, so cleanup
is just an INSERT of `dismissed` rows. That means:

  * NOTHING is written to research_articles -- Research search and meta-analysis
    still see these articles, which is correct: a holdings snapshot is bad as an
    *idea* but fine as *reference data*.
  * No relevance_score rewrite, so no other consumer of that score is affected.
  * Reversible with one statement:
        DELETE FROM idea_triage WHERE decided_by = 'auto_cleanup';

LABEL HYGIENE -- important
--------------------------
Rows are stamped `decided_by = 'auto_cleanup'`. These are NOT user labels. Any
future relevance training, or any "is triage being used?" metric, must filter
`decided_by <> 'auto_cleanup'` or it will read machine cleanup as human engagement
-- exactly the trap that made H7's empty-triage finding meaningful in the first place.

ON CONFLICT DO NOTHING guarantees a real Accept/Dismiss is never overwritten.

Run from project root:
  python web_dashboard/scripts/cleanup_ideas_inbox.py                 # dry run
  python web_dashboard/scripts/cleanup_ideas_inbox.py --execute
  python web_dashboard/scripts/cleanup_ideas_inbox.py --days 30 --execute
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

IDEA_TYPES = ("Alpha Research", "Opportunity Discovery")


def _safe(text: Any, width: int) -> str:
    s = str(text if text is not None else "").replace("\n", " ").strip()[:width]
    try:
        s.encode(sys.stdout.encoding or "utf-8")
        return s
    except (UnicodeEncodeError, TypeError):
        return s.encode("ascii", "replace").decode("ascii")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true", help="write the dismissals")
    parser.add_argument("--days", type=int, default=14,
                        help="lookback window; defaults to the inbox window (14)")
    args = parser.parse_args()

    from ideas_quality import (
        NEUTRAL_SENTIMENT_SQL,
        NO_CATALYST_CONCLUSION_RE,
        SENTIMENT_EXEMPT_REASONS,
        TITLE_REASONS,
    )
    from postgres_client import PostgresClient

    pg = PostgresClient()

    reason_case = " ".join(
        f"WHEN ra.title ~* '{pattern}' THEN '{label}'" for label, pattern in TITLE_REASONS
    )
    # Unconditional patterns vs those needing a neutral-sentiment confirmation.
    unconditional_re = "|".join(
        p for label, p in TITLE_REASONS if label in SENTIMENT_EXEMPT_REASONS
    )
    guarded_re = "|".join(
        p for label, p in TITLE_REASONS if label not in SENTIMENT_EXEMPT_REASONS
    )
    neutral_sql = NEUTRAL_SENTIMENT_SQL
    select_sql = f"""
        SELECT ra.id, ra.title, ra.source, ra.relevance_score, ra.logic_check,
               ra.sentiment, ra.conclusion,
               CASE {reason_case} ELSE 'no_catalyst_conclusion' END AS reason
        FROM research_articles ra
        LEFT JOIN idea_triage it ON it.article_id = ra.id
        WHERE ra.article_type = ANY(%s)
          AND ra.fetched_at >= NOW() - INTERVAL '1 day' * %s
          AND it.id IS NULL
          AND (
                ra.title ~* %s
                OR ((ra.title ~* %s OR ra.conclusion ~* %s) AND {neutral_sql})
              )
        ORDER BY ra.relevance_score DESC NULLS LAST, ra.fetched_at DESC
    """
    rows = pg.execute_query(
        select_sql,
        (list(IDEA_TYPES), args.days, unconditional_re, guarded_re, NO_CATALYST_CONCLUSION_RE),
    )

    total = pg.execute_query(
        """
        SELECT COUNT(*) AS n
        FROM research_articles ra
        LEFT JOIN idea_triage it ON it.article_id = ra.id
        WHERE ra.article_type = ANY(%s)
          AND ra.fetched_at >= NOW() - INTERVAL '1 day' * %s
          AND it.id IS NULL
        """,
        (list(IDEA_TYPES), args.days),
    )[0]["n"]

    mode = "EXECUTE" if args.execute else "DRY RUN"
    print(f"Ideas inbox cleanup [{mode}] — {args.days}d window")
    print(f"{len(rows)} of {total} open ideas match "
          f"({(100.0 * len(rows) / total) if total else 0:.0f}%)\n")

    by_reason: dict[str, int] = {}
    for r in rows:
        by_reason[r["reason"]] = by_reason.get(r["reason"], 0) + 1

    print(f"{'score':>5}  {'reason':<24} {'logic/sent':<22} title")
    print("-" * 108)
    for r in rows:
        ls = f"{r.get('logic_check') or '-'}/{r.get('sentiment') or '-'}"
        print(f"{str(r.get('relevance_score') or '-'):>5}  {r['reason']:<24} "
              f"{_safe(ls, 22):<22} {_safe(r['title'], 52)}")

    print("\nmatches by reason:", " ".join(f"{k}={v}" for k, v in sorted(by_reason.items())))

    if not args.execute:
        print("\nDry run — review the list above, then re-run with --execute.")
        print("Undo after executing:")
        print("  DELETE FROM idea_triage WHERE decided_by = 'auto_cleanup';")
        return 0

    if not rows:
        print("\nNothing to dismiss.")
        return 0

    inserted = pg.execute_update(
        f"""
        INSERT INTO idea_triage (article_id, status, decided_by, notes)
        SELECT ra.id, 'dismissed', 'auto_cleanup',
               'low_value:' || (CASE {reason_case} ELSE 'no_catalyst_conclusion' END)
        FROM research_articles ra
        LEFT JOIN idea_triage it ON it.article_id = ra.id
        WHERE ra.article_type = ANY(%s)
          AND ra.fetched_at >= NOW() - INTERVAL '1 day' * %s
          AND it.id IS NULL
          AND (
                ra.title ~* %s
                OR ((ra.title ~* %s OR ra.conclusion ~* %s) AND {neutral_sql})
              )
        ON CONFLICT (article_id) DO NOTHING
        """,
        (list(IDEA_TYPES), args.days, unconditional_re, guarded_re, NO_CATALYST_CONCLUSION_RE),
    )
    print(f"\ndismissed {inserted if inserted is not None else len(rows)} article(s) "
          f"as decided_by='auto_cleanup'")
    print("Undo: DELETE FROM idea_triage WHERE decided_by = 'auto_cleanup';")
    return 0


if __name__ == "__main__":
    sys.exit(main())
