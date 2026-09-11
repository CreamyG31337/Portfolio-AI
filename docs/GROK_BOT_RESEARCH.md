# Grok Bot weekday X research

Grok Bot (Cursor Pro) is a separate app with a persistent cloud VM. It has no public API. This repo exposes a **tiny token-auth Flask ingest** so the Bot can pull a watchlist queue and write X briefs into Research Postgres.

It does **not** write Insights, `research_articles`, or social sentiment. A later LLM job can consume `grok_x_briefs`.

## What the Bot is for

StockTwits and Reddit already run in-app. **X is the hole.** The Bot’s native read-only X plugin is the collector. One weekday sweep, max 5 tickers.

## Server env

**Prod:** Woodpecker secret `grok_bot_token` (mapped to `GROK_BOT_TOKEN`). Create the secret **before** merging the `from_secret` line — a missing name fails the pipeline.

**Dev (this machine):** `GROK_BOT_TOKEN` in `web_dashboard/.env` only.

`GROK_WATCHLIST_FUNDS` is a **code default**: `Project Chimera` and `RRSP Lance Webull`. No Woodpecker secret. Local override with `GROK_WATCHLIST_FUND=TEST` or `GROK_WATCHLIST_FUNDS=TEST`.

Generate a token:

```powershell
.\venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(32))"
```

Woodpecker → repository → Settings → Secrets → add `grok_bot_token` (lowercase). Put the **same** value on the Grok Bot VM. Redeploy after the secret exists.

Apply DDL on Research Postgres (already done on the URL in local `.env`):

```powershell
.\venv\Scripts\activate
Get-Content database\migrations\2026-09_add_grok_x_briefs.sql | .\venv\Scripts\python.exe -c "import os,sys; import psycopg2; sql=sys.stdin.read(); conn=psycopg2.connect(os.environ['RESEARCH_DATABASE_URL']); conn.autocommit=True; conn.cursor().execute(sql); print('ok')"
```

Or run the SQL file with `psql` against `RESEARCH_DATABASE_URL`. Do **not** apply this via Supabase MCP (wrong database).

## API

Auth: `Authorization: Bearer <GROK_BOT_TOKEN>`. CSRF-exempt. Cookie login is not used.

Base URL in production: `https://ai-trading.drifting.space`

### `GET /api/grok/queue`

Returns active **A then B** tickers from **both** Project Chimera and RRSP Lance Webull. Returns at most (5 minus distinct tickers already briefed today, UTC), so it can be empty after a full run. Skips C-tier, `ideas_inbox` discovery names, and tickers that already have a brief for **today** (UTC) on either fund. Prefer never-briefed, then oldest prior brief. Same ticker on both funds is one queue item (`funds` lists both). Rate-limited to 30 requests/hour.

```powershell
curl.exe -sS -H "Authorization: Bearer $env:GROK_BOT_TOKEN" `
  https://ai-trading.drifting.space/api/grok/queue
```

```json
{
  "funds": ["Project Chimera", "RRSP Lance Webull"],
  "limit": 5,
  "data": [
    {
      "ticker": "AAA",
      "priority_tier": "A",
      "fund": "Project Chimera",
      "funds": ["Project Chimera"],
      "last_brief_at": null,
      "last_cited_urls": []
    }
  ]
}
```

### `POST /api/grok/briefs`

One ticker or `{ "briefs": [ ... ] }` (max 5). Optional per-brief `fund` field (echo from queue item or resolved from eligible watchlist). Upsert on `(fund, ticker, sweep_date)`. Rejects tickers not on either fund’s eligible watchlist. Rejects a 6th distinct ticker for the day across both funds (`429`). Max 8 posts per ticker, 65,536-character body limit. Rate-limited to 30 requests/hour.

```powershell
curl.exe -sS -X POST -H "Authorization: Bearer $env:GROK_BOT_TOKEN" `
  -H "Content-Type: application/json" `
  https://ai-trading.drifting.space/api/grok/briefs `
  -d "{\"ticker\":\"AAA\",\"body\":\"Quiet since yesterday.\",\"notable\":false,\"themes\":[],\"posts\":[]}"
