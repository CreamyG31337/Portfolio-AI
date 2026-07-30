-- Mirror of migrations/008_create_yt_sources.sql for clean Research schema exports.
-- Table: youtube_sources

CREATE TABLE IF NOT EXISTS youtube_sources (
  id                      SERIAL PRIMARY KEY,
  kind                    VARCHAR(20)  NOT NULL DEFAULT 'channel',
  channel_id              VARCHAR(64),
  handle                  VARCHAR(120),
  query_text              TEXT,
  label                   VARCHAR(200) NOT NULL,
  alpha_mechanism         VARCHAR(20),
  confidence_weight       NUMERIC(3,2) NOT NULL DEFAULT 1.00,
  expected_tickers        TEXT[]       NOT NULL DEFAULT '{}',
  enabled                 BOOLEAN      NOT NULL DEFAULT true,
  max_videos_per_poll     INTEGER      NOT NULL DEFAULT 5,
  min_duration_s          INTEGER      NOT NULL DEFAULT 120,
  max_duration_s          INTEGER,
  last_video_id           VARCHAR(16),
  last_seen_at            TIMESTAMPTZ,
  last_polled_at          TIMESTAMPTZ,
  last_success_at         TIMESTAMPTZ,
  consecutive_failures    INTEGER      NOT NULL DEFAULT 0,
  last_error_reason       VARCHAR(32),
  captions_ok             BOOLEAN,
  notes                   TEXT,
  added_by                VARCHAR(200),
  source_of_recommendation VARCHAR(200),
  created_at              TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  updated_at              TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_youtube_sources_channel
  ON youtube_sources(channel_id) WHERE channel_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_youtube_sources_query
  ON youtube_sources(query_text) WHERE query_text IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_youtube_sources_enabled
  ON youtube_sources(enabled) WHERE enabled = true;
