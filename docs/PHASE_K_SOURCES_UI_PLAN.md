# Sources Admin Page — RSS + YouTube (Phase K support)

**Status:** in progress (steps 1–6 implemented in code; apply migrations + verify UI). **Owner:** implementing agent (Cursor).
**Created:** 2026-07-28. **Updated:** 2026-07-28 (implementation started).

Companion to [`PHASE_JK_PLAN.md`](PHASE_JK_PLAN.md) Phase K. That doc owns the ingest
pipeline; this doc owns the **config table + admin UI** that feeds it.

> **Seed data lives in [`PHASE_K_SOURCE_LIST.md`](PHASE_K_SOURCE_LIST.md)** — 13
> handle-and-`channel_id`-verified channels as a ready-to-paste bulk-import payload
> matching §5.2, plus the duration guardrails that make `min_duration_s` /
> `max_duration_s` load-bearing rather than cosmetic.

---

## 1. Goal

One admin page at `/admin/sources` for managing the two collector allowlists:

1. **RSS feeds** — table `rss_feeds` exists and is live, but has **no UI**. Today it is
   edited by writing throwaway Python scripts
   ([`add_research_feed.py`](../web_dashboard/scripts/add_research_feed.py),
   [`add_hunterbrook_feed.py`](../web_dashboard/scripts/add_hunterbrook_feed.py),
   [`remove_bad_feed.py`](../web_dashboard/scripts/remove_bad_feed.py)).
2. **YouTube sources** — table `youtube_sources` does **not exist yet**. Create it here.

The YouTube allowlist is arriving as a bulk research deliverable (25–50 channels with
per-channel metadata, plus scheduled search queries and IR channels), so **bulk import is
the primary interaction**, not one-at-a-time entry. Design for paste-a-list first.

### Non-goals (v1)

- No ingest job. `youtube_caption_ingest_job` is Phase K3 and is out of scope here.
- No per-source ROI charts — that needs G1 evidence + K5.
- No editing of `research_domain_health` (the existing Research Blacklist card in
  `ai_settings.html` keeps that job).
- No merging of the two tables into one polymorphic `sources` table. See §3.

---

## 2. Current state — verified facts to design against

