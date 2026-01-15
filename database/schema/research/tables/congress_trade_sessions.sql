-- Table: congress_trade_sessions
DROP TABLE IF EXISTS congress_trade_sessions CASCADE;

CREATE TABLE congress_trade_sessions (
    id INTEGER NOT NULL DEFAULT nextval('congress_trade_sessions_id_seq'::regclass),
    politician_id INTEGER,
    politician_name VARCHAR(255) NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    trade_count INTEGER DEFAULT 0,
    total_value_estimate VARCHAR(100),
    conflict_score NUMERIC(3, 2),
    confidence_score NUMERIC(3, 2),
    ai_summary TEXT,
    last_analyzed_at TIMESTAMP,
    needs_reanalysis BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now(),
    model_used VARCHAR(100),
    analysis_version INTEGER DEFAULT 1,
    risk_pattern VARCHAR(20)
,
    PRIMARY KEY (id)
);

-- Indexes
CREATE INDEX idx_congress_trade_sessions_dates ON congress_trade_sessions (start_date, end_date);
CREATE INDEX idx_congress_trade_sessions_needs_reanalysis ON congress_trade_sessions (needs_reanalysis);
CREATE INDEX idx_congress_trade_sessions_politician ON congress_trade_sessions (politician_name);
CREATE INDEX idx_congress_trade_sessions_risk_pattern ON congress_trade_sessions (risk_pattern);
CREATE INDEX idx_congress_trade_sessions_score ON congress_trade_sessions (conflict_score);
CREATE UNIQUE INDEX unique_politician_date_range ON congress_trade_sessions (politician_name, start_date, end_date);