# Twitter Scraper Library Comparison

## New Option Found: @the-convocation/twitter-scraper

**GitHub:** https://github.com/the-convocation/twitter-scraper
**Last Updated:** December 31, 2025 (v0.21.1) ✅ Very Active!

## Critical Difference: Node.js vs Python

| Library | Language | Last Update | Authentication | Account Ban Risk |
|---------|----------|-------------|----------------|------------------|
| **twscrape** | Python | April 2025 | Required | Medium |
| **@the-convocation/twitter-scraper** | **Node.js** | Dec 31, 2025 | Required | Medium-High |

## Detailed Comparison

### @the-convocation/twitter-scraper (Node.js)

**Pros:**
- ✅ **Very actively maintained** (updated 4 days ago!)
- ✅ **Fast** - "extremely fast" access to tweet data
- ✅ **Feature-rich** - TypeScript support, CORS proxy, CycleTLS for Cloudflare bypass
- ✅ **Well documented** - 574 GitHub stars, active community
- ✅ **Custom rate limiting** - configurable strategies
- ✅ **Edge runtime support** - works with Cloudflare Workers

**Cons:**
- ❌ **Node.js only** - your codebase is Python
- ❌ **Account ban risk** - "any account you log into... is subject to being banned at any time"
- ❌ **Rate limiting** - can pause up to 13 minutes
- ❌ **Brittle** - "Twitter regularly breaks this library" (API changes)
- ❌ **Requires integration** - would need Node.js service or subprocess

**Installation:**
```bash
npm install @the-convocation/twitter-scraper
```

### twscrape (Python)

**Pros:**
- ✅ **Python native** - fits your codebase perfectly
- ✅ **Async** - uses Python asyncio
- ✅ **Actively maintained** - April 2025 update
- ✅ **Account rotation** - built-in multi-account support
- ✅ **Simple integration** - drop into existing `social_service.py`

**Cons:**
- ⚠️ **Account ban risk** - same as all scrapers
- ⚠️ **Rate limits** - Twitter's standard limits apply
- ⚠️ **Less frequent updates** - April 2025 vs Dec 2025

**Installation:**
```bash
pip install twscrape
```

## Integration Approaches

### Option 1: Use twscrape (Python) - RECOMMENDED

**Why:** Direct Python integration, no additional infrastructure needed.

**Implementation:**
```python
# In social_service.py
async def fetch_twitter_sentiment(self, ticker: str) -> Dict[str, Any]:
    from twscrape import API, gather

    api = API()
    tweets = await gather(api.search(f"${ticker}", limit=20))
    # ... process tweets
```

**Time to implement:** 1-2 hours
**Complexity:** Low
**Maintenance:** Low

---

### Option 2: Node.js Microservice with @the-convocation/twitter-scraper

**Why:** Most actively maintained library, very fast, feature-rich.

**Architecture:**
```
┌─────────────────────────────────────────────────────┐
│  Python (social_service.py)                          │
│    ↓ HTTP request                                   │
│  Node.js Twitter Service (Express/Fastify)          │
│    ↓ @the-convocation/twitter-scraper               │
│  Twitter/X API                                       │
└─────────────────────────────────────────────────────┘
```

**Implementation:**

1. Create Node.js service:
```javascript
// twitter-service/index.js
import Scraper from '@the-convocation/twitter-scraper';
import express from 'express';

const app = express();
const scraper = new Scraper();

// Login once at startup
await scraper.login(
  process.env.TWITTER_USERNAME,
  process.env.TWITTER_PASSWORD
);

app.get('/search/:ticker', async (req, res) => {
  const { ticker } = req.params;

  const tweets = [];
  for await (const tweet of scraper.searchTweets(`$${ticker}`, 20)) {
    tweets.push({
      text: tweet.text,
      likes: tweet.likes,
      retweets: tweet.retweets,
      created_at: tweet.timestamp
    });
  }

  res.json({ ticker, tweets });
});

app.listen(3000);
```

2. Add to docker-compose.yml:
```yaml
twitter-service:
  build: ./twitter-service
  container_name: twitter-scraper
  ports:
    - "3000:3000"
  environment:
    - TWITTER_USERNAME=${TWITTER_USERNAME}
    - TWITTER_PASSWORD=${TWITTER_PASSWORD}
  networks:
    - trading-network
```

3. Call from Python:
```python
# In social_service.py
def fetch_twitter_sentiment(self, ticker: str) -> Dict[str, Any]:
    import requests

    response = requests.get(
        f"http://twitter-service:3000/search/{ticker}",
        timeout=30
    )
    data = response.json()

    tweets = data['tweets']
    # ... process tweets with Ollama
```

**Time to implement:** 4-6 hours
**Complexity:** Medium-High
**Maintenance:** Medium

---

### Option 3: Python Subprocess to Node.js Script

**Why:** Use Node.js library without full microservice.

