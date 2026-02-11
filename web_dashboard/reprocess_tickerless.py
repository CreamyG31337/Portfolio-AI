#!/usr/bin/env python3
"""
Reprocess Tickerless Articles
==============================

Interactive script to reprocess articles that have no tickers.
Uses GLM 4.5-air to determine:
  1. Is this article genuinely about finance/stocks/investing?
  2. If yes, what tickers should it be tagged with?

Articles that are NOT finance-related (error pages, movie reviews, recipes, etc.)
are flagged for deletion.

Run:  python reprocess_tickerless.py
"""

import json
import logging
import os
import sys
import time
from pathlib import Path

# Fix Windows console encoding for Unicode output
if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Path setup
web_dir = Path(__file__).resolve().parent
if str(web_dir) not in sys.path:
    sys.path.insert(0, str(web_dir))
project_root = str(web_dir.parent)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

import requests
from dotenv import load_dotenv

# Load .env from web_dashboard and project root
load_dotenv(web_dir / ".env")
load_dotenv(web_dir.parent / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# Suppress noisy HTTP request logs from httpx/supabase
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
BATCH_SIZE = 10
GLM_MODEL = "glm-4.5-air"
GLM_MAX_TOKENS = 8192
GLM_TIMEOUT = 120

# ---------------------------------------------------------------------------
# GLM prompt -- the key piece
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = (
    "You are a financial data quality analyst reviewing articles scraped from "
    "the web. Your job is to classify each article and extract stock ticker "
    "symbols ONLY when the article is genuinely about publicly traded companies, "
    "financial markets, investing, or related topics.\n\n"
    "Return ONLY valid JSON, no markdown fences or explanation."
)

def build_user_prompt(articles: list[dict]) -> str:
    """Build the numbered prompt for a batch of articles."""
    lines = []
    for idx, art in enumerate(articles, start=1):
        title = (art.get("title") or "Untitled")[:200]
        # Use first 600 chars of content to give GLM enough context
        content = (art.get("content") or art.get("summary") or "")[:600]
        content = content.replace("\n", " ").strip()
        source = art.get("source") or "unknown"
        lines.append(f'{idx}. Source: {source} | Title: "{title}"\n   Content: {content}')

    article_list = "\n\n".join(lines)

    return (
        "Below are articles that currently have NO ticker symbols assigned.\n"
        "For each article, you must decide:\n\n"
        "A) Is this article GENUINELY about finance, stock markets, publicly traded "
        "companies, investing, IPOs, earnings, M&A, economic data, commodities, "
        "crypto, or other financial topics?\n\n"
        "B) If YES: extract the relevant stock ticker symbols (US exchanges preferred, "
        "but include TSX/ASX/etc. if that's the primary listing). Only include tickers "
        "for companies that are a MAIN SUBJECT of the article, not passing mentions.\n\n"
        "C) If NO: the article is junk (error page, access denied, movie/TV review, "
        "recipe, sports, entertainment gossip, product review unrelated to stocks, "
        "clickbait with no financial content, etc.) -- return \"JUNK\" for it.\n\n"
        "IMPORTANT RULES:\n"
        "- A company name appearing in a non-financial context does NOT make it financial. "
        "Example: an article reviewing Netflix shows is NOT about NFLX stock.\n"
        "- Error pages, access denied pages, cookie notices are JUNK.\n"
        "- Articles about a company's PRODUCTS (new iPhone features) are only financial "
        "if they discuss stock price, revenue, earnings, market impact, or investor perspective.\n"
        "- Press releases about company operations, partnerships, contracts, FDA approvals, "
        "new products WITH business/market implications ARE financial.\n"
        "- Macro economic news (GDP, interest rates, jobs data) is financial even without tickers.\n"
        "  For macro news with no specific company, return an empty ticker list [].\n\n"
        f"Articles:\n\n{article_list}\n\n"
        "Return a JSON object mapping article number to either:\n"
        '  - A list of ticker symbols: {"1": ["AAPL", "MSFT"]}\n'
        '  - An empty list for financial articles with no specific tickers: {"2": []}\n'
        '  - The string "JUNK" for non-financial content: {"3": "JUNK"}\n\n'
        "Example response:\n"
        '{"1": ["TSLA"], "2": "JUNK", "3": [], "4": ["AMZN", "WMT"], "5": "JUNK"}'
    )


def call_glm(prompt: str, api_key: str, base_url: str) -> dict | None:
    """Call GLM and parse JSON response."""
    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": GLM_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.0,
        "max_tokens": GLM_MAX_TOKENS,
    }

    for attempt in range(3):
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=GLM_TIMEOUT)
            if resp.status_code == 429:
                delay = 10 * (2 ** attempt)
                logger.warning("Rate limited. Waiting %ds...", delay)
                time.sleep(delay)
                continue
            resp.raise_for_status()

            data = resp.json()
            choices = data.get("choices") or []
            if not choices:
                logger.warning("GLM returned empty choices")
                return None

            content = (choices[0].get("message") or {}).get("content", "")
            if not content:
                logger.warning("GLM returned empty content (reasoning model token issue?)")
                return None

            content = content.strip()
            if content.startswith("```"):
                content = content.split("\n", 1)[-1] if "\n" in content else content
                if content.endswith("```"):
                    content = content[:-3]
                content = content.strip()

            result = json.loads(content)
            if isinstance(result, dict):
                return result
            logger.warning("GLM returned non-dict: %s", type(result))
            return None

        except json.JSONDecodeError as e:
            logger.warning("JSON parse failed: %s\nRaw: %s", e, content[:500])
            return None
        except requests.exceptions.Timeout:
            logger.warning("Timeout (attempt %d)", attempt + 1)
            if attempt < 2:
                time.sleep(10)
                continue
            return None
        except Exception as e:
            logger.warning("GLM call failed: %s", e)
            return None

    return None


