## RLS Audit — Phase 0 (read-only investigation)

**Project:** Supabase `injqbxdqyxfvannygadt` (CreamyG31337's Project, us-east-2, Postgres 17.6.1).
**Date:** 2026-05-20.
**Scope:** 9 `public.*` tables flagged by `list_tables` advisor as RLS-disabled.
**Method:** live SQL via Supabase MCP (`execute_sql`, read-only) + repo grep. No DDL was applied.

---

### Immediate concerns

These three findings are not table-specific and apply across the board. Surface
before reading the per-table sections.

1. **anon and authenticated currently have full DML on every flagged table.**
   `information_schema.role_table_grants` reports `SELECT, INSERT, UPDATE, DELETE,
   TRUNCATE, REFERENCES, TRIGGER` for both roles on all nine tables. The
   default Supabase grant set applies and **nothing has been revoked**. I
   confirmed exploitability by running `SET LOCAL ROLE anon; SELECT count(*)
   FROM public.apscheduler_jobs;` — it returned `53`. Any browser holding the
   project's publishable/anon key can read or mutate any of these tables.

2. **`public` schema USAGE is granted to anon/authenticated**
   (`has_schema_privilege('anon','public','USAGE') = true`). Combined with #1
   this means tables in `public` are reachable through PostgREST without any
   extra exposure config (`pgrst.db_schemas` is the runtime default; the
   `public` schema is exposed by default in Supabase). There is no second
   defense layer that we can rely on.

3. **`apscheduler_jobs` has 53 live job pickles readable as anon.** Worst of the
   three categories of risk: anon can drop rows (DELETE-grant present), which
   would silently break the scheduler until the container restarts. This is the
   single most urgent table — see verdict below.

No anonymous *write* path was found in the application code, but the database
grants alone allow it from any client holding the publishable key.

---

### 1. Per-table risk assessment

Common context for every row below:

- `relrowsecurity = false` (RLS off; confirmed via `pg_class`).
- `anon`, `authenticated`, and `service_role` all hold `SELECT/INSERT/UPDATE/
  DELETE/TRUNCATE/REFERENCES/TRIGGER` (Supabase default grants, never revoked).
- `has_table_privilege('anon', ...)` returns `true` for every SELECT/INSERT/
  UPDATE/DELETE on every table — I verified this in a single query.
- The table is reachable via PostgREST because schema USAGE is granted and the
  `public` schema is exposed by default.

For brevity I do not repeat those facts under each table; I only note
table-specific deltas.

#### 1.1 `public.job_retry_queue` (554 rows)

- **Writers:** `utils/job_tracking.py` (`add_to_retry_queue`, `mark_retrying`,
  `mark_resolved`, `mark_abandoned`, `mark_pending_retry`) — every call site
  instantiates `SupabaseClient(use_service_role=True)`. Background only.
- **Readers:** `utils/job_tracking.py::get_pending_retries`,
  `web_dashboard/scheduler/jobs_retry.py`,
  `web_dashboard/scripts/check_job_backlog_health.py`,
  `web_dashboard/scheduler/jobs_watchdog.py` — all service-role.
- **No user-facing Flask route reads or writes this table** (grep across
  `web_dashboard/routes/`, `web_dashboard/templates/`, and JS bundles is clean).
- **Content sensitivity:** stores `error_message` strings (truncated to 1000
  chars) which can contain ticker symbols, API endpoints, and stack-trace
  excerpts. Not catastrophic but non-public.
- **Tampering risk:** anon DELETE would silently swallow failed jobs and break
  the retry pipeline.
- **Verdict: HIGH** (because anon DELETE/UPDATE/INSERT is currently possible
  and would break scheduler self-healing).

#### 1.2 `public.apscheduler_jobs` (53 rows)

- **Writers:** APScheduler's `SQLAlchemyJobStore` (see
  `web_dashboard/scheduler/scheduler_core.py:250`). This connects via
  `SUPABASE_DATABASE_URL` as the `postgres` user — not via PostgREST — so RLS
  cannot block it.
