---
name: Falsifiable Proposal
description: Require hypothesis/mechanism/direction/horizon/falsification before any conviction claim
target_prompts:
  - ticker_analysis
  - ticker_meta_analysis
  - analyze_congress_trades
triggers:
  keywords: []
  article_types: []
  always: true
priority: 1
max_tokens: 320
---
## Falsifiable Proposal (required)

Before stating a stance or conflict verdict, emit a falsifiable claim. This is not optional prose — the JSON gate rejects outputs that omit it.

Include either a top-level object or a nested `"falsifiable_proposal"` object with **all** of:

- `hypothesis`: one sentence claim about what should happen in the market
- `mechanism`: why the market would pay for this (economic / behavioral reason)
- `expected_direction`: one of `bullish`, `bearish`, `higher_means_up`, `higher_means_down`, `higher_signal_predicts_higher_future_return`, `higher_signal_predicts_lower_future_return`
- `horizon_days`: `7`, `30`, or `90` only (must match Learn scoring horizons)
- `falsification_criteria`: list of concrete fails (e.g. "excess vs benchmark ≤ 0 at 30d", "sign flips after next earnings", "subsumed by 21d momentum alone")
- `expected_failure_modes`: list of ways this claim is usually noise

Do **not** invent prices. Prefer `INSUFFICIENT_DATA` / lower confidence when evidence is thin — still emit the proposal describing what would have been tested if data existed.
