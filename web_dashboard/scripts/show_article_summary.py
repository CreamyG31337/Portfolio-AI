#!/usr/bin/env python3
"""Show article summary from database"""
import os
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / 'web_dashboard'))

from dotenv import load_dotenv
env_path = project_root / 'web_dashboard' / '.env'
if env_path.exists():
    load_dotenv(env_path)
else:
    load_dotenv()

from postgres_client import PostgresClient

client = PostgresClient()

# Query for Bright Minds article
result = client.execute_query("""
    SELECT id, title, summary
    FROM research_articles
    WHERE title ILIKE '%Bright Minds%'
    ORDER BY fetched_at DESC
    LIMIT 1
""")

if result:
    article = result[0]
    summary = article['summary']
    print(f"ID: {article['id']}")
    print(f"Title: {article['title']}")
    print(f"\nFirst 300 chars (repr to see exact whitespace):")
    print(repr(summary[:300]))
    print(f"\nFirst line characters (hex):")
    first_line = summary.split('\n')[0] if summary else ''
    for i, char in enumerate(first_line[:50]):
        if char in ' \t':
            print(f"  [{i}] '{char}' (space)" if char == ' ' else f"  [{i}] '{char}' (tab)")
        else:
            print(f"  [{i}] '{char}'")
    print(f"\nFirst line starts with whitespace: {first_line and first_line[0] in ' \t'}")
else:
    print("No Bright Minds article found")
