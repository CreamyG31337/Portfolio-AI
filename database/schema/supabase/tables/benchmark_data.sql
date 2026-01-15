-- Table: benchmark_data
DROP TABLE IF EXISTS benchmark_data CASCADE;

CREATE TABLE benchmark_data (
    id BIGINT NOT NULL DEFAULT nextval('benchmark_data_id_seq'::regclass),
    ticker TEXT NOT NULL,
    date DATE NOT NULL,
    open NUMERIC(12, 4),
    high NUMERIC(12, 4),
    low NUMERIC(12, 4),
    close NUMERIC(12, 4) NOT NULL,
    volume BIGINT,
    adjusted_close NUMERIC(12, 4),
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now()
,
    PRIMARY KEY (id)
);

-- Indexes
CREATE UNIQUE INDEX benchmark_data_ticker_date_key ON benchmark_data (ticker, date);
CREATE INDEX idx_benchmark_ticker_date ON benchmark_data (ticker, date);