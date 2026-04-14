CREATE POLICY "Service role full access outbound_newsletter_types"
    ON "outbound_newsletter_types"
    FOR ALL
    TO public
    USING ((auth.role() = 'service_role'::text))
    WITH CHECK ((auth.role() = 'service_role'::text));
