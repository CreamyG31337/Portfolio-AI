#!/usr/bin/env python3
"""
Check Congress Trades Job Execution Logs
========================================
"""

import sys
import io
from pathlib import Path
from datetime import datetime, timedelta, timezone

# Fix Windows console encoding
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Add project root to path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / 'web_dashboard'))

from supabase_client import SupabaseClient

def check_congress_trades_job():
    """Check recent congress trades job executions."""
    client = SupabaseClient(use_service_role=True)
    
    # Get last 7 days
    today = datetime.now(timezone.utc)
    week_ago = today - timedelta(days=7)
    
    print("\n" + "=" * 80)
    print("CONGRESS TRADES JOB EXECUTIONS (Last 7 days)")
    print("=" * 80)
    print()
    
    result = client.supabase.table('job_executions')\
        .select('*')\
        .eq('job_name', 'congress_trades')\
        .gte('started_at', week_ago.isoformat())\
        .order('started_at', desc=True)\
        .limit(20)\
        .execute()
    
    if not result.data:
        print("❌ No executions found in the last 7 days")
        print("\nPossible reasons:")
        print("  1. Job is not running (scheduler not started or job paused)")
        print("  2. Job is failing immediately before logging")
        print("  3. Job name mismatch (check scheduler registration)")
        return
    
    print(f"Found {len(result.data)} executions:\n")
    
    for i, record in enumerate(result.data, 1):
        started = record.get('started_at', 'N/A')
        if started and len(started) > 19:
            started = started[:19]
        
        status = record.get('status', 'N/A')
        duration = record.get('duration_ms', 0)
        error_msg = record.get('error_message') or record.get('message', 'N/A')
        
        # Truncate long messages
        if error_msg and len(error_msg) > 150:
            error_msg = error_msg[:147] + "..."
        
        status_icon = "✅" if status == "success" else "❌" if status == "failed" else "⏳"
        
        print(f"{i}. {status_icon} [{started}]")
        print(f"   Status: {status:8} | Duration: {duration:6}ms")
        print(f"   Message: {error_msg}")
        print()
    
    # Summary
    success_count = sum(1 for r in result.data if r.get('status') == 'success')
    failed_count = sum(1 for r in result.data if r.get('status') == 'failed')
    running_count = sum(1 for r in result.data if r.get('status') == 'running')
    
    print("=" * 80)
    print(f"Summary: {success_count} successful, {failed_count} failed, {running_count} running")
    print("=" * 80)
    
    # Check for common error patterns
    if failed_count > 0:
        print("\n🔍 Analyzing failures...\n")
        errors = [r.get('error_message') or r.get('message', '') for r in result.data if r.get('status') == 'failed']
        
        error_patterns = {
            'FMP_API_KEY': sum(1 for e in errors if 'FMP_API_KEY' in str(e)),
            'ImportError': sum(1 for e in errors if 'ImportError' in str(e) or 'Missing dependency' in str(e)),
            'HTTP': sum(1 for e in errors if 'HTTP' in str(e) or 'requests' in str(e).lower()),
            'politician': sum(1 for e in errors if 'politician' in str(e).lower()),
            'database': sum(1 for e in errors if 'database' in str(e).lower() or 'supabase' in str(e).lower()),
        }
        
        for pattern, count in error_patterns.items():
            if count > 0:
                print(f"  ⚠️  {pattern}: {count} occurrence(s)")

if __name__ == "__main__":
    check_congress_trades_job()
