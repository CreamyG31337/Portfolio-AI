CREATE POLICY "Service role full access outbound_newsletter_sends"
    ON "outbound_newsletter_sends"
    FOR ALL
    TO public
    USING ((auth.role() = 'service_role'::text))
    WITH CHECK ((auth.role() = 'service_role'::text));
