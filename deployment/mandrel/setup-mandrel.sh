#!/bin/bash
# ============================================================
# Mandrel MCP Server Setup Script
# ============================================================
# This script sets up Mandrel on your Ubuntu server.
# Run this script on your server after copying the deployment files.
#
# Usage:
#   chmod +x setup-mandrel.sh
#   ./setup-mandrel.sh
#
# Prerequisites:
#   - PostgreSQL running in Docker container (postgres-17.5)
#   - Docker and Docker Compose installed
#   - Git installed
# ============================================================

set -e  # Exit on error

# Configuration (can be overridden by environment variables)
MANDREL_DIR="${MANDREL_DIR:-/home/lance/mandrel}"
MANDREL_DB_NAME="${MANDREL_DB_NAME:-mandrel_dev}"
POSTGRES_CONTAINER="${POSTGRES_CONTAINER:-postgres-17.5}"
POSTGRES_USER="${POSTGRES_USER:-postgres}"

echo "=============================================="
echo "Mandrel MCP Server Setup"
echo "=============================================="

# Step 1: Create database
echo ""
echo "[Step 1/5] Creating Mandrel database..."
echo "----------------------------------------------"

# Check if database exists (PostgreSQL in Docker)
# Connect to 'postgres' database first (default database that always exists)
if docker exec "$POSTGRES_CONTAINER" psql -U "$POSTGRES_USER" -d postgres -lqt 2>/dev/null | cut -d \| -f 1 | grep -qw "$MANDREL_DB_NAME"; then
    echo "Database '$MANDREL_DB_NAME' already exists."
else
    echo "Creating database '$MANDREL_DB_NAME'..."
    docker exec "$POSTGRES_CONTAINER" psql -U "$POSTGRES_USER" -d postgres -c "CREATE DATABASE $MANDREL_DB_NAME;" || {
        echo "Error: Failed to create database. Check PostgreSQL container is running."
        exit 1
    }
    echo "Database created."
fi

# Enable pgvector extension
echo "Enabling pgvector extension..."
docker exec "$POSTGRES_CONTAINER" psql -U "$POSTGRES_USER" -d "$MANDREL_DB_NAME" -c "CREATE EXTENSION IF NOT EXISTS vector;" || {
    echo "Warning: Failed to enable pgvector. It may already be enabled or not available."
}
echo "pgvector extension enabled."

# Step 2: Clone Mandrel repository
echo ""
echo "[Step 2/5] Setting up Mandrel directory..."
echo "----------------------------------------------"

if [ -d "$MANDREL_DIR" ]; then
    echo "Mandrel directory exists. Pulling latest changes..."
    cd "$MANDREL_DIR"
    git pull origin main || echo "Git pull failed, continuing with existing code..."
    # Pin to specific version if needed (uncomment and set version)
    # git checkout v0.1.0 || echo "Version tag not found, using main branch"
else
    echo "Cloning Mandrel repository..."
    git clone https://github.com/RidgetopAi/mandrel.git "$MANDREL_DIR"
    cd "$MANDREL_DIR"
    # Pin to specific version if needed (uncomment and set version)
    # git checkout v0.1.0 || echo "Version tag not found, using main branch"
fi

# Step 3: Copy deployment files
echo ""
echo "[Step 3/5] Copying deployment configuration..."
echo "----------------------------------------------"

# Copy docker-compose.yml if provided
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$SCRIPT_DIR/docker-compose.yml" ]; then
    cp "$SCRIPT_DIR/docker-compose.yml" "$MANDREL_DIR/docker-compose.yml"
    echo "Copied docker-compose.yml"
fi

# Create .env file if it doesn't exist
if [ ! -f "$MANDREL_DIR/.env" ]; then
    echo "Creating .env file..."
    echo "Please enter your PostgreSQL password:"
    read -s POSTGRES_PASSWORD
    echo "Please enter your PostgreSQL username:"
    read -r DB_USER
    cat > "$MANDREL_DIR/.env" << EOF
# Mandrel Database Configuration
# PostgreSQL is in Docker container (${POSTGRES_CONTAINER})
MANDREL_DB_USER=${DB_USER}
MANDREL_DB_NAME=${MANDREL_DB_NAME}
MANDREL_DB_PASSWORD=${POSTGRES_PASSWORD}
MANDREL_DB_PORT=5432
EOF
    echo ".env file created."
else
    echo ".env file already exists."
fi

# Step 4: Start services
echo ""
echo "[Step 4/5] Starting Mandrel services..."
echo "----------------------------------------------"

cd "$MANDREL_DIR"

# Build and start containers
docker-compose down 2>/dev/null || true
docker-compose build --no-cache
docker-compose up -d

# Wait for services to be ready
echo "Waiting for services to start..."
sleep 10

# Step 5: Run migrations
echo ""
echo "[Step 5/5] Running database migrations..."
echo "----------------------------------------------"

# Run migrations inside the container
docker exec mandrel-mcp npm run migrate || {
    echo "Migration via npm failed, trying direct migration..."
    docker exec mandrel-mcp npx tsx scripts/migrate.ts || {
        echo "Warning: Migrations may need to be run manually."
        echo "Try: docker exec -it mandrel-mcp npm run migrate"
    }
}

# Verify deployment
echo ""
echo "=============================================="
echo "Verification"
echo "=============================================="

# Check container status
echo "Container status:"
docker-compose ps

# Test health endpoint
echo ""
echo "Testing health endpoint..."
sleep 5
if curl -s http://localhost:8081/health > /dev/null 2>&1; then
    echo "✅ Mandrel MCP Server is healthy!"
    curl -s http://localhost:8081/health | head -c 200
    echo ""
else
    echo "⚠️  Health check failed. Check logs with: docker-compose logs mandrel-mcp"
fi

# Test Redis
echo ""
echo "Testing Redis..."
if docker exec mandrel-redis redis-cli ping | grep -q "PONG"; then
    echo "✅ Redis is healthy!"
else
    echo "⚠️  Redis check failed. Check logs with: docker-compose logs redis"
fi

echo ""
echo "=============================================="
echo "Setup Complete!"
echo "=============================================="
echo ""
echo "Mandrel MCP Server is running at: http://localhost:8081"
echo ""
echo "Next steps:"
echo "1. Update Cursor MCP settings to connect (see README.md)"
echo "2. Test connection: curl http://localhost:8081/health"
echo ""
echo "Useful commands:"
echo "  View logs:     docker-compose logs -f"
echo "  Restart:       docker-compose restart"
echo "  Stop:          docker-compose down"
echo "  Check health:  curl http://localhost:8081/health"
echo "  List tools:    curl http://localhost:8081/mcp/tools/schemas"
