-- Table: exchange_rates
DROP TABLE IF EXISTS exchange_rates CASCADE;

CREATE TABLE exchange_rates (
    id UUID NOT NULL DEFAULT uuid_generate_v4(),
    from_currency VARCHAR(3) NOT NULL,
    to_currency VARCHAR(3) NOT NULL,
    rate NUMERIC(10, 6) NOT NULL,
    timestamp TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT now()
,
    PRIMARY KEY (id)
);

-- Indexes
CREATE UNIQUE INDEX exchange_rates_from_currency_to_currency_timestamp_key ON exchange_rates (from_currency, to_currency, timestamp);
CREATE INDEX idx_exchange_rates_currencies ON exchange_rates (from_currency, to_currency);
CREATE INDEX idx_exchange_rates_currencies_timestamp ON exchange_rates (from_currency, to_currency, timestamp);
CREATE INDEX idx_exchange_rates_timestamp ON exchange_rates (timestamp);