- **Also written by:** `scheduler_core.py:596–603` does a service-role
  `DELETE` to wipe-and-re-register jobs on startup. Service-role.
- **Readers:** `scheduler_core.py:1717–1729` service-role fallback to compute
  "Next Run" in multi-worker Flask. No anon/authenticated reads anywhere.
- **Content sensitivity:** **highest** of the nine. Pickled job state including
  internal job IDs, cron triggers, and `next_run_time`. Anon DELETE here would
  cause the scheduler to come up with no jobs after the next restart.
- **Verdict: HIGH** — destructive tampering plausible; sensitive
  internal-only state.

#### 1.3 `public.ai_analysis_queue` (949 rows)

- **Writers:** background jobs only (`web_dashboard/scheduler/jobs_etf_analysis.py`,
  `web_dashboard/scheduler/jobs_ticker_analysis.py`,
  `web_dashboard/etf_meta_pipeline.py`, `web_dashboard/ticker_analysis_service.py`).
  Every write site I read either explicitly constructs
  `SupabaseClient(use_service_role=True)` or is passed one from `app.py:3857`
  (`supabase = SupabaseClient(use_service_role=True)`).
- **Readers:** same set + `web_dashboard/scripts/check_etf_ai_status.py`
  (operator script). No user-facing Flask route reads it.
- **Content sensitivity:** ticker symbols, analysis types, retry counts, error
  messages, model outputs. Plain operational data, but the LLM
  output (`result_json`) may contain narrative paragraphs we don't intend to
  expose.
- **Verdict: HIGH** — anon DELETE/UPDATE would corrupt the analysis pipeline
  state (e.g. flip rows back to `pending` or mark them `completed` falsely).

#### 1.4 `public.ai_analysis_skip_list` (0 rows currently)

- Row count via `select count(*)` is 0; the `relpages` stats estimate of 11 was
  stale from the May 2026 cleanup (see `docs/meta_analysis_roadmap.md`).
- **Writers/readers:** `web_dashboard/ai_skip_list_manager.py::AISkipListManager`
  — constructor takes a `SupabaseClient`. All current call sites
  (`app.py:3859`, `app.py:3911`, `scheduler/jobs_ticker_analysis.py:91`,
  `ticker_analysis_service.py:159`, scripts) pass a service-role client.
- **No user-facing Flask route touches it.**
- **Content sensitivity:** ticker symbols + failure-reason strings. The
  reason string may contain stack-trace fragments (see the May 2026
  `NoneType.__format__` incident referenced in the manager docstring).
- **Verdict: MEDIUM** — currently empty so blast radius is low, but the same
  anon DML problem applies if/when it repopulates.

#### 1.5 `public.insider_trades` (130 069 rows)

- **Writers:** `web_dashboard/scheduler/jobs_insiders.py::fetch_insider_trades_job`
  uses `supabase_client.supabase.table("insider_trades").upsert(...)` — service
  role (background job).
- **Writers (one-shot scripts):** `delete_insider_trades_*` in
  `web_dashboard/scripts/` — service role only, never called from a route.
- **Readers (user-facing!):**
  - `web_dashboard/routes/ai_routes.py:84`
    (`_get_insider_trades_for_portfolio`) reads via
    `get_supabase_client_flask()` — **this is the user-token / `authenticated`
    role path**.
  - `web_dashboard/templates/insider_trades.html` renders the
    `/insider_trades` page; the JS bundle calls API routes that resolve back
    through `ai_routes.py` and the user-token client.
- **Tampering risk:** anon can today INSERT/UPDATE/DELETE 130k rows of real
  SEC Form 4 data. The data itself is public, but a poisoned row can flow
  straight into LLM prompts via `_get_insider_trades_for_portfolio` and
  influence AI output for any authenticated user.
