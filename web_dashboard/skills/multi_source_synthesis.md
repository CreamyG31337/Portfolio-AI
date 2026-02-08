---
name: Multi-Source Signal Synthesis
description: Cross-source weighting and conflict-resolution framework for ticker conviction scoring
target_prompts:
  - ticker_analysis
triggers:
  keywords: []
  article_types: []
  always: true
priority: 2
max_tokens: 520
---
## Multi-Source Synthesis Framework

### Reliability Hierarchy
- Prefer strong institutional flow and high-quality insider signals over noisy social chatter.
- Use source reliability and freshness as explicit weighting factors.

### Conflict Resolution
- Bullish flow + bearish crowd sentiment can still be constructive.
- Bearish flow + euphoric sentiment can indicate distribution risk.
- Alignment across sources increases conviction.

### Data Sufficiency and Confidence
- Avoid high-conviction calls from sparse/weak evidence.
- Calibrate confidence downward for stale, contradictory, or low-quality inputs.

### Output Requirements
- Explain why final stance reflects weighted cross-source evidence, not a single signal.
