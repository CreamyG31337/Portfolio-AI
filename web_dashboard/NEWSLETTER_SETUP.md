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
ollama pull nomic-embed-text
```

## Production Deployment (Woodpecker CI)

Add these secrets to Woodpecker:
- `mailgun_api_key` - Your Mailgun API key
- `mailgun_webhook_signing_key` - Your Mailgun webhook signing key
- `newsletter_email` - The email address for receiving newsletters

These will be mapped to environment variables in your deployment config.

## Features

✅ Mailgun webhook integration with HMAC-SHA256 signature verification
✅ Automatic text extraction from HTML/plain text emails
✅ Ticker symbol extraction using regex patterns
✅ Ollama embeddings (nomic-embed-text, 768 dimensions) for semantic search
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
