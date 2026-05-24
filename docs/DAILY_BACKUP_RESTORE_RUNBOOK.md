# Daily Backup Restore Runbook

> **This is a one-environment project.** The only Supabase project the
> codebase talks to is **production**. There is no staging copy. Every command
> in this runbook runs against live user, fund, and contribution data. There
> is no undo.
>
> Read the entire runbook before running anything. The restore script
> (`web_dashboard/scripts/restore_daily_backup.py`) is **untested in this
> environment** — there is no safe place to test it. The first time it is
> ever run for real, it should be on a single, low-blast-radius table (e.g.
> `system_settings`, not `user_funds`) using `--strategy upsert` (the default).

---

## What gets backed up

Job: `daily_critical_data_backup_job` (runs daily at **12:00 UTC**).

Two destinations — both written every day:

| Destination | Path |
|---|---|
| Host volume | `/home/lance/trading-dashboard-backups/<YYYY-MM-DD>/...` (mounted into the Flask container at `/app/web_dashboard/backups/daily/`) |
| Supabase Storage (private bucket `daily-backups`) | `daily/<YYYY-MM-DD>/...` |

Each daily folder contains:

```text
<YYYY-MM-DD>/
├── trade_log/
│   ├── <fund_slug>_trades.csv      ← per-fund full trade history
│   └── ...
└── tables/
    ├── user_profiles.csv
    ├── user_funds.csv
    ├── funds.csv
    ├── fund_thesis.csv
    ├── fund_thesis_pillars.csv
    ├── fund_contributions.csv
    ├── system_settings.csv
    ├── watched_tickers_v2.csv
    ├── ai_analysis_skip_list.csv
    ├── contributors.csv
    └── contributor_access.csv
```

The list of tables is the constant `CRITICAL_APP_TABLES` in
`web_dashboard/scheduler/jobs_daily_backup.py`. Adding a new table to backup
also requires adding its primary key to `TABLE_PRIMARY_KEYS` in
`web_dashboard/scripts/restore_daily_backup.py`.

---

## What is **not** restorable by this runbook

* **`trade_log`** — the script refuses. Trade log is the system-of-record for
  cash balances, positions, and dividends. A blind upsert/replace would
  desynchronize derived state. If you need to recover a trade, use the snapshot
  CSV as evidence and re-enter the trade through the admin UI.
* **Auth users (`auth.users`)** — those rows live in the Supabase Auth schema
  and are not backed up. `user_profiles.id` and `user_funds.user_id` are
  foreign keys to `auth.users`; if an auth user has been deleted, restoring
  the public-schema rows that reference it will fail. Recreate the auth user
  first (Supabase Dashboard → Auth → Users), then run the restore.
* **Operational/rebuildable tables** — by design (`ai_task_queue`,
  `apscheduler_jobs`, `job_executions`, market/research/feed tables, etc.).

---

## Decision flow

```text
Something is wrong with the DB.
│
├─ Is the wrong row easy to fix in the admin UI?
│  └─ Yes → fix it there. Done. Move on.
│
├─ Was the bad change limited to one row / a handful of rows?
│  └─ Yes → use the admin UI, or run a hand-crafted SQL fix via Supabase MCP
│           (`execute_sql`) using the snapshot CSV as the source of truth.
│           Do NOT use this restore script — it is heavier than you need.
│
└─ Is a whole table corrupted / accidentally truncated / mass-edited?
   └─ Yes → continue with this runbook.
```

Always prefer the smallest possible intervention. The restore script is for
"the table is meaningfully broken" not "one column on one row is wrong".

---

## Before running anything

1. **Identify the bad change.**
   * What table? When did it happen? What query/UI action caused it?
   * What snapshot date is known-good? (Usually the most recent snapshot
     written **before** the bad change.)

2. **Sanity check the snapshot exists** (read-only, harmless):

   ```powershell
   # PowerShell on the dev machine, with prod env vars loaded
   python web_dashboard\scripts\restore_daily_backup.py --list-snapshots --source storage
   python web_dashboard\scripts\restore_daily_backup.py --list-snapshots --source host
   ```

   If both lists are empty, the daily job has never run successfully — stop
   here and investigate `job_executions` for `daily_critical_data_backup`.

3. **Decide between sources.**
   * `--source storage` is the cloud copy. Always available unless someone
     deleted the bucket. Use this by default.
   * `--source host` requires running the script *inside* the
     `trading-dashboard-flask` container (so the volume mount is visible).
     Useful as a cross-check that the two destinations agree.

4. **Decide between strategies.**
   * `--strategy upsert` (default): writes the snapshot rows on top of
     current rows, keyed on the primary key. Rows that exist in prod but not
     in the snapshot are **preserved**. Idempotent — safe to retry. **Use
     this unless you know you need the other one.**
   * `--strategy truncate-and-replace`: additionally **deletes** rows that
     exist in prod but not in the snapshot. Required when the bad change
     *added* rows that need to be removed. Per-row `DELETE` keyed on PK
     (no bulk `DELETE FROM`) so foreign keys are honored. Requires
     `--allow-truncate` on top of the other confirmation flags.

