# Scheduler Health Check Runbook

This runbook is the standard way to verify scheduler and job health in production.
Use server-side checks only. Local-machine checks can produce false negatives.

## Scope

- Read-only operational checks for scheduler health.
- Validate whether jobs are active, stale, or failing.
- Prevent accidental commits of personal/portfolio artifacts while debugging.

## Do Not

- Do not restart containers/services during diagnostics-only checks.
- Do not pause/resume jobs during diagnostics-only checks.
- Do not run write/migration scripts as part of health verification.

## Prerequisites

- Tailscale connected.
- SSH access to `lance@ts-ubuntu-server`.
- Private key accessible from this machine/session.

## 60-Second Quick Check

Run these in order:

```bash
tailscale status
ssh -i "<key_path>" lance@ts-ubuntu-server "hostname && date && whoami"
ssh -i "<key_path>" lance@ts-ubuntu-server "docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.RunningFor}}'"
ssh -i "<key_path>" lance@ts-ubuntu-server "docker logs --since 30m trading-dashboard --tail 200"
ssh -i "<key_path>" lance@ts-ubuntu-server "docker exec trading-dashboard python /app/web_dashboard/scripts/check_job_status.py"
ssh -i "<key_path>" lance@ts-ubuntu-server "docker exec trading-dashboard python /app/web_dashboard/scripts/read_job_logs.py --days 1 --limit 120"
```

## Detailed Verification Flow

1. Connectivity and identity
   - Confirm expected tailnet peers with `tailscale status`.
   - Confirm you are on the right host/user via `hostname && whoami`.

2. Runtime/container health
   - Confirm `trading-dashboard` and `trading-dashboard-flask` are `Up` and healthy.
   - If they are healthy, move to scheduler/log checks before concluding anything is broken.

3. Scheduler heartbeat evidence
   - In `trading-dashboard` logs, confirm frequent entries like:
     - `Scheduler Heartbeat ... executed successfully`
   - Heartbeat every ~15s indicates the scheduler loop is alive.

4. Job execution state
   - Use `check_job_status.py` to see jobs currently marked running (includes `ui_ai_summaries` alongside ETF/ticker AI jobs).
   - Use `read_job_logs.py --days 1` for recent success/failure/running status.
   - **`ui_ai_summaries`**: weekdays ~2h cadence (10:10 / 12:10 / 14:10 / 16:10 / 18:10 America/New_York). Refreshes tier-1 `ui_ai_summary` (dashboard portfolio digest) and tier-2 `ui_ai_rollup_fund` per production fund; skips LLM calls when `inputs_digest` is unchanged. Requires research tables `ui_ai_summary` and `ui_ai_rollup_fund` (see `apply_etf_ai_schema.py` / schema files).

5. Confirm or disprove stale-job claims
   - Query specific jobs over the last week:

```bash
ssh -i "<key_path>" lance@ts-ubuntu-server \
  "docker exec trading-dashboard python /app/web_dashboard/scripts/read_job_logs.py --days 7 --job <job_name> --limit 10"
```

## Interpreting Results

Use these rules before raising an incident:

- `running` now: job actively executing (may be long-running).
- `success` today: usually healthy.
- `failed` once with interruption text (for example container restart): transient unless repeated.
- No run in several days:
  - May still be expected for weekly/monthly schedules.
  - Confirm schedule and day/time before labeling as outage.

Market-day jobs may appear stale on weekends/holidays depending on trigger configuration.

## Known Benign Log Signals

These can be noisy but not necessarily outages:

- `missing ScriptRunContext! ... can be ignored when running in bare mode`
- Some external content fetch failures (`403`, paywalls, blocked sources)
- Temporary source-specific warnings if overall job still completes successfully

## Failure Triage Matrix

| Symptom | Likely Cause | Read-only Confirmation |
|---|---|---|
| `Permission denied (publickey,password)` on SSH | wrong user/key or key ACL issue | retry with known good key path and verify key permissions |
| Scheduler appears down locally but jobs still execute | checking wrong machine/context | run all checks from server via `docker exec trading-dashboard ...` |
| Job marked failed once with interruption | container restart interrupted run | inspect recent logs for restart timing and next run status |
| Job appears stale | cron/market-hour schedule mismatch | run `read_job_logs.py --days 7 --job <job_name>` |
| No heartbeat entries in recent logs | scheduler process issue | inspect `docker logs --since 30m trading-dashboard --tail 200` for heartbeat absence and scheduler errors |

## Privacy and Git Safety Checklist (Required)

Before committing docs/debug artifacts:

1. Review staging state:
   - `git status --short`
2. Confirm ignored sensitive patterns are still in effect:
   - `web_dashboard/scripts/*_audit.jsonl`
   - `web_dashboard/scripts/improved_reasons_*.csv`
   - `web_dashboard/scripts/improved_reasons_*.txt`
   - `backups/**/*.sql`, `backups/**/*.dump`, `*.db-backup.sql`
   - cookie/credential artifacts (`webai_cookies.json`, `ai_service_cookies.json`, credential files)
3. Keep ad-hoc diagnostics outside repo when possible.
4. Never commit files containing personal portfolio positions, old/new rationale text dumps, raw credentials, or cookie data.

## Escalation Notes

Escalate when:

- multiple critical jobs fail repeatedly in the same window,
- heartbeat disappears and no jobs run,
- container health degrades (`unhealthy`/restart loop),
- or DB job records stop updating entirely.

When escalating, include:

- command outputs from quick check,
- failing job names and last success timestamps,
- and exact error snippets from `read_job_logs.py` output.
