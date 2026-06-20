import os
import sys
from datetime import datetime, timedelta

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from web_dashboard.supabase_client import SupabaseClient

def check_job_logs():
    client = SupabaseClient()
    
    # Check job execution logs for today
    today = datetime.now().date()
    yesterday = today - timedelta(days=1)
    
    print("=== JOB EXECUTION LOGS (last 24 hours) ===\n")
    
    response = client.supabase.table("job_executions") \
        .select("*") \
        .eq("job_name", "update_portfolio_prices") \
        .gte("executed_at", yesterday.isoformat()) \
        .order("executed_at", desc=True) \
        .limit(10) \
        .execute()
    
    if not response.data:
        print("No job executions found in last 24 hours")
        return
    
    import pandas as pd
    df = pd.DataFrame(response.data)
    
    print(f"Found {len(df)} executions:\n")
    for row in df.to_dict('records'):
        print(f"Time: {row['executed_at']}")
        print(f"Success: {row['success']}")
        print(f"Message: {row.get('message', 'N/A')}")
        print(f"Duration: {row.get('duration_ms', 0)}ms")
        print("-" * 60)

if __name__ == "__main__":
    check_job_logs()
