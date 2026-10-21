# P&L Calculation Verification Summary

## Overview

This document explains how profit and loss (P&L) is calculated in the system and provides comprehensive testing tools to verify the calculations manually.

## P&L Calculation Methods

### 1. Total P&L (Unrealized P&L)
**Formula**: `(Current Price - Average Price) × Shares`
**Purpose**: Shows total unrealized profit/loss since purchase
**Used in**: Portfolio snapshots, position tracking

### 2. Daily P&L
**Formula**: `(Current Price - Previous Day Price) × Shares`
**Purpose**: Shows profit/loss for the current day
**Used in**: Daily performance tracking, prompt generator

### 3. Multi-Day P&L (5-day, 7-day, etc.)
**Formula**: `(Current Price - N Days Ago Price) × Shares`
**Purpose**: Shows profit/loss over specific time periods
**Used in**: Historical performance analysis, trend tracking

### 4. Percentage P&L
**Formula**: `(P&L Amount / Cost Basis) × 100`
**Purpose**: Shows P&L as a percentage of investment
**Used in**: Performance metrics, portfolio analysis

## System Components

### 1. Database Views (`database/schema/supabase/`)
- **`latest_positions`**: Current positions with calculated P&L
- **`daily_portfolio_snapshots`**: Daily portfolio values
- **`historical_pnl_summary`**: Historical P&L calculations

### 2. Financial Calculations (`financial/`)
- **`calculations.py`**: Core P&L calculation functions
- **`pnl_calculator.py`**: P&L calculator class
- **`currency_handler.py`**: Currency conversion for P&L

### 3. Portfolio Models (`data/models/`)
- **`Position`**: Individual position with P&L fields
- **`PortfolioSnapshot`**: Portfolio-level P&L tracking

### 4. Prompt Generator (`prompt_generator.py`)
- **`_format_portfolio_table()`**: Formats P&L for display
- **Daily P&L calculation**: `((current_price - prev_price) / prev_price) * 100`
- **Total P&L calculation**: `(unrealized_pnl / cost_basis) * 100`

## Testing Framework

### 1. Manual P&L Verification (`debug/test_pnl_calculations_manual.py`)
**Purpose**: Verify P&L calculations with known test data
**Features**:
- Creates 7-day test scenario with known price movements
- Calculates expected P&L values manually
- Compares manual calculations with system calculations
- Verifies daily, 5-day, and total P&L

**Usage**:
```bash
# Run full manual verification
python debug/test_pnl_calculations_manual.py --fund PNL_TEST --action full-test

# Create test scenario only
python debug/test_pnl_calculations_manual.py --fund PNL_TEST --action create-scenario
```

### 2. Comprehensive P&L Verification (`debug/test_comprehensive_pnl_verification.py`)
**Purpose**: Test P&L calculations across multiple tickers and time periods
**Features**:
- Multiple tickers with different price movements
- Historical position tracking
- Database view verification
- Prompt generator testing (placeholder)

**Usage**:
```bash
# Run comprehensive verification
python debug/test_comprehensive_pnl_verification.py --fund COMPREHENSIVE_TEST --action full-test

# Verify database calculations only
python debug/test_comprehensive_pnl_verification.py --fund COMPREHENSIVE_TEST --action verify-database
```

### 3. Portfolio Debug Utilities (`debug/portfolio_debug_utilities.py`)
**Purpose**: Debug and analyze portfolio calculations
**Features**:
- Trade analysis by ticker
- P&L summary calculations
- Consistency testing
- Error identification

**Usage**:
```bash
# Analyze trades
python debug/portfolio_debug_utilities.py --fund TEST_FUND --action analyze-trades

# Calculate P&L summary
python debug/portfolio_debug_utilities.py --fund TEST_FUND --action calculate-pnl
```

## Test Scenarios

### 1. Basic P&L Test
**Scenario**: Single ticker with 7-day price history
**Data**: 100 shares @ $100, price progression: $100 → $105 → $110 → $108 → $112 → $115 → $118 → $120
**Expected Results**:
- Total P&L: $2,000 (20%)
- Daily P&L (Day 7): $200 (1.69%)
- 5-day P&L (Day 7 vs Day 2): $1,000 (9.09%)

