#!/usr/bin/env python3
"""
Backfill script to extract tickers for articles where they are missing.
Re-processes content using Ollama and updates the database.
"""

import sys
import json
import logging
from pathlib import Path
from typing import Tuple, List, Dict, Any

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from web_dashboard.postgres_client import PostgresClient
from web_dashboard.ollama_client import get_ollama_client, check_ollama_health
from web_dashboard.research_repository import ResearchRepository
from web_dashboard.research_utils import validate_ticker_in_content, validate_ticker_format
from dotenv import load_dotenv

# Setup minimal logging to console
logging.basicConfig(
    level=logging.INFO,
    format='%(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# Load environment
load_dotenv("web_dashboard/.env")


def backfill_tickers(
    max_articles: int = None,
    stop_on_failures: int = 3,
    min_success_rate: float = 0.5,
    model: str = None
) -> None:
    """Backfill missing tickers for existing articles.
    
    Args:
        max_articles: Maximum number of articles to process (None = all)
        stop_on_failures: Stop after N consecutive failures
        min_success_rate: Minimum success rate to continue (0.0 to 1.0)
        model: Model to use (None = use default from settings)
    """
    print("=" * 80)
    print("Ticker Extraction Backfill")
    print("=" * 80)
    
    # Check Ollama
    if not check_ollama_health():
        print("[ERROR] Ollama is not available. Please start Ollama first.")
        return
    
    # Initialize clients
    try:
        repo = ResearchRepository()
        ollama_client = get_ollama_client()
        if not ollama_client:
            print("[ERROR] Failed to initialize Ollama client")
            return
    except Exception as e:
        print(f"[ERROR] Error initializing clients: {e}")
        return
    
    # Get model
    if model is None:
        try:
            from web_dashboard.settings import get_summarizing_model
            model = get_summarizing_model()
        except Exception:
            model = "llama3.2:3b"
    
    print(f"[INFO] Using model: {model}")
    
    # Get articles needing analysis
    # Criteria: tickers is NULL OR empty array, and content is available
    print("\n[INFO] Finding articles needing ticker extraction...")
    query = """
        SELECT id, title, content, summary, sector 
        FROM research_articles 
        WHERE (tickers IS NULL OR cardinality(tickers) = 0)
          AND content IS NOT NULL 
          AND LENGTH(content) > 200
        ORDER BY fetched_at DESC
    """
    
    if max_articles:
        query += f" LIMIT {max_articles}"
    
    articles = repo.client.execute_query(query)
    
    if not articles:
        print("[OK] No articles need backfilling. All articles seemingly have tickers (or are too short).")
        return
    
    print(f"[INFO] Found {len(articles)} articles to process")
    print(f"[INFO] Settings: stop after {stop_on_failures} failures")
    
    # Process articles
    success_count = 0
    fail_count = 0
    no_tickers_count = 0
    consecutive_failures = 0
    
    for i, article in enumerate(articles, 1):
        article_id = article['id']
        title = article.get('title', 'Untitled')[:60]
        content = article.get('content', '')
        
        # Safe title printing
        try:
            title_display = title
            print(f"\n[{i}/{len(articles)}] Processing: {title_display}...")
        except UnicodeEncodeError:
            print(f"\n[{i}/{len(articles)}] Processing article ID {article_id}...")
        
        # Generate analysis
        try:
            summary_data = ollama_client.generate_summary(content, model=model)
            
            if not summary_data or not isinstance(summary_data, dict):
                print(f"   [ERROR] Invalid response from Ollama")
                fail_count += 1
                consecutive_failures += 1
                continue
            
            # Extract tickers with real-company validation
            from web_dashboard.ticker_validator import extract_and_validate_tickers
            extracted_tickers = extract_and_validate_tickers(
                summary_data, title, content,
            )
            
            # Extract sector if missing
            extracted_sector = summary_data.get("sectors", [])[0] if summary_data.get("sectors") else article.get('sector')
            
            # Update article
            # Note: We must update at least one field for this to work.
            # If we didn't find any tickers, saving None/empty is fine, but we should log it.
            
            update_success = repo.update_article_analysis(
                article_id=article_id,
                # Preserve existing summary if new one is empty? No, generate_summary creates a new one.
                summary=summary_data.get("summary", article.get("summary")),
                tickers=extracted_tickers if extracted_tickers else None,
                sector=extracted_sector,
                # Also update CoT fields if available, why not
                claims=summary_data.get("claims"),
                fact_check=summary_data.get("fact_check"),
                conclusion=summary_data.get("conclusion"),
                sentiment=summary_data.get("sentiment"),
                sentiment_score=summary_data.get("sentiment_score"),
                logic_check=summary_data.get("logic_check")
            )
            
            if update_success:
                if extracted_tickers:
                    print(f"   [OK] Found tickers: {extracted_tickers}")
                    success_count += 1
                else:
                    print(f"   [WARN] No tickers found ensuring validation.")
                    no_tickers_count += 1
                    success_count += 1 # Technically a success execution, just no tickers found
                
                consecutive_failures = 0
            else:
                print(f"   [ERROR] Database update failed")
                fail_count += 1
                consecutive_failures += 1
            
            # Safety stop
            if consecutive_failures >= stop_on_failures:
                print(f"\n[WARN] Stopping: {consecutive_failures} consecutive failures")
                break
                
        except Exception as e:
            print(f"   [ERROR] Exception: {e}")
            fail_count += 1
            consecutive_failures += 1
            if consecutive_failures >= stop_on_failures:
                break
    
    # Summary
    print("\n" + "=" * 80)
    print("Backfill Summary")
    print("=" * 80)
    print(f"[OK] Articles Updated: {success_count}")
    print(f"     - With Tickers: {success_count - no_tickers_count}")
    print(f"     - Without Tickers: {no_tickers_count}")
    print(f"[FAIL] Failed: {fail_count}")
    print("=" * 80)


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Backfill tickers for existing articles")
    parser.add_argument(
        "--max",
        type=int,
        default=None,
        help="Maximum number of articles to process"
    )
    parser.add_argument(
        "--stop-failures",
        type=int,
        default=3,
        help="Stop after N consecutive failures"
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Model to use (default: from settings)"
    )
    
    args = parser.parse_args()
    
    backfill_tickers(
        max_articles=args.max,
        stop_on_failures=args.stop_failures,
        model=args.model
    )
