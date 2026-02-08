---
name: Newsletter Evaluation
description: Framework for separating promotional newsletters from independent analysis
target_prompts:
  - summary
triggers:
  keywords: []
  article_types: [Newsletter]
  always: false
priority: 3
max_tokens: 460
---
## Newsletter Credibility Framework

### Promotion vs Research
- Detect compensation disclosures, affiliate links, and upsell framing.
- Distinguish analysis intent from subscription-conversion intent.

### Bias Pattern Detection
- Flag perma-bull or fear-marketing styles that ignore disconfirming data.
- Treat cherry-picked track records as low-evidence claims.

### Multi-Ticker Handling
- Extract all meaningful tickers, not just headline symbols.
- Separate primary thesis ticker from incidental mentions.

### Output Requirements
- In `fact_check`, note disclosure language and incentive alignment concerns.
