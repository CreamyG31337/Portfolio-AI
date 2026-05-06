from supabase_client import SupabaseClient
sb = SupabaseClient(use_service_role=True)
res = sb.supabase.table('apscheduler_jobs').select('id,next_run_time').order('id').limit(200).execute()
rows = res.data or []
print('apscheduler_jobs rows:', len(rows))
for r in rows:
    if 'ui_ai' in r.get('id','') or 'market_daily_brief' in r.get('id',''):
        print('TARGET', r)
print('sample ids:', [r.get('id') for r in rows[:20]])
