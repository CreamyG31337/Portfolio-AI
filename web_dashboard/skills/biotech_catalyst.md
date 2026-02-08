---
name: Biotech Catalyst Analysis
description: Clinical-stage and FDA-event framework for biotech and pharma catalyst analysis
target_prompts:
  - summary
  - ticker_analysis
triggers:
  keywords: [FDA, Phase 1, Phase 2, Phase 3, PDUFA, NDA, BLA, clinical trial, orphan drug, biotech, pharma, drug approval, AdCom, advisory committee, CRL, complete response, IND, investigational new drug, pipeline, therapeutic, oncology, immunotherapy]
  article_types: []
  always: false
priority: 1
max_tokens: 560
---
## Biotech Catalyst Framework

Use this structure for biotech/pharma trial and regulatory events.

### Phase and Probability Context
- Identify the **exact stage**: pre-IND, Phase 1, 2, 3, filing/review.
- Provide rough probability framing by stage and indicate uncertainty.
- Treat single-asset stories as high binary-risk profiles.

### Regulatory Event Mapping
- Distinguish PDUFA, AdCom, CRL, NDA/BLA acceptance, and label-expansion events.
- Assess whether the event is truly value-creating or already priced in.

### Trial Quality Checks
- Call out sample size, endpoint quality (surrogate vs hard outcomes), and controls.
- Flag underpowered data, post-hoc subgroup dependence, or short follow-up windows.

### Commercial and Competitive Context
- Include patent life, competitive landscape, and reimbursement risk.
- For partnerships, parse upfront vs milestones vs royalties to gauge real economics.

### Output Requirements
- In `conclusion`, state likely path, key binary risk, and estimated confidence.
- If trial/regulatory details are vague, reduce conviction explicitly.
