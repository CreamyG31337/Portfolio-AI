#!/usr/bin/env node
/**
 * Test @the-convocation/twitter-scraper
 * ======================================
 *
 * Tests the Node.js twitter-scraper library to compare with Python's twscrape.
 *
 * Setup:
 * 1. npm install
 * 2. Set environment variables:
 *    - TWITTER_USERNAME
 *    - TWITTER_PASSWORD
 *    - TWITTER_EMAIL (optional)
 *    - TWITTER_EMAIL_PASSWORD (optional)
 * 3. node test.js
 */

import { Scraper } from '@the-convocation/twitter-scraper';
import { writeFileSync } from 'fs';

// Test configuration
const TEST_TICKERS = ['AAPL', 'TSLA', 'NVDA', 'AMD', 'PLTR'];
const MAX_TWEETS_PER_TICKER = 10;

class TwitterScraperTest {
  constructor() {
    this.scraper = new Scraper();
    this.results = {};
  }

  async initialize() {
    console.log('=' .repeat(80));
    console.log('Twitter Scraper Test (@the-convocation/twitter-scraper)');
    console.log('=' .repeat(80));
    console.log('');

    // Check for credentials
    const username = process.env.TWITTER_USERNAME;
    const password = process.env.TWITTER_PASSWORD;

    if (!username || !password) {
      console.error('❌ Missing Twitter credentials');
      console.log('');
      console.log('Set environment variables:');
      console.log('  export TWITTER_USERNAME="your_username"');
      console.log('  export TWITTER_PASSWORD="your_password"');
      console.log('');
      console.log('Or on Windows:');
      console.log('  set TWITTER_USERNAME=your_username');
      console.log('  set TWITTER_PASSWORD=your_password');
      console.log('');
      return false;
    }

    try {
      console.log('--- Step 1: Login to Twitter ---');
      console.log(`Logging in as ${username}...`);

      await this.scraper.login(username, password);

      // Verify login worked
      const isLoggedIn = await this.scraper.isLoggedIn();
      if (!isLoggedIn) {
        console.error('❌ Login failed');
        return false;
      }

      console.log('✅ Successfully logged in');
      console.log('');
      return true;

    } catch (error) {
      console.error('❌ Error during login:', error.message);
      console.log('');
      console.log('Common issues:');
      console.log('  - Wrong username/password');
      console.log('  - Account locked/suspended');
      console.log('  - Rate limited by Twitter');
      console.log('  - Need to verify account (email/phone)');
      console.log('');
      return false;
    }
  }

  async searchTicker(ticker, maxTweets = 20) {
    console.log(`\n--- Testing ${ticker} ---`);

    try {
      // Search for cashtag
      const query = `$${ticker}`;
      console.log(`Searching for: ${query}`);

      const tweets = [];
      let count = 0;

      // Use searchTweets generator
      for await (const tweet of this.scraper.searchTweets(query, maxTweets, 'Latest')) {
        count++;

        tweets.push({
          id: tweet.id,
          text: tweet.text || '',
          created_at: tweet.timestamp ? new Date(tweet.timestamp * 1000).toISOString() : null,
          author: tweet.username || 'unknown',
          likes: tweet.likes || 0,
          retweets: tweet.retweets || 0,
          replies: tweet.replies || 0,
          views: tweet.views || 0,
          url: tweet.permanentUrl || '',
          engagement_score: (tweet.likes || 0) + (tweet.retweets || 0) * 2 + (tweet.replies || 0)
        });

        // Show progress
        if (count % 5 === 0) {
          console.log(`  Fetched ${count} tweets...`);
        }
      }

      // Sort by engagement
      tweets.sort((a, b) => b.engagement_score - a.engagement_score);

      console.log(`✅ Found ${tweets.length} tweets for ${ticker}`);

      // Show top 3
      if (tweets.length > 0) {
        console.log('\n  Top tweets:');
        tweets.slice(0, 3).forEach((tweet, i) => {
          console.log(`\n  Tweet #${i + 1}:`);
          console.log(`  Author: @${tweet.author}`);
          console.log(`  Text: ${tweet.text.substring(0, 100)}${tweet.text.length > 100 ? '...' : ''}`);
          console.log(`  Engagement: ${tweet.engagement_score} (L:${tweet.likes} RT:${tweet.retweets} R:${tweet.replies})`);
          console.log(`  URL: ${tweet.url}`);
        });
      }

      return {
        ticker,
        query,
        tweets,
        count: tweets.length,
        success: true
      };

    } catch (error) {
      console.error(`❌ Error searching ${ticker}:`, error.message);

      return {
        ticker,
        tweets: [],
        count: 0,
        success: false,
        error: error.message
      };
    }
  }

