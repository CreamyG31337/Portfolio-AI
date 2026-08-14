#!/usr/bin/env python3
"""
Operate the social sentiment AI pipeline by hand, one phase at a time.

The pipeline is social_metrics.raw_data -> social_posts -> sentiment_sessions
-> social_sentiment_analysis. Each stage is a separate subcommand so a backfill
can be inspected between steps instead of running end to end blind.

Usage:
    python scripts/backfill_social_sentiment.py status
    python scripts/backfill_social_sentiment.py retire-orphans [--apply]
    python scripts/backfill_social_sentiment.py extract --days 14 [--apply]
    python scripts/backfill_social_sentiment.py sessions [--apply]
    python scripts/backfill_social_sentiment.py enqueue --days 14 [--limit N] [--apply]

Every subcommand is read-only unless --apply is passed.
"""

import argparse
import logging
import sys
import time
from pathlib import Path

# Setup path
current_file = Path(__file__).resolve()
project_root = current_file.parent.parent
sys.path.insert(0, str(project_root))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("backfill_social_sentiment")


def _postgres():
    from postgres_client import PostgresClient

    return PostgresClient()


def cmd_status(args: argparse.Namespace) -> int:
    """Report row counts at every stage of the pipeline."""
    pc = _postgres()
    checks = [
        ("social_metrics rows", "SELECT COUNT(*) n FROM social_metrics"),
        (
            "  ...unextracted with posts",
            """SELECT COUNT(*) n FROM social_metrics sm
               WHERE jsonb_typeof(sm.raw_data)='array' AND jsonb_array_length(sm.raw_data)>0
                 AND NOT EXISTS (SELECT 1 FROM social_posts sp WHERE sp.metric_id=sm.id)""",
        ),
        ("social_posts rows", "SELECT COUNT(*) n FROM social_posts"),
        ("sentiment_sessions rows", "SELECT COUNT(*) n FROM sentiment_sessions"),
        (
            "  ...pending AI analysis",
            "SELECT COUNT(*) n FROM sentiment_sessions WHERE needs_ai_analysis = TRUE",
        ),
        (
            "  ...pending but orphaned",
            """SELECT COUNT(*) n FROM sentiment_sessions ss
               WHERE ss.needs_ai_analysis = TRUE
                 AND NOT EXISTS (
                   SELECT 1 FROM social_posts sp WHERE sp.session_id = ss.id
                 )""",
        ),
        (
            "social_posts not yet in a session",
            "SELECT COUNT(*) n FROM social_posts WHERE session_id IS NULL",
        ),
        ("social_sentiment_analysis rows", "SELECT COUNT(*) n FROM social_sentiment_analysis"),
        (
            "  ...within dashboard 7d window",
            """SELECT COUNT(*) n FROM social_sentiment_analysis
               WHERE analyzed_at > NOW() - INTERVAL '7 days'""",
        ),
        ("extracted_tickers rows", "SELECT COUNT(*) n FROM extracted_tickers"),
    ]
    for label, query in checks:
        try:
            rows = pc.execute_query(query)
            logger.info("%-34s %s", label, rows[0]["n"] if rows else "?")
        except Exception as exc:
            logger.error("%-34s ERROR: %s", label, exc)
    return 0


