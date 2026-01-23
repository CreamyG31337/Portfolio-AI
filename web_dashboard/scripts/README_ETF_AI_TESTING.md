# ETF AI Analysis Jobs - Testing Guide

## Preventing Concurrent Execution

The jobs now have built-in protection against running concurrently:

1. **Automatic Check**: Both jobs check the `job_executions` table before starting
2. **Skip if Running**: If a job is already running, the new instance will skip and log a message
3. **max_instances=1**: Jobs are registered with `max_instances=1` which prevents APScheduler from running multiple instances

## Testing Safely

### Option 1: Pause Jobs via Admin UI (Recommended)

1. Go to the admin scheduler page in the web dashboard
2. Find `etf_group_analysis` and `ticker_analysis` jobs
3. Click "Pause" on both jobs
4. Test manually using the test scripts
5. Resume when done

### Option 2: Check Job Status First

Before testing, check if jobs are running:

```powershell
# Check if jobs are currently running
python -c "from web_dashboard.supabase_client import SupabaseClient; db = SupabaseClient(use_service_role=True); result = db.supabase.table('job_executions').select('job_name').eq('status', 'running').in_('job_name', ['etf_group_analysis', 'ticker_analysis']).execute(); print('Running:', [r['job_name'] for r in result.data] if result.data else 'None')"
```

### Option 3: Test During Off-Hours

The jobs are scheduled for:
- `etf_group_analysis`: 9:00 PM EST
- `ticker_analysis`: 10:00 PM EST

Test outside these hours to avoid conflicts.

## Manual Testing

```powershell
# Test ETF group analysis
python web_dashboard\scripts\test_run_etf_jobs.py --job etf_group

# Test ticker analysis (will run for up to 2 hours)
python web_dashboard\scripts\test_run_etf_jobs.py --job ticker
```

## How the Protection Works

1. **Job Start Check**: Each job checks `job_executions` table for a running instance
2. **Early Return**: If found, logs a message and returns immediately
3. **No Duplicate Work**: Prevents processing the same queue items twice

## Verifying Protection

After starting a manual test, the scheduled job (if it triggers) will see the running instance and skip:

```
⏸️  Job etf_group_analysis is already running. Skipping to prevent concurrent execution.
```

This ensures safe testing without conflicts.
