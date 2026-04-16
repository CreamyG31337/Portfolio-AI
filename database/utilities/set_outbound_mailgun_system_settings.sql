-- Outbound portfolio digest: non-secret Mailgun settings in system_settings.
-- Run in Supabase SQL Editor (production or test) as a user with write access.
--
-- IMPORTANT (Mailgun):
--   Replace placeholders below with YOUR verified Mailgun sending domain from the
--   Mailgun dashboard (often mg.example.com, not necessarily your public app URL).
--   If sends fail with 401/404, use the exact hostname shown under Sending → Domains.
--
-- Env vars MAILGUN_SEND_DOMAIN / MAILGUN_FROM override these; remove them if you
-- want the database to be the source of truth.

INSERT INTO public.system_settings (key, value, description, updated_at)
VALUES
  (
    'mailgun_send_domain',
    to_jsonb('mg.example.com'::text),
    'Mailgun API sending domain (must match Mailgun verified domain)',
    now()
  ),
  (
    'mailgun_from',
    to_jsonb('Portfolio <noreply@mg.example.com>'::text),
    'RFC5322 From header for outbound digest',
    now()
  )
ON CONFLICT (key) DO UPDATE SET
  value = EXCLUDED.value,
  description = COALESCE(EXCLUDED.description, public.system_settings.description),
  updated_at = EXCLUDED.updated_at;
