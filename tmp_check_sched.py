import scheduler.scheduler_core as sc
rows = sc.get_all_jobs_status()
print('jobs_status_len', len(rows))
for r in rows:
    if r.get('id') in ('ui_ai_summaries','ui_ai_summaries_weekend','market_daily_brief','market_daily_brief_catchup'):
        print(r.get('id'), r.get('next_run'), r.get('is_paused'), r.get('scheduler_stopped'), r.get('trigger'))
