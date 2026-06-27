I've reviewed the 4 commits made in the last 12 hours:

**[cb75a7f8] feat(reddit): RSS feed cache and rate-limit handling for social sentiment**
- Implemented robust RSS feed caching and rate-limiting for Reddit.
- Added a `RedditClient` and `RedditFeedCache` to reduce API load by fetching finance sub hot feeds once per job.
- Added `RedditConnectivityStatus` probe and robust `429` (Rate Limit) logging.
- **Bug/Flaw identified:** In `tests/test_reddit_connectivity_live.py`, the live test `test_reddit_api_reachable` is failing with `AssertionError: Reddit OAuth rejected (HTTP 403)`. The probe `check_reddit_connectivity` seems to trigger a `403` which the test doesn't gracefully skip (unlike `429`), indicating Reddit might have blocked the RSS/OAuth credentials entirely. (I ran `pytest` on these test files to confirm the failure).

**[6307ae23] fix(portfolio): prevent holdings vanishing on partial snapshots**
- Modified `latest_positions` view to anchor to the fund-wide max snapshot date.
- Added logic in `jobs_portfolio.py` to carry forward the last known price for failed ticker fetches so the position stays in the snapshot.
- Utilized `is_trade_sell()` in backfill rebuilds and diagnostic scripts.
- No obvious flaws found; standard fallback caching strategy implemented well.

**[ccba8939] Move repo off OneDrive to C:\Projects with migration script and index exclusions.**
- Added `scripts/migrate_off_onedrive.ps1` to help move the workspace off OneDrive syncing paths.
- Added `.cursorindexingignore` to skip `venv`, `node_modules`, `cache`.
- Clean configuration update.

**[330659dd] Add Graphify export/import scripts for sharing graphs outside OneDrive.**
- Added PowerShell scripts `graphify_export.ps1`, `graphify_import.ps1`, `graphify_status.ps1` to share knowledge graphs via zip/USB to avoid OneDrive sync conflicts.
- Script structure looks solid and handles file operations safely with checksum validation (`SHA256`).

*Test Execution:* I ran `pytest` against the modified test files for the reddit commit.
The suite fails on `test_reddit_api_reachable` returning `Reddit Connectivity Status(..., status_code=403)` which breaks the live test.
