-- Table: rss_feeds
DROP TABLE IF EXISTS rss_feeds CASCADE;

CREATE TABLE rss_feeds (
    id INTEGER NOT NULL DEFAULT nextval('rss_feeds_id_seq'::regclass),
    name VARCHAR(200) NOT NULL,
    url TEXT NOT NULL,
    category VARCHAR(100),
    enabled BOOLEAN DEFAULT true,
    last_fetched_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now()
,
    PRIMARY KEY (id)
);

-- Indexes
CREATE INDEX idx_rss_feeds_enabled ON rss_feeds (enabled);
CREATE INDEX idx_rss_feeds_last_fetched ON rss_feeds (last_fetched_at);
CREATE UNIQUE INDEX rss_feeds_url_key ON rss_feeds (url);