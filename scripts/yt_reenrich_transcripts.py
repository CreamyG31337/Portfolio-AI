#!/usr/bin/env python3
"""Re-run summarize + ticker extraction over already-stored ``YouTube Transcript`` rows.

Uses the stored ``content``, so this costs **LLM calls only — zero YouTube caption
quota**. That is the point: captions are the rate-limited resource (~90 fetches per
egress IP per day, docs/PHASE_K_SOURCE_LIST.md §14), so any change to extraction or
scoring can be replayed over the corpus for free.

Written for the expected_tickers-contamination fix: ``summarize_transcript`` used to
prepend the *source's* registered tickers to every video, so all 8 early rows carried
ASML/TSM/INTC/AMAT (including an Apple M1 teardown) and every one scored a flat 0.80.
Tickers now come from the transcript unless the source is issuer-published
(``alpha_mechanism = 'EARNINGS_IR'``). Re-run to bring old rows onto the new rule.

Also prunes rows below the thin-caption floor (``YOUTUBE_TRANSCRIPT_MIN_CHARS``):
a body of a few sentences is a degenerate caption track, not a transcript, and one
such row (78 chars) predates the guard.

Usage (from repo root, venv active)::

    python scripts/yt_reenrich_transcripts.py                  # dry run: show the plan
    python scripts/yt_reenrich_transcripts.py --apply
    python scripts/yt_reenrich_transcripts.py --apply --prune-thin
    python scripts/yt_reenrich_transcripts.py --apply --article-id <uuid>

Dry run is the default; nothing is written without ``--apply``.

Exit codes:
  0 completed (or dry run)
  1 one or more rows failed to re-enrich
  2 bad CLI usage
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
_WEB = _REPO_ROOT / "web_dashboard"
for path in (_REPO_ROOT, _WEB):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

logger = logging.getLogger("yt_reenrich")

# Labels carry U+200B, which a cp1252 Windows console cannot encode.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass


def _load_rows(article_id: str | None) -> list[dict[str, Any]]:
    from postgres_client import PostgresClient
    from yt_articles import ARTICLE_TYPE

    sql = """
        SELECT id, title, content, tickers, summary, relevance_score, source_metadata
        FROM research_articles
        WHERE article_type = %s
    """
    params: list[Any] = [ARTICLE_TYPE]
    if article_id:
        sql += " AND id = %s"
        params.append(article_id)
    sql += " ORDER BY id"
    return [dict(r) for r in PostgresClient().execute_query(sql, tuple(params))]


def _metadata(row: dict[str, Any]) -> dict[str, Any]:
    meta = row.get("source_metadata") or {}
    if isinstance(meta, str):
        import json

        try:
            meta = json.loads(meta)
        except Exception:
            meta = {}
    return meta if isinstance(meta, dict) else {}


def _expected_tickers_for(meta: dict[str, Any]) -> list[str]:
    """The source row's registered tickers, needed only for issuer channels."""
    source_id = meta.get("youtube_source_id")
    if source_id is None:
        return []
    from postgres_client import PostgresClient

    rows = PostgresClient().execute_query(
        "SELECT expected_tickers FROM youtube_sources WHERE id = %s", (int(source_id),)
    )
    if not rows:
        return []
    return [str(t).upper().strip() for t in (rows[0]["expected_tickers"] or [])]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Re-summarize stored YouTube transcripts (no caption quota cost)"
    )
    parser.add_argument(
        "--apply", action="store_true", help="Write changes (default is a dry run)"
    )
    parser.add_argument(
        "--prune-thin",
        action="store_true",
        help="Delete rows whose body is below YOUTUBE_TRANSCRIPT_MIN_CHARS",
    )
    parser.add_argument("--article-id", help="Limit to one research_articles row")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    from dotenv import load_dotenv

    load_dotenv(_REPO_ROOT / ".env")

    from postgres_client import PostgresClient
    from research_repository import ResearchRepository
    from yt_articles import content_min_chars, enrich_saved_transcript, is_issuer_channel

    try:
        rows = _load_rows(args.article_id)
    except Exception as exc:
        logger.error("Could not load transcript rows: %s", exc)
        return 1

    if not rows:
        print("No YouTube Transcript rows matched.")
        return 0

    floor = content_min_chars()
    thin = [r for r in rows if len(r.get("content") or "") < floor]
    keep = [r for r in rows if len(r.get("content") or "") >= floor]

    print(f"\n{len(rows)} transcript row(s); floor={floor} chars")
    print(f"  {len(keep)} to re-enrich, {len(thin)} below floor\n")

    for row in thin:
        action = "DELETE" if args.prune_thin else "skip (use --prune-thin to remove)"
        print(f"  [thin {len(row.get('content') or '')}c] {row['title'][:52]!r} -> {action}")

    for row in keep:
        meta = _metadata(row)
        issuer = is_issuer_channel(meta)
        print(
            f"  [{len(row.get('content') or ''):>6}c] {str(row['title'])[:44]!r}\n"
            f"        mechanism={meta.get('alpha_mechanism') or '-'} "
            f"issuer={issuer} current_tickers={row.get('tickers')}"
        )

    if not args.apply:
        print("\nDry run — nothing written. Re-run with --apply.")
        return 0

    # Same holdings-scoped relevance input the ingest path uses, so re-scored
    # rows are comparable to freshly landed ones.
    from yt_article_ingest import _production_holdings

    owned = _production_holdings()

    repo = ResearchRepository()
    failures = 0

    if args.prune_thin and thin:
        client = PostgresClient()
        for row in thin:
            try:
                client.execute_update(
                    "DELETE FROM research_articles WHERE id = %s", (row["id"],)
                )
                print(f"deleted thin row {row['id']}")
            except Exception as exc:
                failures += 1
                logger.error("Delete failed for %s: %s", row["id"], exc)

    for row in keep:
        meta = _metadata(row)
        issuer = is_issuer_channel(meta)
        expected = _expected_tickers_for(meta) if issuer else []
        try:
            result = enrich_saved_transcript(
                research_repo=repo,
                article_id=str(row["id"]),
                title=str(row.get("title") or ""),
                content=str(row.get("content") or ""),
                expected_tickers=expected,
                owned_tickers=owned,
                duration_s=meta.get("duration_s"),
                issuer_channel=issuer,
            )
            print(
                f"re-enriched {row['id']}: {row.get('tickers')} -> {result.tickers} "
                f"(relevance {row.get('relevance_score')} -> {result.relevance_score})"
            )
        except Exception as exc:
            failures += 1
            logger.error("Re-enrich failed for %s: %s", row["id"], exc)

    print(f"\nDone. {len(keep) - failures} re-enriched, {failures} failed.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
