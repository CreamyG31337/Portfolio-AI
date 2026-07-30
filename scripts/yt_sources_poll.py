#!/usr/bin/env python3
"""Phase K3 ops CLI: poll the ``youtube_sources`` allowlist for new videos.

Same code path as the scheduled ``youtube_caption_ingest`` job — this only exists
so ops can inspect and bound one run without touching the scheduler.

Usage (from repo root, venv active)::

    python scripts/yt_sources_poll.py --dry-run
    python scripts/yt_sources_poll.py --source-id 3 --max-videos 2
    python scripts/yt_sources_poll.py --list-only --source-id 3

``--dry-run`` lists candidates and reports what would be ingested without
fetching captions, writing articles, or touching source cursors/health.
``--list-only`` goes further and skips the DB entirely for one source's listing.

Exit codes:
  0 poll completed (soft-fails are not failures)
  1 nothing polled / listing failed for the requested source
  2 bad CLI usage
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_WEB = _REPO_ROOT / "web_dashboard"
for path in (_REPO_ROOT, _WEB):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

logger = logging.getLogger("yt_sources_poll")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Poll enabled youtube_sources rows for new videos (Phase K3)."
    )
    parser.add_argument(
        "--source-id",
        type=int,
        help="Poll only this youtube_sources.id (must still be enabled)",
    )
    parser.add_argument(
        "--max-videos",
        type=int,
        help="Override the global per-run ingest cap (YOUTUBE_INGEST_MAX_PER_RUN)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List + report only; no caption fetch, no DB writes, no cursor updates",
    )
    parser.add_argument(
        "--list-only",
        action="store_true",
        help="Print the newest-first listing for --source-id and exit (no ingest)",
    )
    parser.add_argument("--json", action="store_true", help="Machine-readable output")
    args = parser.parse_args(argv)

    if args.list_only and args.source_id is None:
        parser.error("--list-only requires --source-id")

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    from postgres_client import PostgresClient
    from scheduler.jobs_yt import (
        load_enabled_sources,
        poll_youtube_sources,
        production_holdings,
    )

    postgres_client = PostgresClient()

    if args.list_only:
        from yt_captions import CaptionFetchError, list_source_videos

        rows = load_enabled_sources(postgres_client, source_id=args.source_id)
        if not rows:
            print(
                f"No enabled youtube_sources row with id={args.source_id}",
                file=sys.stderr,
            )
            return 1
        try:
            videos = list_source_videos(rows[0], limit=args.max_videos)
        except CaptionFetchError as exc:
            print(f"FAIL {exc.reason}: {exc}", file=sys.stderr)
            return 1
        payload = [
            {
                "video_id": v.video_id,
                "url": v.watch_url,
                "title": v.title,
                "upload_date": v.upload_date,
                "duration_s": v.duration_s,
            }
            for v in videos
        ]
        if args.json:
            print(json.dumps(payload, indent=2, ensure_ascii=False))
        else:
            print(f"{len(payload)} videos (newest first) for {rows[0].get('label')}:")
            for item in payload:
                print(f"  {item['video_id']}  {item['title'] or '-'}")
        return 0

    from research_repository import ResearchRepository

    ollama_client = None
    if not args.dry_run:
        try:
            from ollama_client import get_ollama_client

            ollama_client = get_ollama_client()
        except Exception as exc:
            logger.warning("Ollama client unavailable (no embeddings): %s", exc)

    summary = poll_youtube_sources(
        postgres_client=postgres_client,
        research_repo=ResearchRepository(),
        owned_tickers=production_holdings() if not args.dry_run else [],
        ollama_client=ollama_client,
        max_videos=args.max_videos,
        source_id=args.source_id,
        dry_run=args.dry_run,
    )

    if args.json:
        print(
            json.dumps(
                {
                    "sources_polled": summary.sources_polled,
                    "landed": summary.landed,
                    "attempted": summary.attempted,
                    "considered": summary.considered,
                    "skipped_exists": summary.skipped_exists,
                    "skipped_duration": summary.skipped_duration,
                    "soft_failed": summary.soft_failed,
                    "errors": summary.errors,
                    "listing_errors": summary.listing_errors,
                    "capped": summary.capped,
                    "sources": [
                        {
                            "source_id": r.source_id,
                            "label": r.label,
                            "listed": r.listed,
                            "attempted": r.attempted,
                            "landed": r.landed,
                            "soft_failed": r.soft_failed,
                            "listing_error": r.listing_error,
                            "cursor_advanced_to": r.cursor_advanced_to,
                        }
                        for r in summary.results
                    ],
                },
                indent=2,
                ensure_ascii=False,
            )
        )
    else:
        print(summary.message)
        for result in summary.results:
            print(
                f"  [{result.source_id}] {result.label}: listed={result.listed} "
                f"landed={result.landed} soft_fail={result.soft_failed} "
                f"cursor={result.cursor_advanced_to or '-'} "
                f"error={result.listing_error or '-'}"
            )

    return 0 if summary.sources_polled else 1


if __name__ == "__main__":
    raise SystemExit(main())
