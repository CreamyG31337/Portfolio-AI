-- AI Assistant chat transcripts (one active thread per user+fund)
CREATE TABLE IF NOT EXISTS public.ai_assistant_chats (
  user_id UUID NOT NULL REFERENCES public.user_profiles(user_id) ON DELETE CASCADE,
  fund TEXT NOT NULL,
  messages JSONB NOT NULL DEFAULT '[]'::jsonb,
  model TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, fund),
  CONSTRAINT ai_assistant_chats_messages_is_array
    CHECK (jsonb_typeof(messages) = 'array'),
  CONSTRAINT ai_assistant_chats_fund_nonempty
    CHECK (length(trim(fund)) > 0)
);

CREATE INDEX IF NOT EXISTS idx_ai_assistant_chats_updated
  ON public.ai_assistant_chats (updated_at DESC);

ALTER TABLE public.ai_assistant_chats ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Service role full access ai_assistant_chats" ON public.ai_assistant_chats;
CREATE POLICY "Service role full access ai_assistant_chats"
  ON public.ai_assistant_chats
  FOR ALL
  TO public
  USING (auth.role() = 'service_role'::text)
  WITH CHECK (auth.role() = 'service_role'::text);

DROP POLICY IF EXISTS "Users can select own ai_assistant_chats" ON public.ai_assistant_chats;
CREATE POLICY "Users can select own ai_assistant_chats"
  ON public.ai_assistant_chats
  FOR SELECT
  TO authenticated
  USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users can insert own ai_assistant_chats" ON public.ai_assistant_chats;
CREATE POLICY "Users can insert own ai_assistant_chats"
  ON public.ai_assistant_chats
  FOR INSERT
  TO authenticated
  WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users can update own ai_assistant_chats" ON public.ai_assistant_chats;
CREATE POLICY "Users can update own ai_assistant_chats"
  ON public.ai_assistant_chats
  FOR UPDATE
  TO authenticated
  USING (auth.uid() = user_id)
  WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS "Users can delete own ai_assistant_chats" ON public.ai_assistant_chats;
CREATE POLICY "Users can delete own ai_assistant_chats"
  ON public.ai_assistant_chats
  FOR DELETE
  TO authenticated
  USING (auth.uid() = user_id);
