# Social Sentiment Tracking Documentation

## Overview
The Social Sentiment Tracking feature monitors crowd sentiment for watched tickers on social media platforms (Reddit and StockTwits) to identify potential momentum shifts or viral interest.

## Architecture

### 1. Data Sources
- **Reddit**: Unauthenticated public search API.
  - Queries: `$TICKER` (always) and `TICKER` (if not common word).
  - **Noise Filters**:
    - Common words (e.g., AI, CAT, GOOD) are restricted to cashtag-only searches.
    - Plain text searches require strict word-boundary matching (regex).
  - Rate Limit: ~1 request/sec (safe mode).
  - Scope: Recent posts (last 24 hours).
- **StockTwits**: Public API (with FlareSolverr bypass).
  - Endpoint: `streams/symbol/{ticker}.json`.
  - Scope: Recent messages (last 60 minutes).

### 2. Job Workflow (`social_sentiment`)
Some steps run every **60 minutes**:
1.  **Ticker Discovery**: Combines `watched_tickers` (active) and `latest_positions` (owned).
2.  **StockTwits Fetch**:
    - Uses FlareSolverr to bypass Cloudflare protection.
    - Calculates `bull_bear_ratio` based on user-tagged sentiment (Bullish/Bearish).
    - Counts message `volume`.
3.  **Reddit Fetch**:
    - Performs smart rate limiting (sleeps only if needed).
    - Searches and deduplicates posts.
    - Selects top 5 posts by engagement score.
    - **Inline AI Analysis**: Sends content to Ollama (Granite model) to generate:
        - `sentiment`: (EUPHORIC, BULLISH, NEUTRAL, BEARISH, FEARFUL)
        - `reasoning`: Concise explanation of the sentiment.
4.  **Data Storage**:
    - Saves metrics to `social_metrics` table.
    - Stores raw posts/comments in `raw_data` JSONB column.

### 3. Database Schema
- **`social_metrics`**: Stores snapshots of sentiment.
  - `ticker`, `platform`, `volume`, `sentiment_score`, `bull_bear_ratio`.
  - `raw_data`: JSON blob of top posts used for analysis.

### 4. Subreddit Scanner (Discovery Job)
- **Schedule**: Every 4 hours.
- **Goal**: Find *new* investment opportunities (tickers not yet watched).
- **Targets**: `r/pennystocks`, `r/RobinHoodPennyStocks`, `r/microcap`, `r/Shortsqueeze`.
- **Logic**:
  - Fetches top posts (Score > 20).
  - Fetches top comments for context ("Deep Dive").
  - Uses AI to determine if the post is a valid "Due Diligence" pitch.
  - Svaes valid findings to `research_articles` with `article_type='reddit_discovery'`.

## Key Configurations
- **Job Interval**: 60 minutes.
- **AI Model**: `granite4.1:8b` (via Ollama).
- **Timeout**: 90 seconds for AI streaming calls.
- **Rate Limits**: 
  - Reddit: Dynamic sleep (ensures >2s between requests).
  - StockTwits: Dependent on FlareSolverr/Proxy latency.

## Effectiveness & Future Improvements

### Current Limitations
- **Snapshot Only**: Analyzes current state, doesn't inherently track "rate of change" (acceleration).
- **StockTwits AI**: StockTwits data is only counted (volume/ratio), not analyzed by AI for nuance.
- **Coverage**: Only checks main Reddit search, not specific subreddits (e.g., r/penny_stocks) explicitly.

### Proposed Enhancements
1.  **Trend/Momentum Detection**:
    - Compare current volume/sentiment vs. 24h moving average.
    - Alert on "spikes" (e.g., volume > 300% of normal).
2.  **StockTwits AI**:
    - Feed top StockTwits messages to Ollama for deeper qualitative analysis (sarcasm detection).
3.  **Cross-Platform Signal**:
    - Create a "Confirmed Viral" signal if BOTH Reddit and StockTwits show > 200% volume spike.
4.  **Keyword Monitoring**:
    - Track specific phrases like "due diligence", "yolo", "catalyst" for higher conviction signal.
