-- Table: congress_trades_analysis
DROP TABLE IF EXISTS congress_trades_analysis CASCADE;

CREATE TABLE congress_trades_analysis (
    id INTEGER NOT NULL DEFAULT nextval('congress_trades_analysis_id_seq'::regclass),
    trade_id INTEGER NOT NULL,
    conflict_score NUMERIC(3, 2),
    reasoning TEXT,
    model_used VARCHAR(100) NOT NULL DEFAULT 'granite3.3:8b'::character varying,
    analyzed_at TIMESTAMP DEFAULT now(),
    analysis_version INTEGER DEFAULT 1,
    confidence_score NUMERIC(3, 2),
    session_id INTEGER,
    risk_pattern VARCHAR(20)
,
    PRIMARY KEY (id)
);

-- Foreign Keys
ALTER TABLE congress_trades_analysis ADD CONSTRAINT congress_trades_analysis_session_id_fkey FOREIGN KEY (session_id) REFERENCES congress_trade_sessions(id);

-- Indexes
CREATE UNIQUE INDEX congress_trades_analysis_unique_trade_model_version ON congress_trades_analysis (trade_id, model_used, analysis_version);
CREATE INDEX idx_congress_trades_analysis_analyzed_at ON congress_trades_analysis (analyzed_at);
CREATE INDEX idx_congress_trades_analysis_confidence ON congress_trades_analysis (confidence_score);
CREATE INDEX idx_congress_trades_analysis_risk_pattern ON congress_trades_analysis (risk_pattern);
CREATE INDEX idx_congress_trades_analysis_score ON congress_trades_analysis (conflict_score);
CREATE INDEX idx_congress_trades_analysis_session ON congress_trades_analysis (session_id);
CREATE INDEX idx_congress_trades_analysis_trade_id ON congress_trades_analysis (trade_id);