# Trading Dashboard Flask Deployment Guide

Since port 5000 is already used by the NFT calculator Flask app, the Trading Dashboard Flask app runs on **port 5001**.

**Note**: This app is deployed as a Docker container via Woodpecker CI/CD. The container is automatically built and deployed when you push to the main branch.

## UI Framework: Flowbite

All Flask templates use **Flowbite** (Tailwind CSS component library) for mobile-responsive navigation and UI components:

- **Mobile Navigation** - Hamburger menu with collapsible sidebar
- **User Menu** - Dropdown in top-right header (Settings, Logout)
- **Responsive Design** - Works on phones, tablets, and desktops
- **Pre-built Components** - Dropdowns, modals, drawers, etc.

Flowbite is loaded via CDN (no Python package required). See [FLOWBITE_GUIDE.md](FLOWBITE_GUIDE.md) for component usage and examples.

## Automatic Deployment (Recommended)

The Flask app is automatically deployed via Woodpecker CI/CD when you push to the main branch. The `.woodpecker.yml` file builds and deploys:
- `trading-dashboard-flask` container (Flask on port 5001)
- `cookie-refresher` container (sidecar)

Streamlit (`trading-dashboard` on 8501) is no longer built or deployed.

No manual deployment needed - just push to main branch!

## Manual Deployment Options

If you need to deploy manually or outside of CI/CD:

### Option 1: Docker (Recommended for Manual Deployment)

Build and run the Flask container:

```bash
# From project root
docker build -f web_dashboard/Dockerfile.flask -t trading-dashboard-flask .
docker run -d \
  --name trading-dashboard-flask \
  --restart unless-stopped \
  -p 5001:5001 \
  --add-host=host.docker.internal:host-gateway \
  -v /home/lance/trading-dashboard-logs:/app/web_dashboard/logs \
  -v /shared/cookies:/shared/cookies \
  -e FLASK_PORT=5001 \
  -e SUPABASE_URL=your_url \
  -e SUPABASE_PUBLISHABLE_KEY=your_key \
  -e SUPABASE_SECRET_KEY=your_secret \
  -e APP_DOMAIN=app.example.com \
  trading-dashboard-flask
```

### Option 2: Systemd Service (Alternative to Docker)

Create `/etc/systemd/system/trading-dashboard-flask.service`:

```ini
[Unit]
Description=Trading Dashboard Flask App
After=network.target

[Service]
Type=simple
User=your-user
WorkingDirectory=/path/to/LLM-Micro-Cap-trading-bot/web_dashboard
Environment="FLASK_PORT=5001"
Environment="PATH=/path/to/venv/bin:/usr/local/bin:/usr/bin:/bin"
ExecStart=/path/to/venv/bin/python app.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Then:
```bash
sudo systemctl daemon-reload
sudo systemctl enable trading-dashboard-flask
sudo systemctl start trading-dashboard-flask
sudo systemctl status trading-dashboard-flask
```

### Option 3: Gunicorn (Recommended for Production)

Install gunicorn:
```bash
pip install gunicorn
```

Run with gunicorn:
```bash
cd web_dashboard
gunicorn -w 4 -b 0.0.0.0:5001 app:app
```

Or with systemd service using gunicorn:

```ini
[Unit]
Description=Trading Dashboard Flask App (Gunicorn)
After=network.target

[Service]
Type=simple
User=your-user
WorkingDirectory=/path/to/LLM-Micro-Cap-trading-bot/web_dashboard
Environment="FLASK_PORT=5001"
Environment="PATH=/path/to/venv/bin:/usr/local/bin:/usr/bin:/bin"
ExecStart=/path/to/venv/bin/gunicorn -w 4 -b 0.0.0.0:5001 app:app
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

## Port Configuration

The port can be configured via environment variable:

```bash
export FLASK_PORT=5001
python app.py
```

Or in your deployment configuration (systemd, Docker, etc.).

## Verifying Deployment

1. Check if Flask is running:
   ```bash
   curl http://localhost:5001/settings
   # Should return HTML (or redirect if not authenticated)
   ```

2. Check logs:
   ```bash
   # Docker
   docker logs -f trading-dashboard-flask
   
   # Systemd
   sudo journalctl -u trading-dashboard-flask -f
   ```

3. Test API endpoint:
   ```bash
   curl http://localhost:5001/api/settings/timezone \
     -X POST \
     -H "Content-Type: application/json" \
     -d '{"timezone": "America/Los_Angeles"}' \
     --cookie "auth_token=your_token"
   ```

## Scheduler Health Verification (Read-Only)

Use the server-first runbook for scheduler/job health checks:
[`docs/SCHEDULER_HEALTH_CHECK_RUNBOOK.md`](docs/SCHEDULER_HEALTH_CHECK_RUNBOOK.md)

Quick check (no restarts, no writes):

```bash
tailscale status
ssh -i "<key_path>" lance@ts-ubuntu-server "hostname && date && whoami"
ssh -i "<key_path>" lance@ts-ubuntu-server "docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.RunningFor}}'"
ssh -i "<key_path>" lance@ts-ubuntu-server "docker logs --since 30m trading-dashboard --tail 200"
ssh -i "<key_path>" lance@ts-ubuntu-server "docker exec trading-dashboard python /app/web_dashboard/scripts/check_job_status.py"
```

Important: do not use local-machine scheduler checks as the source of truth for production.

## Caddy Configuration

Route all dashboard traffic to port **5001**. See `Caddyfile.example` and `CADDYFILE_MIGRATION.md` — remove any `/streamlit` or `8501` blocks from your live Caddyfile.

## Troubleshooting

### Port Already in Use

If port 5001 is already in use:
```bash
# Find what's using the port
sudo lsof -i :5001
# or
sudo netstat -tulpn | grep 5001

# Kill the process or change FLASK_PORT to another port
```

### Flask Not Starting

Check:
1. Virtual environment is activated
2. All dependencies are installed: `pip install -r requirements.txt`
3. Environment variables are set (SUPABASE_URL, etc.)
4. Port 5001 is not blocked by firewall

### Caddy Can't Connect

Check:
1. Flask container is running: `docker ps | grep trading-dashboard-flask`
2. Container is listening on port 5001: `docker logs trading-dashboard-flask`
3. Caddy can reach localhost:5001
4. Firewall allows connections on port 5001
5. Caddyfile syntax is correct (run `caddy validate`)

### Container Won't Start

Check:
1. Docker image built successfully: `docker images | grep trading-dashboard-flask`
2. Environment variables are set correctly
3. Port 5001 is not already in use
4. Check container logs: `docker logs trading-dashboard-flask`
