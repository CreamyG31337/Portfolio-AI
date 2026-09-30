-- Migration: Fix ticker_analysis index + column widths
-- Date: 2026-05-20
-- Description:
--   Three independent bugs were causing every nightly ticker_analysis insert
--   to fail for a different subset of tickers, which (combined with the old
--   skip-list policy) permanently banned 84 tickers in January 2026:
--
--   1. ``idx_ticker_analysis_embedding`` was a btree index on a vector(768)
--      column. btree's max row size is 2704 bytes; a 768-dim float vector is
--      ~3072 bytes, so every insert with an embedding raised:
--          "index row size 3088 exceeds btree version 4 maximum 2704"
--      The correct index for vector similarity search is HNSW (or IVFFLAT).
--
--   2. Several ``VARCHAR(20)`` columns were too narrow for verbose LLM
--      responses (e.g. timeframe="short-term swing 1-2 weeks") raising:
--          "value too long for type character varying(20)"
--      The DB columns are widened here; the application code also defensively
--      truncates / normalizes before insert.
--
--   3. ``sentiment_score`` and ``confidence_score`` were ``NUMERIC(3,2)``
--      (range -9.99..9.99). LLMs occasionally returned percentage-scale
--      values (e.g. 50 instead of 0.5) raising:
--          "numeric field overflow ... precision 3, scale 2"
--      The columns are widened here as a backstop; the application code also
--      auto-scales 0-100 → 0-1 and clamps to [-1, 1] before insert.

BEGIN;

-- Bug 1: vector index ----------------------------------------------------------
DROP INDEX IF EXISTS idx_ticker_analysis_embedding;

-- Cosine distance is the standard for sentence-transformer-style embeddings;
-- HNSW is the modern pgvector default and outperforms IVFFLAT on small/medium
-- tables. Adjust `m` / `ef_construction` later if recall needs tuning.
CREATE INDEX idx_ticker_analysis_embedding
    ON ticker_analysis
    USING hnsw (embedding vector_cosine_ops);

-- Bug 2: widen verbose string columns ------------------------------------------
ALTER TABLE ticker_analysis
    ALTER COLUMN sentiment      TYPE VARCHAR(40),
    ALTER COLUMN timeframe      TYPE VARCHAR(60),
    ALTER COLUMN target_price   TYPE VARCHAR(60),
    ALTER COLUMN stop_loss      TYPE VARCHAR(60),
    ALTER COLUMN entry_zone     TYPE VARCHAR(100),
    ALTER COLUMN stance         TYPE VARCHAR(20);

-- Bug 3: widen score precision (still tightly constrained, but no false overflows) -
ALTER TABLE ticker_analysis
    ALTER COLUMN sentiment_score  TYPE NUMERIC(5, 4),
    ALTER COLUMN confidence_score TYPE NUMERIC(5, 4);

COMMIT;
