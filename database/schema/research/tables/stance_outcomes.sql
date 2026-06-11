-- Scored returns for stance_history rows at 7/30/90-day horizons.
CREATE TABLE IF NOT EXISTS stance_outcomes (
    id UUID NOT NULL DEFAULT gen_random_uuid(),
    stance_id UUID NOT NULL REFERENCES stance_history (id) ON DELETE CASCADE,
    horizon_days SMALLINT NOT NULL,
    baseline_price NUMERIC(14, 4),
    end_price NUMERIC(14, 4),
    ticker_return NUMERIC(10, 6),
    benchmark_return NUMERIC(10, 6),
    excess_return NUMERIC(10, 6),
    scored_at TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (id),
    CONSTRAINT stance_outcomes_unique UNIQUE (stance_id, horizon_days)
);

CREATE INDEX IF NOT EXISTS idx_stance_outcomes_stance ON stance_outcomes (stance_id);

COMMENT ON TABLE stance_outcomes IS
    'Directional outcome scores vs ^RUT; V1 scores BUY/SELL only';
