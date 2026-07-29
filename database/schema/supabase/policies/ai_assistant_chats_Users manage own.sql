CREATE POLICY "Users can select own ai_assistant_chats"
    ON "ai_assistant_chats"
    FOR SELECT
    TO authenticated
    USING (auth.uid() = user_id);

CREATE POLICY "Users can insert own ai_assistant_chats"
    ON "ai_assistant_chats"
    FOR INSERT
    TO authenticated
    WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can update own ai_assistant_chats"
    ON "ai_assistant_chats"
    FOR UPDATE
    TO authenticated
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can delete own ai_assistant_chats"
    ON "ai_assistant_chats"
    FOR DELETE
    TO authenticated
    USING (auth.uid() = user_id);
