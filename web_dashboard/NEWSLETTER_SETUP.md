# Newsletter Inbox System - Setup Instructions

## Quick Start

### 1. Add Environment Variables

Add to `web_dashboard/.env`:
```bash
# Mailgun Configuration
MAILGUN_API_KEY=your_mailgun_api_key_here
MAILGUN_WEBHOOK_SIGNING_KEY=your_mailgun_signing_key_here

# Newsletter Email Address
NEWSLETTER_EMAIL=your-newsletter-address@yourdomain.com
```

### 2. Run Database Migration

```bash
cd web_dashboard
python - << EOF
from postgres_client import PostgresClient
client = PostgresClient()
with open('schema/create_newsletters_table.sql', 'r') as f:
    sql = f.read()
with client.get_connection() as conn:
    cursor = conn.cursor()
    cursor.execute(sql)
    conn.commit()
    print("✅ Newsletter table created successfully")
EOF
```

### 3. Configure Mailgun Route

In Mailgun dashboard:
- **Expression**: `match_recipient("your-newsletter-address@yourdomain.com")`
- **Action**: Forward to webhook: `https://your-app-domain.com/api/webhooks/newsletter`

### 4. Ensure Ollama Model is Available

```bash
ollama pull bge-m3
```

> The embedding model is configurable via `AI_EMBED_MODEL` (default `bge-m3`, 1024-dim). If you change it, also set `AI_EMBED_DIM` to the model's output size and update the `embedding vector(N)` column type to match (see `database/migrations/2026-05_migrate_embeddings_to_bge_m3_1024.sql` for the pattern).

## Production Deployment (Woodpecker CI)

Add these secrets to Woodpecker:
- `mailgun_api_key` - Your Mailgun API key
- `mailgun_webhook_signing_key` - Your Mailgun webhook signing key
- `newsletter_email` - The email address for receiving newsletters

These will be mapped to environment variables in your deployment config.

### Outbound portfolio digest (per-user email)

Sends a thin Mailgun email plus an expiring hosted digest (`/digest/view`). Separate from the **inbound** research newsletter pipeline.

**Supabase:** apply schema under `database/schema/supabase/` for `outbound_newsletter_*` and `user_newsletter_subscriptions` (seed type `portfolio_digest`).

**Environment variables** (add to `web_dashboard/.env` or deployment):

```bash
# Same API key as inbound is fine if your Mailgun account allows sending
MAILGUN_API_KEY=...
# Verified Mailgun domain for sending (e.g. mg.yourdomain.com)
MAILGUN_SEND_DOMAIN=mg.yourdomain.com
# RFC5322 From header
MAILGUN_FROM=Portfolio <noreply@mg.yourdomain.com>
# Optional EU API: https://api.eu.mailgun.net/v3
# MAILGUN_API_BASE=https://api.eu.mailgun.net/v3

# Public site URL for links in email (digest, KPI images, settings)
PUBLIC_BASE_URL=https://your-app-domain.com
# Optional subject override
# OUTBOUND_DIGEST_SUBJECT=Your portfolio digest

# Digest tokens use the same secret as Flask sessions
FLASK_SECRET_KEY=...
```

**Woodpecker:** you can reuse `mailgun_api_key`. Add optional secrets `mailgun_send_domain` and `mailgun_from` if you want them injected explicitly; the deploy step can also set `PUBLIC_BASE_URL` from `APP_DOMAIN` (see pipeline comments).

**Scheduler:** enable job `outbound_portfolio_digest` in the admin scheduler UI (off by default). It runs due sends per `user_newsletter_subscriptions` cadence when Mailgun env vars are set.

**User opt-in:** Settings page stores preferences only in `user_newsletter_subscriptions`, not `user_profiles.preferences`.

## Features

✅ Mailgun webhook integration with HMAC-SHA256 signature verification
✅ Automatic text extraction from HTML/plain text emails
✅ Ticker symbol extraction using regex patterns
✅ Ollama embeddings (`bge-m3`, 1024 dimensions — configurable via `AI_EMBED_MODEL` / `AI_EMBED_DIM`) for semantic search
✅ PostgreSQL storage with pgvector for similarity search
✅ Web UI with search, filtering, and pagination
✅ Duplicate prevention via message ID

## API Endpoints

- `POST /api/webhooks/newsletter` - Mailgun webhook (no auth required)
- `GET /api/newsletters` - List newsletters (paginated, with ticker filter)
- `GET /api/newsletters/<id>` - Get single newsletter
- `POST /api/newsletters/search` - Semantic search using vector similarity

## Testing

Send a test email to your configured newsletter address and check:
1. Webhook logs: `tail -f app.log | grep newsletter`
2. Database: `psql <research_db> -c "SELECT COUNT(*) FROM newsletters;"`
3. Web UI: Visit `/newsletters` page
