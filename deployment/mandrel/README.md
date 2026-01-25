# Mandrel MCP Server Deployment

This folder contains everything needed to deploy Mandrel on your Ubuntu server for persistent AI memory across development sessions.

## What is Mandrel?

Mandrel provides persistent memory infrastructure for AI-assisted development. It stores:
- Development context with semantic search (384D vector embeddings)
- Architectural decisions with rationale
- Task tracking and progress
- Project-specific knowledge bases

## Quick Start

### Option A: PowerShell Deployment Script (Recommended)

```powershell
# Copy template and configure
cd deployment/mandrel
cp deploy.ps1.example deploy.ps1
# Edit deploy.ps1 with your SSH key path and server details

# Run deployment
.\deploy.ps1
```

### Option B: Direct Server Setup

```bash
# SSH to server
ssh -i /path/to/your/id_rsa lance@your-server

# Clone your repo (if not already cloned)
cd /home/lance
git clone <your-repo-url> trading-bot
cd trading-bot

# Run setup
cd deployment/mandrel
chmod +x setup-mandrel.sh
./setup-mandrel.sh
```

### Option C: Via Woodpecker CI/CD

Add a Woodpecker step to deploy Mandrel (see `.woodpecker.yml` integration below).

### Configure Your IDE

**For Cursor:**
1. Copy the template: `cp mcps/mandrel/SERVER_METADATA.json.example mcps/mandrel/SERVER_METADATA.json`
2. Edit `mcps/mandrel/SERVER_METADATA.json` and replace `your-server` with your actual server hostname/IP
3. **Important:** Use port `8082` (MCP HTTP Bridge), not `8081` (direct REST API)
4. Restart Cursor to load the MCP server configuration

**For Antigravity/VS Code:**
- See `deployment/mandrel/ANTIGRAVITY_SETUP.md` for complete setup instructions
- Configuration format is the same as Cursor
- **Important:** Use port `8082` (MCP HTTP Bridge) section

## Files in This Folder

| File | Purpose |
|------|---------|
| `docker-compose.yml` | Docker Compose config for Mandrel + Redis |
| `setup-mandrel.sh` | Automated setup script for Ubuntu server |
| `deploy.ps1.example` | PowerShell deployment script template (copy to deploy.ps1) |
| `create-database.sql` | SQL script to create database (manual alternative) |
| `caddy-snippet.txt` | Optional Caddyfile snippet (not used - direct port access) |
| `.env.example` | Environment variables template (copy to .env) |

## Server-Specific Configuration

**PostgreSQL Setup:**
- PostgreSQL runs in Docker container: `postgres-17.5`
- Database user: Set via `POSTGRES_USER` environment variable or `.env` file
- Container is on `PROD` Docker network
- Setup script uses `docker exec` to create database

**Port Configuration:**
- Mandrel MCP Server: Port `8081` (8080 taken by searxng)
- Redis: Port `6379` (internal, not exposed)

**Network Configuration:**
- Mandrel connects to `PROD` network to access PostgreSQL
- Uses Docker network DNS: `postgres-17.5` as hostname

## Manual Setup (Alternative)

If you prefer manual setup:

### Step 1: Create Database (PostgreSQL in Docker)