def fetch_tickerless_articles(pg, limit: int = 10, offset: int = 0) -> list[dict]:
    """Fetch articles with no tickers that haven't been validated yet."""
    return pg.execute_query("""
        SELECT id, title, content, summary, source, article_type, url,
               fetched_at
        FROM research_articles
        WHERE (tickers IS NULL OR tickers = '{}')
          AND ticker_validated_at IS NULL
          AND article_type NOT IN ('ETF Change', 'ETF Analysis')
          AND content IS NOT NULL
          AND LENGTH(content) > 50
        ORDER BY fetched_at DESC
        LIMIT %s OFFSET %s
    """, (limit, offset))


def apply_results(pg, articles: list[dict], glm_result: dict) -> dict:
    """Apply GLM results. Returns stats dict."""
    stats = {"assigned": 0, "junk": 0, "macro": 0, "skipped": 0}

    for idx, art in enumerate(articles, start=1):
        article_id = str(art["id"])
        title = (art.get("title") or "")[:80]
        result = glm_result.get(str(idx))

        if result is None:
            logger.warning("  %d. NO RESULT from GLM: %s", idx, title)
            stats["skipped"] += 1
            continue

        if result == "JUNK":
            logger.info("  %d. 🗑️  JUNK: %s", idx, title)
            # Mark as junk by setting relevance_score very low + validated
            pg.execute_update("""
                UPDATE research_articles
                SET relevance_score = 0.05,
                    ticker_validated_at = NOW()
                WHERE id = %s
            """, (article_id,))
            stats["junk"] += 1

        elif isinstance(result, list):
            if result:
                # Validate tickers through our new validator
                try:
                    from ticker_validator import validate_extracted_tickers
                    content = art.get("content") or art.get("summary") or ""
                    validated = validate_extracted_tickers(
                        tickers=result,
                        companies=[],
                        article_text=f"{title}\n{content}",
                        strict=True,
                    )
                except Exception:
                    validated = result

                validated = [t.upper().strip() for t in validated if t.strip()]

                if validated:
                    logger.info("  %d. ✅ TICKERS %s: %s", idx, validated, title)
                    pg.execute_update("""
                        UPDATE research_articles
                        SET tickers = %s,
                            ticker_validated_at = NOW()
                        WHERE id = %s
                    """, (validated, article_id))
                    stats["assigned"] += 1
                else:
                    logger.info(
                        "  %d. ⚠️  GLM said %s but validator rejected all: %s",
                        idx, result, title,
                    )
                    pg.execute_update("""
                        UPDATE research_articles
                        SET ticker_validated_at = NOW()
                        WHERE id = %s
                    """, (article_id,))
                    stats["macro"] += 1
            else:
                # Empty list = financial but no specific tickers (macro news)
                logger.info("  %d. 📊 MACRO (no tickers): %s", idx, title)
                pg.execute_update("""
                    UPDATE research_articles
                    SET ticker_validated_at = NOW()
                    WHERE id = %s
                """, (article_id,))
                stats["macro"] += 1
        else:
            logger.warning("  %d. UNEXPECTED type %s: %s", idx, type(result), title)
            stats["skipped"] += 1

    return stats


