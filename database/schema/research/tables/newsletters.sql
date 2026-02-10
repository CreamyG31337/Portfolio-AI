-- Table: newsletters
DROP TABLE IF EXISTS newsletters CASCADE;

CREATE TABLE newsletters (
    id UUID NOT NULL DEFAULT gen_random_uuid(),
    sender VARCHAR(500) NOT NULL,
    sender_name VARCHAR(500),
    recipient VARCHAR(500) NOT NULL,
    subject TEXT NOT NULL,
    body_plain TEXT,
    body_html TEXT,
    tickers ARRAY,
    summary TEXT,
    embedding NULL,
    received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    processed_at TIMESTAMP,
    message_id VARCHAR(500),
    article_url TEXT,
    ticker_sentiment JSONB
,
    PRIMARY KEY (id)
);

-- Indexes
CREATE INDEX idx_newsletters_embedding ON newsletters (embedding);
CREATE INDEX idx_newsletters_received_at ON newsletters (received_at);
CREATE INDEX idx_newsletters_sender ON newsletters (sender);
CREATE INDEX idx_newsletters_tickers ON newsletters (tickers);
CREATE UNIQUE INDEX newsletters_message_id_unique ON newsletters (message_id);