---
name: Canadian Market Context
description: TSX/TSXV/CSE market structure and Canada-specific regulatory/trading context
target_prompts:
  - summary
  - ticker_analysis
triggers:
  keywords: [.TO, .V, .CN, TSX, TSXV, CSE, NEO, SEDAR, TFSA, RRSP, Canadian, Canada, Toronto Stock Exchange, Venture Exchange, OSC, BCSC, NI 43-101, Health Canada]
  article_types: []
  always: false
priority: 2
max_tokens: 260
---
## Canadian Market Lens

Use this lens for Canadian-listed names, filings, or policy context.

### Listing-Tier Signal
- Interpret exchange tier (TSX, TSXV, CSE, NEO) as maturity/liquidity signal.
- Recognize ticker suffix conventions (.TO, .V, .CN) and venue implications.

### Regulatory Context
- Reference SEDAR+ and provincial regulator oversight (OSC/BCSC/CSA).
- For mining/cannabis, include NI 43-101 or Health Canada context where relevant.

### Investor and Currency Context
- Mention TFSA/RRSP considerations when behavior may be tax-account influenced.
- For dual-listed names, note CAD/USD translation and liquidity fragmentation effects.

### Output Requirements
- In `conclusion`, include any Canada-specific risk or structural caveat.
