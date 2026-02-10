---
name: Social Sentiment Analysis
description: Social-media sentiment reliability and manipulation-risk framework
target_prompts:
  - crowd_sentiment
triggers:
  keywords: []
  article_types: []
  always: true
priority: 2
max_tokens: 240
---
## Crowd Sentiment Reliability Framework

### Source Behavior Differences
- Account for Reddit long-form DD vs rapid StockTwits message style.
- Weight evidence-backed posts higher than slogan-driven momentum chatter.

### Regime and Extremes
- Extreme euphoria can mark late-stage chasing risk.
- Extreme fear can mark capitulation but needs confirmation.

### Manipulation and Bot Risk
- Flag repetitive phrasing bursts, account-age anomalies, and copy-paste patterns.
- Escalate caution on obscure tickers with sudden coordinated posting volume.

### Output Requirements
- Choose one label from the allowed sentiment classes.
- Keep reasoning concise and tied to observable language patterns.
