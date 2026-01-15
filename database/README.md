# Database Schema

This directory contains the authoritative and modular database schema for the project. 

> [!IMPORTANT]
> The **Source of Truth** for the database schema is now located in the `database/schema/` directory. Legacy incremental migrations and ad-hoc fixes have been consolidated into this modular structure.

## 🏗️ Schema Organization

The schema is divided into two main environments, each with its own modular subdirectories:

### 1. Supabase Production (`database/schema/supabase/`)
Contains the full schema for the core application database.
- **`tables/`**: Individual table definitions.
- **`functions/`**: PL/pgSQL functions and business logic.
- **`views/`**: Database views for reporting and dashboards.
- **`triggers/`**: Automation triggers.
- **`policies/`**: Row Level Security (RLS) policies.
- **`sequences/`**: Auto-incrementing sequences.
- **`types/`**: Custom database types (Enums, etc.).

### 2. Research Database (`database/schema/research/`)
Contains the schema for the AI research and data collection database.

## 🚀 Fresh Database Setup

To set up a fresh database environment:

1. Navigate to the desired database folder (e.g., `database/schema/supabase/`).
2. Run the **`_init_schema.sql`** script. 
   - This master script handles dependency ordering (creating types/functions before tables/views).
   - In Supabase, you can copy the contents into the SQL Editor.

## 🔄 Maintenance & Syncing

To keep these files in sync with a live database after making changes in production:

```powershell
.\web_dashboard\venv\Scripts\python.exe scripts\export_clean_schema.py
```

This script will connect to the databases defined in your `.env` file and regenerate the modular SQL files based on the actual live schema.

## 🛠️ Additional Folders

- **`debug/`**: Diagnostic scripts for troubleshooting data issues.
- **`utilities/`**: Scripts for development (sample data, RLS toggles).
- **`archive/`**: Historical migrations kept for context only.
- **`analysis/`**: SQL queries used for data analysis and reporting.
