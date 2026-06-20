# Flask Caching Implementation Summary

## What We Use

### `flask_cache_utils.py`

- **`@cache_data(ttl=seconds)`** — memoize expensive data fetches
- **`@cache_resource`** — long-lived clients/resources
- Cache keys from function arguments + user scope (`get_flask_cache_scope_id()`)
- Integrates with `dashboard_constants.get_cache_ttl()` / `cache_version.py` for invalidation
- Falls back to in-memory cache if Flask-Caching is unavailable

### `app.py`

- Flask-Caching initialized (SimpleCache by default; Redis optional in production)
- `clear_all_caches()` called after trade entry via `utils/cache_utils.py`

## Documentation

- **`FLASK_CACHING_GUIDE.md`** — patterns and examples
- **`examples/flask_caching_example.py`** — sample usage

## Common TTLs

Match `dashboard_constants.get_cache_ttl()` and route-level needs (often 300s for portfolio data, longer for static reference data). See `admin_utils.get_scheduler_status_cached` and `flask_data_utils` for real usage.

## Invalidation

- `bump_cache_version()` / `clear_all_caches()` after writes
- Trade entry clears price, FX, and Flask caches (`utils/cache_utils.clear_trade_related_caches`)

## Adding Cache to a New Route

1. Import `@cache_data` from `flask_cache_utils`
2. Include user/fund in arguments so keys are scoped correctly
3. Choose TTL from `get_cache_ttl()` or explicit seconds
4. Add tests with mocks — see `tests/test_flask_*.py` patterns
