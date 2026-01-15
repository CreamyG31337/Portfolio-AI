-- Table: research_articles
DROP TABLE IF EXISTS research_articles CASCADE;

CREATE TABLE research_articles (
    id UUID NOT NULL DEFAULT gen_random_uuid(),
    ticker VARCHAR(20),
    sector VARCHAR(100),
    article_type VARCHAR(50),
    title TEXT NOT NULL,
    url TEXT,
    summary TEXT,
    content TEXT,
    source VARCHAR(100),
    published_at TIMESTAMP,
    fetched_at TIMESTAMP DEFAULT now(),
    relevance_score NUMERIC(3, 2),
    embedding NULL,
    tickers ARRAY,
    fund VARCHAR(100),
    claims JSONB,
    fact_check TEXT,
    conclusion TEXT,
    sentiment VARCHAR(20),
    sentiment_score DOUBLE PRECISION,
    logic_check VARCHAR(20),
    archive_submitted_at TIMESTAMP,
    archive_checked_at TIMESTAMP,
    archive_url TEXT
,
    PRIMARY KEY (id)
);

-- Indexes
CREATE INDEX idx_research_articles_archive_submitted ON research_articles (archive_submitted_at);
CREATE INDEX idx_research_articles_archive_url ON research_articles (archive_url);
CREATE INDEX idx_research_claims ON research_articles (claims);
CREATE INDEX idx_research_fetched ON research_articles (fetched_at);
CREATE INDEX idx_research_fund ON research_articles (fund);
CREATE INDEX idx_research_logic_check ON research_articles (logic_check);
CREATE INDEX idx_research_sentiment ON research_articles (sentiment);
CREATE INDEX idx_research_sentiment_score ON research_articles (sentiment_score);
CREATE INDEX idx_research_ticker ON research_articles (ticker);
CREATE INDEX idx_research_tickers_gin ON research_articles (tickers);
CREATE INDEX idx_research_type ON research_articles (article_type);
CREATE UNIQUE INDEX research_articles_url_key ON research_articles (url);