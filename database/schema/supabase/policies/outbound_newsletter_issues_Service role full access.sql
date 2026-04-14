CREATE POLICY "Service role full access outbound_newsletter_issues"
    ON "outbound_newsletter_issues"
    FOR ALL
    TO public
    USING ((auth.role() = 'service_role'::text))
    WITH CHECK ((auth.role() = 'service_role'::text));
