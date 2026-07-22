## 2026-07-22 - Cleanup Orphaned Alter Scripts
 **Learning:** When rolling up table schema updates (like adding columns), ad-hoc `alter_table.sql` scripts should not remain in the `database/schema/research/` modular schema root if the changes are already incorporated into the main `tables/` file. They cause clutter and aren't executed during a fresh boot.
 **Prevention:** Move orphaned ad-hoc migration or alter scripts to `database/archive/` once their changes have been consolidated into the canonical table definitions.