- **Verdict: HIGH** — anon write path into LLM context is the worst pattern
  here; read exposure is less interesting because the underlying data is
  public on SEC.gov.

#### 1.6 `public.congress_trade_returns` (28 083 rows)

- **Writers:** `web_dashboard/scheduler/jobs_congress_returns.py::compute_congress_trade_returns_job`
  — service role.
- **Readers:** scheduler-side reads only (same file); referenced in
  `database/schema/supabase/views/congress_trades_enriched.sql`. User-facing
  pages read the *view* (`congress_trades_enriched`), not this base table
  directly.
- **Content sensitivity:** computed `pct_change` per congressperson trade —
  derivative of public data, but represents in-house analytics.
- **Tampering risk:** anon UPDATE could poison the leaderboard /
  performance numbers shown to authenticated users (the view selects from
  this table).
- **Verdict: MEDIUM** — anon write path leaks into a user-facing view, but
  the data ultimately comes from public sources so read exposure is minor.

#### 1.7 `public.congress_positions` (3 014 rows)

- **Writers:** `web_dashboard/scheduler/jobs_congress_positions.py::compute_congress_positions_job`
  — service role only.
- **Readers (user-facing!):**
  - `web_dashboard/app.py:5500` `/api/congress_trades/positions/data` and
    `app.py:5600` `/api/congress_trades/positions/leaderboard` both:
    `if is_admin(): client = SupabaseClient(use_service_role=True) else:
    client = get_supabase_client_flask()`. **Regular authenticated users
    read this table via PostgREST as `authenticated`.**
  - The `get_politician_leaderboard` SQL function (in
    `database/schema/supabase/functions/`) also references this table.
- **Tampering risk:** same shape as `congress_trade_returns` — anon poisons,
  authenticated user sees corrupted leaderboard.
- **Verdict: MEDIUM** — write tampering is the real issue; reads expose only
  derivative public data.

#### 1.8 `public.ui_ai_summary` (0 rows)

- **Status in Supabase: orphaned.** Schema lives under
  `database/schema/research/tables/ui_ai_summary.sql` (note: *research*, not
  *supabase*). The application code path
  (`web_dashboard/ui_ai_summary_service.py`, `web_dashboard/routes/dashboard_routes.py`,
  `web_dashboard/routes/research_routes.py`, `web_dashboard/routes/signals_routes.py`)
  uses `PostgresClient` against `RESEARCH_DATABASE_URL` — a separate
  Postgres instance, not Supabase. The Supabase copy is reachable but unused.
- **Writers/readers in Supabase:** none in source.
- **Tampering risk:** an attacker could pre-populate the empty table to mess
  with future migrations or confuse operators. Limited blast radius today.
- **Verdict: LOW** (orphaned + empty), but worth fixing to avoid future
  surprise if someone wires it up.

#### 1.9 `public.ui_ai_rollup_fund` (0 rows)

- Same situation as 1.8: schema under `database/schema/research/tables/`,
  application reads/writes through `PostgresClient` (research DB) only. No
  Supabase code path.
- **Verdict: LOW** (orphaned + empty).

---

### 2. Recommended remediation per table

Picking from the menu (A = RLS + service-role + authenticated policies;
B = RLS + service-role only; C = keep RLS off, revoke grants; D = no action).

