#!/usr/bin/env python3
"""Phase K2 run-once: one YouTube video (or one ``youtube_sources`` row) -> one article.

Lands a ``YouTube Transcript`` row in Research Postgres end to end: fetch captions
(K1) -> clean -> normalize -> upsert by canonical watch URL -> summarize + ticker
extract (inline, or enqueued when ``youtube_transcript_summary`` is enabled on the
AI task queue).

Usage (from repo root, venv active)::

    python scripts/youtube_article_ingest.py "https://www.youtube.com/watch?v=LPEXkI_4qI4"
    python scripts/youtube_article_ingest.py LPEXkI_4qI4 --source-id 3
    python scripts/youtube_article_ingest.py LPEXkI_4qI4 --dry-run
    python scripts/youtube_article_ingest.py LPEXkI_4qI4 --force --queue

``--source-id`` pulls the allowlist row (expected_tickers, duration gates, handle,
alpha_mechanism) so the landed row carries the same provenance the K3 poller will.
Only allowlisted sources should be ingested — this script does not discover videos.

Exit codes:
  0 row landed (saved or queued) / already present
  1 soft-fail (blocked / no_captions / age_restricted / ...) or save error
  2 bad CLI usage
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
_WEB = _REPO_ROOT / "web_dashboard"
for path in (_REPO_ROOT, _WEB):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

logger = logging.getLogger("youtube_article_ingest")


def _load_source_row(source_id: int) -> dict[str, Any] | None:
    from postgres_client import PostgresClient

    rows = PostgresClient().execute_query(
        "SELECT * FROM youtube_sources WHERE id = %s", (source_id,)
    )
    return dict(rows[0]) if rows else None


def _production_holdings() -> list[str]:
    """Holdings-scoped relevance input — production funds only."""
    try:
        from supabase_client import SupabaseClient

        client = SupabaseClient(use_service_role=True)
        funds = (
            client.supabase.table("funds")
            .select("name")
            .eq("is_production", True)
            .execute()
        )
        names = [f["name"] for f in (funds.data or [])]
        if not names:
            return []
        positions = (
            client.supabase.table("latest_positions")
            .select("ticker")
            .in_("fund", names)
            .execute()
        )
        return sorted(
            {str(p["ticker"]) for p in (positions.data or []) if p.get("ticker")}
        )
    except Exception as exc:
        logger.warning("Could not load production holdings: %s", exc)
        return []


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Land one allowlisted YouTube video as a research_articles row (Phase K2)."
    )
    parser.add_argument("url_or_id", help="YouTube watch URL or 11-char video id")
    parser.add_argument(
        "--source-id",
        type=int,
        help="youtube_sources.id to attribute this video to (expected_tickers, duration gates)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-ingest even when the watch URL already exists (re-summarizes)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch + normalize and print the article fields; no DB write, no LLM",
    )
    parser.add_argument(
        "--queue",
        action="store_true",
        help="Force AI-task-queue enrichment regardless of AI_QUEUE_JOBS",
    )
    parser.add_argument(
        "--inline",
        action="store_true",
        help="Force inline summarize regardless of AI_QUEUE_JOBS",
    )
    parser.add_argument(
        "--no-embedding",
        action="store_true",
        help="Skip the Ollama embedding call (faster inline runs)",
    )
    parser.add_argument("--json", action="store_true", help="Machine-readable output")
    args = parser.parse_args(argv)

    if args.queue and args.inline:
        parser.error("--queue and --inline are mutually exclusive")

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    source_row = None
    if args.source_id is not None:
        source_row = _load_source_row(args.source_id)
        if source_row is None:
            print(f"No youtube_sources row with id={args.source_id}", file=sys.stderr)
            return 2
        if not source_row.get("enabled"):
            print(
                f"youtube_sources id={args.source_id} is disabled — "
                "enable it on /admin/sources before ingesting",
                file=sys.stderr,
            )
            return 2

    from youtube_articles import ingest_video, normalize_transcript
    from youtube_captions import CaptionFetchError, fetch_caption_text

    if args.dry_run:
        try:
            result = fetch_caption_text(args.url_or_id)
        except CaptionFetchError as exc:
            payload = {"ok": False, "reason": exc.reason, "error": str(exc)}
            print(json.dumps(payload, indent=2) if args.json else f"FAIL {exc.reason}: {exc}")
            return 1
        article = normalize_transcript(result, source_row=source_row)
        preview = {
            "ok": True,
            "dry_run": True,
            "article_type": "YouTube Transcript",
            "url": article.url,
            "title": article.title,
            "source": article.source,
            "published_at": (
                article.published_at.isoformat() if article.published_at else None
            ),
            "content_chars": len(article.content),
            "truncated": article.truncated,
            "source_metadata": article.source_metadata,
            "expected_tickers": list(article.expected_tickers),
        }
        print(json.dumps(preview, indent=2, ensure_ascii=False))
        return 0

    from ollama_client import get_ollama_client
    from research_repository import ResearchRepository

    use_queue: bool | None = None
    if args.queue:
        use_queue = True
    elif args.inline:
        use_queue = False

    outcome = ingest_video(
        args.url_or_id,
        research_repo=ResearchRepository(),
        source_row=source_row,
        owned_tickers=_production_holdings(),
        ollama_client=None if args.no_embedding else get_ollama_client(),
        force=args.force,
        use_queue=use_queue,
    )

    payload = {
        "ok": outcome.landed or outcome.status == "skipped_exists",
        "status": outcome.status,
        "video_id": outcome.video_id,
        "url": outcome.url,
        "article_id": outcome.article_id,
        "title": outcome.title,
        "source": outcome.source,
        "char_count": outcome.char_count,
        "tickers": outcome.tickers,
        "reason": outcome.reason,
        "message": outcome.message,
    }
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(f"status={outcome.status}")
        for key, value in payload.items():
            if key in ("ok", "status") or value in (None, "", [], 0):
                continue
            print(f"  {key}: {value}")

    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
