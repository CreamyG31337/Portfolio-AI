import re

with open('web_dashboard/scheduler/jobs_stance_outcomes.py', 'r') as f:
    content = f.read()

old_func = """def record_scoring_attempt(
    postgres: Any,
    *,
    stance_id: str,
    horizon_days: int,
    reason: str,
) -> None:
    \"\"\"Increment the failed-attempt counter for a (stance, horizon) pair.

    Transient reasons ("not matured yet") must not burn attempts, or a stance could
    be dead-lettered before it was ever eligible to score.
    \"\"\"
    if reason in TRANSIENT_SKIP_REASONS:
        return
    postgres.execute_update(
        \"\"\"
        INSERT INTO stance_outcome_attempts (stance_id, horizon_days, attempts, last_reason, last_attempt_at)
        VALUES (%s::uuid, %s, 1, %s, NOW())
        ON CONFLICT (stance_id, horizon_days) DO UPDATE SET
            attempts = stance_outcome_attempts.attempts + 1,
            last_reason = EXCLUDED.last_reason,
            last_attempt_at = NOW()
        \"\"\",
        (str(stance_id), horizon_days, reason),
    )"""

new_func = """def record_scoring_attempts(
    postgres: Any,
    attempts: list[tuple[str, int, str]],
) -> None:
    \"\"\"Increment the failed-attempt counter for a batch of (stance, horizon) pairs.

    Transient reasons ("not matured yet") must not burn attempts, or a stance could
    be dead-lettered before it was ever eligible to score.
    \"\"\"
    valid_attempts = [
        (str(stance_id), horizon_days, reason)
        for stance_id, horizon_days, reason in attempts
        if reason not in TRANSIENT_SKIP_REASONS
    ]
    if not valid_attempts:
        return
    postgres.execute_many(
        \"\"\"
        INSERT INTO stance_outcome_attempts (stance_id, horizon_days, attempts, last_reason, last_attempt_at)
        VALUES (%s::uuid, %s, 1, %s, NOW())
        ON CONFLICT (stance_id, horizon_days) DO UPDATE SET
            attempts = stance_outcome_attempts.attempts + 1,
            last_reason = EXCLUDED.last_reason,
            last_attempt_at = NOW()
        \"\"\",
        valid_attempts,
    )"""

content = content.replace(old_func, new_func)
with open('web_dashboard/scheduler/jobs_stance_outcomes.py', 'w') as f:
    f.write(content)
