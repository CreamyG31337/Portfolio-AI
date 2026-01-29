## 2026-01-16 - Global Polling Anti-Pattern
**Learning:** Found aggressive global polling (5s interval) in `_scripts_content.html` for scheduler status. This runs on every page extending `base.html`, regardless of tab visibility or user role.
**Action:** When implementing polling in this codebase, always:
1. Use reasonable interval based on use case (5s for admin-critical, 30s+ for non-critical).
2. Wrap in `!document.hidden` check to pause in background tabs.
3. Add `visibilitychange` listener for immediate resume when tab becomes visible.

## 2026-02-14 - Historical Snapshot Query Optimization
**Learning:** The `_get_positions_as_of_date_flask_cached` function was fetching all historical data (`.lte("date", as_of_str)`) and filtering in Python, causing O(N*T) data transfer where T is history length. Supabase/Postgres scans were inefficient for large datasets.
**Action:** For "as of date" queries on snapshot tables:
1. First find the *latest specific date* using `.select("date").lte(...).order("date", desc=True).limit(1)`.
2. Then fetch rows for that *exact* date using `.eq("date", found_date)`.
3. This reduces fetch volume from "All History" to "Single Snapshot" (O(1) relative to history).
