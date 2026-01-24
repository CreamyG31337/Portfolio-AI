# Mandrel MCP Server Deployment

This folder contains everything needed to deploy Mandrel on your Ubuntu server for persistent AI memory across development sessions.

## What is Mandrel?

Mandrel provides persistent memory infrastructure for AI-assisted development. It stores:
- Development context with semantic search (384D vector embeddings)
- Architectural decisions with rationale
- Task tracking and progress
- Project-specific knowledge bases

## Quick Start

### 1. Copy Files to Server

```bash
# From your local machine
scp -r deployment/mandrel lance@your-server:/home/lance/
```

### 2. Run Setup Script

```bash
# SSH to server
ssh lance@your-server

# Run setup
cd /home/lance/mandrel
chmod +x setup-mandrel.sh
./setup-mandrel.sh
```

### 3. Configure Cursor

Copy the MCP configuration to your Cursor settings (see below).

## Files in This Folder

| File | Purpose |
|------|---------|
| `docker-compose.yml` | Docker Compose config for Mandrel + Redis |
| `setup-mandrel.sh` | Automated setup script for Ubuntu server |
| `create-database.sql` | SQL script to create database (manual alternative) |
| `caddy-snippet.txt` | Caddyfile snippet for HTTPS reverse proxy |
| `.env.example` | Environment variables template (copy to .env) |

## Manual Setup (Alternative)

If you prefer manual setup:

### Step 1: Create Database

```bash
sudo -u postgres psql -f create-database.sql
```

### Step 2: Clone Mandrel

```bash
cd /home/lance
git clone https://github.com/RidgetopAi/mandrel.git mandrel
```

### Step 3: Configure Environment

```bash
cd /home/lance/mandrel
cp .env.example .env
# Edit .env with your database credentials
```

### Step 4: Start Services

```bash
docker-compose up -d
```

### Step 5: Run Migrations

```bash
docker exec mandrel-mcp npm run migrate
```

## Cursor Configuration

Add to `~/.cursor/mcp.json` (create if doesn't exist):

```json
{
  "mcpServers": {
    "mandrel": {
      "url": "http://your-server-ip:8080",
      "transport": "http"
    }
  }
}
```

Or with HTTPS (if Caddy configured):

```json
{
  "mcpServers": {
    "mandrel": {
      "url": "https://mandrel.your-domain.com",
      "transport": "http"
    }
  }
}
```

## Verification

```bash
# Test health endpoint
curl http://your-server-ip:8080/health

# Check container status
docker-compose ps

# View logs
docker-compose logs -f mandrel-mcp
```

## Available Mandrel Tools

Once connected, you'll have access to these MCP tools:

| Category | Tools |
|----------|-------|
| **System** | `mandrel_ping`, `mandrel_status` |
| **Context** | `context_store`, `context_search`, `context_get_recent`, `context_stats` |
| **Decisions** | `decision_record`, `decision_search`, `decision_update`, `decision_stats` |
| **Projects** | `project_list`, `project_create`, `project_switch`, `project_current` |
| **Tasks** | `task_create`, `task_list`, `task_update`, `task_details` |
| **Search** | `smart_search`, `get_recommendations` |

## Troubleshooting

### Container won't start
```bash
docker-compose logs mandrel-mcp
```

### Database connection issues
```bash
# Test from inside container
docker exec -it mandrel-mcp sh
# Then try connecting to database
```

### Migration fails
```bash
# Run migrations manually
docker exec -it mandrel-mcp npx tsx scripts/migrate.ts
```

### Redis connection issues
```bash
docker exec mandrel-redis redis-cli ping
```

## Redis Reuse

The Redis instance can be reused for other purposes:

```
redis://your-server-ip:6379/0  → Mandrel (job queues)
redis://your-server-ip:6379/1  → Flask sessions
redis://your-server-ip:6379/2  → Price cache
redis://your-server-ip:6379/3  → Rate limiting
```