```bash
# Create database using docker exec
docker exec postgres-17.5 psql -U your_postgres_user -c "CREATE DATABASE mandrel_dev;"

# Enable pgvector extension
docker exec postgres-17.5 psql -U your_postgres_user -d mandrel_dev -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

### Step 2: Clone Mandrel

```bash
cd /home/lance
git clone https://github.com/RidgetopAi/mandrel.git mandrel
cd mandrel
# Optional: Pin to specific version
# git checkout v0.1.0
```

### Step 3: Configure Environment

```bash
cd /home/lance/mandrel
cp deployment/mandrel/.env.example .env
# Edit .env with your database credentials
```

### Step 4: Copy Docker Compose

```bash
cp deployment/mandrel/docker-compose.yml .
```

### Step 5: Start Services

```bash
docker-compose up -d
```

### Step 6: Run Migrations

```bash
docker exec mandrel-mcp npm run migrate
```

## Cursor Configuration

Add to `~/.cursor/mcp.json` (create if doesn't exist):

```json
{
  "mcpServers": {
    "mandrel": {
      "url": "http://your-server:8082",
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
# Test bridge health endpoint (port 8082)
curl http://your-server:8082/health

# Test direct Mandrel API (port 8081 - for debugging only)
curl http://your-server:8081/health

# Check container status
docker-compose ps

# View logs
docker-compose logs -f mandrel-mcp

# List available tools via bridge (MCP JSON-RPC)
curl -X POST http://your-server:8082/ \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'

# List tools via direct Mandrel API (for debugging)
curl http://your-server:8081/mcp/tools/schemas
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

## Ongoing Updates

**Automatic (Watchtower):**
- Watchtower automatically updates Mandrel container when new images are available
- No manual intervention needed for container updates

**Manual Updates (If Needed):**
```bash
ssh -i /path/to/your/id_rsa lance@your-server
cd /home/lance/mandrel
git pull origin main  # Update Mandrel source
# Copy new docker-compose.yml if changed
docker-compose pull   # Update images
docker-compose up -d --build  # Rebuild and restart
docker exec mandrel-mcp npm run migrate  # Run migrations if needed
```

**No custom update scripts needed** - standard docker-compose handles everything.

## Tool Discovery and Updates

### How Mandrel Tools Work

**Auto-Discovery via API:**
- Bridge exposes MCP JSON-RPC endpoint at `http://your-server:8082/`
- Mandrel exposes `GET /mcp/tools/schemas` at `http://your-server:8081/mcp/tools/schemas` (direct API, not MCP-compliant)
- Returns complete tool definitions with `inputSchema` for all tools
- Source of truth: `toolDefinitions.ts` in Mandrel codebase
- When Watchtower updates Mandrel, new tools automatically available via API

**Cursor Tool Definitions:**
- JSON files in `mcps/mandrel/tools/*.json` are for IDE autocomplete/validation
- Cursor can query Mandrel's API for tool discovery
- JSON files provide better IDE experience (type hints, descriptions, validation)
- **JSON files are optional** - Cursor can work with just the API

### Update Workflow

**Automatic (Watchtower):**
1. Watchtower detects new Mandrel image
2. Pulls and restarts container automatically
3. New tools immediately available via MCP bridge at `http://your-server:8082/`
4. Cursor can discover new tools via API

**Manual Updates (Optional):**
- If Mandrel adds new tools, update JSON files in `mcps/mandrel/tools/` for better IDE experience
- Or create a sync script: `curl -X POST http://your-server:8082/ -H "Content-Type: application/json" -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' > tools.json`
- Update `AGENTS.md` if tool usage patterns change significantly

**Recommended Approach:**
- Let Watchtower handle container updates automatically
- Monitor Mandrel releases/changelog for new tools
- Update JSON files only when new tools are added (for better IDE autocomplete)
- Document new tools in `AGENTS.md` when they become available

## Woodpecker CI/CD Integration (Optional)

Since your deployment files are in git, you can add Mandrel deployment to your `.woodpecker.yml`:

```yaml
deploy-mandrel:
  image: docker:24
  volumes:
    - /var/run/docker.sock:/var/run/docker.sock
  environment:
    MANDREL_DB_PASSWORD:
      from_secret: mandrel_db_password
  commands:
    - cd /home/lance/mandrel
    - git pull origin main || true
    - cp /home/lance/trading-bot/deployment/mandrel/docker-compose.yml .
    - docker-compose down || true
    - docker-compose build
    - docker-compose up -d
    - sleep 10
    - docker exec mandrel-mcp npm run migrate || true
  when:
    event: push
    branch: [main, master]
```

**Required Woodpecker Secret:**
- `mandrel_db_password` - Your PostgreSQL password (set in Woodpecker secrets)

The `.env.example` file shows what environment variables are needed. Woodpecker will use the secrets you configure.

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
redis://your-server:6379/0  → Mandrel (job queues)
redis://your-server:6379/1  → Flask sessions
redis://your-server:6379/2  → Price cache
redis://your-server:6379/3  → Rate limiting
```

Note: Redis is created as a new container for Mandrel (isolation). The existing `redis` container on `searxng-stack_searxng-net` is separate.