```

```json
{
  "ticker": "AAA",
  "sweep_date": "2026-09-09",
  "body": "Notable: promoter thread claiming a financing.",
  "notable": true,
  "themes": ["financing rumor"],
  "posts": [
    {"url": "https://x.com/user/status/123", "post_id": "123", "summary": "Claims overnight raise"}
  ]
}
```

Validation and behavior:

- `sweep_date` must be the UTC date today or yesterday (`YYYY-MM-DD`); anything else is a 400. Defaults to UTC today.
- Post `url`s must start with `http://` or `https://` (max 2,000 chars); `theme` strings are truncated to 100 chars (max 20 themes).
- A same-day re-POST keeps an `evaluated` or `ignored` status unless `body` or `posts` changed (which resets `status` to `ingested`). New rows start as `ingested`.

## Bot VM checklist (operator)

Do this **in Grok Bot**, not in Cursor IDE. The laptop `mcp.json` does not carry over.

1. Connect the **X** plugin (read-only). Do not install Drive/GitHub unless you later change this design.
2. Store **only** `GROK_BOT_TOKEN` and the dashboard base URL. Never `SUPABASE_*`, `RESEARCH_DATABASE_URL`, or broker logins. All Bots share the VM.
3. Optional debug dir: `/workspace/grok-research/` for the last JSON if a run dies mid-way. Queue/SEEN live in the DB, not markdown files.
4. Paste the **Bot profile** below into the Bot profile. Keep send/buy/delete behind approval (this job should never need them).
5. Manual test: set `GROK_WATCHLIST_FUND=TEST` on Flask (or pin 1–2 TEST names on the watchlist), run `/x-watchlist-sweep` in chat, confirm rows with `SELECT ticker, sweep_date, notable FROM grok_x_briefs ORDER BY created_at DESC LIMIT 10`.
6. Save the skill after a good run. Define failure behavior first: X plugin error → POST nothing, tell chat, **do not** scrape x.com or open the dashboard.
7. Weekday routine **07:30 America/New_York**. Confirm timezone in Settings → Agent. Pause after the first scheduled run and check the **weekly Bot usage bar** before leaving it on.

### Bot profile (paste)

Role: Watchlist X listener for the micro-cap research loop.

Sources: X plugin only (cashtag `$TICKER` + company name, last 24–48h). Do not use StockTwits/Reddit.

Output: `POST /api/grok/briefs` after `GET /api/grok/queue`. Chat gets a one-liner (tickers + which were notable).

Caps: max 5 tickers per run, max ~15 unique posts cited.

Never: trade, post/reply/DM on X, log into the trading dashboard or brokers, spawn Cursor cloud agents, hold database URLs, treat memory as prices or positions.

### Skill `/x-watchlist-sweep` (paste)

When to use: weekday morning sweep, or ad-hoc when asked to check X for watchlist names.

Inputs: `GROK_BOT_TOKEN`, `GROK_API_BASE` (dashboard origin).

Steps:

1. `GET {GROK_API_BASE}/api/grok/queue` with `Authorization: Bearer $GROK_BOT_TOKEN`.
2. If the queue is empty, stop and say so.
3. For each ticker: X plugin search `$TICKER` and company name, last 24–48h. Skip cashtag spam and unrelated mentions. Prefer posts not in `last_cited_urls`.
4. `POST {GROK_API_BASE}/api/grok/briefs` per ticker (or one batch ≤5) with `fund` copied from the queue item, markdown `body`, `notable`, `themes`, `posts[{url, post_id?, summary}]`.
5. Chat: list tickers, notable vs quiet, and any HTTP errors.

Validation: every queued ticker either POSTed `200` or was skipped with a reason. No dashboard browser login. No x.com scraping if the plugin fails.

Output: DB rows (`status=ingested`). Optional copy of the JSON under `/workspace/grok-research/`.

Needs approval: nothing on this path.

## Later (not this v1)

A job can move `ingested` → `evaluated` / `ignored`, file `thesis_evidence` `user_url` rows, or post an advisory Insights `llm_reply`. Do not bump `last_reviewed_at` from Bot text.

## Security

- Token is scoped to these two routes; still a secret on a shared Bot VM.
- HTTPS only.
- Untrusted X text is stored as data. Any later LLM that reads `posts`/`body` must wrap it the same way social sentiment does.

## Tests

```powershell
.\venv\Scripts\activate
python -m pytest tests/test_flask_grok_bot.py -v
```
