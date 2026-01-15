-- Table: extracted_tickers
DROP TABLE IF EXISTS extracted_tickers CASCADE;

CREATE TABLE extracted_tickers (
    id INTEGER NOT NULL DEFAULT nextval('extracted_tickers_id_seq'::regclass),
    analysis_id INTEGER,
    ticker VARCHAR(20) NOT NULL,
    confidence NUMERIC(3, 2),
    context TEXT,
    is_primary BOOLEAN DEFAULT false,
    company_name VARCHAR(200),
    sector VARCHAR(100),
    extracted_at TIMESTAMP DEFAULT now()
,
    PRIMARY KEY (id)
);

-- Foreign Keys
ALTER TABLE extracted_tickers ADD CONSTRAINT extracted_tickers_analysis_id_fkey FOREIGN KEY (analysis_id) REFERENCES social_sentiment_analysis(id);