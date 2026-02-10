# Congress Trades Temporary Scripts

This folder contains temporary scripts, one-time fixes, and test scripts related to Congress Trades functionality.

## Scripts Moved Here

### One-Time Fix Scripts
- `deduplicate_congress_trades.py` - One-time deduplication script
- `remove_all_congress_dupes.py` - One-time cleanup script
- `migrate_add_confidence_score.py` - One-time migration script

### Temporary/Test Scripts
- `inspect_trades_for_filtering.py` - Inspection/debug tool
- `test_*.py` - Various test scripts
- `find_*.py` - Various find/search scripts
- `insert_discovery_job.py` - One-time helper script

### Duplicate Investigation Scripts (Temporary)
- `check_april.py` - Check for April 2025 trades
- `check_evans_dupes.py` - Check Dwight Evans duplicates
- `check_missing_april.py` - Check missing April data
- `comprehensive_dupe_check.py` - Comprehensive duplicate check
- `debug_dwight_trades.py` - Debug Dwight Evans trades
- `delete_evans_dupes.py` - Delete Dwight Evans duplicates
- `find_all_dupes.py` - Find all duplicates
- `find_dupes.py` - Find duplicates
- `find_null_dupes.py` - Find duplicates with NULL values
- `find_null_owner_dupes.py` - Find duplicates with NULL owner

### Test Data
- `reddit_AAPL_response.json` - Test data file

## Production Scripts

Production scripts remain in `web_dashboard/scripts/`:
- `seed_congress_trades.py` - Production import (direct to congress_trades table)
- `analyze_congress_trades_batch.py` - AI analysis tool

Note: The staging workflow and all related scripts were removed in Feb 2026.
The old workflow (scrape -> staging -> validate -> promote) was replaced by direct FMP API inserts.

