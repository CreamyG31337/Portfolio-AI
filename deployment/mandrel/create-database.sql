-- ============================================================
-- Mandrel Database Setup Script
-- ============================================================
-- PostgreSQL is running in Docker container (postgres-17.5)
-- Run this script using docker exec:
--
--   docker exec -i postgres-17.5 psql -U x7k9pQzW3vT2 -f - < create-database.sql
--
-- Or run commands directly:
--   docker exec postgres-17.5 psql -U your_postgres_user -c "CREATE DATABASE mandrel_dev;"
--   docker exec postgres-17.5 psql -U your_postgres_user -d mandrel_dev -c "CREATE EXTENSION IF NOT EXISTS vector;"
-- ============================================================

-- Create the database
CREATE DATABASE mandrel_dev;

-- Connect to the new database and enable pgvector
\c mandrel_dev

-- Enable pgvector extension for semantic search
CREATE EXTENSION IF NOT EXISTS vector;

-- Verify extension is installed
SELECT extname, extversion FROM pg_extension WHERE extname = 'vector';

\echo 'Mandrel database created successfully with pgvector extension!'