def cmd_retire_orphans(args: argparse.Namespace) -> int:
    """Retire pending sessions that have no posts to analyze.

    A session with no social_posts rows has no content to analyze and never
    will. Left pending it sits at the head of the oldest-first queue and
    starves everything behind it.
    """
    pc = _postgres()
    select_orphans = """
        SELECT ss.id, ss.ticker, ss.platform, ss.session_start
        FROM sentiment_sessions ss
        WHERE ss.needs_ai_analysis = TRUE
          AND NOT EXISTS (
              SELECT 1 FROM social_posts sp WHERE sp.session_id = ss.id
          )
        ORDER BY ss.session_start
    """
    orphans = pc.execute_query(select_orphans)
    logger.info("Found %s orphaned pending session(s)", len(orphans))
    for row in orphans[:10]:
        logger.info(
            "  id=%s %s/%s session_start=%s",
            row["id"], row["ticker"], row["platform"], row["session_start"],
        )
    if len(orphans) > 10:
        logger.info("  ... and %s more", len(orphans) - 10)

    if not orphans:
        return 0
    if not args.apply:
        logger.info("DRY RUN -- pass --apply to retire these sessions")
        return 0

    updated = pc.execute_update(
        """
        UPDATE sentiment_sessions ss
        SET needs_ai_analysis = FALSE
        WHERE ss.needs_ai_analysis = TRUE
          AND NOT EXISTS (
              SELECT 1 FROM social_posts sp WHERE sp.session_id = ss.id
          )
        """
    )
    logger.info("✅ Retired %s orphaned session(s)", updated)
    return 0


def cmd_extract(args: argparse.Namespace) -> int:
    """Extract posts out of social_metrics.raw_data into social_posts."""
    from social_service import SocialSentimentService

    pc = _postgres()
    remaining_q = """
        SELECT COUNT(*) n FROM social_metrics sm
        WHERE jsonb_typeof(sm.raw_data)='array' AND jsonb_array_length(sm.raw_data)>0
          AND sm.created_at > NOW() - (%s * INTERVAL '1 day')
          AND (%s IS NULL OR sm.platform = %s)
          AND NOT EXISTS (SELECT 1 FROM social_posts sp WHERE sp.metric_id=sm.id)
    """
    platform = args.platform or None
    remaining = pc.execute_query(remaining_q, (args.days, platform, platform))[0]["n"]
    logger.info(
        "%s metric row(s) awaiting extraction within %s days (platform=%s)",
        remaining, args.days, platform or "all",
    )

    if not args.apply:
        logger.info("DRY RUN -- pass --apply to extract")
        return 0
    if not remaining:
        return 0

    service = SocialSentimentService()
    total_posts = 0
    total_metrics = 0
    total_dupes = 0
    started = time.time()
    while True:
        result = service.extract_posts_from_raw_data(
            limit=args.batch_size, since_days=args.days, platform=platform
        )
        processed = result["processed"]
        total_metrics += processed
        total_posts += result["posts_created"]
        total_dupes += result.get("posts_duplicate", 0)
        if processed == 0:
            break
        logger.info(
            "  progress: %s/%s metrics, %s posts, %.1fs elapsed",
            total_metrics, remaining, total_posts, time.time() - started,
        )
        if args.max_metrics and total_metrics >= args.max_metrics:
            logger.info("Reached --max-metrics cap of %s", args.max_metrics)
            break

    logger.info(
        "✅ Extraction complete: %s metrics, %s posts created, %s cross-poll "
        "duplicates skipped, in %.1fs",
        total_metrics, total_posts, total_dupes, time.time() - started,
    )
    return 0


def cmd_sessions(args: argparse.Namespace) -> int:
    """Group extracted posts into one session per ticker per UTC day."""
    from social_service import SocialSentimentService

    pc = _postgres()
    unassigned = pc.execute_query(
        "SELECT COUNT(*) n FROM social_posts WHERE session_id IS NULL AND posted_at IS NOT NULL"
    )[0]["n"]
    logger.info("%s post(s) not yet covered by a session", unassigned)

    if not args.apply:
        logger.info("DRY RUN -- pass --apply to create sessions")
        return 0
    if not unassigned:
        return 0

    service = SocialSentimentService()
    total_sessions = 0
    total_assigned = 0
    started = time.time()
    # create_sentiment_sessions works a bounded batch per call, so cap the
    # loop rather than trusting it to always report zero progress at the end.
    for _ in range(args.max_passes):
        result = service.create_sentiment_sessions()
        if result["sessions_created"] == 0:
            break
        total_sessions += result["sessions_created"]
        total_assigned += result["posts_assigned"]
        logger.info(
            "  progress: %s sessions, %s posts assigned, %.1fs elapsed",
            total_sessions, total_assigned, time.time() - started,
        )
    else:
        logger.warning(
            "Hit --max-passes (%s); re-run to continue", args.max_passes
        )

    logger.info(
        "✅ Session creation complete: %s sessions, %s posts in %.1fs",
        total_sessions, total_assigned, time.time() - started,
    )
    return 0