**Implementation:**
```python
# In social_service.py
def fetch_twitter_sentiment_nodejs(self, ticker: str) -> Dict[str, Any]:
    import subprocess
    import json

    # Call Node.js script
    result = subprocess.run(
        ['node', 'scripts/twitter_search.js', ticker],
        capture_output=True,
        text=True,
        timeout=30
    )

    tweets = json.loads(result.stdout)
    # ... process tweets
```

```javascript
// scripts/twitter_search.js
import Scraper from '@the-convocation/twitter-scraper';

const ticker = process.argv[2];
const scraper = new Scraper();

await scraper.login(process.env.TWITTER_USERNAME, process.env.TWITTER_PASSWORD);

const tweets = [];
for await (const tweet of scraper.searchTweets(`$${ticker}`, 20)) {
  tweets.push({
    text: tweet.text,
    likes: tweet.likes,
    retweets: tweet.retweets
  });
}

console.log(JSON.stringify(tweets));
```

**Time to implement:** 2-3 hours
**Complexity:** Medium
**Maintenance:** Medium

---

## My Recommendation

### For Quick Implementation: twscrape (Python)

**Use twscrape if:**
- ✅ You want to get Twitter data running TODAY
- ✅ You prefer pure Python (no Node.js complexity)
- ✅ Your team is comfortable with Python
- ✅ You want minimal infrastructure changes

**Steps:**
1. `pip install twscrape`
2. Set up burner Twitter account
3. Run test: `python debug/test_twscrape_twitter.py`
4. Integrate into `social_service.py`
5. Done!

---

### For Best Long-Term Solution: Node.js Microservice

**Use @the-convocation/twitter-scraper if:**
- ✅ You're comfortable with Node.js
- ✅ You want the most actively maintained library
- ✅ You want the fastest performance
- ✅ You're willing to invest in infrastructure
- ✅ You plan to expand Twitter features (DMs, profiles, etc.)

**Steps:**
1. Create Node.js Twitter service
2. Add to docker-compose.yml
3. Set up burner Twitter account
4. Call from Python via HTTP
5. Done!

---

## Side-by-Side Feature Comparison

| Feature | twscrape | @the-convocation/twitter-scraper |
|---------|----------|----------------------------------|
| **Language** | Python | Node.js |
| **Last Update** | April 2025 | Dec 31, 2025 ⭐ |
| **GitHub Stars** | ~1.2k | ~574 |
| **Authentication** | Required | Required |
| **Multi-account** | ✅ Built-in | ⚠️ Manual |
| **Rate Limiting** | Auto-handles | Configurable strategies |
| **Search Tweets** | ✅ | ✅ |
| **User Profiles** | ✅ | ✅ |
| **Trending Topics** | ❌ | ✅ |
| **Tweet Details** | ✅ | ✅ |
| **Cloudflare Bypass** | Partial | ✅ CycleTLS |
| **TypeScript** | ❌ | ✅ |
| **Installation** | `pip install` | `npm install` |
| **Python Integration** | Native | HTTP/Subprocess |

---

## Test Both Options

I can create test scripts for both:

### Test twscrape (Already created):
```bash
python debug/test_twscrape_twitter.py
```

### Test Node.js scraper (new):
Would you like me to create:
1. `debug/twitter-service-test/` - standalone Node.js test
2. Test script to compare both side-by-side

---

## My Final Recommendation

**Start with twscrape** because:
1. ✅ Faster to implement (hours vs days)
2. ✅ Pure Python (your team's expertise)
3. ✅ Works today with your existing infrastructure
4. ✅ Easy to test and validate

**If twscrape works but you hit issues:**
- Account bans become frequent
- Rate limits are too restrictive
- Need more features (trending, profiles)

**Then migrate to Node.js microservice:**
- More actively maintained
- Better Cloudflare bypass
- More features available
- Worth the investment at that point

---

## Next Steps

**Option A: Test twscrape (Quick Start)**
```bash
# 1. Install
pip install twscrape

# 2. Set up account
twscrape add_accounts
# Enter: username, password, email, email_password

# 3. Login
twscrape login_accounts

# 4. Test
python debug/test_twscrape_twitter.py
```

**Option B: Test Node.js scraper (Best Long-Term)**
```bash
# 1. Create test directory
mkdir debug/twitter-service-test
cd debug/twitter-service-test

# 2. Initialize Node.js project
npm init -y
npm install @the-convocation/twitter-scraper

# 3. Create test script
# (I can create this for you)

# 4. Test
node test.js
```

**Which approach would you like to try first?**

---

## Sources
- [GitHub - the-convocation/twitter-scraper](https://github.com/the-convocation/twitter-scraper)
- [@the-convocation/twitter-scraper Documentation](https://the-convocation.github.io/twitter-scraper/)
- [@the-convocation/twitter-scraper on npm](https://www.npmjs.com/package/@the-convocation/twitter-scraper)
