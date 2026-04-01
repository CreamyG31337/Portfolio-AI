-- Cached LLM verdicts cross-checking action-queue rows vs saved research.

CREATE TABLE IF NOT EXISTS action_queue_ai_review (
    id UUID NOT NULL DEFAULT gen_random_uuid(),
    fund_key TEXT NOT NULL DEFAULT '',
    ticker VARCHAR(20) NOT NULL,
    signal_analysis_date DATE,
    verdict VARCHAR(30) NOT NULL,
    one_liner TEXT,
    model_used VARCHAR(100),
    updated_at TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (id),
    CONSTRAINT action_queue_ai_review_unique_key UNIQUE (fund_key, ticker, signal_analysis_date)
);

CREATE INDEX IF NOT EXISTS idx_action_queue_ai_review_ticker ON action_queue_ai_review (ticker);
CREATE INDEX IF NOT EXISTS idx_action_queue_ai_review_updated ON action_queue_ai_review (updated_at DESC);

COMMENT ON TABLE action_queue_ai_review IS 'Optional cached AI alignment check for dashboard action queue rows';
