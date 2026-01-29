#!/usr/bin/env python3
"""
Cleanup Mislabeled Research Articles
=====================================

One-time script: finds research articles tagged with tickers that do not appear
in the article content, reports them, and optionally deletes them.

- Default: --dry-run (scan and report only, no deletes).
- Use --execute to actually delete (with confirmation prompt).
- Use --limit N to cap how many articles to scan (for testing).

Run from project root:
  python web_dashboard/scripts/cleanup_mislabeled_research_articles.py [--dry-run] [--execute] [--limit N]
"""

import argparse
import sys
from pathlib import Path
from typing import Any, List

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "web_dashboard"))

from dotenv import load_dotenv

env_path = project_root / "web_dashboard" / ".env"
if env_path.exists():
    load_dotenv(env_path)
else:
    load_dotenv()

from postgres_client import PostgresClient
from research_utils import validate_ticker_in_content


def _safe_display(s: str, max_len: int = 70) -> str:
    """Return a string safe for Windows console (avoids UnicodeEncodeError)."""
    if s is None:
        return ""
    s = str(s).strip()[:max_len]
    try:
        s.encode(sys.stdout.encoding or "utf-8")
        return s
    except (UnicodeEncodeError, TypeError):
        return s.encode("ascii", "replace").decode("ascii")


def _normalize_tickers(article: dict) -> List[str]:
    """Build list of ticker strings from article (tickers array or legacy ticker column)."""
    tickers: List[str] = []
    if article.get("tickers"):
        raw = article["tickers"]
        if isinstance(raw, list):
            for t in raw:
                if t is not None and str(t).strip():
                    tickers.append(str(t).strip().upper())
        elif raw is not None and str(raw).strip():
            tickers.append(str(raw).strip().upper())
    if not tickers and article.get("ticker"):
        t = article["ticker"]
        if t is not None and str(t).strip():
            tickers.append(str(t).strip().upper())
    return tickers


def _text_to_check(article: dict) -> str:
    """Content for validation: content if present, else title + summary."""
    content = article.get("content")
    if content and isinstance(content, str) and content.strip():
        return content
    title = article.get("title") or ""
    summary = article.get("summary") or ""
    return f"{title} {summary}".strip()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Find and optionally delete research articles tagged with tickers not in content."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Only scan and report; do not delete (default).",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually delete mislabeled articles after confirmation.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Cap number of articles to scan (for testing).",
    )
    # --execute turns off dry-run
    args = parser.parse_args()
    dry_run = not args.execute

    print("=" * 70)
    print("Cleanup Mislabeled Research Articles")
    print("=" * 70)
    if dry_run:
        print("Mode: DRY-RUN (report only, no deletes)")
    else:
        print("Mode: EXECUTE (will delete after confirmation)")
    if args.limit:
        print(f"Limit: scanning at most {args.limit} articles")
    print()

    try:
        client = PostgresClient()
        print("[OK] Connected to database")
        print()

        # Fetch all articles that have at least one ticker
        query = """
            SELECT id, url, title, content, summary, tickers, ticker, source, fetched_at
            FROM research_articles
            WHERE (tickers IS NOT NULL AND array_length(tickers, 1) > 0)
               OR (ticker IS NOT NULL AND ticker != '')
            ORDER BY fetched_at DESC
        """
        if args.limit is not None:
            query += f" LIMIT {args.limit}"
        articles = client.execute_query(query)

        if not articles:
            print("[OK] No articles with tickers found. Nothing to do.")
            return

        total = len(articles)
        skipped_no_content: List[dict] = []
        to_delete: List[dict] = []

        for article in articles:
            tickers = _normalize_tickers(article)
            if not tickers:
                continue
            text = _text_to_check(article)
            if not text:
                skipped_no_content.append(article)
                continue
            # Delete only if NO tagged ticker appears in content
            if not any(validate_ticker_in_content(t, text) for t in tickers):
                to_delete.append(article)

        # Report
        print(f"Scanned: {total} article(s) with at least one ticker")
        print(f"Skipped (no content to check): {len(skipped_no_content)}")
        print(f"Would delete (no tagged ticker in content): {len(to_delete)}")
        print()

        if to_delete:
            print("Articles that would be deleted:")
            print()
            for a in to_delete:
                tickers = _normalize_tickers(a)
                print(f"  id:   {a.get('id')}")
                print(f"  url:  {_safe_display(str(a.get('url') or ''), 80)}")
                print(f"  title: {_safe_display(a.get('title') or '')}")
                print(f"  tagged tickers: {tickers}")
                if a.get("source"):
                    print(f"  source: {_safe_display(str(a['source']), 50)}")
                if a.get("fetched_at"):
                    print(f"  fetched_at: {a['fetched_at']}")
                print()
            print(f"Total: {len(to_delete)} article(s)")
            print()

            if not dry_run:
                response = input("Delete these articles? (yes/no): ").strip().lower()
                if response not in ("yes", "y"):
                    print("Cancelled. No articles deleted.")
                    return
                print()
                print("Deleting related market_relationships...")
                ids = [a["id"] for a in to_delete]
                rel_deleted = client.execute_update(
                    "DELETE FROM market_relationships WHERE source_article_id = ANY(%s)",
                    (ids,),
                )
                print(f"  Deleted {rel_deleted} relationship(s)")
                print("Deleting research_articles...")
                art_deleted = client.execute_update(
                    "DELETE FROM research_articles WHERE id = ANY(%s)",
                    (ids,),
                )
                print(f"[OK] Deleted {art_deleted} article(s)")
        else:
            print("[OK] No mislabeled articles to delete.")

    except Exception as e:
        print(f"\n[ERROR] {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
