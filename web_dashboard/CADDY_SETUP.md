# Caddy Setup (Flask Dashboard)

The trading dashboard runs on port **5001**. Use `Caddyfile.example` as the reference.

## Production host

- Live file: `/home/lance/caddy/Caddyfile` (bind-mounted into the `caddy` container)
- Site block: `ai-trading.drifting.space` / `aitrading.drifting.space`

## Routing

| Path | Target |
|------|--------|
| `/auth_callback.html`, `/set_cookie.html`, `/login.html` | Static files under `/ai-trading/frontend` |
| `/research/*` | `/ai-trading/research` PDFs |
| `/api/*`, `/assets/*`, `/static/*` | `reverse_proxy localhost:5001` |
| Everything else | `reverse_proxy localhost:5001` |

## After editing the Caddyfile

1. `docker exec caddy caddy validate --config /etc/caddy/Caddyfile`
2. `docker exec caddy caddy reload --config /etc/caddy/Caddyfile`

## Ports on the host

| Service | Port | Container |
|---------|------|-----------|
| Trading dashboard | 5001 | `trading-dashboard-flask` |
| NFT calculator | 5000 | `nft-calc-backend` |

When TLS terminates at Cloudflare, keep the `trusted_proxies` CIDR blocks from `Caddyfile.example`.
