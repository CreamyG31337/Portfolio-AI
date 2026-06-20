# Authentication Guide

## Overview

The Flask dashboard uses a two-tier authentication system:

1. **User Authentication** — standard dashboard operations (viewing data, making trades)
   - Supabase Auth with JWT access + refresh tokens
   - Row Level Security (RLS) on data queries
   - Users only see funds assigned to them

2. **Admin Access** — debug scripts and SQL operations
   - Service role key (`SUPABASE_SECRET_KEY`)
   - Bypasses RLS for server-side admin tooling only
   - Never exposed to browsers or user-facing routes

## User Authentication Flow

1. User visits dashboard → redirected to `/auth` if not logged in
2. User signs in (magic link or password) → Supabase returns JWT
3. `auth_callback.html` or `/auth` sets `auth_token` / `refresh_token` cookies
4. `flask_auth_utils.py` resolves the access token per request (refresh when needed)
5. `SupabaseClient(user_token=...)` sends the JWT to PostgREST so RLS applies
6. User logs out → cookies cleared

See also: `web_dashboard/docs/authentication_guide.md` (token refresh / PostgREST patterns).

## Environment Variables

### Required for the dashboard

- `SUPABASE_URL` — Supabase project URL
- `SUPABASE_PUBLISHABLE_KEY` — anon/publishable key for auth API calls
- `FLASK_SECRET_KEY` — Flask session signing
- `APP_DOMAIN` — used for auth callbacks and cookie scope

### Required for admin scripts

- `SUPABASE_SECRET_KEY` — service role key (bypasses RLS)

## Using Admin Utilities

For debug scripts and SQL operations, use `admin_utils.py`:

```python
from admin_utils import get_admin_supabase_client

client = get_admin_supabase_client()
if client:
    result = client.supabase.table("portfolio_positions").select("*").execute()
```

## Security Notes

- **Never expose `SUPABASE_SECRET_KEY`** to the frontend or user-facing code
- User JWTs live in HTTP-only-style cookies (`auth_token`, `refresh_token`) — see `flask_auth_utils.py`
- RLS policies enforce fund-level access in Supabase
- Admin routes use `can_modify_data_flask()` / role checks in `flask_auth_utils.py`
