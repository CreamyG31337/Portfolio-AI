CREATE POLICY "Service role full access user_newsletter_subscriptions"
    ON "user_newsletter_subscriptions"
    FOR ALL
    TO public
    USING ((auth.role() = 'service_role'::text))
    WITH CHECK ((auth.role() = 'service_role'::text));
