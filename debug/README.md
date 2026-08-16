# Debug Tools for LLM Micro-Cap Trading Bot

This folder contains debugging and utility scripts for the trading bot.

## ⚠️ Important: Always Activate Virtual Environment First!

Before running any Python scripts in this project, always activate the virtual environment:

### Windows (PowerShell):
```powershell
.\venv\Scripts\Activate.ps1
```

### Windows (Command Prompt):
```cmd
.\venv\Scripts\activate.bat
```

### Or use the convenience script:
```cmd
debug\activate_venv.bat
```

## Available Debug Scripts

### 1. `comprehensive_price_debug.py`
Main debugging tool for price data issues.

**Usage:**
```bash
# Debug single ticker
python debug/comprehensive_price_debug.py VEE.TO

# Debug multiple tickers
python debug/comprehensive_price_debug.py --multi VEE.TO GMIN.TO

# Quiet mode for scripting
python debug/comprehensive_price_debug.py VEE.TO --quiet
```

### 2. `price_debug.py`
Simple debug script specifically for VEE.TO price data.

### 3. `gmin_debug.py`
Quick debug script for GMIN.TO price data.

### 4. `recalculate_portfolio_data.py`
Comprehensive script that recalculates ALL portfolio data (shares, prices, cost basis) based on the trade log data.

**Usage:**
```bash
# Recalculate all data for default data directory
python debug/recalculate_portfolio_data.py

# Recalculate all data for specific data directory
python debug/recalculate_portfolio_data.py test_data
```

**When to use:**
- After manually editing the trade log
- When portfolio CSV has stale data (shares, prices, or cost basis)
- To verify all calculations are correct
- When you notice share count discrepancies
- To sync portfolio CSV with trade log after manual edits

**What it fixes:**
- Share count discrepancies (e.g., 3.0 vs 3.1406 shares)
- Average price calculations
- Cost basis calculations
- Any data inconsistencies between trade log and portfolio

### 5. `timezone_parsing_test.py`
Test script to verify that timezone parsing doesn't generate pandas FutureWarnings.

**Usage:**
```bash
python debug/timezone_parsing_test.py
```

**When to use:**
- After modifying date parsing code
- To verify timezone handling is working correctly
- Before deploying changes that affect timestamp processing

### 6. `activate_venv.bat`
Convenience script to activate the virtual environment.

## Common Issues and Solutions

### "No module named 'yfinance'" or similar errors
- **Solution**: Always activate the virtual environment first using the commands above.

### Price data discrepancies
- Use `comprehensive_price_debug.py` to compare Yahoo Finance data with portfolio records
- Check for backdated prices (using current price for historical dates)
- Verify previous close vs current price usage

### Missing data ("NO DATA" entries)
- Run the main trading script to fetch current data
- Use debug scripts to verify data accuracy
- Manually correct historical data if needed

## Corporate actions (stock splits)

Use `debug/apply_stock_split.py` to split-adjust `trade_log` rows. It never
rebuilds positions.

```powershell
.\venv\Scripts\python.exe debug\apply_stock_split.py --fund "TEST MNST RRSP" --ticker MNST --ratio 2 --dry-run
.\venv\Scripts\python.exe debug\apply_stock_split.py --fund "TEST MNST RRSP" --ticker MNST --ratio 2 --apply
# production funds also require --i-know-this-is-prod
```

**A split adjustment must be paired with a targeted `portfolio_positions`
repair, not a full historical rebuild**, until the price provider has
back-adjusted its series. Yahoo currently records the MNST 2:1 (ex 2026-08-11)
but has **not** back-adjusted history, so a rebuild from `trade_log` would pair
post-split share counts with pre-split closes (~2x overstatement). See
`docs/corporate_actions.md`.

The script prints the follow-up UPDATE. Use a `shares = <pre-split>` guard —
`shares * 2` is not idempotent while the daily job is live.

Do **not** use `recalculate_portfolio_data.py` / `manual_rebuild.py --apply` as
the split fix. Dry-run a rebuild only to confirm the overstatement.

**Still manual:** Wealthsimple DRIPs/splits that never hit `trade_log`; mixed
personal + bot holdings in one account. Monitor share counts against the
broker.

## File Organization

### Recently Added/Updated Files
- `timezone_parsing_test.py` - Tests timezone parsing to prevent pandas FutureWarnings
- `timezone_parsing_test_result.txt` - Output file from timezone parsing test

### Removed Files (Cleanup)
- `direct_test.py` - Temporary test file (removed)
- `simple_stats_test.py` - Temporary test file (removed) 
- `test_fix.py` - Temporary test file (removed)
- `test_portfolio_stats.py` - Temporary test file (removed)
- `test_timezone_fix.py` - Renamed to `timezone_parsing_test.py`

## Best Practices

1. **Always activate venv first** - This is the most common source of errors
2. **Use test data for development** - Run with `--data-dir test_data` flag
3. **Verify price data accuracy** - Use debug scripts before making corrections
4. **Keep debug scripts updated** - Add new tickers or features as needed
5. **Clean up temporary files** - Remove test files after debugging is complete
6. **Use descriptive names** - Name files clearly to indicate their purpose
