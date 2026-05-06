from postgres_client import PostgresClient
pg = PostgresClient()
q1 = pg.execute_query('SELECT scope, scope_key, updated_at FROM ui_ai_summary ORDER BY updated_at DESC LIMIT 12')
q2 = pg.execute_query('SELECT fund, updated_at FROM ui_ai_rollup_fund ORDER BY updated_at DESC LIMIT 12')
q3 = pg.execute_query('SELECT brief_date, updated_at, headline FROM market_daily_brief ORDER BY brief_date DESC LIMIT 5')
print('ui_ai_summary rows:', len(q1 or []))
for r in (q1 or []):
    print(r)
print('ui_ai_rollup_fund rows:', len(q2 or []))
for r in (q2 or []):
    print(r)
print('market_daily_brief rows:', len(q3 or []))
for r in (q3 or []):
    print(r)
