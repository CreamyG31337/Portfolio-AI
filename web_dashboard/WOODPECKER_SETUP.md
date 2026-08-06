# Woodpecker CI/CD Setup Guide

## Overview

Woodpecker builds and deploys the **Flask** trading dashboard (`trading-dashboard-flask` on port **5001**) plus the `cookie-refresher` sidecar. See `.woodpecker.yml` for the full pipeline.

## Step 1: Add Repository to Woodpecker

1. Open your Woodpecker dashboard
2. Go to **Repositories**
3. Click **Add Repository** or sync repositories
4. Find and activate `LLM-Micro-Cap-trading-bot`

## Step 2: Configure Secrets

In Woodpecker: repository → **Settings** → **Secrets**

### Required

- `supabase_url`
- `supabase_publishable_key`
- `supabase_secret_key`
- `supabase_database_url` — APScheduler SQLAlchemy job store (Supavisor pooler URL)
- `app_domain` — e.g. `ai-trading.drifting.space`

### Optional

- `research_database_url` — Research/AI Postgres
- `fmp_api_key` — Congress trading job
- `zhipu_api_key` — GLM / Z.AI
- `webai_cookies_json` — initial WebAI cookies (sidecar refreshes after)
- `ai_service_web_url` — cookie refresher target
- `flask_secret_key`, `jwt_secret`, `supabase_jwt_secret`
- `youtube_proxy_control_apikey` — Gluetun control-server key for VPN exit rotation (Phase K)
- Mailgun / newsletter secrets as needed

> **`youtube_proxy_control_apikey` must exist before the next push.** `.woodpecker.yml`
> references it with `from_secret`, and Woodpecker fails the pipeline when a named secret is
> missing — the same constraint as `ollama_base_url_2`. The value is the `trading-bot` role's
> `apikey` in `/home/lance/gluetun/data/auth/config.toml` on the deploy host.
>
> It lets the app rotate the VPN exit when YouTube blocks the current IP instead of losing the
> run. `YOUTUBE_PROXY_ROTATE_MODE` (`control`) and `YOUTUBE_PROXY_CONTROL_URL`
> (`http://host.docker.internal:8001`) are not secrets and are defaulted in the deploy step.
> Only `control` mode works inside the container — the `ssh` backend needs an agent key it does
> not have. Without the key, rotation degrades to off and blocks simply stay blocks;
> `yt_proxy_rotation.preflight()` logs which state it is in at the start of every YouTube job.

## Step 3: Verify Docker Socket Access

Woodpecker agent needs `/var/run/docker.sock` mounted with permission to build and run containers.

## Step 4: What Gets Deployed

On push to `main`:

1. Build `trading-dashboard-base` and `trading-dashboard-frontend` (cache layers)
2. Build `trading-dashboard-flask:latest` and `cookie-refresher:latest` in parallel
3. Stop/remove old `trading-dashboard-flask` container
4. Start new Flask container on **5001** (scheduler runs inside this container)
5. Deploy static auth pages to `/deploy_target/frontend`
6. Start/restart `cookie-refresher` sidecar

## Ollama and Optional Env

Woodpecker does not map every optional key from secrets. Production optional vars often live in:

**`/home/lance/trading-dashboard-optional.env`** on the deploy host (sourced during Flask `docker run`):

```bash
OLLAMA_BASE_URL=http://...
OLLAMA_MODEL=...
OLLAMA_ENABLED=true
# MAILGUN_SEND_DOMAIN=mg.example.com
```

Model ↔ host routing defaults live in `web_dashboard/model_config.json` (in the image).

## Portainer / Manual Checks

If managing containers manually:

- Image: `trading-dashboard-flask:latest`
- Port: `5001:5001`
- Name: `trading-dashboard-flask`
- Env: same as Woodpecker deploy block in `.woodpecker.yml`

## Troubleshooting

### Build fails

- Check Woodpecker logs (YAML syntax, Docker build output)
- `docker images | grep trading-dashboard-flask`

### Container can't reach Supabase

- Verify `SUPABASE_URL`, keys, and `SUPABASE_DATABASE_URL` in container env
- `docker logs trading-dashboard-flask`

### Caddy / public URL

- Reverse proxy must target `localhost:5001` — see `Caddyfile.example` and `CADDY_SETUP.md`
