-- AQuA transfer Phase 3: after-cost excess + belief label on stance_outcomes.
-- Additive; safe to re-run.

ALTER TABLE stance_outcomes
    ADD COLUMN IF NOT EXISTS cost_bps SMALLINT;

ALTER TABLE stance_outcomes
    ADD COLUMN IF NOT EXISTS excess_after_cost NUMERIC(10, 6);

ALTER TABLE stance_outcomes
    ADD COLUMN IF NOT EXISTS belief_status VARCHAR(20);

COMMENT ON COLUMN stance_outcomes.cost_bps IS
  'Assumed round-trip cost in basis points applied when scoring (micro-cap cost model).';

COMMENT ON COLUMN stance_outcomes.excess_after_cost IS
  'excess_return minus cost_bps/100 (percentage points).';

COMMENT ON COLUMN stance_outcomes.belief_status IS
  'supported | refuted | inconclusive after cost and direction.';
