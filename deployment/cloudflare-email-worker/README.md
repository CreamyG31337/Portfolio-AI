# Cloudflare Email Routing Worker — `ai-trading`

This Worker handles inbound mail to `ai-research@drifting.space` and POSTs a
JSON envelope to the Flask newsletter webhook on the trading dashboard. It
replaces the legacy Mailgun Routes path that stopped working when the Mailgun
account quota was exhausted in May 2026.

## Pipeline

```
publisher → ai-research@drifting.space
          → Cloudflare Email Routing (zone: drifting.space)
          → Worker `ai-trading` (this folder)
          → POST https://ai-trading.drifting.space/api/webhooks/newsletter
          → Flask `webhook_newsletter` in web_dashboard/app.py
          → research DB `newsletters` table + background AI thread
```

The Worker only forwards the message; all parsing, dedup, and AI processing
happens on the Flask side.

## Files

- `worker.js` — actual Worker source (ES module, `email(...)` handler).
- `wrangler.toml` — Wrangler config for redeploys. No secrets or bindings.
- `README.md` — this file.

## When to redeploy

Edit `worker.js` and run:

```powershell
cd deployment\cloudflare-email-worker
wrangler deploy
```

You need a Cloudflare API token with `Workers Scripts: Edit` and
`Email Routing: Edit` on the `drifting.space` zone. The Wrangler CLI normally
prompts for an OAuth login; alternatively export `CLOUDFLARE_API_TOKEN`
before the deploy.

Do **not** edit the Worker only in the Cloudflare dashboard — keep this
folder authoritative so the source can't disappear with a config wipe.

## Email Routing rule (Cloudflare dashboard)

- Zone: `drifting.space`
- Rule: literal match `to == ai-research@drifting.space` → action `worker`
  → script `ai-trading` (this Worker)
- Catch-all: forward to a personal mailbox (currently
  `lance.colton@gmail.com`) so non-newsletter mail is still recoverable.

If you ever recreate the rule, the action must point at this Worker by name
(`ai-trading`); the Flask side does not care which Worker calls it as long
as the JSON body matches the contract below.

## Webhook contract (must match `webhook_newsletter` in Flask)

```jsonc
POST /api/webhooks/newsletter
Content-Type: application/json
{
  "from":    "<From header value>",       // raw header string, decoded server-side
  "to":      "<To header value>",
  "subject": "<Subject header value>",
  "raw_eml": "<full RFC 5322 message>"     // used to recover real sender + body
}
```

Flask responses:

- `200 {"status":"success","id":"<uuid>","tickers":[...]}` — saved + AI started
- `200 {"status":"duplicate","duplicate_of":"<uuid>",...}` — body-hash dedup
- `400 {"error":"Missing required fields"}` — one of the four fields was empty
- `400 {"error":"Failed to parse raw email"}` — `raw_eml` not RFC 5322
- `500 {"error":"..."}` — DB save or unexpected failure

The Worker only checks `response.ok`. If it's not OK, it calls
`message.setReject(...)` so Cloudflare will treat the email as undeliverable.

## Verifying it's wired up

From the repo root:

```powershell
.\venv\Scripts\activate
python web_dashboard\scripts\send_test_newsletter_webhook.py `
  --url "https://ai-trading.drifting.space/api/webhooks/newsletter" `
  --token "$env:NEWSLETTER_WEBHOOK_TEST_TOKEN"
```

That hits the Flask endpoint directly in dry-run mode (no DB write, no AI),
which proves the Flask side is healthy. To verify the Cloudflare path
end-to-end, forward (or have a publisher deliver to)
`ai-research@drifting.space` and check the `newsletters` table.
