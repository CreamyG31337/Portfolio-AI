-- Failed stance_outcomes scoring attempts (measurement rig M1).
-- Rows are excluded from the scoring queue once attempts >= MAX_SCORING_ATTEMPTS,
-- which prevents unpriceable stances from head-of-line blocking the as_of ASC window.
CREATE TABLE IF NOT EXISTS stance_outcome_attempts (
    stance_id UUID NOT NULL,
    horizon_days SMALLINT NOT NULL,
    attempts INT NOT NULL DEFAULT 0,
    last_reason TEXT,
    last_attempt_at TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (stance_id, horizon_days)
);

CREATE INDEX IF NOT EXISTS idx_stance_outcome_attempts_reason
    ON stance_outcome_attempts (last_reason, attempts DESC);

COMMENT ON TABLE stance_outcome_attempts IS 'Dead-letter tracking for stance outcome scoring (measurement rig M1)';
