#!/usr/bin/env python3
"""Quick script to check remaining ETF Change articles"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from research_repository import ResearchRepository

repo = ResearchRepository()
articles = repo.client.execute_query("""
    SELECT title, summary, fetched_at
    FROM research_articles
    WHERE article_type = 'ETF Change'
    ORDER BY fetched_at DESC
""")

print(f"Remaining ETF Change articles: {len(articles)}\n")
for a in articles:
    print(f"  - {a['title']}: {a['summary']} ({a['fetched_at']})")
