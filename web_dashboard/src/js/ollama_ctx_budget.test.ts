import { describe, expect, it } from 'vitest';
import {
    HERETIC_SOFT_PROMPT_BUDGET,
    ollamaPromptHalfTokens,
    usablePromptTokenBudget,
} from './ollama_ctx_budget.js';

describe('usablePromptTokenBudget', () => {
    it('uses half of Ollama num_ctx, not the full window', () => {
        expect(ollamaPromptHalfTokens(65536)).toBe(32768);
        expect(usablePromptTokenBudget(39000, 'granite4.1:8b')).toBe(19500);
    });

    it('soft-caps heretic to Goose-aligned 28000 under a 65k window', () => {
        expect(usablePromptTokenBudget(65536, 'qwen3.6:27b-heretic')).toBe(
            HERETIC_SOFT_PROMPT_BUDGET,
        );
        expect(usablePromptTokenBudget(65536, 'qwen3.6:27b-heretic-agentic')).toBe(28000);
    });

    it('keeps full window for GLM (not Ollama half-split)', () => {
        expect(usablePromptTokenBudget(128000, 'glm-5.2')).toBe(128000);
    });
});