| # | Table | Pick | Rationale |
|---|---|---|---|
| 1 | `job_retry_queue` | **B** | Only background service-role code touches it. Enabling RLS + a single service-role full-access policy blocks anon entirely without any application change. |
| 2 | `apscheduler_jobs` | **B** | Highest-priority table. APScheduler uses the SQLAlchemy jobstore via direct Postgres (`postgres` user, not `authenticator`/`anon`/`authenticated`), so RLS on `authenticated`/`anon` won't block it. Service-role-only policy is correct. **One caveat under Open questions.** |
| 3 | `ai_analysis_queue` | **B** | All confirmed call sites use service-role. No user-facing route reads or writes. |
| 4 | `ai_analysis_skip_list` | **B** | Same reasoning as 3. Currently empty so risk of regression is minimal. |
| 5 | `insider_trades` | **A** | Background writes are service-role, but `ai_routes.py:84` reads with the user-token client. Need RLS + service-role full + `authenticated` SELECT-only policy. **No** authenticated INSERT/UPDATE/DELETE. |
| 6 | `congress_trade_returns` | **B** | User reads come through the `congress_trades_enriched` view, not this base table. Leaving the base table service-role-only is sufficient and stricter. Confirm view-via-RLS behavior in test plan. |
| 7 | `congress_positions` | **A** | `/api/congress_trades/positions/*` reads with the user-token client for non-admins. Need RLS + service-role full + `authenticated` SELECT-only policy. |
| 8 | `ui_ai_summary` | **B** | Orphaned in Supabase. RLS + service-role full closes the exposure with zero application impact (nothing reads or writes it via Supabase). |
| 9 | `ui_ai_rollup_fund` | **B** | Same as 8. |

I intentionally did not pick **C** (revoke-grants-without-RLS) anywhere. RLS +
a single service-role policy is the more idiomatic Supabase posture, is what
the new `ai_task_queue` table already uses, and matches what the Supabase
advisor expects to see.

---

### 3. Proposed SQL — migration `tighten_rls_on_operational_tables`

DO NOT APPLY YET. The user must (a) answer the open questions in §5, (b)
explicitly authorize the migration, and (c) ideally run it during a low-traffic
window because RLS-on with no policy yet is briefly blocking for any in-flight
non-service-role query.

Apply order matters: **create the policy first, then enable RLS**. Doing
`ENABLE ROW LEVEL SECURITY` before any policy exists locks out the
authenticated reader for `congress_positions` and `insider_trades` between
the two statements, which is visible to live users on a production database.

```sql
-- Migration: tighten_rls_on_operational_tables
-- Pre-req: ai_task_queue already RLS-on with service_role + authenticated
-- policies (do not touch).

BEGIN;

-- ============================================================
-- Group B: service-role-only (no user-facing reads)
--   job_retry_queue, apscheduler_jobs, ai_analysis_queue,
--   ai_analysis_skip_list, congress_trade_returns,
--   ui_ai_summary, ui_ai_rollup_fund
-- ============================================================

-- 1. job_retry_queue
CREATE POLICY "service_role full access"
  ON public.job_retry_queue
  FOR ALL TO service_role
  USING (true) WITH CHECK (true);
ALTER TABLE public.job_retry_queue ENABLE ROW LEVEL SECURITY;

-- 2. apscheduler_jobs
CREATE POLICY "service_role full access"
  ON public.apscheduler_jobs
  FOR ALL TO service_role
  USING (true) WITH CHECK (true);
ALTER TABLE public.apscheduler_jobs ENABLE ROW LEVEL SECURITY;

-- 3. ai_analysis_queue
CREATE POLICY "service_role full access"
  ON public.ai_analysis_queue
  FOR ALL TO service_role
  USING (true) WITH CHECK (true);
ALTER TABLE public.ai_analysis_queue ENABLE ROW LEVEL SECURITY;

-- 4. ai_analysis_skip_list
CREATE POLICY "service_role full access"
  ON public.ai_analysis_skip_list
  FOR ALL TO service_role
  USING (true) WITH CHECK (true);
ALTER TABLE public.ai_analysis_skip_list ENABLE ROW LEVEL SECURITY;

-- 5. congress_trade_returns
CREATE POLICY "service_role full access"
  ON public.congress_trade_returns
  FOR ALL TO service_role
  USING (true) WITH CHECK (true);
ALTER TABLE public.congress_trade_returns ENABLE ROW LEVEL SECURITY;

-- 6. ui_ai_summary
CREATE POLICY "service_role full access"
  ON public.ui_ai_summary
  FOR ALL TO service_role
  USING (true) WITH CHECK (true);
ALTER TABLE public.ui_ai_summary ENABLE ROW LEVEL SECURITY;

-- 7. ui_ai_rollup_fund
CREATE POLICY "service_role full access"
  ON public.ui_ai_rollup_fund
  FOR ALL TO service_role
  USING (true) WITH CHECK (true);
ALTER TABLE public.ui_ai_rollup_fund ENABLE ROW LEVEL SECURITY;

-- ============================================================
-- Group A: service-role full + authenticated SELECT
--   insider_trades, congress_positions
-- ============================================================

-- 8. insider_trades
CREATE POLICY "service_role full access"
  ON public.insider_trades
  FOR ALL TO service_role
  USING (true) WITH CHECK (true);
CREATE POLICY "authenticated read insider trades"
  ON public.insider_trades
  FOR SELECT TO authenticated
  USING (true);
ALTER TABLE public.insider_trades ENABLE ROW LEVEL SECURITY;

-- 9. congress_positions
CREATE POLICY "service_role full access"
  ON public.congress_positions
  FOR ALL TO service_role
  USING (true) WITH CHECK (true);
CREATE POLICY "authenticated read congress positions"
  ON public.congress_positions
  FOR SELECT TO authenticated
  USING (true);
ALTER TABLE public.congress_positions ENABLE ROW LEVEL SECURITY;

COMMIT;
```

