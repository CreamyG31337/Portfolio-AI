-- Table: market_relationships
DROP TABLE IF EXISTS market_relationships CASCADE;

CREATE TABLE market_relationships (
    id INTEGER NOT NULL DEFAULT nextval('market_relationships_id_seq'::regclass),
    source_ticker VARCHAR(20) NOT NULL,
    target_ticker VARCHAR(20) NOT NULL,
    relationship_type VARCHAR(50) NOT NULL,
    confidence_score DOUBLE PRECISION DEFAULT 0.0,
    detected_at TIMESTAMP DEFAULT now(),
    source_article_id UUID
,
    PRIMARY KEY (id)
);

-- Foreign Keys
ALTER TABLE market_relationships ADD CONSTRAINT market_relationships_source_article_id_fkey FOREIGN KEY (source_article_id) REFERENCES research_articles(id);

-- Indexes
CREATE INDEX idx_relationships_article ON market_relationships (source_article_id);
CREATE INDEX idx_relationships_confidence ON market_relationships (confidence_score);
CREATE INDEX idx_relationships_source ON market_relationships (source_ticker);
CREATE INDEX idx_relationships_source_confidence ON market_relationships (source_ticker, confidence_score);
CREATE INDEX idx_relationships_target ON market_relationships (target_ticker);
CREATE INDEX idx_relationships_type ON market_relationships (relationship_type);
CREATE UNIQUE INDEX unique_relationship ON market_relationships (source_ticker, target_ticker, relationship_type);