| Fact | Evidence |
|---|---|
| `rss_feeds` schema is `id, name, url, category, enabled, last_fetched_at, created_at, updated_at` | [`restore_rss_tables.py:19-28`](../web_dashboard/scripts/restore_rss_tables.py#L19-L28) |
| The RSS job reads exactly `SELECT id, name, url FROM rss_feeds WHERE enabled = true` | [`jobs_research.py:334`](../web_dashboard/scheduler/jobs_research.py#L334) |
| The RSS job writes back `UPDATE rss_feeds SET last_fetched_at = NOW() WHERE id = %s` | [`jobs_research.py:443`](../web_dashboard/scheduler/jobs_research.py#L443) |
| Closest existing CRUD UI pattern is the Research Blacklist card | [`ai_settings.html:114-143`](../web_dashboard/templates/ai_settings.html#L114-L143) |
| …backed by GET/POST/DELETE JSON endpoints with `@require_admin` + `can_modify_data_flask()` | [`admin_routes.py:3822-3880`](../web_dashboard/routes/admin_routes.py#L3822-L3880) |
| Admin routes use `/admin/<kebab-name>` and set `current_page='admin_<snake_name>'` | [`_sidebar_content.html:148`](../web_dashboard/templates/components/_sidebar_content.html#L148) |
| Blueprints register in a try/except block with a log line | [`app.py:752-760`](../web_dashboard/app.py#L752-L760) |
| Caption fetch + typed failure reasons already exist | [`youtube_captions.py`](../web_dashboard/youtube_captions.py) |

---

## 3. Key decision: two tables, one page

**Do not** merge `rss_feeds` and `youtube_sources` into a polymorphic table.

`rss_feeds` is load-bearing for a working nightly job. A polymorphic rewrite would force
changes to `jobs_research.py` for zero user-visible benefit, and the two source types have
genuinely different columns (a channel has a cursor and a caption-health state; a feed has
neither). Keep them separate; unify only at the **UI and API layer** via a tabbed page and
a shared table component.

`rss_feeds` changes here are **additive only** — the existing `SELECT` and `UPDATE` above
must keep working untouched.

---

## 4. Schema

### 4.1 New table — `youtube_sources`

```sql
CREATE TABLE IF NOT EXISTS youtube_sources (
  id                      SERIAL PRIMARY KEY,

  -- identity
  kind                    VARCHAR(20)  NOT NULL DEFAULT 'channel',
                          -- channel | search | playlist | ir
  channel_id              VARCHAR(64),          -- UC... canonical id, resolved on save
  handle                  VARCHAR(120),         -- @gamersnexus, display/entry convenience
  query_text              TEXT,                 -- only for kind='search'
  label                   VARCHAR(200) NOT NULL,

  -- scoring (drives downstream LLM confidence weighting)
  alpha_mechanism         VARCHAR(20),
                          -- MARKET_MOVER | LEAK | TEARDOWN | ANALYSIS | EARNINGS_IR
  confidence_weight       NUMERIC(3,2) NOT NULL DEFAULT 1.00,  -- 0.00–2.00
  expected_tickers        TEXT[]       NOT NULL DEFAULT '{}',

  -- control
  enabled                 BOOLEAN      NOT NULL DEFAULT true,
  max_videos_per_poll     INTEGER      NOT NULL DEFAULT 5,
  min_duration_s          INTEGER      NOT NULL DEFAULT 120,
  max_duration_s          INTEGER,              -- NULL = no cap

  -- cursor
  last_video_id           VARCHAR(16),
  last_seen_at            TIMESTAMPTZ,
  last_polled_at          TIMESTAMPTZ,

  -- health
  last_success_at         TIMESTAMPTZ,
  consecutive_failures    INTEGER      NOT NULL DEFAULT 0,
  last_error_reason       VARCHAR(32),  -- youtube_captions.FailureReason literal
  captions_ok             BOOLEAN,      -- NULL = never tested

  -- provenance
  notes                   TEXT,
  added_by                VARCHAR(200),
  source_of_recommendation VARCHAR(200),

  created_at              TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  updated_at              TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- One row per channel; one row per distinct search string.
CREATE UNIQUE INDEX IF NOT EXISTS idx_youtube_sources_channel
  ON youtube_sources(channel_id) WHERE channel_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_youtube_sources_query
  ON youtube_sources(query_text) WHERE query_text IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_youtube_sources_enabled
  ON youtube_sources(enabled) WHERE enabled = true;

ALTER TABLE youtube_sources ADD CONSTRAINT youtube_sources_kind_target_chk
  CHECK (
    (kind = 'search' AND query_text IS NOT NULL)
    OR (kind <> 'search' AND (channel_id IS NOT NULL OR handle IS NOT NULL))
  );
```

**`last_error_reason` must store the literals already defined in
[`youtube_captions.py`](../web_dashboard/youtube_captions.py) `FailureReason`** —
`no_captions | blocked | age_restricted | unavailable | dependency | parse | unknown`.
Do not invent a parallel vocabulary; the UI status column reads these directly.

### 4.2 Additive columns on `rss_feeds`

```sql
ALTER TABLE rss_feeds ADD COLUMN IF NOT EXISTS notes TEXT;
ALTER TABLE rss_feeds ADD COLUMN IF NOT EXISTS consecutive_failures INTEGER NOT NULL DEFAULT 0;
ALTER TABLE rss_feeds ADD COLUMN IF NOT EXISTS last_error TEXT;
ALTER TABLE rss_feeds ADD COLUMN IF NOT EXISTS last_success_at TIMESTAMPTZ;
```

Nothing else on `rss_feeds` changes. Populating `consecutive_failures` / `last_error` from
the job is a **follow-up**, not part of this work — the UI must render them as "—" when null.

### 4.3 Register both tables

Add `youtube_sources` to the schema allowlist at
[`query_and_update_schemas.py:562`](../web_dashboard/schema/query_and_update_schemas.py#L562)
or the SQL interface will reject queries against it.

### 4.4 Migration files

Follow the numbered convention in [`migrations/`](../migrations/):

- `migrations/008_create_youtube_sources.sql`
- `migrations/009_add_rss_feeds_health_columns.sql`

Plus a seed/apply script mirroring
[`restore_rss_tables.py`](../web_dashboard/scripts/restore_rss_tables.py):
`web_dashboard/scripts/apply_sources_migrations.py`.

---

## 5. Backend

New blueprint: **`web_dashboard/routes/sources_routes.py`** (`sources_bp`). Do not grow
`admin_routes.py` — it is already 4758 lines.

Register in [`app.py`](../web_dashboard/app.py) alongside the others, using the same
try/except + `logger.info("✅ Registered Sources Blueprint")` shape as
[`app.py:752-760`](../web_dashboard/app.py#L752-L760).

### 5.1 Endpoints

| Method | Path | Notes |
|---|---|---|
| GET | `/admin/sources` | renders `sources.html`, `current_page='admin_sources'` |
| GET | `/api/admin/sources/rss` | list feeds |
| POST | `/api/admin/sources/rss` | create |
| PATCH | `/api/admin/sources/rss/<int:id>` | update / toggle `enabled` |
| DELETE | `/api/admin/sources/rss/<int:id>` | delete |
| GET | `/api/admin/sources/youtube` | list sources |
| POST | `/api/admin/sources/youtube` | create |
| PATCH | `/api/admin/sources/youtube/<int:id>` | update / toggle |
| DELETE | `/api/admin/sources/youtube/<int:id>` | delete |
| POST | `/api/admin/sources/youtube/test` | probe one source, no DB write (§5.3) |
| POST | `/api/admin/sources/youtube/bulk-preview` | parse + validate a pasted list, no write |
| POST | `/api/admin/sources/youtube/bulk-commit` | insert the previewed rows |

**Every route** gets `@require_admin`. **Every mutating route** additionally checks
`can_modify_data_flask()` and returns 403 with a clear message — copy the exact pattern at
[`admin_routes.py:3834-3845`](../web_dashboard/routes/admin_routes.py#L3834-L3845).

### 5.2 Bulk import contract

`bulk-preview` accepts `{"format": "json"|"csv", "payload": "<raw text>"}` and returns a
per-row verdict so the user sees what will happen **before** committing:

```json
{
  "rows": [
    {
      "label": "Gamers Nexus",
      "handle": "@GamersNexus",
      "kind": "channel",
      "alpha_mechanism": "TEARDOWN",
      "expected_tickers": ["NVDA", "INTC"],
      "status": "new",          // new | duplicate | invalid
      "warnings": ["channel_id not resolved — will resolve on commit"],
      "errors": []
    }
  ],
  "summary": { "new": 18, "duplicate": 4, "invalid": 1 }
}
```

Field names match the research deliverable (see the channel-research prompt: label, handle,
alpha mechanism, tickers, cadence, caption status, notes) so the researcher's output pastes
in with minimal reshaping. Unknown keys are ignored, not fatal. `duplicate` is decided on
`channel_id` first, then `handle`, then `query_text`.

`bulk-commit` inserts only rows the preview marked `new`, and is idempotent — re-running the
same paste inserts nothing.

### 5.3 The Test button

`POST /api/admin/sources/youtube/test` takes `{"url_or_id": "..."}` or `{"id": 12}` and calls
the existing K1 module:

```python
from youtube_captions import CaptionFetchError, fetch_caption_text
```

Return `{ok: true, video_id, language, caption_kind, char_count, title, channel_id}` on
success, or `{ok: false, reason, message}` on `CaptionFetchError` — `reason` is already a
stable literal, so the UI can map it to a friendly string. On success against a saved row,
persist `captions_ok`, `last_success_at`, and reset `consecutive_failures`.

This is the main payoff of reusing K1: you learn a channel's captions are disabled **at add
time**, not days into a silent job.

**This endpoint makes a live network call** — it is the only one that does. Rate-limit it to
one in-flight probe per user and never call it from list rendering.

---

## 6. Frontend

New template **`web_dashboard/templates/sources.html`**, extending `base.html` like the other
admin pages.

Layout: two tabs — **YouTube** (default) and **RSS Feeds** — over a shared table shell.

**Reuse the existing markup vocabulary from
[`ai_settings.html`](../web_dashboard/templates/ai_settings.html)**: `bg-dashboard-surface`,
`border-border`, `text-text-primary` / `-secondary` / `-tertiary`,
`bg-dashboard-surface-alt`, `text-accent`, `btn-outline-danger`, sticky `thead`,
`overflow-x-auto` wrapper. Do **not** introduce new colors — see
[`PALETTE_AUDIT.md`](../PALETTE_AUDIT.md).

### YouTube tab columns

`Label` · `Kind` · `Mechanism` · `Tickers` · `Weight` · `Enabled` (toggle) · `Captions`
(✓ / ✗ / untested) · `Last seen` · `Last error` · Actions (`Test`, `Edit`, `Delete`).

Above the table: a **Bulk import** button opening a modal with a paste area → preview table
(new / duplicate / invalid, color-coded) → **Commit N rows**. Reuse
[`_confirm_modal.html`](../web_dashboard/templates/components/_confirm_modal.html) for
delete confirmations.

### RSS tab columns

`Name` · `URL` · `Category` · `Enabled` (toggle) · `Last fetched` · `Last error` ·
Actions (`Edit`, `Delete`). Inline add row, same shape as the blacklist card's add input.

### Sidebar

Add a link under the existing admin group in
[`_sidebar_content.html`](../web_dashboard/templates/components/_sidebar_content.html),
following the `/admin/ai-settings` entry's markup exactly (`current_page=='admin_sources'`).

---

## 7. Guardrails

1. **Do not alter the `rss_feeds` contract.** `SELECT id, name, url FROM rss_feeds WHERE
   enabled = true` and the `last_fetched_at` update must keep working verbatim. Additive
   columns only.
2. **`enabled` must mean something.** Toggling a row off in the UI has to actually stop
   collection — for RSS that already holds; for YouTube the K3 job must filter on it.
3. **Admin-gate everything**, and honor read-only admins on writes.
4. **No network in unit tests.** Mock `fetch_caption_text`; the K1 test suite
   ([`tests/test_youtube_captions.py`](../tests/test_youtube_captions.py)) shows the
   `monkeypatch.setitem(sys.modules, ...)` pattern to follow.
5. **Do not touch `scheduler/jobs.py` cron windows.** No job is added by this work. When K3
   lands, mind the ET/PT collision footgun documented in `PHASE_JK_PLAN.md`.
6. **`youtube.com` is not a blacklistable domain.** Source health is keyed per channel
   (`youtube:{channel_id}`), never per host — one bad channel must not blacklist all of
   YouTube. See `PHASE_JK_PLAN.md` domain-health row.
7. Treat pasted bulk-import text as untrusted: validate ticker symbols against a charset,
   cap row count, and never interpolate it into SQL.

---

## 8. Task order

1. Migrations + schema-allowlist registration + apply script. Verify `rss_feeds` job still runs.
2. `sources_routes.py` with RSS CRUD only. Ship it — this alone kills the throwaway-script workflow.
3. `sources.html` with the RSS tab + sidebar link.
4. `youtube_sources` CRUD endpoints + YouTube tab (no bulk, no test yet).
5. Test button wired to `fetch_caption_text`.
6. Bulk preview/commit + modal.
7. Seed script for the initial researched channel list.

Steps 1–3 are independently valuable and carry no Phase-K dependency; do not block them on
the YouTube list being finalized.

---

## 9. Acceptance criteria

- [ ] `youtube_sources` exists with the constraints above; `rss_feeds` gained its 4 columns
      and the nightly RSS job still succeeds unchanged.
      *(DDL + apply script landed — run*
      `python web_dashboard/scripts/apply_sources_migrations.py`*)*
- [ ] `/admin/sources` renders both tabs; non-admins get the standard denial; read-only
      admins can view but every write returns 403.
- [ ] An RSS feed can be added, renamed, toggled, and deleted entirely from the UI, and the
      change is picked up by the next `rss_feed_ingest` run.
- [ ] A YouTube channel can be added by `@handle`; `channel_id` is resolved and stored.
- [ ] `Test` on a captioned public video returns language + char count; on a captions-disabled
      video returns `no_captions` and sets `captions_ok = false`.
- [ ] Pasting the researcher's list twice results in the same row count the second time.
- [ ] Unit tests cover bulk-preview classification (new/duplicate/invalid) and the 403
      read-only path, with no network calls.

---

## 10. Open questions

- Should `confidence_weight` be surfaced in the ingest prompt as a number, or bucketed to
  words ("confirmed teardown" vs "unverified leak") before it reaches the LLM? Bucketing is
  probably more reliable but is a K4 concern, not a UI one.
- Do search-kind sources need their own cadence field, or is one global poll interval enough
  for v1? Assume global until proven otherwise.
- Whether to show a per-source "articles produced / last 30d" count once K3 is live — cheap
  to add, but needs a join against `research_articles.source`.
