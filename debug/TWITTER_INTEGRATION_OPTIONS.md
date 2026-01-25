# Twitter/X Integration Options for Social Sentiment

## Investigation Summary

**Date:** 2026-01-25
**Goal:** Add Twitter/X as a data source for social sentiment alongside StockTwits and Reddit

## Current Infrastructure

✅ **What You Have:**
- FlareSolverr (Cloudflare bypass) - running in production
- SearXNG client code - configured but NOT deployed locally
- Ollama AI analysis pipeline - working
- Social sentiment DB schema - supports multiple platforms

❌ **What's Missing:**
- Twitter/X data collection method
- SearXNG container (not running locally)
- twscrape library (not installed)

## Option Comparison

| Option | Pros | Cons | Setup Time | Reliability | Recommendation |
|--------|------|------|-----------|------------|----------------|
| **1. SearXNG Twitter** | No auth needed, existing code | Requires SearXNG deployment, limited data | 30 min | Medium | ⚠️ Deploy first |
| **2. twscrape (API)** | Best data quality, async, actively maintained | Needs Twitter account, ban risk | 1 hour | High | ✅ **RECOMMENDED** |
| **3. Nitter Instances** | No auth needed | Instances unreliable, many shut down | 15 min | Low | ❌ Not recommended |
| **4. FlareSolverr Scraping** | Reuses infrastructure | Slow, fragile, limited data | 2 hours | Low | ⚠️ Fallback only |

## RECOMMENDED APPROACH: twscrape

### Why twscrape?

1. **Actively maintained** - Last updated April 2025
2. **Async Python** - Fits your codebase patterns
3. **Reliable** - Handles X's anti-scraping measures
4. **Good for finance** - Excellent cashtag search ($AAPL, $TSLA)
5. **Full data** - Engagement metrics, timestamps, user info

### Setup Steps

#### 1. Install twscrape
```bash
pip install twscrape
```

#### 2. Create Burner Twitter Account(s)
- Use temporary email (temp-mail.org, guerrillamail.com)
- Use temporary phone number (Google Voice, Burner app, or SMS verification services)
- Create 1-3 accounts (more accounts = better rate limit handling)
- **IMPORTANT:** Don't use your personal account - accounts may get banned

#### 3. Add Accounts to twscrape
```bash
# Add account (interactive)
twscrape add_accounts

# Or add from file
echo "username:password:email:email_password" > accounts.txt
twscrape add_accounts accounts.txt

# Login all accounts
twscrape login_accounts
```

#### 4. Test the Setup
```bash
python debug/test_twscrape_twitter.py
```

This will:
- Verify account setup
- Search for test tickers ($AAPL, $TSLA, etc.)
- Show sample tweets
- Save results to JSON
- Print integration guide

### Integration into social_service.py

After testing, you'll add this method to `web_dashboard/social_service.py`:

