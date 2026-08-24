1. **Optimize `get_unique_holdings` in `web_dashboard/scheduler/jobs_dividends.py`**
   - The current implementation uses an unbounded `.execute()` on the `portfolio_positions` table to fetch unique holdings, which is silently capped at 1000 rows by Supabase PostgREST.
   - Replace it with the shared `fetch_all_rows` helper from `supabase_pagination` to properly retrieve all unique pairs across large databases.

2. **Optimize `calculate_eligible_shares` in `web_dashboard/scheduler/jobs_dividends.py`**
   - The current implementation queries `trade_log` using an unbounded `.execute()` for all trades of a ticker before the ex_date, risking truncation at 1000 rows.
   - Replace it with `fetch_all_rows` to guarantee correct evaluation of all historical trades for eligible shares.

3. **Add limits to `.execute()` reads**
   - Add `.limit(1)` to `client.supabase.table("funds").select("fund_type").eq("name", fund_name).execute()` in `get_fund_type` to avoid unbounded query behavior.
   - `client.supabase.table("funds")` in `get_fund_dividend_mode` already uses `.limit(1)`, and `client.supabase.table("cash_balances")` in `_credit_cash_dividend` already uses `.limit(1)`.

4. **Update mocked tests in `tests/test_jobs_dividends_eligible_shares.py`**
   - Since `calculate_eligible_shares` now uses `fetch_all_rows`, update the tests to mock `supabase_pagination.fetch_all_rows` instead of mocking the deeply chained `.execute()` call on the Supabase client.

5. **Complete pre-commit steps**
   - Complete pre-commit steps to ensure proper testing, verification, review, and reflection are done.

6. **Submit PR**
   - Submit the change using `branch_name='bolt-dividend-pagination'`, `pr_title='⚡ Bolt: Fix silent truncation in dividend calculations'`, and description detailing the unbounded fetches in `get_unique_holdings` and `calculate_eligible_shares` replaced by `fetch_all_rows`.
