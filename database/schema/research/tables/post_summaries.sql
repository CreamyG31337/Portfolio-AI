-- Table: post_summaries
DROP TABLE IF EXISTS post_summaries CASCADE;

CREATE TABLE post_summaries (
    id INTEGER NOT NULL DEFAULT nextval('post_summaries_id_seq'::regclass),
    post_id INTEGER NOT NULL,
    summary TEXT NOT NULL,
    key_points ARRAY,
    sentiment_impact NUMERIC(3, 2),
    summarized_at TIMESTAMP DEFAULT now()
,
    PRIMARY KEY (id)
);