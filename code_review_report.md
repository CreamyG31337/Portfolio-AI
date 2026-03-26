# Code Review Report

## Commit Reviewed
Commit `05725be74a5e961fc34afb3914fdec648c182e98`
**Author:** Lance Colton
**Date:** Tue Mar 24 09:58:35 2026 -0700
**Message:** Refactor amount retrieval in get_recent_activity to use getattr for improved compatibility. This change enhances the handling of missing values while maintaining existing functionality.

## Findings

In `web_dashboard/routes/dashboard_routes.py` (around line 1520), the following change was introduced in `get_recent_activity`:

```python
-                "amount": abs(float(row.get('amount', 0))),
+                "amount": abs(float(getattr(row, "amount", 0) or 0)),
```

### Issue: Incorrect Fallback Logic
The use of `or 0` as a fallback is an anti-pattern when extracting numeric data from dataframes/namedtuples. While it catches `None`, it also incorrectly evaluates valid `0` or `0.0` values as falsy. Although in this specific line the fallback is also `0` (so a value of `0` becomes `0`), using `or` for default values is generally unsafe and can lead to functional regressions if a valid falsy value needs to be preserved or if the default was a different number.

Furthermore, `getattr(row, "amount", 0)` already provides `0` if the attribute is missing. The only reason for the `or 0` is to handle cases where the attribute exists but its value is explicitly `None`.

### Recommendation
To properly handle `None` values without creating functional regressions for valid falsy values, explicit `None` checking should be used instead.

Recommended refactor:
```python
amount_val = getattr(row, "amount", 0)
"amount": abs(float(amount_val if amount_val is not None else 0)),
```
This ensures that `None` is explicitly handled while preserving valid numeric values. This matches the explicit `None` checking pattern used elsewhere in the function (e.g., `shares_val if shares_val is not None else 0`).
