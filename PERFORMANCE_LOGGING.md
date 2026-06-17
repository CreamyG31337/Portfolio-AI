# Performance Logging Enhancement Summary

## Changes Made

We've added comprehensive performance logging throughout the web dashboard to identify the source of the 18-second page load time. The logging now tracks:

### 0. **Session Tracking**
- Each user session gets a unique 8-character session ID (e.g., `a1b2c3d4`)
- All performance logs are prefixed with `[session_id]` for easy filtering
- This allows you to track individual user sessions even when multiple users are active
- Session ID persists across page reloads within the same browser session

### 1. **Main Dashboard Loading** (`web_dashboard/routes/dashboard_routes.py`, `app.py`)
- Individual timing for each data fetch operation:
  - `get_current_positions()`
  - `get_trade_log()`
  - `get_cash_balances()`
  - `calculate_portfolio_value_over_time()`
- Total data load time
- Metrics calculation time:
  - `get_investor_count()`
  - `get_latest_exchange_rate()`
  - `get_user_investment_metrics()` ⚠️ **LIKELY BOTTLENECK**
- Chart creation and rendering:
  - `create_portfolio_value_chart()` (chart_utils)
  - Client-side Plotly render time (browser)

### 2. **User Investment Metrics** (`web_dashboard/portfolio_metrics.py` — `get_user_investment_metrics()`)
This function has detailed logging for each step:
- **Contributions query**: Time to fetch all fund_contributions from database
- **Cash/exchange rate**: Time to get cash balances and exchange rates
- **Parse contributions**: Time to parse timestamps and sort contributions
- **get_historical_fund_values()**: Time to fetch historical portfolio values ⚠️ **LIKELY MAJOR BOTTLENECK**
- **NAV calculations**: Time to calculate Net Asset Value for all contributors
- **Total time**: End-to-end function execution time

## What to Look For in Logs

Based on your original logs showing an 11-second gap, we expect to see (with session IDs):

```
[a1b2c3d4] PERF: calculate_portfolio_value_over_time took 1.53s
[a1b2c3d4] PERF: Total data load took ~2.0s
[a1b2c3d4] PERF: Starting metrics calculations
[a1b2c3d4] PERF: get_investor_count took ~0.1s
[a1b2c3d4] PERF: get_latest_exchange_rate took ~0.1s
[a1b2c3d4] PERF: get_user_investment_metrics took ~10-11s  ⚠️ THIS IS THE BOTTLENECK
  ├─ [a1b2c3d4] Contributions query: ~0.5s
  ├─ [a1b2c3d4] Cash/exchange rate: ~0.2s
  ├─ [a1b2c3d4] Parse contributions: ~0.1s
  ├─ [a1b2c3d4] get_historical_fund_values: ~9-10s  ⚠️ MAJOR BOTTLENECK
  └─ [a1b2c3d4] NAV calculations: ~0.2s
[a1b2c3d4] PERF: Metrics calculations complete, took ~11s total
[a1b2c3d4] PERF: Creating portfolio value chart
[a1b2c3d4] PERF: create_portfolio_value_chart took ~1.8s
```

**Multi-User Example:**
```
[a1b2c3d4] PERF: get_user_investment_metrics - Starting
[e5f6g7h8] PERF: get_user_investment_metrics - Starting  ← Different user
[a1b2c3d4] PERF: get_user_investment_metrics - Contributions query: 0.5s
[e5f6g7h8] PERF: get_user_investment_metrics - Contributions query: 0.4s
[a1b2c3d4] PERF: get_user_investment_metrics - get_historical_fund_values: 9.8s
[e5f6g7h8] PERF: get_user_investment_metrics - get_historical_fund_values: 9.5s
```

## Expected Bottleneck: `get_historical_fund_values()`

This function:
1. Queries `portfolio_positions` table with pagination (potentially 1000s of rows)
2. Fetches historical exchange rates for each date
3. Calculates fund values for each contribution date

### Why It's Slow:
- Multiple database queries (one for positions, multiple for exchange rates)
- Processing large amounts of historical data
- Called every time the dashboard loads (no caching)

## Recommended Optimizations

### 1. **Add Caching to `get_user_investment_metrics()`**

Use `@cache_data` from `flask_cache_utils` (see `FLASK_CACHING_GUIDE.md`).

### 2. **Cache Historical Fund Values**
Create a materialized view or cached table for daily fund values instead of calculating on-the-fly.

### 3. **Optimize `get_historical_fund_values()`**
- Batch exchange rate lookups instead of one-by-one
- Use a single query with JOINs instead of multiple queries
- Consider pre-calculating and storing fund values daily

### 4. **Lazy Load User Metrics**
Only calculate user investment metrics when needed (e.g., in multi-investor view), not for single-investor funds.

## Next Steps

1. **Run the dashboard** and check the logs in the admin panel
2. **Identify the exact bottleneck** from the detailed timing logs
3. **Implement targeted optimizations** based on the data
4. **Consider database indexing** on frequently queried columns (fund, date, contributor)

## Log Location

Logs will appear in:
- Admin panel "Application Logs" tab
- Console output (if running locally)
- Log files (if file logging is enabled)

Look for lines starting with `PERF:` to see all performance metrics.
