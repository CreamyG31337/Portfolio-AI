I have been requested to do a code review of any commits in the last 12 hours.

As per my instructions:
- When the user asks you to perform a code review of historical commits, you are the reviewer.
- Formulate findings and deliver them via the final submission tool (`submit`, `attempt_completion`, or `done`).
- Do not invoke the `request_code_review` tool.
- Include an explicit step to run relevant tests to verify the code and document any encountered failures (Completeness Rule).
- Skip `request_code_review` and `frontend_verification_instructions` in the pre-commit step.
- Base the drafted review strictly on the completely verified diff chunks explicitly captured in the trace.

I have found the following commits in the last 12 hours:
1. `20578839` feat: enhance insider and congress trades formatting and retrieval
2. `356b7fc5` feat(etf): enhance ETF context handling and reporting
3. `99fd59b5` perf: land Bolt vectorization from Jules PRs; palette audit TODOs
4. `bfa11af0` refactor(glm): update GLM model management and deprecate older versions
5. `055867ad` Merge branch 'main' of https://github.com/CreamyG31337/Portfolio-AI
6. `d156395c` fix(data-quality): enhance OHLCV validation and signal integrity

I will read the full patches for these commits to have a grounded review.

1.  *Extract the full patches for review.*
    - I will run `cat diff_20578839.patch`, `cat diff_356b7fc5.patch`, `cat diff_99fd59b5.patch`, `cat diff_bfa11af0.patch`, and `cat diff_d156395c.patch` (handling potential truncation using `head` and `tail` or `split` if they are too large).
2.  *Run relevant tests to verify the code state.*
    - Run Python tests for the changed modules.
    - Test files discovered: `tests/test_ai_congress_context.py`, `tests/test_ai_etf_context.py`, `tests/test_model_registry.py`.
    - Also run frontend checks `pnpm run test:ts` to verify TS changes.
3.  *Complete pre-commit steps to ensure proper testing, verification, review, and reflection are done.*
    - Even though this is a read-only task, I must include this phrasing. I will run `pre_commit_instructions` as required by the system, skipping `request_code_review` and `frontend_verification_instructions`.
4.  *Deliver the code review using `submit`.*
    - Summarize my findings from the diffs and test results in the `description` parameter of the `submit` tool. Use a dummy branch name `review-branch` and title `Code Review for commits in the last 12 hours`.
