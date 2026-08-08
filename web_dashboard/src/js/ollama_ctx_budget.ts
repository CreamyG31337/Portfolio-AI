/**
 * Ollama context budget helpers for UI meters.
 *
 * Verified: Ollama usable *prompt* is ~half of num_ctx; the other half is
 * generation. /api/show reports the full window — do not use full num_ctx as
 * the advisor "Context: used / max" denominator for local Ollama models.
 *
 * Heretic on the 3090: num_ctx 65536 → prompt half ~32768; soft budget 28000
 * matches Goose GOOSE_CONTEXT_LIMIT (backend ollama_ctx.HERETIC_SOFT_PROMPT_BUDGET).
 */

export const HERETIC_SOFT_PROMPT_BUDGET = 28000;

export function ollamaPromptHalfTokens(numCtx: number): number {
    return Math.max(1, Math.floor(Number(numCtx) / 2));
}

export function isHereticModel(modelName: string): boolean {
    return (modelName || "").toLowerCase().includes("heretic");
}

/** True for local Ollama-style tags (not GLM / Gemini / obvious cloud IDs). */
export function isOllamaStyleModel(modelName: string): boolean {
    const name = (modelName || "").trim().toLowerCase();
    if (!name) return false;
    if (name.startsWith("glm-") || name.startsWith("gemini-")) return false;
    return name.includes(":");
}

/**
 * Usable prompt-token budget for the context meter (denominator).
 * Ollama: ~num_ctx/2, heretic soft-capped at 28000.
 * Non-Ollama: full configured window.
 */
export function usablePromptTokenBudget(
    numCtx: number,
    modelName: string,
): number {
    const ctx = Math.max(0, Number(numCtx) || 0);
    if (ctx <= 0) return 0;
    if (!isOllamaStyleModel(modelName)) {
        return ctx;
    }
    const half = ollamaPromptHalfTokens(ctx);
    if (isHereticModel(modelName)) {
        return Math.min(half, HERETIC_SOFT_PROMPT_BUDGET);
    }
    return half;
}
