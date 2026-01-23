#!/usr/bin/env python3
"""Quick status check for ETF AI analysis."""

import sys
from pathlib import Path
from datetime import datetime, timezone

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(1, str(project_root / "web_dashboard"))

from dotenv import load_dotenv
load_dotenv(project_root / "web_dashboard" / ".env")

from supabase_client import SupabaseClient

db = SupabaseClient(use_service_role=True)
today = datetime.now(timezone.utc).date().strftime('%Y-%m-%d')

# Check queue
queue_result = db.supabase.table('ai_analysis_queue') \
    .select('*') \
    .eq('analysis_type', 'etf_group') \
    .order('created_at', desc=True) \
    .limit(10) \
    .execute()

print(f"Queue items: {len(queue_result.data)}")
for item in queue_result.data[:5]:
    print(f"  {item['target_key']} - {item['status']}")

# Check today's changes
changes_result = db.supabase.from_('etf_holdings_changes') \
    .select('etf_ticker') \
    .eq('date', today) \
    .limit(10) \
    .execute()

etf_tickers = list(set([r['etf_ticker'] for r in changes_result.data or []]))
print(f"\nETF changes for today ({today}): {len(etf_tickers)} ETFs")
print(f"  ETFs: {', '.join(etf_tickers[:10])}")
