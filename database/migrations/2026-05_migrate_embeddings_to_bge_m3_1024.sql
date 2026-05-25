-- Migrate research DB embeddings from nomic-embed-text (vector(768)) to bge-m3 (vector(1024)).
--
-- This intentionally clears existing embeddings because 768-dim nomic vectors
-- and 1024-dim bge-m3 vectors are not comparable. Refill with:
--   python web_dashboard/scripts/reembed_research_vectors.py

CREATE EXTENSION IF NOT EXISTS vector;

DROP INDEX IF EXISTS idx_newsletters_embedding;
DROP INDEX IF EXISTS idx_research_articles_embedding;
DROP INDEX IF EXISTS idx_ticker_analysis_embedding;

UPDATE newsletters SET embedding = NULL WHERE embedding IS NOT NULL;
UPDATE research_articles SET embedding = NULL WHERE embedding IS NOT NULL;
UPDATE ticker_analysis SET embedding = NULL WHERE embedding IS NOT NULL;

ALTER TABLE newsletters
    ALTER COLUMN embedding TYPE vector(1024);

ALTER TABLE research_articles
    ALTER COLUMN embedding TYPE vector(1024);

ALTER TABLE ticker_analysis
    ALTER COLUMN embedding TYPE vector(1024);

CREATE INDEX IF NOT EXISTS idx_newsletters_embedding
    ON newsletters
    USING hnsw (embedding vector_cosine_ops);

CREATE INDEX IF NOT EXISTS idx_research_articles_embedding
    ON research_articles
    USING hnsw (embedding vector_cosine_ops);

CREATE INDEX IF NOT EXISTS idx_ticker_analysis_embedding
    ON ticker_analysis
    USING hnsw (embedding vector_cosine_ops);
