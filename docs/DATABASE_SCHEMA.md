# Supabase Database Schema Documentation

## Overview
The "Portfolio-AI" database schema is defined using raw SQL files located in `database/schema/supabase/` and `database/schema/research/`. These folders are the **single source of truth** for the database structure.

**Optimization Status:** Views pre-calculate `market_value` and P&L for performance.
**Initialization:** Run `_init_schema.sql` in each directory to apply the modular schema from scratch.

> **Note:** Always check the `database/schema/` directory for the most up-to-date definitions.
