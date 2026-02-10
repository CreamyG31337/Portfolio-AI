---
name: Micro-Cap Red Flags
description: Red-flag framework for micro/small-cap dilution, financing, and promotion risk
target_prompts:
  - summary
  - ticker_analysis
triggers:
  keywords: [dilution, reverse split, shelf registration, ATM offering, warrant, shell company, going concern, toxic financing, convertible note, PIPE, death spiral, pump and dump, low float, SEC enforcement, auditor change, late filing, Form 12b-25]
  article_types: []
  always: false
priority: 1
max_tokens: 360
---
## Micro-Cap Red Flag Checklist

Apply this framework when a company appears to be micro-cap or highly speculative.

### Capital Structure and Dilution Risk
- Identify recent or pending **shelf/ATM/warrant/convertible** financing.
- Flag **death-spiral** risk if convertibles are priced off market with reset features.
- Note repeated reverse splits or serial share-count expansion.

### Promotion vs Fundamentals
- Distinguish operational milestones from promotional language.
- Flag **pump-and-dump** indicators: sudden hype, weak filings, low float volatility.
- Treat unsupported upside claims as low reliability.

### Governance and Compliance
- Escalate concern for auditor turnover, late filings, Form 12b-25, or SEC actions.
- Highlight related-party transactions and management churn as quality risks.

### Output Requirements
- In `fact_check`, list concrete red flags and evidence.
- If multiple major red flags exist, bias `logic_check` toward `HYPE_DETECTED`.
- In `conclusion`, explicitly state dilution/financing downside pathways.
