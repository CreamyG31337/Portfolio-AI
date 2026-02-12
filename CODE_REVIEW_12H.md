# Code Review: Commit 462dc3bb76b1717233ab7608bb362a832f79c64b

**Commit:** `462dc3bb76b1717233ab7608bb362a832f79c64b`
**Author:** Lance Colton
**Date:** 6 hours ago
**Message:** `fix(research): Also protect high-relevance tickerless articles from junk deletion`

## Overview
This commit modifies the automated "junk article" cleanup logic to protect high-relevance articles even if they lack ticker symbols. Previously, articles with no tickers were generally considered junk unless they matched specific protected types (e.g., Newsletters, ETFs) or sources (e.g., Reddit). The update adds a relevance score threshold check to this protection logic.

## Changes Reviewed

### 1. `web_dashboard/routes/research_routes.py`

#### `_is_likely_junk` Function
The Python logic for identifying junk articles was updated:
```python
        # High relevance articles are likely useful sector/macro news
        relevance = article.get("relevance_score")
        if relevance is not None and float(relevance) > 0.3:
            return False
```
*   **Correctness:** This correctly implements the intent. If an article has a relevance score > 0.3, it returns `False` (not junk), protecting it from deletion.
*   **Null Handling:** The code properly handles `None` values for `relevance_score`.
*   **Type Safety:** The explicit `float()` conversion handles cases where the score might be a string or Decimal.

#### `delete_junk_articles_endpoint` Function
The SQL query for bulk deletion was updated:
```sql
            DELETE FROM research_articles
            WHERE (tickers IS NULL OR tickers = '{}')
              AND ticker_validated_at IS NULL
              AND COALESCE(relevance_score, 0) <= 0.3  -- Added condition
              AND COALESCE(article_type, '') NOT IN (
                  'ETF Change', 'ETF Analysis', 'Newsletter', 'Seeking Alpha Symbol'
              )
              ...
```
*   **Correctness:** The condition `AND COALESCE(relevance_score, 0) <= 0.3` ensures that only articles with a low (or null) relevance score are deleted. High relevance articles (> 0.3) are excluded from the `DELETE` operation.
*   **Null Handling:** `COALESCE(relevance_score, 0)` correctly treats NULL scores as 0, which is safe for deletion (assuming valid articles should have a score).

### 2. `web_dashboard/reprocess_tickerless.py`
This file was reviewed but appears unchanged in logic relative to the commit message (it handles manual reprocessing). It correctly sets `ticker_validated_at` when processing articles, which protects them from the bulk deletion logic reviewed above (since the delete query checks `ticker_validated_at IS NULL`).

## Findings & Recommendations

### 1. Hardcoded Threshold (Magic Number)
The threshold value `0.3` is hardcoded in two places:
-   `web_dashboard/routes/research_routes.py`: `_is_likely_junk` (Python)
-   `web_dashboard/routes/research_routes.py`: `delete_junk_articles_endpoint` (SQL)

**Recommendation:** define a constant, e.g., `RELEVANCE_THRESHOLD_FOR_TICKERLESS = 0.3` in a shared configuration or constants file (like `research_utils.py` or `settings.py`) to ensure consistency and easier updates in the future.

### 2. Logic Duplication
The logic for determining "junk" status is duplicated between the Python function `_is_likely_junk` and the SQL query in `delete_junk_articles_endpoint`. While necessary due to the different execution contexts (application logic vs. bulk database operation), this increases the risk of drift.

**Recommendation:** Ensure the list of protected article types (`ETF Change`, `Newsletter`, etc.) matches exactly between the SQL query and the `_PROTECTED_ARTICLE_TYPES` set in Python. Currently, they appear to match.

### 3. Verification of "Relevance Score" Availability
The logic assumes that "high-relevance" articles will have a populated `relevance_score`. If the ingestion pipeline (scraper) does not calculate this score immediately, valid articles might be deleted before they are scored.

**Recommendation:** Verify that the scraping/ingestion process assigns a `relevance_score` (even a provisional one) or that the deletion job runs only after scoring has occurred. If `relevance_score` is NULL, it defaults to 0 and the article is deleted.

## Conclusion
The changes correctly implement the fix described in the commit message. The logic is sound and safe, protecting valuable content from accidental deletion. The recommendations above are for future maintainability and robustness.
