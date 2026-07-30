-- Phase K2: per-collector metadata for research_articles.
--
-- YouTube transcripts need video_id / channel_id / duration_s / caption_lang /
-- caption_kind alongside the article row. The existing JSONB columns are already
-- semantically owned by the summarizer (``claims`` = CoT step 1,
-- ``ticker_sentiment`` = per-ticker sentiment), so stuffing collector facts into
-- them would collide with every re-summarize. One generic, nullable JSONB column
-- keeps the schema minimal while staying reusable for future collectors instead
-- of adding a youtube-specific column now.
--
-- Additive only. Safe to re-run.

ALTER TABLE research_articles
    ADD COLUMN IF NOT EXISTS source_metadata JSONB;

COMMENT ON COLUMN research_articles.source_metadata IS
  'Collector-specific facts about where this row came from (Phase K2). YouTube Transcript rows carry video_id, channel_id, channel, duration_s, caption_lang, caption_kind (manual|auto), fetch_source, truncated. Never written by the summarizer — safe to re-enrich an article without losing provenance.';

CREATE INDEX IF NOT EXISTS idx_research_articles_source_metadata
    ON research_articles USING gin (source_metadata)
    WHERE source_metadata IS NOT NULL;