---

## The four-step restore (table-at-a-time)

> **Run on the dev machine** unless you specifically need `--source host`,
> in which case `docker exec -it trading-dashboard-flask` first.

### Step 1 — Preview (read-only, no DB writes)

```powershell
python web_dashboard\scripts\restore_daily_backup.py `
    --table funds `
    --date 2026-05-24 `
    --source storage
```

This prints a diff:

```text
=== Diff preview for table 'funds' ===
Snapshot rows: 51
Current rows:  51
Would INSERT (in snapshot, not in DB):     0
Would UPDATE (PK match, content differs):  3
Would PRESERVE (in DB, not in snapshot):   0  (strategy=upsert; pass --strategy truncate-and-replace to delete)
  Sample updates: '...uuid-1...', '...uuid-2...', '...uuid-3...'
```

* If the diff is **bigger than you expected**, stop. Investigate before
  applying. The restore script makes no attempt to be clever — if your
  snapshot date is wrong, the diff will look wild.
* If the diff is **empty**, no restore is needed. Exit 0.

### Step 2 — Decide on strategy

| Symptom | Strategy |
|---|---|
| Rows were edited in place; row count is the same | `upsert` (default) |
| Rows were deleted; row count is lower than the snapshot | `upsert` (will re-insert them) |
| Rows were *added* maliciously / in error; row count is higher than snapshot | `truncate-and-replace` |

### Step 3 — Apply

For an upsert restore (most common):

```powershell
python web_dashboard\scripts\restore_daily_backup.py `
    --table funds `
    --date 2026-05-24 `
    --source storage `
    --apply `
    --confirm-restore PROD
```

For a truncate-and-replace restore:

```powershell
python web_dashboard\scripts\restore_daily_backup.py `
    --table funds `
    --date 2026-05-24 `
    --source storage `
    --apply `
    --confirm-restore PROD `
    --strategy truncate-and-replace `
    --allow-truncate
```

The script will print the diff again, then upsert / delete-and-upsert in
batches of 500 rows.

### Step 4 — Verify

After the restore returns, immediately spot-check:

```sql
-- via Supabase MCP execute_sql
select count(*) from <table>;
select * from <table> where <pk> = '<expected-row-pk>';
```

If verification fails, **do not panic and do not re-run with a different
strategy**. The upsert path is idempotent — re-running it will not make
things worse. Investigate first.

---

## Failure modes and what they mean

| Symptom | Likely cause | What to do |
|---|---|---|
| `Host snapshot not found at /app/web_dashboard/backups/daily/...` | Running on dev machine but `--source host`; or volume not mounted | Use `--source storage`, or run inside the Flask container |
| `Storage object daily-backups/... could not be downloaded` | Wrong date, or bucket not yet created | Run `setup_daily_backup_bucket.py`; check `--list-snapshots --source storage` |
| `snapshot is empty (0 bytes / no header)` | The table was empty when backed up — Supabase REST returns no column metadata for empty result sets | If you really want to restore an empty table on top of current rows, pass `--allow-empty-snapshot` AND `--strategy truncate-and-replace --allow-truncate` |
| `--apply was passed but --confirm-restore PROD was not` | You are missing the second confirmation flag | Add `--confirm-restore PROD`. This is intentional friction. |
| `--strategy=truncate-and-replace requires --allow-truncate` | You asked for the destructive strategy but didn't pass the third flag | Add `--allow-truncate`. This is intentional friction. |
| `snapshot does not contain primary-key column` | Schema drift between snapshot and current table | Investigate. Likely you need a hand-written SQL fix instead of this script. |
| `Restore aborted mid-flight` | A batch failed (FK violation, type coercion bug, network blip) | Re-run with the same arguments. The upsert path is idempotent. |

---

## Things this runbook deliberately does NOT cover

* **Restoring everything in one command.** There is no `--all-tables` flag and
  there will not be one. Restore is always one table at a time so blast
  radius is bounded.
* **Restoring across schema migrations.** If the snapshot pre-dates a schema
  change, the upsert may fail on a missing/new column. In that case,
  hand-write the migration before restoring.
* **Restore from a partial backup.** The script trusts that the snapshot file
  it was given is complete. The daily job either writes the full table CSV
  or doesn't write that file at all.

---

## Related files

* Backup job: [`web_dashboard/scheduler/jobs_daily_backup.py`](../web_dashboard/scheduler/jobs_daily_backup.py)
* Bucket setup: [`web_dashboard/scripts/setup_daily_backup_bucket.py`](../web_dashboard/scripts/setup_daily_backup_bucket.py)
* Restore script: [`web_dashboard/scripts/restore_daily_backup.py`](../web_dashboard/scripts/restore_daily_backup.py)
* Whitelist of restorable tables (must stay in sync with the backup job):
  `TABLE_PRIMARY_KEYS` in `web_dashboard/scripts/restore_daily_backup.py`
