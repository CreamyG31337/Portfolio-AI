---
name: Technical Analysis Context
description: Practical chart-structure and level quality framework for ticker analysis
target_prompts:
  - ticker_analysis
triggers:
  keywords: []
  article_types: []
  always: true
priority: 3
max_tokens: 500
---
## Technical Analysis Context

### Structure First
- Determine trend via higher highs/lows vs lower highs/lows.
- Identify support/resistance from swing points, volume nodes, and round levels.

### Confirmation Quality
- Treat breakouts with weak volume as lower-confidence moves.
- Use moving averages (50/200) as context, not sole decision criteria.

### Reliability Filters
- De-emphasize TA for very illiquid micro-caps with erratic prints.
- If data quality is insufficient, explicitly avoid over-precise levels.

### Output Requirements
- Provide practical entry/target/stop only when signal quality supports it.
