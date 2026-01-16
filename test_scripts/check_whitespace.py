"""Check for leading whitespace issues in research article summaries."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import re
from web_dashboard.supabase_client import SupabaseClient

client = SupabaseClient(use_service_role=True)
result = client.table('research_articles').select('id,ticker,summary').execute()
articles = result.data

issues = []
for a in articles:
    summary = a.get('summary', '') or ''
    if re.search(r'^\s+[-•*]', summary, re.MULTILINE):
        issues.append((a['id'], a['ticker'], summary[:100]))

print(f'Total articles: {len(articles)}')
print(f'Articles with leading whitespace: {len(issues)}')

for id, ticker, preview in issues[:10]:
    print(f'  - {id}: {ticker}')
    print(f'    Preview: {repr(preview[:60])}...')
