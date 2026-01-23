#!/usr/bin/env python3
"""Quick check if ETF AI jobs are running."""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(1, str(project_root / "web_dashboard"))

from dotenv import load_dotenv
load_dotenv(project_root / "web_dashboard" / ".env")

from supabase_client import SupabaseClient

db = SupabaseClient(use_service_role=True)

# Check running jobs
running = db.supabase.table('job_executions') \
    .select('job_name, started_at') \
    .eq('status', 'running') \
    .in_('job_name', ['etf_group_analysis', 'ticker_analysis']) \
    .execute()

if running.data:
    print("WARNING: These jobs are currently running:")
    for job in running.data:
        print(f"  - {job['job_name']} (started: {job.get('started_at', 'N/A')})")
    print("\nWait for them to finish before testing manually.")
else:
    print("OK: No ETF AI jobs are currently running.")
    print("Safe to test manually.")
