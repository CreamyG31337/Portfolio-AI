#!/usr/bin/env python3
"""
Dry-run test: AI ticker inference on articles with no explicit ticker symbols.

This script does NOT write to the database. It samples recent research_articles
with missing tickers, filters to items that do not contain obvious ticker
symbols in the text, and runs AI summarization to inspect inferred tickers.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from dotenv import load_dotenv

# Ensure project root imports work when run from repo root.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
WEB_DASHBOARD_ROOT = PROJECT_ROOT / "web_dashboard"
if str(WEB_DASHBOARD_ROOT) not in sys.path:
    sys.path.insert(0, str(WEB_DASHBOARD_ROOT))

from web_dashboard.ollama_client import check_ollama_health, generate_summary
from web_dashboard.postgres_client import PostgresClient
from web_dashboard.ticker_inference import infer_tickers_from_companies, infer_tickers_from_text


EXPLICIT_TICKER_RE = re.compile(r"(?:\$[A-Z]{1,5}(?:\.[A-Z]{1,3})?\b)|(?:\b[A-Z]{1,5}(?:\.[A-Z]{1,3})?\b)")


def has_explicit_ticker(text: str) -> bool:
    if not text:
        return False
    return bool(EXPLICIT_TICKER_RE.search(text))


def main() -> int:
    load_dotenv("web_dashboard/.env")

    if not check_ollama_health():
        print("[ERROR] Ollama is not reachable. Start Ollama first.")
        return 1

    client = PostgresClient()
    rows = client.execute_query(
        """
        SELECT id, title, article_type, content, fetched_at
        FROM research_articles
        WHERE (tickers IS NULL OR cardinality(tickers) = 0)
          AND content IS NOT NULL
          AND LENGTH(content) > 800
        ORDER BY fetched_at DESC
        LIMIT 250
        """
    )

    candidates = []
    for row in rows:
        content = row.get("content") or ""
        if not has_explicit_ticker(content):
            candidates.append(row)
        if len(candidates) >= 8:
            break

    if not candidates:
        print("[INFO] No suitable no-explicit-ticker candidates found.")
        return 0

    print(f"[INFO] Testing {len(candidates)} no-explicit-ticker research articles...")
    inferred_non_empty = 0

    for idx, row in enumerate(candidates, start=1):
        article_id = row.get("id")
        title = (row.get("title") or "").strip().replace("\n", " ")
        article_type = (row.get("article_type") or "").strip()
        content = row.get("content") or ""

        print("")
        print(f"[{idx}] id={article_id}")
        print(f"    type={article_type or 'N/A'}")
        print(f"    title={title[:120]}")

        summary_input = f"Title: {title}\n\n{content}" if title else content
        result = generate_summary(summary_input, article_type=article_type)
        if not isinstance(result, dict):
            print("    inferred_tickers=[] (invalid AI response)")
            continue

        tickers = result.get("tickers") or []
        companies = result.get("companies") or []
        company_ticker_fallback = infer_tickers_from_companies(companies)
        title_fallback = infer_tickers_from_text(title)
        effective = sorted(set(tickers) | set(company_ticker_fallback) | set(title_fallback))
        print(f"    ai_tickers={tickers}")
        print(f"    company_fallback={company_ticker_fallback}")
        print(f"    title_fallback={title_fallback}")
        print(f"    effective_tickers={effective}")
        if companies:
            print(f"    companies_sample={companies[:5]}")

        if effective:
            inferred_non_empty += 1

    print("")
    print(
        f"[RESULT] research_articles: inferred tickers for {inferred_non_empty}/{len(candidates)} "
        "no-explicit-ticker items"
    )

    newsletter_rows = client.execute_query(
        """
        SELECT id, subject, body_plain, body_html, received_at
        FROM newsletters
        WHERE (tickers IS NULL OR cardinality(tickers) = 0)
          AND (
            (body_plain IS NOT NULL AND LENGTH(body_plain) > 400)
            OR (body_html IS NOT NULL AND LENGTH(body_html) > 800)
          )
        ORDER BY received_at DESC
        LIMIT 250
        """
    )

    newsletter_candidates = []
    for row in newsletter_rows:
        body_plain = row.get("body_plain") or ""
        body_html = row.get("body_html") or ""
        text = body_plain if body_plain else body_html
        if not has_explicit_ticker(text):
            newsletter_candidates.append(row)
        if len(newsletter_candidates) >= 8:
            break

    if not newsletter_candidates:
        print("[INFO] No suitable no-explicit-ticker newsletters found.")
        return 0

    print("")
    print(f"[INFO] Testing {len(newsletter_candidates)} no-explicit-ticker newsletters...")
    newsletter_inferred_non_empty = 0

    for idx, row in enumerate(newsletter_candidates, start=1):
        nl_id = row.get("id")
        subject = (row.get("subject") or "").strip().replace("\n", " ")
        body_plain = row.get("body_plain") or ""
        body_html = row.get("body_html") or ""
        text = body_plain if body_plain else body_html

        print("")
        print(f"[N{idx}] id={nl_id}")
        print(f"     subject={subject[:120]}")

        result = generate_summary(text, article_type="Newsletter")
        if not isinstance(result, dict):
            print("     inferred_tickers=[] (invalid AI response)")
            continue

        tickers = result.get("tickers") or []
        companies = result.get("companies") or []
        company_ticker_fallback = infer_tickers_from_companies(companies)
        title_fallback = infer_tickers_from_text(subject)
        effective = sorted(set(tickers) | set(company_ticker_fallback) | set(title_fallback))
        print(f"     ai_tickers={tickers}")
        print(f"     company_fallback={company_ticker_fallback}")
        print(f"     title_fallback={title_fallback}")
        print(f"     effective_tickers={effective}")
        if companies:
            print(f"     companies_sample={companies[:5]}")

        if effective:
            newsletter_inferred_non_empty += 1

    print("")
    print(
        f"[RESULT] newsletters: inferred tickers for {newsletter_inferred_non_empty}/{len(newsletter_candidates)} "
        "no-explicit-ticker items"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
