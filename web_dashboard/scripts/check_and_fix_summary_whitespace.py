#!/usr/bin/env python3
"""
Check and fix research article summaries with leading whitespace
"""

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

def normalize_summary(summary: str) -> str:
    """Normalize summary by stripping leading whitespace from each line."""
    if not summary:
        return summary
    lines = summary.split('\n')
    normalized_lines = [line.lstrip() for line in lines]
    return '\n'.join(normalized_lines).strip()

def main():
    import argparse
    parser = argparse.ArgumentParser(description='Check and fix summary whitespace')
    parser.add_argument('--yes', action='store_true', help='Auto-fix without prompting')
    args = parser.parse_args()
    client = PostgresClient()
    
    # Find all articles with summaries that have leading whitespace
    print("Checking for summaries with leading whitespace...\n")
    
    # Get all summaries and check in Python (more reliable than SQL pattern matching)
    query = """
        SELECT id, title, summary
        FROM research_articles
        WHERE summary IS NOT NULL 
          AND summary != ''
        ORDER BY fetched_at DESC
        LIMIT 500
    """
    
    all_articles = client.execute_query(query)
    
    # Filter to only those with leading whitespace
    articles = []
    for article in all_articles:
        summary = article.get('summary', '')
        if summary:
            # Check if any line starts with whitespace
            lines = summary.split('\n')
            has_leading_whitespace = any(
                line and len(line) > 0 and line[0] in ' \t' 
                for line in lines
            )
            if has_leading_whitespace:
                articles.append(article)
    
    if not articles:
        print("[OK] No summaries with leading whitespace found!")
        return 0
    
    print(f"Found {len(articles)} articles with leading whitespace in summaries\n")
    
    # Show examples
    print("Examples of affected summaries:")
    print("=" * 80)
    for i, article in enumerate(articles[:5], 1):
        print(f"\n{i}. {article['title'][:60]}...")
        summary = article['summary']
        first_line = summary.split('\n')[0] if summary else ''
        print(f"   First line: {repr(first_line[:80])}")
    
    if len(articles) > 5:
        print(f"\n... and {len(articles) - 5} more")
    
    print("\n" + "=" * 80)
    
    # Ask for confirmation (unless --yes flag)
    if not args.yes:
        response = input(f"\nFix {len(articles)} summaries? (yes/no): ").strip().lower()
        if response != 'yes':
            print("Aborted.")
            return 0
    else:
        print(f"\nAuto-fixing {len(articles)} summaries...")
    
    # Fix summaries
    print("\nFixing summaries...")
    fixed_count = 0
    
    with client.get_connection() as conn:
        cursor = conn.cursor()
        
        for article in articles:
            article_id = article['id']
            original_summary = article['summary']
            normalized_summary = normalize_summary(original_summary)
            
            if normalized_summary != original_summary:
                update_query = "UPDATE research_articles SET summary = %s WHERE id = %s"
                cursor.execute(update_query, (normalized_summary, article_id))
                fixed_count += 1
        
        conn.commit()
    
    print(f"[OK] Fixed {fixed_count} summaries!")
    return 0

if __name__ == "__main__":
    sys.exit(main())
