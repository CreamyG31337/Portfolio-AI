-- Table: congress_trades_staging
DROP TABLE IF EXISTS congress_trades_staging CASCADE;

CREATE TABLE congress_trades_staging (
    id INTEGER NOT NULL DEFAULT nextval('congress_trades_staging_id_seq'::regclass),
    ticker VARCHAR(20) NOT NULL,
    politician VARCHAR(200) NOT NULL,
    chamber VARCHAR(20) NOT NULL,
    transaction_date DATE NOT NULL,
    disclosure_date DATE NOT NULL,
    type VARCHAR(20) NOT NULL,
    amount VARCHAR(100),
    price NUMERIC(10, 2) DEFAULT NULL::numeric,
    asset_type VARCHAR(50),
    party VARCHAR(50),
    state VARCHAR(2),
    owner VARCHAR(100),
    conflict_score DOUBLE PRECISION,
    notes TEXT,
    import_batch_id UUID DEFAULT gen_random_uuid(),
    import_timestamp TIMESTAMP DEFAULT now(),
    validation_status VARCHAR(20) DEFAULT 'pending'::character varying,
    validation_notes TEXT,
    promoted_to_production BOOLEAN DEFAULT false,
    promoted_at TIMESTAMP,
    source_url TEXT,
    raw_data JSONB
,
    PRIMARY KEY (id)
);

-- Indexes
CREATE INDEX idx_staging_batch ON congress_trades_staging (import_batch_id);
CREATE INDEX idx_staging_date ON congress_trades_staging (transaction_date);
CREATE INDEX idx_staging_politician ON congress_trades_staging (politician);
CREATE INDEX idx_staging_promoted ON congress_trades_staging (promoted_to_production);
CREATE INDEX idx_staging_status ON congress_trades_staging (validation_status);
CREATE INDEX idx_staging_ticker ON congress_trades_staging (ticker);