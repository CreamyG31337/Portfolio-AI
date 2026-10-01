import re

with open('tests/test_jobs_stance_outcomes.py', 'r') as f:
    content = f.read()

content = content.replace("record_scoring_attempt,", "record_scoring_attempts,")
content = content.replace(
    'record_scoring_attempt(pg, stance_id="uuid-1", horizon_days=30, reason=SKIP_NOT_MATURED)',
    'record_scoring_attempts(pg, [("uuid-1", 30, SKIP_NOT_MATURED)])'
)
content = content.replace(
    'record_scoring_attempt(pg, stance_id="uuid-1", horizon_days=30, reason=SKIP_NO_TICKER_PRICE)',
    'record_scoring_attempts(pg, [("uuid-1", 30, SKIP_NO_TICKER_PRICE)])'
)
content = content.replace("pg.execute_update.called", "pg.execute_many.called")

with open('tests/test_jobs_stance_outcomes.py', 'w') as f:
    f.write(content)
