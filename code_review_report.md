# Code Review Report (Last 12 Hours)

## Commit `0a17874` - UI quick-win TODOs for dashboard and ticker detail styling
**Review:**
*   **dashboard.html**: Swapped a custom group markup to a Flowbite-style button group. Looks cleaner and more standard.
*   **ticker_details.ts** & **ticker_details.html**: Swapped hardcoded inline width styles for composite bars to use a CSS variable (`--bar-width`). This aligns well with standard practices and improves the maintainability of the Tailwind utility-first approach.
*   **insider_trades.html** & **input.css**: Moved hardcoded RGB colors for AG grid highlights to tokenized Tailwind classes in `input.css`. Much cleaner and respects the dynamic theming system (e.g., dark mode).

**Conclusion:** Good commit. Resolves UI TODOs properly.

## Commit `7a69ae1` - Harden social-media LLM ingestion against prompt-style input
**Review:**
*   **prompt_safety.py**: Added a new helper module for untrusted prompt content. Includes sanitization (`sanitize_for_llm`), xml wrapper (`wrap_untrusted_content`), and a text analyzer (`contains_instruction_like_text`).
*   **ollama_client.py** & **social_service.py**: Applied the new safety features to sanitize user/scraped input before feeding to the LLM.

**Issue:**
There is a missing `< >` replacement in `prompt_safety.py`. Specifically, in the memory for the project, it states:
> Security Standard: Untrusted free-text fields (e.g., descriptions, notes from APIs) must be sanitized using `web_dashboard.utils.llm_utils.sanitize_for_llm(text)` before LLM ingestion. This function removes control characters, zero-width spaces, and replaces angle brackets `< >` with square brackets `[ ]` to mitigate prompt injection.

However, `sanitize_for_llm` in `web_dashboard/prompt_safety.py` does not replace angle brackets `< >` with square brackets `[ ]`. This needs to be added to completely fulfill the security standard.

```python
def sanitize_for_llm(text: Optional[str], *, max_chars: int | None = None) -> str:
    ...
    safe = _INVISIBLE_BIDI_RE.sub("", safe)
    safe = _CONTROL_CHARS_RE.sub(" ", safe)
    # MISSING: safe = safe.replace("<", "[").replace(">", "]")
    safe = safe.strip()
    ...
```

**Conclusion:** Needs follow-up to add angle bracket sanitization.

## Commit `fb53faf` - Simplify redundant company-name type check in table formatter
**Review:**
*   **table_formatter.py**: Removed a redundant `isinstance(company_name, str)` check. In the preceding block, `company_name` is explicitly set to either `str(company_raw)`, `company_raw.strip()`, or `'N/A'`, so it is guaranteed to be a string. This makes the code simpler and easier to follow without changing behavior.

**Conclusion:** Good, safe refactor.