```python
async def fetch_twitter_sentiment(self, ticker: str, max_duration: Optional[float] = None) -> Dict[str, Any]:
    """Fetch sentiment from Twitter/X using twscrape

    Args:
        ticker: Ticker symbol to fetch
        max_duration: Optional timeout (similar to Reddit)

    Returns:
        Dictionary with:
        - volume: Tweet count in last 24 hours
        - sentiment_label: AI-categorized label
        - sentiment_score: Numeric score (-2.0 to 2.0)
        - raw_data: Top 3 tweets as JSONB
    """
    from twscrape import API, gather

    fetch_start = time.time()

    try:
        api = API()

        # Search for cashtag (last 24 hours)
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        query = f"(${ticker} OR #{ticker}) since:{cutoff.strftime('%Y-%m-%d')}"

        # Fetch tweets
        tweets_raw = await gather(api.search(query, limit=20))

        # Process tweets
        tweets = []
        for tweet in tweets_raw:
            # Check timeout
            if max_duration and (time.time() - fetch_start) > max_duration:
                logger.debug(f"Twitter fetch timeout for {ticker}")
                break

            tweets.append({
                'text': tweet.rawContent,
                'engagement': (tweet.likeCount or 0) + (tweet.retweetCount or 0) * 2,
                'created_at': tweet.date.isoformat(),
                'author': tweet.user.username,
                'url': tweet.url
            })

        # Sort by engagement
        tweets.sort(key=lambda x: x['engagement'], reverse=True)

        # Analyze top 5 tweets with Ollama (reuse Reddit pattern)
        texts = [t['text'] for t in tweets[:5]]
        sentiment_label = 'NEUTRAL'
        sentiment_score = 0.0

        if texts and self.ollama:
            try:
                result = self.ollama.analyze_crowd_sentiment(texts, ticker)
                sentiment_label = result.get('sentiment', 'NEUTRAL')
                sentiment_score = self.map_sentiment_label_to_score(sentiment_label)
            except Exception as e:
                logger.warning(f"Ollama sentiment analysis failed for {ticker}: {e}")

        # Prepare raw_data (top 3 tweets)
        raw_data = None
        if tweets:
            raw_data = [
                {
                    'text': t['text'][:500],
                    'engagement': t['engagement'],
                    'author': t['author'],
                    'url': t['url']
                }
                for t in tweets[:3]
            ]

        logger.debug(f"Twitter {ticker}: volume={len(tweets)}, sentiment={sentiment_label}")

        return {
            'volume': len(tweets),
            'sentiment_label': sentiment_label,
            'sentiment_score': sentiment_score,
            'raw_data': raw_data
        }

    except Exception as e:
        logger.error(f"Error fetching Twitter sentiment for {ticker}: {e}", exc_info=True)
        return {
            'volume': 0,
            'sentiment_label': 'NEUTRAL',
            'sentiment_score': 0.0,
            'raw_data': None
        }
```

### Scheduler Integration

Update your social sentiment job to include Twitter:

```python
# In the job that fetches social sentiment
for ticker in watched_tickers:
    # Existing sources
    stocktwits = service.fetch_stocktwits_sentiment(ticker)
    reddit = service.fetch_reddit_sentiment(ticker, max_duration=30)

    # NEW: Twitter
    twitter = await service.fetch_twitter_sentiment(ticker, max_duration=30)

    # Save all three
    service.save_metrics(ticker, 'stocktwits', stocktwits)
    service.save_metrics(ticker, 'reddit', reddit)
    service.save_metrics(ticker, 'twitter', twitter)  # Platform field already exists!
```

### Rate Limiting Considerations

1. **Account Rotation**
   - twscrape automatically rotates between accounts
   - Add 2-3 accounts for better resilience

2. **Search Limits**
   - ~50 searches per account per 15 minutes
   - With 3 accounts = ~150 searches per 15 min
   - If you have 50 watchlist tickers, that's plenty

3. **Backoff Strategy**
   - Add 2-5 second delay between searches
   - Monitor for rate limit errors
   - Retry with exponential backoff

