---
name: Ticker Meta Synthesis
description: Reconcile prior AI outputs without treating them as ground truth
target_prompts:
  - ticker_meta_analysis
triggers:
  keywords: []
  article_types: []
always: true
priority: 3
max_tokens: 220
---
## Meta-Analysis Rules

- Prior model outputs may be wrong, stale, or mutually inconsistent. Weight agreement across independent sources; flag disagreement explicitly.
- Prefer **INSUFFICIENT_DATA** or lower **confidence_adjusted** when the bundle lacks social, congress, or article coverage.
- Never restate numeric price levels unless they appear verbatim in the artifact bundle.
- **action_items** should be analyst workflow steps (e.g. verify catalyst dates, check latest filing), not trade orders.
