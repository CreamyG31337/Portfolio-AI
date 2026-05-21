CREATE POLICY "Allow authenticated users to read insider trades" ON "insider_trades" FOR SELECT TO authenticated USING (true);
