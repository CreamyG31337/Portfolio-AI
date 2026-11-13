-- Migration: corporate_actions ledger + transactional stock-split apply
-- Date: 2026-11-13
-- Database: Supabase (production app DB)
--
-- The daily price job rebuilds share counts from trade_log on every run, so a
-- split that nobody applies by hand leaves the old share count multiplied by
-- the new post-split price. ITA 3:1 (2026-11-05) and CRWD 4:1 (2026-07-02)
-- both went unnoticed that way. web_dashboard/split_guard.py now detects splits
-- and calls apply_stock_split(); this table is the ledger that keeps a split
-- from ever being applied twice (MNST was applied by hand, seeded below).

CREATE TABLE IF NOT EXISTS corporate_actions (
    id                  BIGSERIAL PRIMARY KEY,
    fund                VARCHAR(100)  NOT NULL,
    ticker              VARCHAR(20)   NOT NULL,
    action_type         VARCHAR(20)   NOT NULL DEFAULT 'split'
                        CHECK (action_type IN ('split')),
    -- Ex-date as the data provider stamps it.
    ex_date             DATE          NOT NULL,
    -- New shares per old share (3 for 3:1, 0.1 for 1:10).
    ratio               NUMERIC(12,6) NOT NULL CHECK (ratio > 0),
    -- 'applied': trade_log and positions adjusted.
    -- 'unconfirmed': the provider reported a split but our stored prices never
    --  showed the matching cliff; left alone on purpose (see split_guard.py).
    status              VARCHAR(20)   NOT NULL CHECK (status IN ('applied', 'unconfirmed')),
    -- First portfolio_positions date carrying the post-split price. Trades
    -- before it were adjusted, position rows on/after it were adjusted.
    cliff_date          DATE,
    trades_adjusted     INTEGER,
    positions_adjusted  INTEGER,
    source              VARCHAR(40)   NOT NULL,
    notes               TEXT,
    created_at          TIMESTAMPTZ   NOT NULL DEFAULT now(),
    UNIQUE (fund, ticker, action_type, ex_date)
);

ALTER TABLE corporate_actions ENABLE ROW LEVEL SECURITY;

COMMENT ON TABLE corporate_actions IS
    'Ledger of stock splits applied to trade_log/portfolio_positions. The unique '
    'key stops split_guard from applying the same split twice.';

-- Splits already applied by hand before the ledger existed.
INSERT INTO corporate_actions
    (fund, ticker, ex_date, ratio, status, cliff_date, source, notes, created_at)
VALUES
    ('RRSP Lance Webull', 'MNST', '2026-08-11', 2, 'applied', '2026-08-10', 'manual',
     'debug/apply_stock_split.py + targeted position repair; see docs/corporate_actions.md',
     '2026-08-13'),
    ('TFSA', 'MNST', '2026-08-11', 2, 'applied', '2026-08-10', 'manual',
     'debug/apply_stock_split.py + targeted position repair; see docs/corporate_actions.md',
     '2026-08-13')
ON CONFLICT (fund, ticker, action_type, ex_date) DO NOTHING;

-- Applies one split in a single transaction. The ledger insert comes first, so
-- a second call for the same (fund, ticker, ex_date) fails on the unique key
-- and adjusts nothing. Trade rows are cut at the ET calendar date.
CREATE OR REPLACE FUNCTION apply_stock_split(
    p_fund        TEXT,
    p_ticker      TEXT,
    p_ex_date     DATE,
    p_ratio       NUMERIC,
    p_cliff_date  DATE,
    p_source      TEXT,
    p_notes       TEXT DEFAULT NULL
) RETURNS JSONB
LANGUAGE plpgsql
SET search_path = public
AS $$
DECLARE
    v_id        BIGINT;
    v_trades    INTEGER;
    v_positions INTEGER;
BEGIN
    IF p_ratio IS NULL OR p_ratio <= 0 THEN
        RAISE EXCEPTION 'apply_stock_split: ratio must be > 0 (got %)', p_ratio;
    END IF;

    INSERT INTO corporate_actions
        (fund, ticker, ex_date, ratio, status, cliff_date, source, notes)
    VALUES
        (p_fund, p_ticker, p_ex_date, p_ratio, 'applied', p_cliff_date, p_source, p_notes)
    RETURNING id INTO v_id;

    UPDATE trade_log
       SET shares = shares * p_ratio,
           price  = price / p_ratio
     WHERE fund = p_fund
       AND ticker = p_ticker
       AND (date AT TIME ZONE 'America/New_York')::date < p_cliff_date;
    GET DIAGNOSTICS v_trades = ROW_COUNT;

    -- total_value is generated (shares * price). cost_basis is invariant.
    UPDATE portfolio_positions
       SET shares           = shares * p_ratio,
           pnl              = round(shares * p_ratio * price - cost_basis, 2),
           total_value_base = round(shares * p_ratio * price * coalesce(exchange_rate, 1), 2),
           pnl_base         = round((shares * p_ratio * price - cost_basis) * coalesce(exchange_rate, 1), 2)
     WHERE fund = p_fund
       AND ticker = p_ticker
       AND date_only >= p_cliff_date;
    GET DIAGNOSTICS v_positions = ROW_COUNT;

    UPDATE corporate_actions
       SET trades_adjusted = v_trades,
           positions_adjusted = v_positions
     WHERE id = v_id;

    RETURN jsonb_build_object(
        'id', v_id,
        'trades_adjusted', v_trades,
        'positions_adjusted', v_positions
    );
END;
$$;

REVOKE ALL ON FUNCTION apply_stock_split(TEXT, TEXT, DATE, NUMERIC, DATE, TEXT, TEXT)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION apply_stock_split(TEXT, TEXT, DATE, NUMERIC, DATE, TEXT, TEXT)
    TO service_role;
