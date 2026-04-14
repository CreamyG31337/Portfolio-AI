CREATE POLICY "Users can view own newsletter subscriptions"
    ON "user_newsletter_subscriptions"
    FOR SELECT
    TO authenticated
    USING (auth.uid() = user_id);

CREATE POLICY "Users can insert own newsletter subscriptions"
    ON "user_newsletter_subscriptions"
    FOR INSERT
    TO authenticated
    WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can update own newsletter subscriptions"
    ON "user_newsletter_subscriptions"
    FOR UPDATE
    TO authenticated
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can delete own newsletter subscriptions"
    ON "user_newsletter_subscriptions"
    FOR DELETE
    TO authenticated
    USING (auth.uid() = user_id);