### 2. Multi-Ticker Test
**Scenario**: Multiple tickers with different price movements
**Data**: 
- AAPL_TEST: 50 shares @ $150, progression: $150 → $155 → $160 → $158 → $162 → $165 → $168 → $170
- TSLA_TEST: 25 shares @ $200, progression: $200 → $210 → $220 → $215 → $225 → $230 → $235 → $240
**Expected Results**:
- AAPL_TEST: Total P&L $1,000 (13.33%)
- TSLA_TEST: Total P&L $1,000 (20.00%)

### 3. FIFO P&L Test
**Scenario**: Multiple purchases and sales with FIFO tracking
**Data**: Buy 100 @ $50, Buy 50 @ $60, Sell 75 @ $70
**Expected Results**:
- Remaining shares: 75
- Cost basis: $2,750 (75 × $36.67 average)
- Realized P&L: $1,500 (75 × ($70 - $50))

## Verification Process

### 1. Create Test Data
```bash
# Create 7-day test scenario
python debug/test_pnl_calculations_manual.py --fund PNL_TEST --action create-scenario

# Create historical positions
python debug/test_pnl_calculations_manual.py --fund PNL_TEST --action create-positions
```

### 2. Verify Manual Calculations
```bash
# Verify manual P&L calculations
python debug/test_pnl_calculations_manual.py --fund PNL_TEST --action verify-manual
```

### 3. Test System Calculations
```bash
# Test system P&L calculations
python debug/test_pnl_calculations_manual.py --fund PNL_TEST --action test-system
```

### 4. Run Comprehensive Verification
```bash
# Run full verification
python debug/test_comprehensive_pnl_verification.py --fund COMPREHENSIVE_TEST --action full-test
```

## Expected Results

### Manual Calculations
- **Total P&L**: `(Current Price - Buy Price) × Shares`
- **Daily P&L**: `(Current Price - Previous Day Price) × Shares`
- **5-day P&L**: `(Current Price - 5 Days Ago Price) × Shares`
- **Percentage P&L**: `(P&L Amount / Cost Basis) × 100`

### System Calculations
- **Database Views**: Should match manual calculations
- **Portfolio Snapshots**: Should include correct P&L values
- **Prompt Generator**: Should format P&L correctly for display

### Verification Criteria
- **Exact Match**: P&L values within $0.01
- **Percentage Match**: P&L percentages within 0.01%
- **Consistency**: All system components show same values
- **Historical Accuracy**: Multi-day calculations are correct

## Common Issues and Solutions

### 1. Precision Errors
**Issue**: Decimal precision differences between calculations
**Solution**: Use `Decimal` type for all financial calculations
**Verification**: Check that differences are < $0.01

### 2. Missing Historical Data
**Issue**: No previous day prices for daily P&L calculation
**Solution**: Ensure 7 days of historical positions are created
**Verification**: Check that all required historical data exists

### 3. Currency Conversion
**Issue**: P&L calculations in different currencies
**Solution**: Use consistent currency for calculations
**Verification**: Check that all values are in same currency

### 4. Database View Updates
**Issue**: Database views not reflecting latest data
**Solution**: Refresh views or recalculate positions
**Verification**: Check that database views match expected values

## Usage Examples

### Quick P&L Test
```bash
# Create and test basic P&L scenario
python debug/test_pnl_calculations_manual.py --fund QUICK_TEST --action full-test
```

### Multi-Ticker Test
```bash
# Test multiple tickers with different price movements
python debug/test_comprehensive_pnl_verification.py --fund MULTI_TEST --action full-test
```

### Debug Portfolio Issues
```bash
# Analyze existing portfolio
python debug/portfolio_debug_utilities.py --fund EXISTING_FUND --action full-analysis
```

## Conclusion

The P&L calculation verification system provides:

1. **Manual Verification**: Test P&L calculations with known data
2. **System Testing**: Verify database views and portfolio calculations
3. **Comprehensive Coverage**: Test multiple tickers and time periods
4. **Debug Tools**: Identify and fix calculation issues
5. **Documentation**: Clear understanding of P&L calculation methods

This framework ensures that P&L calculations are accurate and consistent across all system components, providing confidence in the financial data displayed to users.
