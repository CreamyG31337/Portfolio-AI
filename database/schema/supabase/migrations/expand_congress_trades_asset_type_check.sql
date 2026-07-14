-- Expand congress_trades.asset_type to cover executive OGE instrument categories.
-- Preferred / corporate bonds map to a parent equity ticker but are not common stock.

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'congress_trades_asset_type_check'
    ) THEN
        ALTER TABLE congress_trades DROP CONSTRAINT congress_trades_asset_type_check;
    END IF;

    ALTER TABLE congress_trades
        ADD CONSTRAINT congress_trades_asset_type_check
        CHECK (asset_type IS NULL OR asset_type IN (
            'Stock',
            'Crypto',
            'ETF',
            'Preferred',
            'Corporate Bond',
            'Municipal Bond',
            'Treasury',
            'Other'
        ));
END $$;