4. **Account Health**
   - Check account status weekly: `twscrape accounts_info`
   - Replace banned accounts as needed
   - Keep accounts active (don't just scrape, occasionally browse)

## Alternative: SearXNG (If You Want to Deploy It)

If you prefer not to manage Twitter accounts, you can deploy SearXNG:

### 1. Add SearXNG to docker-compose.yml

```yaml
searxng:
  image: searxng/searxng:latest
  container_name: searxng
  ports:
    - "8080:8080"
  volumes:
    - ./searxng:/etc/searxng:rw
  environment:
    - SEARXNG_BASE_URL=http://localhost:8080
  restart: unless-stopped
  networks:
    - trading-network
```

### 2. Configure Twitter Search Engine

Edit `searxng/settings.yml` to enable Twitter/social media engines.

### 3. Test SearXNG Twitter Search

```bash
python debug/test_twitter_options.py
```

### 4. Integrate SearXNG Search

```python
def fetch_twitter_sentiment_searxng(self, ticker: str) -> Dict[str, Any]:
    """Fetch Twitter sentiment via SearXNG (no auth required)"""
    from searxng_client import get_searxng_client

    searxng = get_searxng_client()
    if not searxng:
        return {'volume': 0, 'error': 'SearXNG unavailable'}

    # Search for ticker
    results = searxng.search(
        query=f"${ticker} OR #{ticker}",
        engines=['twitter'],  # If Twitter engine is enabled
        time_range='day',
        max_results=20
    )

    # Extract tweets from results
    tweets = [r for r in results.get('results', [])
              if 'twitter.com' in r.get('url', '') or 'x.com' in r.get('url', '')]

    # Process similar to twscrape approach
    # ...
```

## Next Steps

### Option A: Use twscrape (Recommended)

1. ✅ Install twscrape: `pip install twscrape`
2. ✅ Set up burner Twitter account(s)
3. ✅ Run test script: `python debug/test_twscrape_twitter.py`
4. ✅ Review results in `debug/twitter_test_results.json`
5. ✅ Add `fetch_twitter_sentiment()` to `social_service.py`
6. ✅ Update social sentiment job to call Twitter fetcher
7. ✅ Test with watchlist tickers
8. ✅ Monitor for rate limits and account health

### Option B: Deploy SearXNG

1. ⚠️ Add SearXNG to `docker-compose.yml`
2. ⚠️ Configure Twitter search engine in settings
3. ⚠️ Start SearXNG: `docker-compose up -d searxng`
4. ⚠️ Run test: `python debug/test_twitter_options.py`
5. ⚠️ Integrate into social_service.py

### Option C: Backup (FlareSolverr Scraping)

Only use if both options above fail:
1. ❌ Test FlareSolverr scraping: `python debug/test_twitter_flaresolverr.py`
2. ❌ Accept limitations (slow, fragile, limited data)
3. ❌ Implement as fallback only

## Test Scripts Created

| Script | Purpose | When to Use |
|--------|---------|-------------|
| `test_twitter_options.py` | Investigate all options (SearXNG, twscrape) | Initial investigation |
| `test_twscrape_twitter.py` | Test twscrape Twitter collection | After installing twscrape |
| `test_twitter_flaresolverr.py` | Test FlareSolverr scraping | Fallback only |

## Database Schema

**Good news:** No schema changes needed! The existing `social_metrics` table already supports:
- `platform` field (can be 'stocktwits', 'reddit', or 'twitter')
- `raw_data` JSONB for tweet storage
- `sentiment_label` and `sentiment_score` for AI analysis

## Success Metrics

After integration, you should see:
- ✅ Twitter data in `social_metrics` table with `platform='twitter'`
- ✅ AI analysis in `social_sentiment_analysis` table
- ✅ Combined sentiment view in dashboard (StockTwits + Reddit + Twitter)
- ✅ Increased data coverage (more tickers with sentiment data)

## Risk Mitigation

### Account Bans
- Use burner accounts only
- Rotate multiple accounts
- Don't over-query (respect rate limits)
- Monitor account health weekly

### Data Quality
- Filter by engagement (min likes/retweets)
- Validate ticker mentions in tweet text
- Watch for bot accounts
- Consider verified accounts more heavily

### Performance
- Set `max_duration` timeout (30 seconds recommended)
- Use async patterns (already in twscrape)
- Add delays between searches (2-5 seconds)
- Cache results for repeat queries

## Questions?

If you encounter issues:
1. Check `debug/twitter_test_results.json` for detailed error messages
2. Review twscrape docs: https://github.com/vladkens/twscrape
3. Monitor account status: `twscrape accounts_info`
4. Check rate limits: Look for 429 errors in logs

---

**Ready to proceed?** Start with installing twscrape and running the test script!
