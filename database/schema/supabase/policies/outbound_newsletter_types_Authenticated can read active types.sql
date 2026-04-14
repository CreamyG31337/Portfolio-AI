CREATE POLICY "Authenticated can read active outbound newsletter types"
    ON "outbound_newsletter_types"
    FOR SELECT
    TO authenticated
    USING (is_active = true);
