-- Allow 'llm' as a resolution source for the OGE asset -> ticker cache.
-- LLM-proposed tickers are validated (yfinance name-overlap) before being cached.

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'og_asset_ticker_map_source_check'
    ) THEN
        ALTER TABLE og_asset_ticker_map
            DROP CONSTRAINT og_asset_ticker_map_source_check;
    END IF;

    ALTER TABLE og_asset_ticker_map
        ADD CONSTRAINT og_asset_ticker_map_source_check
        CHECK (source IN ('suffix', 'open_cabinet', 'securities', 'yfinance', 'llm', 'manual'));
END $$;
