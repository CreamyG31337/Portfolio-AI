# Portfolio Architecture

## Core Concepts

### Trade Log (Source of Truth)
- File: `llm_trade_log.csv`
- Records EVERY trade action with exact timestamp
- Append-only: Trades are never removed or modified
- Multiple trades per day: Normal and expected (buy 10am, sell 11am, buy 2pm)

### Portfolio Snapshots (Derived Data)
- File: `llm_portfolio_update.csv`
- Shows portfolio state at end of each trading day
- NOT a trade log: One snapshot per date with final state
- Calculated by processing all trades up to that date
- Should be rebuilt when: Backdated trades are added

## Rules

1. **When executing a trade**:
   - ✅ Add to trade log (always)
   - ✅ If today: Update today's snapshot
   - ✅ If backdated: Skip snapshot update, warn user to run rebuild

2. **One snapshot per date**:
   - Timestamp should be market close (16:00) for historical
   - Contains ALL active positions at end of day
   - Multiple trades on same day = ONE final snapshot

3. **When in doubt**:
   - Run rebuild script: `python debug/rebuild_portfolio_complete.py --data-dir <dir>`
   - This recreates snapshots from trade log (source of truth)

## Backdated Trades

When you add a backdated trade:
1. Trade is saved to trade log ✅
2. System automatically detects the backdated trade ✅
3. System automatically rebuilds all affected historical snapshots ✅
4. No manual intervention required ✅

The system automatically:
- Detects when a trade is backdated (timestamp < today)
- Rebuilds all portfolio snapshots from that date onwards
- Ensures all historical snapshots include the new trade
- Maintains data integrity without user intervention

## Architecture Benefits

### Separation of Concerns
- **Trade Log**: Records what happened (immutable history)
- **Portfolio Snapshots**: Shows current state (calculated/derived)

### Data Integrity
- Trade log is the single source of truth
- Portfolio snapshots can be rebuilt from trade log
- No risk of inconsistent data between trade log and snapshots

### Performance
- Portfolio snapshots are pre-calculated for fast loading
- Rebuild script handles complex calculations once
- Daily snapshots provide efficient historical queries

## Common Issues and Solutions

### Duplicate Snapshots
**Problem**: Multiple snapshots for the same date
**Cause**: Backdated trades creating partial snapshots
**Solution**: Run rebuild script to consolidate

### Missing Historical Data
**Problem**: Portfolio snapshots don't reflect backdated trades
**Cause**: Backdated trades only update trade log, not snapshots
**Solution**: Run rebuild script to update snapshots

### Inconsistent Data
**Problem**: Trade log and portfolio snapshots don't match
**Cause**: Manual edits or failed updates
**Solution**: Run rebuild script to recalculate from trade log

## Implementation Details

### Repository Pattern
- `BaseRepository`: Abstract interface defining standard operations
- `CSVRepository`: Local CSV file storage implementation
- `SupabaseRepository`: Cloud database storage implementation
- `DualWriteRepository`: Writes to both CSV and Supabase (CSV read source)
- `SupabaseDualWriteRepository`: Writes to both (Supabase read source)

**Design Principles:**
- **Factory Pattern**: Use `data.repositories.repository_factory.get_repository()` to instantiate
- **Interface Segregation**: All repositories implement standard methods (`get_portfolio_data`, `save_trade`)
- **Dependency Injection**: Repositories are injected into services, never hardcoded

**Usage:**
- ✅ Use `repository.get_portfolio_data()` to read data
- ✅ Use `repository.save_portfolio_snapshot()` to write data
- ❌ Never use `pd.read_csv()` or direct file access
- This ensures application logic remains decoupled from storage implementation

### Snapshot Creation
- **Today's trades**: Update snapshot immediately
- **Backdated trades**: Skip snapshot update, warn user
- **Historical rebuild**: Use rebuild script for complete recalculation

### Data Flow
1. Trade executed → Saved to trade log
2. If today's trade → Update today's snapshot
3. If backdated trade → Skip snapshot, warn user
4. User runs rebuild script → All snapshots recalculated

## Best Practices

1. **Always use rebuild script for backdated trades**
2. **Never manually edit portfolio snapshots**
3. **Use trade log as source of truth**
4. **Run rebuild script when in doubt**
5. **Test with small datasets first**

## Troubleshooting

### Portfolio Won't Load
- Check for duplicate snapshots
- Run rebuild script to fix
- Verify trade log integrity

### Missing Positions
- Check if backdated trade was added
- Run rebuild script to update snapshots
- Verify trade log contains the trade

### Performance Issues
- Rebuild script may take time for large datasets
- Consider running during off-hours
- Monitor disk space during rebuild
