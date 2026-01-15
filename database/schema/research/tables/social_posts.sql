-- Table: social_posts
DROP TABLE IF EXISTS social_posts CASCADE;

CREATE TABLE social_posts (
    id INTEGER NOT NULL DEFAULT nextval('social_posts_id_seq'::regclass),
    metric_id INTEGER,
    platform VARCHAR(20) NOT NULL,
    post_id VARCHAR(100),
    content TEXT NOT NULL,
    author VARCHAR(100),
    posted_at TIMESTAMP,
    engagement_score INTEGER DEFAULT 0,
    url TEXT,
    extracted_tickers ARRAY,
    created_at TIMESTAMP DEFAULT now()
,
    PRIMARY KEY (id)
);

-- Foreign Keys
ALTER TABLE social_posts ADD CONSTRAINT social_posts_metric_id_fkey FOREIGN KEY (metric_id) REFERENCES social_metrics(id);