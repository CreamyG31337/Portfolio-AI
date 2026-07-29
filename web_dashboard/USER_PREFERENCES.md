# User Preferences System

## Overview

User preferences are stored in the **Supabase database** using a JSONB column in `user_profiles`. This provides:

- ✅ Persistent storage across sessions and devices
- ✅ Per-user preferences (respects authentication)
- ✅ Fast access with session state caching
- ✅ Secure (RLS policies ensure users can only access their own preferences)

## Multiple Users, Same Contributor Account

**Important:** Preferences are stored **per dashboard user** (login), not per contributor (investor).

### Scenario: Multiple Users Viewing Same Contributor

When multiple dashboard users can view the same contributor's account (via `contributor_access` table):

```
Contributor: "Lance Colton" (investor)
├── User: lance.colton@gmail.com (owner)
│   └── Preferences: {timezone: "America/Los_Angeles", theme: "dark"}
├── User: assistant@lancecolton.com (viewer)
│   └── Preferences: {timezone: "America/New_York", theme: "light"}
└── User: accountant@example.com (viewer)
    └── Preferences: {timezone: "UTC", theme: "light"}
```

**Each user has their own preferences**, even though they're viewing the same contributor's data. This is correct because:
- Each user may be in a different timezone
- Each user may prefer different UI themes/settings
- Preferences are personal to the dashboard user, not the contributor

### How It Works

1. **Preferences are stored in `user_profiles.preferences`**
   - Linked to `user_id` (dashboard user), not `contributor_id`
   - Each user gets their own preferences JSONB object

2. **RLS policies ensure security**
   - Users can only read/write their own preferences
   - `auth.uid()` is used to identify the current user

3. **Data access vs. preferences**
   - **Data access**: Controlled by `contributor_access` table (who can see which contributor's data)
   - **Preferences**: Stored per user in `user_profiles` (personal UI settings)

## Database Schema

### Migration

Run the migration to add the preferences column:

```bash
# In Supabase SQL editor or via psql
psql -f database/schema/supabase/functions/set_user_preference.sql
```

This adds:
- `preferences JSONB` column to `user_profiles` table
- GIN index for efficient JSONB queries
- Helper RPC functions: `get_user_preference()`, `set_user_preference()`, `get_user_preferences()`

## Usage

### Python API

```python
from user_preferences import (
    get_user_preference,
    set_user_preference,
    get_user_timezone,
    set_user_timezone
)

# Get a preference (with default)
timezone = get_user_timezone()  # Returns timezone string or None
theme = get_user_preference('theme', default='light')

# Set a preference
set_user_timezone('America/Los_Angeles')
set_user_preference('theme', 'dark')
```

### Features

1. **Automatic Caching**: Preferences are cached in the Flask session for performance
2. **Type Safety**: Values are stored as JSONB, supporting strings, numbers, booleans, objects, arrays
3. **Secure**: Uses RLS policies - users can only access their own preferences
4. **Fallback**: If user not authenticated, returns default values gracefully

## Timezone Preference

The scheduler UI now uses the user's timezone preference:

1. User sets timezone in Settings page (`/settings`)
2. Scheduler UI reads preference and displays all times in user's timezone
3. Falls back to system timezone if no preference set

### Setting Timezone

Users can set their timezone via:
- **Settings Page**: Navigate to Settings in the dashboard sidebar
- **Programmatic**: Use `set_user_timezone('America/Los_Angeles')`

## Files

- `database/schema/supabase/functions/set_user_preference.sql` - Database migration
- `web_dashboard/user_preferences.py` — Python utility functions
- `web_dashboard/templates/settings.html` — Settings UI
- Admin scheduler pages — use `get_user_timezone()` for display

## Example: Adding a New Preference

```python
# Get preference
value = get_user_preference('my_new_setting', default='default_value')

# Set preference
set_user_preference('my_new_setting', 'new_value')
```

## Notes

- Preferences are stored as JSONB, so you can store complex objects/arrays
- Session cache is cleared on logout (Flask session / `auth.py`)
- All RPC functions use `SECURITY DEFINER` to ensure proper RLS enforcement

