-- Phase I1: story dedup + corroboration on research_articles.
--
-- Exact URL dedup already exists. Near-duplicate headlines from SearXNG + RSS
-- (same catalyst, different wording/URL) still double-extract and inflate
-- independent-evidence counts. These columns let ingest skip re-summarize on a
-- story match and record how many distinct publishers covered it.
--
-- Additive only. Safe to re-run.

ALTER TABLE research_articles
    ADD COLUMN IF NOT EXISTS corroboration_count INT NOT NULL DEFAULT 1;

ALTER TABLE research_articles
    ADD COLUMN IF NOT EXISTS corroboration_sources TEXT[] NOT NULL DEFAULT '{}';

COMMENT ON COLUMN research_articles.corroboration_count IS
  'Distinct publisher count for this story cluster (Phase I1). Starts at 1; increments when another source matches via story_identity.';
COMMENT ON COLUMN research_articles.corroboration_sources IS
  'Normalized publisher keys (usually URL hosts) that have corroborated this article.';

CREATE INDEX IF NOT EXISTS idx_research_articles_corroboration
    ON research_articles (corroboration_count DESC)
    WHERE corroboration_count > 1;
