# Code Review Report: Signals Model Selection Functionality

**Commit:** `e751b6fba4904962303fbe82e359f4149bdf8b4e`
**Title:** `feat(ticker): add signals model selection functionality`

## Summary
This commit introduces the ability to select different AI models (including WebAI/Gemini and GLM/Z.AI models) for ticker analysis and potentially for signal explanations. It updates the `PersistentConversationSession` to support model selection and adds UI elements for model selection in the Ticker Details page.

## Findings

### 1. Incomplete Implementation of Signals Model Selection
While the UI for selecting a model in the "Technical Signals" section has been added (`ticker_details.html`), the functionality appears to be incomplete in the following areas:

*   **Frontend (`web_dashboard/src/js/ticker_details.ts`):**
    The `loadSignals` function initializes the model selector but **does not send the selected model** to the backend API.
    ```typescript
    // Current implementation in loadSignals
    const response = await fetch(`/api/signals/analyze/${ticker}?${aiParam}`, { ... });
    // Should likely be:
    // const modelParam = selectedSignalsModel ? `&model=${encodeURIComponent(selectedSignalsModel)}` : '';
    // const response = await fetch(`/api/signals/analyze/${ticker}?${aiParam}${modelParam}`, ...);
    ```

*   **Backend Route (`web_dashboard/routes/signals_routes.py`):**
    The `api_analyze_ticker` endpoint does not read or use a `model` query parameter. It uses the default system configuration.

*   **Signal Explainer (`web_dashboard/signals/ai_explainer.py`):**
    The `generate_signal_explanation` function relies on `settings.get_summarizing_model()` and does not accept a `model` override parameter. It essentially ignores any user selection even if it were passed.

### 2. Ticker Analysis Service Restrictions
The `TickerAnalysisService` (`web_dashboard/ticker_analysis_service.py`) has been updated to accept a `model_override`, but it explicitly **blocks/downgrades** WebAI (Gemini) and GLM models:

```python
    def _resolve_analysis_model(self, model_override: Optional[str]) -> str:
        # ...
            if is_webai_model(model_override) or model_override.startswith("glm-"):
                logger.warning(
                    "Model %s is not supported for ticker analysis; falling back to default",
                    model_override
                )
                return get_summarizing_model()
```

If the intention of the commit was to allow using these models for ticker analysis, this logic prevents it. If these models are indeed unsuitable (e.g., due to JSON formatting requirements), the UI should probably filter them out or the backend should support them (e.g., via non-JSON fallback or using `PersistentConversationSession`).

### 3. Security Note: Conversation Storage
The `PersistentConversationSession` (`web_dashboard/webai_wrapper.py`) saves conversation history to `data/conversations`.
```python
        self.storage_dir = project_root / "data" / "conversations"
        self.storage_dir.mkdir(parents=True, exist_ok=True)
```
**Recommendation:** Ensure these files are created with restricted permissions (e.g., `0o600`) as they may contain sensitive user prompts or AI responses.

### 4. Positive Aspects
*   **Infrastructure Update:** The `WebAIWrapper` and `OllamaClient` have been significantly improved to support a wider range of models and routing logic.
*   **Persistent Sessions:** The addition of `PersistentConversationSession` is a robust way to handle stateful conversations with the WebAI service.

## Recommendations
1.  **Update Frontend:** Modify `loadSignals` in `ticker_details.ts` to include the selected model in the API request.
2.  **Update Backend:** Update `api_analyze_ticker` in `signals_routes.py` to accept the `model` parameter.
3.  **Update Explainer:** Modify `generate_signal_explanation` in `ai_explainer.py` to accept and use the `model` parameter.
4.  **Review Ticker Analysis Constraints:** Re-evaluate if WebAI models should be strictly blocked in `TickerAnalysisService`. If they support the required context window, they could be enabled.
5.  **Security:** Add `os.chmod(self.session_file, 0o600)` when saving conversation metadata.