def main(max_batches: int = 1):
    from postgres_client import PostgresClient
    from glm_config import get_zhipu_api_key, ZHIPU_BASE_URL

    api_key = get_zhipu_api_key()
    if not api_key:
        print("ERROR: No GLM API key. Set ZHIPU_API_KEY or configure in AI Settings.")
        return

    pg = PostgresClient()

    # Count total unprocessed
    count_row = pg.execute_query("""
        SELECT COUNT(*) as cnt FROM research_articles
        WHERE (tickers IS NULL OR tickers = '{}')
          AND ticker_validated_at IS NULL
          AND article_type NOT IN ('ETF Change', 'ETF Analysis')
          AND content IS NOT NULL
          AND LENGTH(content) > 50
    """)
    total = count_row[0]["cnt"] if count_row else 0
    print(f"\n{'='*70}")
    print(f"Tickerless articles to reprocess: {total}")
    print(f"{'='*70}\n")

    if total == 0:
        print("Nothing to do!")
        return

    batch_num = 0
    total_stats = {"assigned": 0, "junk": 0, "macro": 0, "skipped": 0}
    offset = 0
    problem_ids: list[str] = []

    while True:
        batch_num += 1
        print(f"\n--- Batch {batch_num} (offset {offset}) ---")

        articles = fetch_tickerless_articles(pg, limit=BATCH_SIZE, offset=0)
        # Note: offset=0 because we're modifying rows as we go (validated ones
        # won't appear in the next query)

        if not articles:
            print("No more articles to process!")
            break

        print(f"Processing {len(articles)} articles...")
        for idx, art in enumerate(articles, start=1):
            title = (art.get("title") or "")[:80]
            source = art.get("source") or "?"
            print(f"  {idx}. [{source}] {title}")

        prompt = build_user_prompt(articles)
        print(f"\nCalling GLM ({GLM_MODEL})...")
        start = time.time()
        result = call_glm(prompt, api_key, ZHIPU_BASE_URL)
        elapsed = time.time() - start
        print(f"GLM responded in {elapsed:.1f}s")

        if result is None:
            print("GLM FAILED for this batch. Skipping...")
            # Mark these as validated so we don't loop on them
            for art in articles:
                pg.execute_update(
                    "UPDATE research_articles SET ticker_validated_at = NOW() WHERE id = %s",
                    (str(art["id"]),),
                )
            continue

        print(f"\nResults:")
        stats = apply_results(pg, articles, result)
        for k, v in stats.items():
            total_stats[k] += v

        print(f"\nBatch stats: {stats}")
        print(f"Running totals: {total_stats}")

        # Track any articles that got unexpected results for manual review
        for idx, art in enumerate(articles, start=1):
            res = result.get(str(idx))
            if res is None or (isinstance(res, list) and not res):
                pass  # macro or skipped -- fine
            elif res == "JUNK":
                pass  # expected
            elif isinstance(res, list) and res:
                pass  # got tickers
            else:
                problem_ids.append(str(art["id"]))

        # Ask to continue
        remaining = pg.execute_query("""
            SELECT COUNT(*) as cnt FROM research_articles
            WHERE (tickers IS NULL OR tickers = '{}')
              AND article_type NOT IN ('ETF Change', 'ETF Analysis')
              AND content IS NOT NULL
              AND LENGTH(content) > 50
              AND ticker_validated_at IS NULL
        """)
        remaining_count = remaining[0]["cnt"] if remaining else 0
        print(f"\nRemaining unprocessed: {remaining_count}")

        if remaining_count == 0:
            print("All done!")
            break

        if max_batches > 0 and batch_num >= max_batches:
            print(f"\nReached batch limit ({max_batches}). Stopping.")
            break

        # Auto-continue (no interactive prompt in batch mode)
        time.sleep(2)

    print(f"\n{'='*70}")
    print(f"FINAL TOTALS: {total_stats}")
    if problem_ids:
        print(f"Problem article IDs: {problem_ids}")
    print(f"{'='*70}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--batches", type=int, default=1,
                        help="Number of batches to run (default: 1)")
    args = parser.parse_args()
    main(max_batches=args.batches)
