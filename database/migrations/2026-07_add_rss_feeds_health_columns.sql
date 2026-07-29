-- Research DB: additive rss_feeds health columns for /admin/sources.
-- Same as migrations/009_add_rss_feeds_health_columns.sql.

ALTER TABLE rss_feeds ADD COLUMN IF NOT EXISTS notes TEXT;
ALTER TABLE rss_feeds ADD COLUMN IF NOT EXISTS consecutive_failures INTEGER NOT NULL DEFAULT 0;
ALTER TABLE rss_feeds ADD COLUMN IF NOT EXISTS last_error TEXT;
ALTER TABLE rss_feeds ADD COLUMN IF NOT EXISTS last_success_at TIMESTAMPTZ;
