# Congress Trades Re-analysis (Run from Repo)

When you update the congress analysis job code and want to **re-analyze a month** (e.g. January) **from your machine** so the job keeps running even if you redeploy the app (UI-triggered jobs would stop on deploy).

## 1. Reset that month’s sessions (set scores to null so they’re re-run)

From repo root, with venv activated:

```powershell
.\venv\Scripts\activate
python web_dashboard\scripts\reset_january_sessions_for_reanalysis.py --year 2026 --month 1
```

- **Default:** January of the current year. Use `--year` and `--month` for another month.
- This marks those sessions as `needs_reanalysis = TRUE` and clears `conflict_score`, `confidence_score`, `ai_summary`, `risk_pattern`, and per-trade analysis for that month so the batch job will pick them up.

## 2. Run the session analysis from the repo

Same shell (or new one with venv activated), from repo root:

```powershell
.\venv\Scripts\activate
python web_dashboard\scripts\analyze_congress_trades_batch.py --sessions --batch-size 10
```

- **No `--rescore`:** Only sessions with `needs_reanalysis = TRUE` are processed (i.e. the January ones you just reset).
- **No `--limit`:** Runs until there are no more sessions needing analysis.
- This process is independent of the Flask app, so redeploying the app won’t stop it.

## Optional: rescore everything (all sessions)

To re-analyze **all** sessions with updated logic (not just one month):

```powershell
python web_dashboard\scripts\analyze_congress_trades_batch.py --sessions --rescore --batch-size 10 --limit 5000
```

- Use `--limit` to cap how many sessions to process in one run.

## Related

- **Scheduler job (UI):** `rescore_congress_sessions_job` in `jobs_congress.py` runs the same batch script via subprocess; starting it from the UI ties it to the app process.
- **Batch script:** `web_dashboard/scripts/analyze_congress_trades_batch.py` (session-based analysis with `--sessions`).
