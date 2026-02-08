---
name: ETF and Institutional Flow
description: ETF flow interpretation framework for accumulation, distribution, and rotation signal quality
target_prompts:
  - etf_analysis
  - summary
  - ticker_analysis
triggers:
  keywords: [ETF holdings, accumulation, distribution, institutional flow, sector rotation, rebalancing, index reconstitution, creation unit, fund flow]
  article_types: []
  always: false
  always_for: [etf_analysis]
priority: 2
max_tokens: 500
---
## ETF and Institutional Flow Framework

### Active vs Passive Interpretation
- Distinguish active funds (conviction expression) from passive index mechanics.
- Avoid treating passive rebalance events as discretionary bullish signals.

### Flow Pattern Read
- Identify multi-day accumulation/distribution trends versus one-day noise.
- Evaluate AUM-relative significance, not just absolute share change.

### Cross-Validation
- Increase confidence when multiple ETFs show aligned direction.
- Treat isolated tiny changes as weak evidence.

### Output Requirements
- State whether changes imply conviction, rebalance, or mixed interpretation.
