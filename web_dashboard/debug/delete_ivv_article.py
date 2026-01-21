#!/usr/bin/env python3
"""Delete IVV article from 2026-01-20"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from research_repository import ResearchRepository

repo = ResearchRepository()
result = repo.client.execute_query("""
    SELECT id, title, summary
    FROM research_articles
    WHERE article_type = 'ETF Change'
      AND title LIKE 'IVV Daily Holdings Update%'
      AND DATE(fetched_at) = '2026-01-20'
""")

print(f"Found {len(result)} IVV article(s) from 2026-01-20")
for r in result:
    print(f"  - {r['title']}: {r['summary']}")
    if repo.delete_article(str(r['id'])):
        print(f"    [OK] Deleted")
    else:
        print(f"    [ERROR] Failed to delete")
