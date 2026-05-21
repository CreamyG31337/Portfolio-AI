CREATE POLICY "Allow service role full access" ON "insider_trades" FOR ALL TO service_role USING (true) WITH CHECK (true);
