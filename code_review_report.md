# Code Review Report (Last 12 Hours)

This review covers the commits made in the past 12 hours.

## `0a17874c` Close UI quick-win TODOs for dashboard and ticker detail styling.

* **Description**: Addressed low-hanging fruit in the UI styling by swapping inline styling to use CSS variables and Tailwind utility classes.
* **Review**:
    * **`web_dashboard/src/js/ticker_details.ts`**: Safely replaced direct assignment of `style.width` with `style.setProperty('--bar-width', ...)` which correctly conforms with the custom `ticker-composite-progress` CSS class added in `input.css`.
    * **`web_dashboard/static/css/input.css`**: Appropriate usage of Tailwind `@apply` derivatives and CSS variables. Consistent naming convention with existing classes.
    * **`web_dashboard/templates/dashboard.html`**: Cleaned up the comments and standardized the markup for Flowbite toggle groups.
    * **`web_dashboard/templates/insider_trades.html`**: Safely removed raw style tag with rgba logic, replaced entirely by custom classes added in `input.css`.
    * **`web_dashboard/templates/ticker_details.html`**: Correct implementation of the CSS variable and utility class mapping.

## `7a69ae18` Harden social-media LLM ingestion against prompt-style input.

* **Description**: Addressed prompt-injection vulnerabilities inside the `OllamaClient` and `SocialSentimentService` by creating a new `prompt_safety.py` utility module that provides functions to sanitize text.
* **Review**:
    * **`web_dashboard/prompt_safety.py`**: Strong implementation. Uses robust regex for invisible bidi characters (`\u200B`, `\u200C`, `\u200D`, etc.) and control characters. Truncates text appropriately. The instruction-like regex captures common system prompt injection patterns like "ignore previous", "system prompt", etc. Good use of XML delimiters for `<user_content>`.
    * **`web_dashboard/test_prompt_safety.py`**: Good test coverage, correctly verifying string sanitization.
    * **`web_dashboard/ollama_client.py`**: Integrated the new module efficiently. Wraps text in `<user_content source="social_post_X">` inside the loop before passing it to the prompt.
    * **`web_dashboard/social_service.py`**: Successfully implements sanitization and delimiter usage for both Reddit and generic social posts. Max character constraints ensure payloads don't exceed model limits.

## `fb53faf6` Simplify redundant company-name type check in table formatter.

* **Description**: Cleaned up `display/table_formatter.py` by removing an unnecessary `isinstance(company_name, str)` check.
* **Review**:
    * **`display/table_formatter.py`**: Good refactor. The code immediately above it guarantees `company_name` is either populated correctly or defaults to `'N/A'`. Since both outcomes are strings, checking for `isinstance(..., str)` was dead code.

## `f7bf4aa9` ⚡ Bolt: Replace pandas iterrows with itertuples

* **Description**: Optimized the `get_recent_activity` and `get_movers_data` loops by exchanging `.iterrows()` for `.itertuples(index=False)`.
* **Review**:
    * **`web_dashboard/flask_data_utils.py`**: Excellent optimization. `.itertuples()` is much faster for Pandas DataFrames. Because it yields `namedtuple` objects rather than `pd.Series`, the commit correctly updated field access to use `getattr(row, 'column_name', default)` instead of `row.get('column_name')` or `row['column_name']`. Added appropriate explicit casting to `float` handling None values.

## `8a497c86` Optimize PortfolioSnapshot ticker lookups via internal cache

* **Description**: Optimization update to drop `get_position_by_ticker` inside `PortfolioSnapshot` from O(N) to O(1) by generating an internal dictionary on `__post_init__`.
* **Review**:
    * **`data/models/portfolio.py`**: The `__post_init__` hook successfully creates `_positions_by_ticker`. `add_position` and `remove_position` successfully update the internal cache and fallback checks exist to prevent crashes during pipeline unpickling/deserialization loops that bypass standard instantiation. Memory impact is negligible compared to the significant iteration speedups.
    * **`.jules/bolt.md`**: Kept documentation context updated.

## Summary

The recent commits are generally highly effective, properly optimizing performance (`O(1)` caching, `itertuples`) while enhancing security (prompt injection sanitization) and removing tech debt (Tailwind UI variables). All code appears sound and follows the stated repository conventions (Tailwind Flowbite mappings, explicitly typed python properties).
