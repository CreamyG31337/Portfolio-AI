---
name: Merger and Special Situations
description: M&A, spinoff, SPAC, activist, and rights-offering special situation framework
target_prompts:
  - summary
  - ticker_analysis
triggers:
  keywords: [merger, acquisition, acquir, M&A, spinoff, spin-off, tender offer, going private, SPAC, de-SPAC, activist, 13D, strategic alternatives, rights offering, privatization, buyout, LBO, definitive agreement, break fee]
  article_types: []
  always: false
priority: 2
max_tokens: 250
---
## Merger and Special Situations Framework

### Deal Structure and Spread
- Separate cash, stock, and mixed consideration implications.
- For arb setups, quantify spread, timeline, and key break risks.

### Regulatory and Execution Risk
- Include antitrust/HSR and CFIUS risk when relevant.
- Track financing certainty, termination rights, and break-fee asymmetry.

### Event-Type Nuances
- Spinoff: watch forced seller dynamics and standalone valuation reset.
- SPAC/de-SPAC: assess trust value, redemptions, PIPE dilution, sponsor incentives.
- Activist/13D: differentiate credible operational catalyst vs headline noise.

### Output Requirements
- In `conclusion`, provide base case and deal-break downside case.
