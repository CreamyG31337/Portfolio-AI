"""
Rollback helper for the limited 2026-07-17 congress scrape.

Recovery plan (prod):
1. Pre-scrape backup table: congress_trades_backup_20260717_prescrape
   (recent ~120d rows + all Kean rows; created before scrape)
2. High-water mark before scrape: max_id = 190490, total = 32417

If scrape goes wrong:

A) Delete NEW rows inserted after the high-water mark:
   DELETE FROM congress_trades WHERE id > 190490;

B) Restore UPDATED rows that exist in the backup (match on unique key):
   -- See restore_updated_from_backup() below / run via psql or MCP execute_sql

C) After confirmed good, drop the backup:
   DROP TABLE congress_trades_backup_20260717_prescrape;
"""

from __future__ import annotations

# Captured immediately before the limited scrape attempt
PRE_SCRAPE_MAX_ID = 190490
PRE_SCRAPE_TOTAL = 32417
BACKUP_TABLE = "congress_trades_backup_20260717_prescrape"

ROLLBACK_DELETE_NEW_SQL = f"""
-- Step A: remove rows inserted by the scrape (ids above pre-scrape high-water mark)
DELETE FROM congress_trades
WHERE id > {PRE_SCRAPE_MAX_ID};
"""

ROLLBACK_RESTORE_UPDATED_SQL = f"""
-- Step B: restore any pre-existing rows that were overwritten by upsert
-- Matches the unique key (politician_id, ticker, transaction_date, amount, type, owner)
UPDATE congress_trades AS live
SET
  chamber = b.chamber,
  party = b.party,
  state = b.state,
  disclosure_date = b.disclosure_date,
  price = b.price,
  asset_type = b.asset_type,
  conflict_score = b.conflict_score,
  notes = b.notes,
  asset_description = b.asset_description,
  owner = b.owner,
  amount = b.amount,
  type = b.type
FROM {BACKUP_TABLE} AS b
WHERE live.id = b.id
  AND live.id <= {PRE_SCRAPE_MAX_ID};
"""

VERIFY_SQL = f"""
SELECT
  (SELECT COUNT(*) FROM congress_trades) AS live_total,
  (SELECT MAX(id) FROM congress_trades) AS live_max_id,
  (SELECT COUNT(*) FROM congress_trades WHERE id > {PRE_SCRAPE_MAX_ID}) AS new_rows_since_scrape,
  (SELECT COUNT(*) FROM {BACKUP_TABLE}) AS backup_rows,
  (SELECT COUNT(*) FROM congress_trades WHERE ticker='EQT' AND politician_id IN (425,5414)) AS kean_eqt;
"""

if __name__ == "__main__":
    print("Pre-scrape max_id:", PRE_SCRAPE_MAX_ID)
    print("Backup table:", BACKUP_TABLE)
    print("\n--- DELETE NEW ---\n", ROLLBACK_DELETE_NEW_SQL)
    print("\n--- RESTORE UPDATED ---\n", ROLLBACK_RESTORE_UPDATED_SQL)
    print("\n--- VERIFY ---\n", VERIFY_SQL)
