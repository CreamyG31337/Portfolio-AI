#!/usr/bin/env python3
"""
Evaluate ticker inference quality on a batch of recent articles.

This is read-only: it does not write to the database.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Dict, List, Set

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
WEB_DASHBOARD_ROOT = PROJECT_ROOT / "web_dashboard"
if str(WEB_DASHBOARD_ROOT) not in sys.path:
    sys.path.insert(0, str(WEB_DASHBOARD_ROOT))

from web_dashboard.ollama_client import check_ollama_health, generate_summary
from web_dashboard.postgres_client import PostgresClient
from web_dashboard.research_utils import validate_ticker_format
from web_dashboard.ticker_inference import infer_tickers_from_companies, infer_tickers_from_text
from web_dashboard.ticker_utils import get_all_unique_tickers


ACCESS_DENIED_WHERE = """
(
    COALESCE(title,'') ILIKE '%access to this page has been denied%'
 OR COALESCE(content,'') ILIKE '%access to this page has been denied%'
 OR COALESCE(content,'') ILIKE '%before we continue%'
 OR COALESCE(content,'') ILIKE '%press & hold to confirm you are a human%'
 OR COALESCE(content,'') ILIKE '%press and hold to confirm you are a human%'
 OR COALESCE(content,'') ILIKE '%checking your browser before accessing%'
 OR COALESCE(content,'') ILIKE '%verify you are human%'
 OR COALESCE(content,'') ILIKE '%please enable javascript and cookies to continue%'
 OR COALESCE(content,'') ILIKE '%cf-chl-%'
)
"""

def safe_text(value: str) -> str:
    try:
        value.encode("cp1252")
        return value
    except Exception:
        return value.encode("ascii", "ignore").decode("ascii")


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate AI ticker inference quality on recent articles")
    parser.add_argument("--limit", type=int, default=25, help="Number of articles to evaluate")
    parser.add_argument("--days", type=int, default=21, help="Lookback window in days")
    args = parser.parse_args()

    load_dotenv("web_dashboard/.env")

    if not check_ollama_health():
        print("[ERROR] Ollama not reachable.")
        return 1

    client = PostgresClient()
    known_universe: Set[str] = set(get_all_unique_tickers() or [])

    days = max(1, int(args.days))
    limit = max(1, int(args.limit))

    query = f"""
    SELECT id, title, article_type, content, fetched_at
    FROM research_articles
    WHERE (tickers IS NULL OR cardinality(tickers) = 0)
      AND fetched_at >= NOW() - INTERVAL '{days} days'
      AND content IS NOT NULL
      AND LENGTH(content) > 500
      AND NOT {ACCESS_DENIED_WHERE}
    ORDER BY fetched_at DESC
    LIMIT {limit}
    """
    rows = client.execute_query(query)
    if not rows:
        print("[INFO] No eligible rows found.")
        return 0

    print(f"[INFO] Evaluating {len(rows)} articles from last {args.days} days")

    inferred_any = 0
    total_tickers = 0
    known_tickers = 0
    invalid_tickers = 0
    unknown_counter: Counter[str] = Counter()
    per_article: List[Dict[str, object]] = []

    for i, row in enumerate(rows, start=1):
        article_id = row["id"]
        title = (row.get("title") or "").strip().replace("\n", " ")
        article_type = (row.get("article_type") or "").strip()
        content = row.get("content") or ""
        summary_input = f"Title: {title}\n\n{content}" if title else content

        result = generate_summary(summary_input, article_type=article_type)
        if not isinstance(result, dict):
            result = {}

        ai_tickers = [t for t in (result.get("tickers") or []) if isinstance(t, str)]
        company_fallback = infer_tickers_from_companies(result.get("companies") or [])
        title_fallback = infer_tickers_from_text(title)
        effective = sorted(set(ai_tickers) | set(company_fallback) | set(title_fallback))

        valid_effective: List[str] = []
        for t in effective:
            if validate_ticker_format(t):
                valid_effective.append(t.upper())
            else:
                invalid_tickers += 1

        effective = sorted(set(valid_effective))
        if effective:
            inferred_any += 1

        for t in effective:
            total_tickers += 1
            if t in known_universe:
                known_tickers += 1
            else:
                unknown_counter[t] += 1

        per_article.append(
            {
                "id": article_id,
                "title": title[:120],
                "article_type": article_type or "N/A",
                "tickers": effective,
            }
        )

        print(f"[{i:02d}] {safe_text(article_type or 'N/A')} | {safe_text(title[:90])}")
        print(f"     -> {safe_text(str(effective))}")

    coverage_pct = (inferred_any / len(rows) * 100.0) if rows else 0.0
    known_pct = (known_tickers / total_tickers * 100.0) if total_tickers else 0.0
    avg_per_article = (total_tickers / len(rows)) if rows else 0.0

    print("")
    print("=" * 72)
    print("[SUMMARY]")
    print(f"articles_evaluated={len(rows)}")
    print(f"with_any_ticker={inferred_any} ({coverage_pct:.1f}%)")
    print(f"total_inferred_tickers={total_tickers}")
    print(f"avg_tickers_per_article={avg_per_article:.2f}")
    print(f"known_universe_tickers={known_tickers}/{total_tickers} ({known_pct:.1f}%)")
    print(f"invalid_tickers_filtered={invalid_tickers}")
    if unknown_counter:
        top_unknown = ", ".join([f"{k}:{v}" for k, v in unknown_counter.most_common(10)])
        print(f"top_unknown_tickers={top_unknown}")
    else:
        print("top_unknown_tickers=none")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
