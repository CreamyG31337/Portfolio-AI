-- Phase K sources UI: youtube_sources allowlist (Research DB).
-- Additive. Safe to re-run. See docs/PHASE_K_SOURCES_UI_PLAN.md.

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
  last_error_reason       VARCHAR(32),  -- yt_captions.FailureReason literal
  captions_ok             BOOLEAN,      -- NULL = never tested

  -- provenance
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

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'youtube_sources_kind_target_chk'
  ) THEN
    ALTER TABLE youtube_sources ADD CONSTRAINT youtube_sources_kind_target_chk
      CHECK (
        (kind = 'search' AND query_text IS NOT NULL)
        OR (kind <> 'search' AND (channel_id IS NOT NULL OR handle IS NOT NULL))
      );
  END IF;
END $$;

COMMENT ON TABLE youtube_sources IS
  'Allowlisted YouTube channels/playlists/IR/search queries for Phase K caption ingest. Managed via /admin/sources.';
COMMENT ON COLUMN youtube_sources.last_error_reason IS
  'yt_captions.FailureReason: no_captions | blocked | age_restricted | unavailable | dependency | parse | unknown';
COMMENT ON COLUMN youtube_sources.confidence_weight IS
  'Downstream LLM confidence multiplier (0.00–2.00). Bucketing vs numeric is a K4 concern.';
