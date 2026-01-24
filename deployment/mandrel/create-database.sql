-- ============================================================
-- Mandrel Database Setup Script
-- ============================================================
-- Run this script on your PostgreSQL server to create the
-- Mandrel database with pgvector extension.
--
-- Usage (as postgres user):
--   psql -f create-database.sql
--
-- Or manually:
--   sudo -u postgres psql -f create-database.sql
-- ============================================================

-- Create the database
CREATE DATABASE mandrel_dev;

-- Connect to the new database and enable pgvector
\c mandrel_dev

-- Enable pgvector extension for semantic search
CREATE EXTENSION IF NOT EXISTS vector;

-- Verify extension is installed
SELECT extname, extversion FROM pg_extension WHERE extname = 'vector';

-- Grant permissions (adjust username as needed)
-- GRANT ALL PRIVILEGES ON DATABASE mandrel_dev TO your_user;

\echo 'Mandrel database created successfully with pgvector extension!'