def cmd_enqueue(args: argparse.Namespace) -> int:
    """Enqueue pending sessions onto the AI task queue."""
    from scheduler.ai_task_workers import (
        AIQueueConfig,
        enqueue_social_sentiment_analysis_tasks,
    )
    from supabase_client import SupabaseClient

    pc = _postgres()
    params = []
    age_clause = ""
    if args.days:
        age_clause = "AND ss.session_start > NOW() - (%s * INTERVAL '1 day')"
        params.append(args.days)
    query = f"""
        SELECT ss.id
        FROM sentiment_sessions ss
        WHERE ss.needs_ai_analysis = TRUE
          {age_clause}
          AND EXISTS (
              SELECT 1 FROM social_posts sp WHERE sp.session_id = ss.id
          )
        ORDER BY ss.session_start DESC
    """
    if args.limit:
        query += " LIMIT %s"
        params.append(args.limit)

    rows = pc.execute_query(query, tuple(params) if params else None)
    session_ids = [int(r["id"]) for r in rows]
    logger.info("%s session(s) ready to enqueue", len(session_ids))

    if not session_ids:
        return 0
    if not args.apply:
        logger.info("DRY RUN -- pass --apply to enqueue")
        logger.info("  first ids: %s", session_ids[:20])
        return 0

    config = AIQueueConfig.from_env()
    if not config.enabled:
        logger.warning("AI_QUEUE_ENABLED is not set -- workers will not pick these up")

    stats = enqueue_social_sentiment_analysis_tasks(
        SupabaseClient(use_service_role=True),
        session_ids,
        priority=args.priority,
        enqueued_by=args.enqueued_by,
        max_attempts=config.max_attempts,
    )
    logger.info(
        "✅ Enqueued %s/%s task(s), failed=%s",
        stats["enqueued"], stats["attempted"], stats["failed"],
    )
    return 1 if stats["failed"] else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("status", help="report pipeline row counts")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("retire-orphans", help="retire pending sessions whose metrics are gone")
    p.add_argument("--apply", action="store_true", help="perform the update")
    p.set_defaults(func=cmd_retire_orphans)

    p = sub.add_parser("extract", help="extract raw_data into social_posts")
    p.add_argument("--days", type=int, default=14, help="only metrics newer than N days")
    p.add_argument("--batch-size", type=int, default=500, help="metrics per pass")
    p.add_argument("--max-metrics", type=int, default=0, help="stop after N metrics (0 = no cap)")
    p.add_argument("--platform", default="", help="restrict to 'stocktwits' or 'reddit'")
    p.add_argument("--apply", action="store_true", help="perform the extraction")
    p.set_defaults(func=cmd_extract)

    p = sub.add_parser("sessions", help="group posts into sentiment sessions")
    p.add_argument("--max-passes", type=int, default=200, help="safety cap on batch passes")
    p.add_argument("--apply", action="store_true", help="perform the session creation")
    p.set_defaults(func=cmd_sessions)

    p = sub.add_parser("enqueue", help="enqueue pending sessions for AI analysis")
    p.add_argument("--days", type=int, default=14, help="only sessions newer than N days")
    p.add_argument("--limit", type=int, default=0, help="cap how many to enqueue (0 = all)")
    p.add_argument("--priority", type=int, default=0, help="queue priority (cron uses 10)")
    p.add_argument("--enqueued-by", default="backfill", help="enqueued_by tag")
    p.add_argument("--apply", action="store_true", help="perform the enqueue")
    p.set_defaults(func=cmd_enqueue)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
