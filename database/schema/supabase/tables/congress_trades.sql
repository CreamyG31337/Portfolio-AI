-- Table: congress_trades
DROP TABLE IF EXISTS congress_trades CASCADE;

CREATE TABLE congress_trades (
    id INTEGER NOT NULL DEFAULT nextval('congress_trades_id_seq'::regclass),
    ticker VARCHAR(20) NOT NULL,
    chamber VARCHAR(20) NOT NULL,
    transaction_date DATE NOT NULL,
    disclosure_date DATE NOT NULL,
    type VARCHAR(20) NOT NULL,
    amount VARCHAR(100),
    asset_type VARCHAR(50),
    conflict_score DOUBLE PRECISION,
    notes TEXT,
    created_at TIMESTAMP DEFAULT now(),
    price NUMERIC(10, 2) DEFAULT NULL::numeric,
    party VARCHAR(50),
    state VARCHAR(2),
    owner VARCHAR(100) NOT NULL DEFAULT 'Unknown'::character varying,
    politician_id INTEGER
,
    PRIMARY KEY (id)
);

-- Foreign Keys
ALTER TABLE congress_trades ADD CONSTRAINT fk_congress_trades_politician FOREIGN KEY (politician_id) REFERENCES politicians(id);

-- Indexes
CREATE UNIQUE INDEX congress_trades_politician_ticker_date_amount_type_owner_key ON congress_trades (politician_id, ticker, transaction_date, amount, type, owner);
CREATE INDEX idx_congress_chamber ON congress_trades (chamber);
CREATE INDEX idx_congress_conflict_score ON congress_trades (conflict_score);
CREATE INDEX idx_congress_disclosure_date ON congress_trades (disclosure_date);
CREATE INDEX idx_congress_owner ON congress_trades (owner);
CREATE INDEX idx_congress_party ON congress_trades (party);
CREATE INDEX idx_congress_state ON congress_trades (state);
CREATE INDEX idx_congress_ticker ON congress_trades (ticker);
CREATE INDEX idx_congress_trades_politician_id ON congress_trades (politician_id);
CREATE INDEX idx_congress_transaction_date ON congress_trades (transaction_date);