---
name: Insider and Congress Trading Analysis
description: Framework for insider Form 4 and congressional STOCK Act signal quality
target_prompts:
  - summary
  - congress_trades
  - ticker_analysis
triggers:
  keywords: [insider buying, insider selling, Form 4, 10b5-1, cluster buying, congress trade, congressional, senator, representative, STOCK Act, beneficial owner]
  article_types: []
  always: false
  always_for: [congress_trades]
priority: 2
max_tokens: 520
---
## Insider and Congressional Signal Framework

### Insider Trading Interpretation
- Weight **cluster buying** higher than isolated transactions.
- Treat selling as less predictive unless size/timing is exceptional.
- Check 10b5-1 context to separate routine execution from discretionary action.

### Congressional Trade Context
- Map committee jurisdiction overlap to sector/ticker relevance.
- Distinguish potential policy-information edge from routine portfolio activity.
- Use STOCK Act timing/latency caveats when judging immediacy.

### Conviction and Relevance
- Consider dollar size relative to likely net worth and prior behavior.
- Increase confidence only with repeated, aligned activity and context support.

### Output Requirements
- For conflict analysis, explain overlap and confidence drivers explicitly.
- Avoid over-claiming causality when disclosure timing is delayed.
