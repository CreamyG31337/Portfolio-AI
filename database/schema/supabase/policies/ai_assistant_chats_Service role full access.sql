CREATE POLICY "Service role full access ai_assistant_chats"
    ON "ai_assistant_chats"
    FOR ALL
    TO public
    USING ((auth.role() = 'service_role'::text))
    WITH CHECK ((auth.role() = 'service_role'::text));
