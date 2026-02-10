CREATE POLICY "Service role can manage watched_tickers_v2" ON "watched_tickers_v2" FOR ALL TO service_role USING (true) WITH CHECK (true);