**What this migration deliberately does *not* do:**

- It does not `REVOKE` the existing table grants. Once RLS is on with a
  default-deny posture for `anon`/`authenticated`, the grants are inert. A
  follow-up "cleanup grants" migration can revoke them later; not bundling
  this in keeps rollback simple.
- It does not touch `ai_task_queue` (already correctly secured per task spec).
- It does not change `congress_trades_enriched` (a view; inherits the privileges
  of its owner — confirm in test plan).

**Rollback notes.** If anything breaks after applying:

```sql
-- Per-table rollback. Repeat per affected table.
BEGIN;
ALTER TABLE public.<table> DISABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "service_role full access" ON public.<table>;
DROP POLICY IF EXISTS "authenticated read <name>" ON public.<table>;
COMMIT;
```

Because the original grants are still in place, disabling RLS instantly
restores the prior (insecure) behaviour. This is the desired property for an
emergency rollback.

---

### 4. Test plan (post-apply verification)

Run *after* the migration succeeds. Each item lists the user-visible page or
job and what to look for.

**A. Scheduler health (most important — relates to `apscheduler_jobs` and
`job_retry_queue`):**

1. After applying, immediately watch the scheduler container logs for
   `APScheduler` errors. The jobstore uses the `postgres` user via direct
   connection, which bypasses RLS — but verify there is no
   `permission denied for table apscheduler_jobs` in the first minute.
2. Open `/admin/jobs` (admin-only). The "Next Run" column should still
   populate. This is the read path at `scheduler_core.py:1723` and uses
   service-role.
3. Trigger one scheduler job manually from `/admin/scheduler` (e.g.
   `securities_metadata_refresh` — cheap and idempotent). It should complete
   with no `permission denied` in logs and its retry-queue side effects
   should still work.

**B. Congress / insider AI flows (Group A — most likely regression source):**

4. Open `/congress_trades/positions` as a non-admin user. The table should
   populate (`/api/congress_trades/positions/data` hits `congress_positions`
   via the user-token client). Empty/HTTP 500 = the `authenticated` SELECT
   policy is missing or misnamed.
5. Open `/congress_trades/positions` leaderboard tab — same expectation.
6. Open any portfolio's "AI Insights" / Audit pane and confirm the insider-
   trades section still renders. This exercises
   `ai_routes.py::_get_insider_trades_for_portfolio` against `insider_trades`
   with the user-token client.

