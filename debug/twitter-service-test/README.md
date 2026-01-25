# Twitter Scraper Test (Node.js)

Test script for `@the-convocation/twitter-scraper` to compare with Python's `twscrape`.

## Setup

### 1. Install Dependencies

```bash
cd debug/twitter-service-test
npm install
```

### 2. Set Twitter Credentials

**On Linux/Mac:**
```bash
export TWITTER_USERNAME="your_username"
export TWITTER_PASSWORD="your_password"
```

**On Windows (PowerShell):**
```powershell
$env:TWITTER_USERNAME="your_username"
$env:TWITTER_PASSWORD="your_password"
```

**On Windows (CMD):**
```cmd
set TWITTER_USERNAME=your_username
set TWITTER_PASSWORD=your_password
```

### 3. Run Test

```bash
npm test
# or
node test.js
```

## What It Tests

- Logs into Twitter using your credentials
- Searches for 5 test tickers: AAPL, TSLA, NVDA, AMD, PLTR
- Fetches up to 10 tweets per ticker
- Shows engagement metrics (likes, retweets, replies)
- Saves results to `twitter_nodejs_results.json`

## Expected Output

```
================================================================================
Twitter Scraper Test (@the-convocation/twitter-scraper)
================================================================================

--- Step 1: Login to Twitter ---
Logging in as your_username...
✅ Successfully logged in

--- Step 2: Test Twitter Search ---
Testing 5 tickers: AAPL, TSLA, NVDA, AMD, PLTR

--- Testing AAPL ---
Searching for: $AAPL
  Fetched 5 tweets...
  Fetched 10 tweets...
✅ Found 10 tweets for AAPL

  Top tweets:

  Tweet #1:
  Author: @someuser
  Text: $AAPL breaking resistance at $180! This could be the start of a big move...
  Engagement: 245 (L:100 RT:50 R:45)
  URL: https://twitter.com/someuser/status/123456789

...

================================================================================
SUMMARY
================================================================================
AAPL: ✅ 10 tweets found
TSLA: ✅ 10 tweets found
NVDA: ✅ 10 tweets found
AMD: ✅ 10 tweets found
PLTR: ✅ 10 tweets found

✅ Results saved to: twitter_nodejs_results.json
```

## Compare with Python twscrape

To compare both libraries side-by-side:

**Node.js (@the-convocation/twitter-scraper):**
```bash
cd debug/twitter-service-test
node test.js
```

**Python (twscrape):**
```bash
cd ../..
python debug/test_twscrape_twitter.py
```

Then compare:
- `debug/twitter-service-test/twitter_nodejs_results.json` (Node.js)
- `debug/twitter_test_results.json` (Python)

## Integration Options

See the detailed integration guide printed at the end of the test, or read:
- [TWITTER_SCRAPER_COMPARISON.md](../TWITTER_SCRAPER_COMPARISON.md)

## Troubleshooting

### Login Failed
- Check username/password are correct
- Make sure account is not locked/suspended
- Try logging in via web browser first
- Twitter may require email/phone verification

### Rate Limited
- Wait 15 minutes and try again
- Use fewer test tickers
- Add longer delays between searches

### Account Banned
- Use burner account, not personal account
- Create new account with temp email/phone
- Consider using Python twscrape instead (same risk)

## Next Steps

After testing both libraries, decide:

1. **Use Python twscrape** if:
   - You want pure Python integration
   - You want to get it working quickly
   - You're comfortable with Python

2. **Use Node.js scraper** if:
   - You're comfortable with Node.js
   - You want the most actively maintained library (updated Dec 31, 2025!)
   - You're willing to create a microservice or use subprocess
