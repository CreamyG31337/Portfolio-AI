# Database Views Comparison

## Current Database Views

### 1. `latest_positions` (from database/schema/supabase/views/latest_positions.sql)
**Purpose**: Advanced position tracking with historical P&L calculations

**Features**:
- Gets latest position for each ticker per fund
- Calculates **daily P&L** (vs previous day)
- Calculates **weekly P&L** (vs 7 days ago) 
- Calculates **monthly P&L** (vs 30 days ago)
- Includes both dollar amounts and percentages
- Complex CTE structure for historical price lookups

**Sample Output**:
```json
{
  "ticker": "AAPL",
  "fund": "TEST",
  "shares": 10.0,
  "price": 150.0,
  "daily_pnl_dollar": 5.0,
  "daily_pnl_pct": 3.4,
  "weekly_pnl_dollar": 15.0,
  "weekly_pnl_pct": 10.2,
  "monthly_pnl_dollar": 25.0,
  "monthly_pnl_pct": 20.0
}
```

### 2. `current_positions` (currently unapplied/abandoned)
**Purpose**: Simple current position summary with basic P&L

**Features**:
- Gets latest position for each ticker per fund
- Calculates **unrealized P&L** (current value - cost basis)
- Calculates **return percentage**
- Simple, fast query
- No historical comparisons

**Sample Output**:
```json
{
  "ticker": "AAPL", 
  "fund": "TEST",
  "shares": 10.0,
  "current_price": 150.0,
  "cost_basis": 1400.0,
  "market_value": 1500.0,
  "unrealized_pnl": 100.0,
  "return_percentage": 7.14
}
```

### 3. `daily_pnl_summary` (currently unapplied/abandoned)
**Purpose**: Daily portfolio performance summary

**Features**:
- Groups by fund and date
- Shows total positions count
- Calculates total market value
- Calculates total cost basis  
- Calculates total unrealized P&L
- Calculates total return percentage

**Sample Output**:
```json
{
  "fund": "TEST",
  "trade_date": "2025-10-06",
  "positions_count": 23,
  "total_market_value": 50000.0,
  "total_cost_basis": 48000.0,
  "total_unrealized_pnl": 2000.0,
  "total_return_percentage": 4.17
}
```

### 4. `trade_performance` (currently unapplied/abandoned)
**Purpose**: Individual trade performance tracking

**Features**:
- Shows each trade with current price
- Calculates price change P&L
- Calculates return percentage per trade
- Links trade_log with current_positions
- Only shows buy transactions (shares > 0)

**Sample Output**:
```json
{
  "ticker": "AAPL",
  "trade_date": "2025-10-01",
  "shares": 10.0,
  "trade_price": 140.0,
  "current_price": 150.0,
  "price_change_pnl": 100.0,
  "return_percentage": 7.14,
  "reason": "MANUAL BUY"
}
```

### 5. `portfolio_summary` (currently unapplied/abandoned)
**Purpose**: High-level portfolio overview

**Features**:
- One row per fund
- Total positions count
- Total market value
- Total cost basis
- Total unrealized P&L
- Total return percentage
- Last updated timestamp

**Sample Output**:
```json
{
  "fund": "TEST",
  "total_positions": 23,
  "total_market_value": 50000.0,
  "total_cost_basis": 48000.0,
  "total_unrealized_pnl": 2000.0,
  "total_return_percentage": 4.17,
  "last_updated": "2025-10-06T01:59:30.620243+00:00"
}
```

## Key Differences

| View | Complexity | Historical Data | Use Case | Performance |
|------|------------|----------------|----------|-------------|
| `latest_positions` | High | Yes (daily/weekly/monthly) | Advanced analytics | Slower |
| `current_positions` | Low | No | Simple current state | Fast |
| `daily_pnl_summary` | Medium | Yes (daily) | Daily reporting | Medium |
| `trade_performance` | Medium | No | Trade analysis | Medium |
| `portfolio_summary` | Low | No | Dashboard overview | Fast |

## Which Views Are Actually Applied?

**Currently in Database**:
- ✅ `latest_positions` - This is the one that's working (we saw it in the test)

**Not Yet Applied**:
- ❌ `current_positions` - from abandoned migration (not applied yet)
- ❌ `daily_pnl_summary` - from abandoned migration (not applied yet)  
- ❌ `trade_performance` - from abandoned migration (not applied yet)
- ❌ `portfolio_summary` - from abandoned migration (not applied yet)

## Recommendation

1. **Use `latest_positions`** for advanced analytics (already working)
2. **Apply the new views** from abandoned migration only if still desired
3. **Keep both sets** - they serve different purposes:
   - `latest_positions` = Complex historical analysis
   - `current_positions` = Simple current state
   - `portfolio_summary` = Dashboard overview
   - `trade_performance` = Individual trade tracking