**C. Operational queues (Group B — should be a no-op for users):**

7. Run `web_dashboard/scripts/check_job_backlog_health.py` — service-role
   read of `job_retry_queue`. Expect non-empty output, no errors.
8. Watch `ticker_analysis` cron complete one full cycle (look for the
   `ai_analysis_queue` row transitions `pending -> in_progress -> completed`).
9. Hit the `/admin` AI settings / skip-list page if one exists (the
   `AISkipListManager` paths in `app.py:3851` and `:3879`).

**D. View through-test:**

10. `congress_trades_enriched` is a view over `congress_trade_returns` (Group B,
    service-role only). Views in Postgres run with the privileges of the view
    owner unless `WITH SECURITY DEFINER`/`security_invoker` is set. Check
    that public reads of the view still succeed for an authenticated user.
    If they fail, either (a) recreate the view with `security_invoker=true`
    and add a SELECT policy to `congress_trade_returns`, or (b) keep
    `congress_trade_returns` open via a separate `authenticated` SELECT
    policy (move it from Group B to Group A).

**E. Anon smoke test (proves the fix worked):**

11. From a fresh browser tab with the anon key, attempt
    `GET /rest/v1/apscheduler_jobs?select=count`. After the migration this
    should return `permission denied for table apscheduler_jobs` (RLS deny).
    Before the migration this returns 53.

If any check in A or B fails, run the rollback for the offending table
(§3) and re-run the audit for that single table only.

---

### 5. Open questions for the human

These need explicit answers before the migration is safe to apply.

1. **APScheduler connection identity.** `scheduler_core.py:250` builds a
   `SQLAlchemyJobStore` from `SUPABASE_DATABASE_URL`. I am assuming this URL
   embeds the `postgres` superuser credentials (not `authenticator` /
   service-role JWT). If the URL is actually the `authenticator` role or
   has been pinned to a less-privileged role, then enabling RLS on
   `apscheduler_jobs` could break the jobstore at the next scheduler
   restart. Confirm by reading the env value in production or by running
   `SELECT current_user, session_user;` from the scheduler process during
   startup.

2. **Is `congress_trades_enriched` queried by anon at all?** The user-facing
   pages I inspected use `@require_auth`, so every read is `authenticated`.
   If any anon-accessible route (logged-out marketing pages, embeds, etc.)
   reads this view, the Group B verdict for `congress_trade_returns` is
   wrong and we'd want an `authenticated` SELECT policy on the base table
   (or anon read, depending on intent). Grep didn't find one but I'd like
   confirmation that the entire `/congress_trades/*` surface is auth-gated.

3. **`ui_ai_summary` / `ui_ai_rollup_fund` in Supabase — keep, or drop?**
   They are 0 rows, schema lives under `database/schema/research/`, and all
   live code writes to the research DB instead. Two reasonable paths: (a)
   apply the proposed RLS lock as a defensive measure; (b) drop the empty
   Supabase tables entirely so there is one fewer source of confusion.
   Option (a) is what's in the migration above; switch to (b) if you'd
   rather have me prepare a separate `drop_orphaned_ui_ai_tables` migration.

4. **Do we want a follow-up to revoke the now-inert anon/authenticated table
   grants?** Once RLS is on, those grants do nothing, but they're noise in
   `\dp` output and confuse future audits. Default recommendation: yes, in
   a second migration, after we've watched the first one bake for a few
   days. Out of scope for Phase 0.

5. **`ai_analysis_skip_list` is reported with 11 stale rows in `pg_class`
   stats but `count(*)` returns 0.** Most likely a missed `ANALYZE` after the
   May 2026 cleanup. Not a security issue, but worth a `VACUUM ANALYZE
   public.ai_analysis_skip_list;` to keep the advisor numbers honest. Out of
   scope for Phase 0 but cheap to bundle later.

---

*End of Phase 0 report. No SQL has been applied; no application code has been
modified.*
