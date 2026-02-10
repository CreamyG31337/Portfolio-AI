-- Table: signal_analysis
DROP TABLE IF EXISTS signal_analysis CASCADE;

CREATE TABLE signal_analysis (
    id INTEGER NOT NULL DEFAULT nextval('signal_analysis_id_seq'::regclass),
    ticker VARCHAR(20) NOT NULL,
    analysis_date TIMESTAMP NOT NULL,
    structure_signal JSONB,
    timing_signal JSONB,
    fear_risk_signal JSONB,
    overall_signal VARCHAR(10),
    confidence_score DOUBLE PRECISION,
    explanation TEXT,
    created_at TIMESTAMP DEFAULT now(),
    momentum_signal JSONB,
    fundamental_signal JSONB
,
    PRIMARY KEY (id)
);

-- Indexes
CREATE INDEX idx_signal_analysis_signal ON signal_analysis (overall_signal);
CREATE INDEX idx_signal_analysis_ticker_date ON signal_analysis (ticker, analysis_date);
CREATE UNIQUE INDEX signal_analysis_ticker_analysis_date_key ON signal_analysis (ticker, analysis_date);