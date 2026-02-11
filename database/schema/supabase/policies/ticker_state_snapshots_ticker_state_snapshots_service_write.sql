CREATE POLICY "ticker_state_snapshots_service_write" ON "ticker_state_snapshots" FOR ALL TO service_role USING (true) WITH CHECK (true);
