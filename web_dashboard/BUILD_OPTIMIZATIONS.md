# Build and Deployment Optimizations

Optimizations in `.woodpecker.yml` for fast parallel builds and deployments.

## Build Optimizations

### 1. Parallel Docker Builds

Two application images build in parallel:

- `trading-dashboard-flask` (Flask dashboard + scheduler)
- `cookie-refresher` (WebAI cookie sidecar)

Shared cache layers: `trading-dashboard-base`, `trading-dashboard-frontend`.

### 2. Docker BuildKit

```bash
export DOCKER_BUILDKIT=1
export COMPOSE_DOCKER_CLI_BUILD=1
```

### 3. Dockerfile Layer Ordering (`Dockerfile.flask`)

1. System dependencies (rarely changes)
2. `requirements.txt` copy + install
3. Application code last

**Typical times:** first build ~2–3 min; code-only change ~30–60 s.

### 4. Health Checks

`healthcheck.py` probes `http://localhost:5001/` (200 or 302 = healthy).

## Deployment Optimizations

- Single app container stop/start (`trading-dashboard-flask`)
- Image tagging after builds: `trading-dashboard-flask:${CI_COMMIT_SHA}`
- Parallel image cleanup for old tags
- Incremental Research PDF copy (only newer files)

## Build Time Estimates

| Change type | Build | Deploy | Total |
|-------------|-------|--------|-------|
| First build (no cache) | ~2–3 min | ~10 s | ~2.5–3.5 min |
| Code only | ~30–60 s | ~10 s | ~40–75 s |
| Requirements change | ~1.5–2 min | ~10 s | ~1.75–2.5 min |

## Monitoring

Woodpecker logs:

- `Building Docker images in parallel...`
- `✅ All images built and tagged`
- `✅ Trading Dashboard Flask container deployed on port 5001`

## Troubleshooting Slow Builds

```bash
docker system df
docker builder prune -a   # if cache is stale or disk is full
```
