---
name: Earnings Analysis
description: Earnings-quality, guidance, and margin framework for quarterly/annual result interpretation
target_prompts:
  - summary
  - ticker_analysis
triggers:
  keywords: [earnings, EPS, revenue beat, revenue miss, guidance, quarterly results, annual report, fiscal year, same-store sales, operating margin, net income, EBITDA, top line, bottom line, Q1, Q2, Q3, Q4, full year, beat estimates, missed estimates, raised guidance, lowered guidance]
  article_types: []
  always: false
priority: 1
max_tokens: 330
---
## Earnings Interpretation Framework

Apply this framework to quarterly or annual results coverage.

### Quality of Beat/Miss
- Separate GAAP vs adjusted figures and identify one-time items.
- Verify whether beat/miss was operational or accounting-driven.

### Guidance First, Quarter Second
- Prioritize forward guidance changes over backward-looking quarter prints.
- Highlight raised/lowered outlook and management confidence signals.

### Trend and Margin Read
- Assess growth acceleration/deceleration and mix effects.
- Evaluate margin expansion/compression and sustainability.

### Cash Flow Reality Check
- Compare earnings narrative with operating cash flow and balance-sheet trends.
- Flag divergence between reported earnings and cash generation.

### Output Requirements
- In `fact_check`, state what drove performance versus consensus.
- In `conclusion`, include whether results imply trend continuation or mean reversion risk.
