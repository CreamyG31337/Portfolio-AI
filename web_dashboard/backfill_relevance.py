"""One-time backfill: run article_relevance_job repeatedly until all articles are validated."""
import logging
import sys
import os
import time

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'), override=False)

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')

from postgres_client import PostgresClient
from scheduler.jobs_article_relevance import article_relevance_job

pg = PostgresClient()

run = 0
while True:
    # Check how many remain
    rows = pg.execute_query("""
        SELECT COUNT(*) as remaining
        FROM research_articles
        WHERE ticker_validated_at IS NULL
          AND tickers IS NOT NULL
          AND COALESCE(article_type, '') != 'ETF Change'
    """)
    remaining = rows[0]['remaining'] if rows else 0
    
    if remaining == 0:
        print(f"\nAll articles validated! Total runs: {run}")
        break
    
    run += 1
    print(f"\n{'='*60}")
    print(f"Run {run}: {remaining} articles remaining")
    print(f"{'='*60}")
    
    article_relevance_job()
    
    # Brief pause between runs
    if remaining > 200:
        print("Pausing 5s between runs...")
        time.sleep(5)
