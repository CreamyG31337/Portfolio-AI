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

## 2026-02-23 - Ticker Fetch Optimization & Pagination
**Learning:** `get_all_unique_tickers` was fetching only the first 1000 rows of large tables (e.g. `congress_trades`) due to missing pagination, resulting in incorrect/incomplete data. It was also unnecessarily scanning large historical tables for tickers.
**Action:**
1. When fetching "all" items from Supabase, ALWAYS use a pagination loop with `.range(offset, offset + limit)` to bypass the 1000-row default limit.
2. For aggregate lists (like tickers), prioritize master metadata tables (e.g. `securities`) over scanning large transaction logs.

## 2024-05-18 - Pandas JSON Normalization Anti-Pattern
**Learning:** Found that `pd.json_normalize` on a column of dictionaries (`df['securities']`) is significantly slower than doing list comprehensions over the column data (`df['securities'].tolist()`) and extracting properties with `.get()`. This added unnecessary overhead during dashboard metric calculations for things like `get_current_positions_flask`.
**Action:** When flattening a known set of keys from a Series of dicts in Pandas, prefer converting the Series to a list and using a list comprehension instead of `pd.json_normalize`. E.g. `col_list = df['dict_col'].tolist(); df['key'] = [s.get('key') if isinstance(s, dict) else None for s in col_list]`.

## 2024-05-19 - O(M*N) Nested Loop Anti-Pattern in CSV Reconciliation
**Learning:** In `CSVRepository.update_daily_portfolio_snapshot`, finding an updated position for each row involved looping over `snapshot.positions` resulting in an O(M*N) nested loop complexity. When dealing with CSV updates or iterating over DataFrames, linear searches inside loops cause severe performance degradation for larger portfolios.
**Action:** When performing ticker-based lookups within loops, always pre-build a dictionary mapping (e.g., `snapshot_positions_by_ticker = {pos.ticker: pos for pos in snapshot.positions}`) to reduce complexity to O(M+N).

## YYYY-MM-DD - Fetch Distinct Values Without Data Transfer
**Learning:** Found that `get_all_unique_tickers` was performing a full row extraction from 4 large tables using `.execute()` to collect unique tickers, downloading hundreds of megabytes of redundant data over the network only to extract a small set of distinct strings. Also, `.execute()` is limited to 1000 rows without pagination.
**Action:** Use `fetch_unique_column_values_parallel` (which tries an RPC call for O(1) fetch and falls back to chunked, paginated selection) to significantly reduce memory footprint and network transfer when extracting a set of unique column values across large tables.

## 2025-03-05 - O(N) Ticker Lookup Anti-Pattern in PortfolioSnapshot
**Learning:** `PortfolioSnapshot` relied on an $O(N)$ linear list traversal in its `get_position_by_ticker` method. In highly active scenarios involving loops parsing CSV records or rebuilding historical portfolios, repeated calls scale to $O(N^2)$, causing significant CPU overhead for large portfolios.
**Action:** Always wrap data models representing collections with internal dictionary caches to provide $O(1)$ access. Added `_positions_by_ticker` via `__post_init__` to `PortfolioSnapshot`, keeping it cleanly synced during `add_position` and `remove_position` mutations while offering an explicit fallback for deserialization pipelines that bypass the constructor.## 2024-05-01 - Pandas Iteration Bottleneck
**Learning:** `df.iterrows()` is a significant performance bottleneck in large data processing pipelines within scheduler jobs (e.g., `jobs_etf_watchtower.py`, `jobs_portfolio.py`). It instantiates a Pandas Series object for every row, making it notoriously slow (O(n) with high overhead).
**Action:** Replace `df.iterrows()` with vectorized operations (e.g., `.abs().round().tolist()`, boolean vectorization `.all()`) wherever possible. When iteration is absolutely necessary, prefer `.to_dict('records')` (for bulk dictionary creation) or `.itertuples(index=False)` (which yields standard Python tuples and avoids the high overhead of Series instantiation).

## 2026-05-09 - Pandas DataFrame Iteration Bottleneck
**Learning:** The `.iterrows()` method is a significant performance bottleneck in Pandas when iterating over rows, as it yields a `pd.Series` object for every row, incurring heavy object instantiation overhead (O(n) overhead).
**Action:** Replace `.iterrows()` with `.to_dict('records')` when iteration logic expects dictionary-like access. This converts the dataframe to native Python dictionaries upfront, preserving structure while increasing iteration speed by 10x-100x and casting numpy datatypes directly to Python natives for safer serialization.

## 2024-05-18 - Streamlit Render Loop Iterrows Overhead
**Learning:** Found several `iterrows()` usages inside Streamlit render loops in `admin_users.py`, `etf_holdings.py`, `social_sentiment.py` and `chart_utils.py`. Using `iterrows()` inside display and charting loops creates significant overhead due to Pandas instantiating a new Series object per row, turning an O(N) loop into a slow O(N) with massive constant factors.
**Action:** Replace `iterrows()` with `itertuples(index=False)` and use `getattr(row, 'colname')` for row access. This yields standard Python namedtuples, avoiding the Series instantiation overhead and providing a 10-100x speedup for dashboard rendering loops.

## 2024-05-24 - Pandas Row-wise Operations (.apply) in API Responses
**Learning:** In backend data processing functions that return immediate API responses (like `get_all_etf_holdings_changes` in Flask routes), using `.apply(..., axis=1)` creates massive CPU overhead for DataFrames with thousands of rows (e.g., historical ETF holdings). This blocks the main thread and dramatically increases response latency.
**Action:** Always replace `.apply(..., axis=1)` with Pandas/NumPy vectorization (e.g., `np.where`, boolean indexing with `.loc`) which executes 10x-100x faster by bypassing Python interpreter object creation per row.