  async testMultipleTickers(tickers) {
    console.log('\n--- Step 2: Test Twitter Search ---');
    console.log(`Testing ${tickers.length} tickers: ${tickers.join(', ')}`);
    console.log('');

    for (const ticker of tickers) {
      const result = await this.searchTicker(ticker, MAX_TWEETS_PER_TICKER);
      this.results[ticker] = result;

      // Rate limiting - wait 2 seconds between searches
      if (ticker !== tickers[tickers.length - 1]) {
        console.log('\n  Waiting 2 seconds (rate limiting)...');
        await new Promise(resolve => setTimeout(resolve, 2000));
      }
    }
  }

  printSummary() {
    console.log('\n' + '='.repeat(80));
    console.log('SUMMARY');
    console.log('='.repeat(80));

    for (const [ticker, result] of Object.entries(this.results)) {
      if (result.success) {
        console.log(`${ticker}: ✅ ${result.count} tweets found`);
      } else {
        console.log(`${ticker}: ❌ ERROR - ${result.error || 'Unknown error'}`);
      }
    }

    console.log('');
  }

  saveResults() {
    const outputFile = 'twitter_nodejs_results.json';

    writeFileSync(
      outputFile,
      JSON.stringify(this.results, null, 2)
    );

    console.log(`✅ Results saved to: ${outputFile}`);
  }

  printIntegrationGuide() {
    console.log('\n' + '='.repeat(80));
    console.log('INTEGRATION OPTIONS');
    console.log('='.repeat(80));
    console.log(`
Since this is a Node.js library and your codebase is Python, you have 3 options:

Option 1: Node.js Microservice (Recommended for Production)
------------------------------------------------------------
Create a simple Express/Fastify API that wraps this scraper:

  // server.js
  import express from 'express';
  import { Scraper } from '@the-convocation/twitter-scraper';

  const app = express();
  const scraper = new Scraper();

  // Login once at startup
  await scraper.login(process.env.TWITTER_USERNAME, process.env.TWITTER_PASSWORD);

  app.get('/search/:ticker', async (req, res) => {
    const tweets = [];
    for await (const tweet of scraper.searchTweets(\`$\${req.params.ticker}\`, 20)) {
      tweets.push({ text: tweet.text, likes: tweet.likes });
    }
    res.json({ tweets });
  });

  app.listen(3000);

Then call from Python:
  import requests
  response = requests.get('http://localhost:3000/search/AAPL')
  tweets = response.json()['tweets']


Option 2: Python Subprocess (Simpler, but slower)
--------------------------------------------------
Call Node.js script from Python using subprocess:

  import subprocess
  import json

  result = subprocess.run(
    ['node', 'twitter_search.js', 'AAPL'],
    capture_output=True,
    text=True
  )
  tweets = json.loads(result.stdout)


Option 3: Use Python's twscrape instead (Easiest!)
---------------------------------------------------
Skip Node.js entirely and use the Python equivalent:

  pip install twscrape
  # Same functionality, pure Python integration


Comparison:
- Node.js scraper: Updated Dec 31, 2025 (very active!) but requires Node.js
- Python twscrape: Updated April 2025 (active) and pure Python

My Recommendation: Start with twscrape for quick integration, migrate to
Node.js microservice later if you need the extra features/speed.
`);
  }
}

// Main execution
async function main() {
  const test = new TwitterScraperTest();

  // Initialize
  const initialized = await test.initialize();
  if (!initialized) {
    process.exit(1);
  }

  // Test tickers
  await test.testMultipleTickers(TEST_TICKERS);

  // Print summary
  test.printSummary();

  // Save results
  test.saveResults();

  // Print integration guide
  test.printIntegrationGuide();

  console.log('\n' + '='.repeat(80));
  console.log('Test Complete!');
  console.log('='.repeat(80));
}

main().catch(error => {
  console.error('Fatal error:', error);
  process.exit(1);
});
