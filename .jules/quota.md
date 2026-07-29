
## 2025-05-18 - Fix silent signal truncation in Confluence Service
**Bug:** `confluence_service.py` was silently dropping signal hits across the portfolio because its `limit(1000)` was a hard ceiling for an entire batch of tickers rather than per-ticker limit, permanently skipping the middle rows.
**Learning:** PostgREST default maximum rows is 1000. An explicit `limit(1000)` behaves exactly like an unbounded query and is vulnerable to silent data loss if the matched rows exceed 1000. It doesn't throw errors.
**Prevention:** Use `fetch_all_rows` from `supabase_pagination` for potentially unbounded filtered queries instead of one-shot limits.
