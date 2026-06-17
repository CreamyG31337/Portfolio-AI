# Caddyfile Setup (Flask-only)

The trading dashboard is **Flask only** on port **5001**. Streamlit (port 8501) and `/streamlit/*` routing are removed.

Use `web_dashboard/Caddyfile.example` as the source of truth.

## What to change on your server

If your live Caddyfile still has Streamlit blocks, **delete** all of the following:

- `reverse_proxy localhost:8501` (any catch-all or default proxy to 8501)
- `handle_path /streamlit/*` and related `/streamlit` rewrites
- `handle /_stcore/*` (Streamlit WebSocket/health paths)
- Any `trading-dashboard` container reference on port 8501

Then ensure **all app traffic** goes to `localhost:5001` (`trading-dashboard-flask` container).

Minimal pattern:

```caddy
your-domain.com {
    # Static auth pages (unchanged)
    handle /auth_callback.html { ... }
    handle /set_cookie.html { ... }
    handle /login.html { ... }

    # API + static assets → Flask
    handle /api/* {
        reverse_proxy localhost:5001 { trusted_proxies private_ranges }
    }
    handle /assets/* {
        reverse_proxy localhost:5001 { trusted_proxies private_ranges }
    }
    handle /static/* {
        reverse_proxy localhost:5001 { trusted_proxies private_ranges }
    }

    # Default — Flask serves all pages
    reverse_proxy localhost:5001 {
        trusted_proxies private_ranges
    }
}
```

You do **not** need per-page `handle /settings` blocks anymore; Flask owns the whole app.

## Ports

| Service | Port | Container |
|---------|------|-----------|
| Trading dashboard (Flask) | 5001 | `trading-dashboard-flask` |
| NFT calculator (if used) | 5000 | separate app |
| ~~Streamlit~~ | ~~8501~~ | removed |

## Deploy checklist

1. Confirm Flask is up: `docker ps | grep trading-dashboard-flask`
2. Smoke test locally: `curl -I http://localhost:5001/`
3. Edit Caddyfile (remove 8501 / `/streamlit` blocks)
4. Validate: `caddy validate --config /path/to/Caddyfile`
5. Reload: `caddy reload` or `systemctl reload caddy`
6. Test in browser: home page, `/auth`, `/api/v2/...` endpoints
7. Optional cleanup: `docker stop trading-dashboard 2>/dev/null; docker rm trading-dashboard 2>/dev/null`

## Cloudflare

If you terminate TLS at Cloudflare, keep the `trusted_proxies` Cloudflare CIDR blocks in `Caddyfile.example` so Flask sees real client IPs.
