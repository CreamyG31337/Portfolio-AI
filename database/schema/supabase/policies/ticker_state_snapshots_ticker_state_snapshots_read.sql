CREATE POLICY "ticker_state_snapshots_read" ON "ticker_state_snapshots" FOR SELECT TO authenticated USING (true);
