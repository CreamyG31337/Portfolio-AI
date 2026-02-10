-- Backfill blank profile names from contributors using normalized email matches.
UPDATE public.user_profiles up
SET
    full_name = c.name,
    updated_at = NOW()
FROM public.contributors c
WHERE lower(trim(up.email)) = lower(trim(c.email))
  AND btrim(coalesce(up.full_name, '')) = ''
  AND btrim(coalesce(c.name, '')) <> '';

-- Keep auth metadata aligned for accounts with missing full_name metadata.
UPDATE auth.users au
SET raw_user_meta_data = coalesce(au.raw_user_meta_data, '{}'::jsonb)
    || jsonb_build_object('full_name', up.full_name)
FROM public.user_profiles up
WHERE up.user_id = au.id
  AND btrim(coalesce(up.full_name, '')) <> ''
  AND btrim(coalesce(au.raw_user_meta_data ->> 'full_name', '')) = '';
