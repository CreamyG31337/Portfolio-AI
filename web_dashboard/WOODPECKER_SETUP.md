# Woodpecker CI/CD Setup Guide

## Overview

Woodpecker will build the Docker image for the Streamlit dashboard. You'll use Portainer to manage the container deployment.

## Step 1: Add Repository to Woodpecker

1. Open your Woodpecker dashboard
2. Go to **Repositories**
3. Click **"Add Repository"** or sync repositories
4. Find and activate your `LLM-Micro-Cap-trading-bot` repository

## Step 2: Configure Secrets/Environment Variables

In Woodpecker, go to your repository → **Settings** → **Secrets**, and add:

### Required Secrets:
- **`supabase_url`** - Your Supabase project URL (e.g., `https://xxxxx.supabase.co`)
- **`supabase_publishable_key`** - Your Supabase publishable key (for user authentication)
- **`supabase_secret_key`** - Your Supabase service role key (for admin scripts and debug operations)

### Optional Secrets:
- **`research_database_url`** - Postgres connection string for research articles storage
  - Format: `postgresql://user:password@host:port/database`
  - For Docker container connecting to host Postgres: use `host.docker.internal`
  - Example: `postgresql://postgres:password@host.docker.internal:5432/trading_db`
  - If not set, research articles storage will be disabled (non-critical)
  - Note: This is separate from Supabase (which handles portfolio data)
- **`fmp_api_key`** - Financial Modeling Prep API key for Congress Trading Module
  - Get your API key from: https://site.financialmodelingprep.com/developer/docs/
  - Required for `congress_trades` scheduled job to fetch congressional stock trading disclosures
  - If not set, congress trading module will be disabled (job will log error but continue)
- **`webai_cookies_json`** - WebAI service cookies (for WebAI Pro model)
  - JSON string containing cookies: `{"__Secure-1PSID":"...","__Secure-1PSIDTS":"..."}`
  - Used only for initial cookie setup when the cookie refresher sidecar starts
  - A cookie refresher sidecar automatically refreshes cookies and writes them to a shared volume
  - The main app reads cookies from the shared volume, not from environment variables
  - Required for WebAI Pro model to work in production
  - See `web_dashboard/WEBAI_COOKIE_SETUP.md` for extraction instructions

### Optional Secrets (if using Docker registry):
- **`DOCKER_USERNAME`** - Docker Hub/registry username
- **`DOCKER_PASSWORD`** - Docker Hub/registry password

### Optional Secrets (if using SSH deploy instead of Portainer):
- **`SSH_USER`** - SSH username for server
- **`SSH_HOST`** - Server hostname/IP
- **`SSH_KEY`** - SSH private key (if using key auth)

## Step 3: Verify Docker Socket Access

Woodpecker needs access to the Docker socket to build images. Ensure:
- Woodpecker agent has `/var/run/docker.sock` mounted
- The agent user has permission to use Docker

## Step 4: Workflow

1. **Push to repository** → Woodpecker builds the image
2. **Image is available** locally on the server (or in registry if you push)
3. **In Portainer**:
   - Go to **Images** → find `trading-dashboard:latest`
   - Create/update container with environment variables:
     - `SUPABASE_URL`
     - `SUPABASE_PUBLISHABLE_KEY` (for user authentication)
     - `SUPABASE_SECRET_KEY` (for admin scripts)
     - `STREAMLIT_SERVER_HEADLESS=true`
     - `STREAMLIT_BROWSER_GATHER_USAGE_STATS=false`
   - Map port `8501`
   - Set restart policy to `unless-stopped`

## Simplified Pipeline (Build Only)

Since you're using Portainer for container management, the `.woodpecker.yml` can be simplified to just build the image. The current config includes a deploy step that uses SSH - you can remove that if you're only using Portainer.

## Ollama in production (Flask / scheduler)

Woodpecker’s deploy step does **not** map Ollama keys from repository secrets (optional secrets are awkward in Woodpecker). Production gets Ollama the same way as other optional deploy vars:

1. **`/home/lance/trading-dashboard-optional.env`** on the deploy host — sourced before **both** Streamlit and Flask `docker run` (see `.woodpecker.yml`). Put lines such as:
   - `OLLAMA_BASE_URL=http://...` — AMD box (granite primary) when using the legacy pair
   - `OLLAMA_BASE_URL_2=http://...` — NVIDIA / 3090 box (qwen primary)
   - Optional: `OLLAMA_BASE_URL_AMD=...` and `OLLAMA_BASE_URL_NVIDIA=...` if you don’t want to rely on the legacy ordering
   - `OLLAMA_MODEL=...`, `OLLAMA_ENABLED=true`, etc. as needed

2. **Model ↔ host routing** is in the **image**: `web_dashboard/model_config.json` (not secrets). DB overrides (`system_settings` keys like `model_<name>_base_url`) can still override per model.

Local **development** uses `web_dashboard/.env` or repo templates (`.env.test.template`, `web_dashboard/env.example`); those files are not used by the Woodpecker deploy path.

## Environment Variables in Portainer

When creating the container in Portainer, set these environment variables:

```
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_PUBLISHABLE_KEY=your-publishable-key
SUPABASE_SECRET_KEY=your-secret-key
RESEARCH_DATABASE_URL=postgresql://postgres:password@host.docker.internal:5432/trading_db
FMP_API_KEY=your-fmp-api-key-here
# Note: WEBAI_COOKIES_JSON is set in Woodpecker secrets, not as an environment variable in Portainer
# The cookie refresher sidecar reads it and writes cookies to /shared/cookies/webai_cookies.json
# The main app reads cookies from the shared volume automatically
STREAMLIT_SERVER_HEADLESS=true
STREAMLIT_BROWSER_GATHER_USAGE_STATS=false
```

**Note:** `RESEARCH_DATABASE_URL` is optional. If not set, research articles storage will be disabled (you'll see a log message but the app will work normally). This is separate from Supabase, which handles portfolio data.

**Note:** `FMP_API_KEY` is optional. If not set, the Congress Trading Module will be disabled (the scheduled job will log an error but the app will continue to work normally).

**Note:** `SUPABASE_SECRET_KEY` is required for admin scripts and debug operations. It's safe to include in the container since it's server-side only and never exposed to users.

## Troubleshooting

### Build Fails
- Check Woodpecker logs for errors
- Verify Docker socket is accessible
- Ensure build context is correct (project root)

### Image Not Appearing in Portainer
- Check if Woodpecker and Portainer are on the same server
- Verify image was built successfully
- Check Docker images: `docker images | grep trading-dashboard`

### Container Can't Connect to Supabase
- Verify environment variables are set correctly in Portainer
- Check Supabase URL and key are correct
- Ensure network connectivity from container to Supabase

