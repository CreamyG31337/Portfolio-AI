# Code Review Report

## Review of commit `7a307b90ac17a49d89f0651f20093426fa051fe1`

### Findings

- **Bug in logic in `ai_context_builder.py`**:
  The refactoring from `df.iterrows()` to `df.itertuples(index=False)` replaced dictionary `.get()` calls with sequential `getattr(row, ...)` connected by `or` logic (e.g., `getattr(row, 'quantity', None) or getattr(row, 'shares', 0)`).
  This introduces a subtle bug: in Python, an actual numeric value of `0` or `0.0` is falsy. This means a legitimately zero value for `quantity`, `price`, `cost_basis`, etc., will incorrectly fall through the `or` condition instead of being captured as the correct value.

  The correct approach when checking optional fallbacks for numeric values is explicit None-checking (e.g., `val = getattr(row, 'quantity', None); val if val is not None else getattr(row, 'shares', 0)`).
