-- Phase K sources UI: additive health/notes columns on rss_feeds.
-- Does NOT change the load-bearing SELECT id, name, url / last_fetched_at contract.
-- Safe to re-run. See docs/PHASE_K_SOURCES_UI_PLAN.md.

ALTER TABLE rss_feeds ADD COLUMN IF NOT EXISTS notes TEXT;
ALTER TABLE rss_feeds ADD COLUMN IF NOT EXISTS consecutive_failures INTEGER NOT NULL DEFAULT 0;
ALTER TABLE rss_feeds ADD COLUMN IF NOT EXISTS last_error TEXT;
ALTER TABLE rss_feeds ADD COLUMN IF NOT EXISTS last_success_at TIMESTAMPTZ;

COMMENT ON COLUMN rss_feeds.notes IS
  'Admin notes for /admin/sources. Optional.';
COMMENT ON COLUMN rss_feeds.consecutive_failures IS
  'Ingest failure streak. Populated by a follow-up job change; UI shows — when unused.';
COMMENT ON COLUMN rss_feeds.last_error IS
  'Last ingest error message. Optional until the RSS job writes it.';
COMMENT ON COLUMN rss_feeds.last_success_at IS
  'Last successful ingest timestamp. Optional until the RSS job writes it.';
