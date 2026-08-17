/**
 * AI Assistant TypeScript
 * Handles chat interface, streaming responses, context management, and search
 */

import { getCsrfHeaders } from './csrf.js';
import { initCollapsesIn } from './collapse.js';
import { usablePromptTokenBudget } from './ollama_ctx_budget.js';

// Configuration interfaces
interface AIAssistantConfig {
    userEmail: string;
    userTheme: string;
    defaultModel: string;
    availableFunds?: string[];
    ollamaModels: string[];
    ollamaAvailable: boolean;
    searxngAvailable: boolean;
    webaiModels: string[];
    hasWebai: boolean;
    modelConfig: any;
}

interface ContextItem {
    item_type?: string;
    [key: string]: any;
}

interface Message {
    role: 'user' | 'assistant';
    content: string;
}

interface ContextPreviewResponse {
    success: boolean;
    context?: string;
    char_count?: number;
    error?: string;
    timings?: {
        data_fetch?: Record<string, number | string>;
        formatting?: Record<string, number | string>;
    };
}

interface ModelsResponse {
    models?: Array<{ id: string; name: string }>;
    default_model?: string;
}

interface ContextResponse {
    success?: boolean;
    items?: ContextItem[];
}

interface SearchResponse {
    results?: any[];
    [key: string]: any;
}

interface RepositoryResponse {
    articles?: any[];
    [key: string]: any;
}

interface ChatRequest {
    query: string;
    model: string;
    fund: string | null;
    context_items: ContextItem[];
    context_string: string | null;
    conversation_history: Message[];
    include_search: boolean;
    include_repository: boolean;
    include_price_volume: boolean;
    include_fundamentals: boolean;
    include_insider_trades?: boolean;
    include_congress_trades?: boolean;
    include_etf_trades?: boolean;
    include_intelligence_pulse?: boolean;
    search_results: any;
    repository_articles: any;
}

interface ChatResponse {
    response?: string;
    chunk?: string;
    done?: boolean;
    error?: string;
    status?: string;
    name?: string;
}

interface PortfolioIntelligenceResponse {
    matching_articles?: Array<{
        title?: string;
        matched_holdings?: string[];
        summary?: string;
        conclusion?: string;
    }>;
}



interface AIAssistantPortfolioResponse {
    positions?: Array<{ ticker?: string }>;
}

class AIAssistant {
    private config: AIAssistantConfig;
    private messages: Message[];
    private contextItems: ContextItem[];
    private selectedModel: string;
    private selectedFund: string | null;
    private conversationHistory: Message[];
    private includeSearch: boolean;
    private includeRepository: boolean;
    private includePriceVolume: boolean;
    private includeFundamentals: boolean;
    private includeInsiderTrades: boolean;
    private includeCongressTrades: boolean;
    private includeEtfTrades: boolean;
    private includeIntelligencePulse: boolean;

    // Context caching - calculate once, use for all messages
    private contextString: string | null = null;  // The actual context text to send to LLM
    private contextReady: boolean = false;  // True when context is loaded and ready
    private contextLoading: boolean = false; // True while loading (prevent duplicate requests)
    private isSending: boolean = false; // True while a message is being sent (prevent duplicate sends)
    private contextReloadQueued: boolean = false; // True when a refresh is requested during loading
    private contextCache: Map<string, { context: string; charCount: number }> = new Map();
    /** User text awaiting a completed assistant reply (for persist / interrupt stub). */
    private pendingPersistUser: string | null = null;
    /**
     * Portfolio context is attached once per conversation window (like WebAI).
     * Snapshot is expanded back onto the anchor user turn in API history so
     * follow-ups still see holdings without re-sending the blob every request.
     * Re-inject when Clear Chat / fund change / session restore resets the
     * anchor, or when the 20-turn window drops the anchor turn.
     */
    private portfolioContextSnapshot: string | null = null;
    private portfolioContextAnchorIndex: number | null = null;
    private static readonly HISTORY_WINDOW = 20;
    /** Live "Generating…" indicator: elapsed timer + phase label while waiting on the model. */
    private loadingMessageId: string | null = null;
    private loadingPhase: string = 'Generating response…';
    private loadingStartedAt: number = 0;
    private loadingTickTimer: ReturnType<typeof setInterval> | null = null;
    // TODO(perf): Optionally persist cache to localStorage or add a backend cache key
    // to reuse across sessions if context generation becomes expensive.

    constructor(config: AIAssistantConfig) {
        this.config = config;
        this.messages = [];
        this.contextItems = [];
        this.selectedModel = config.defaultModel || 'glm-5.2';
        this.selectedFund = config.availableFunds?.[0] || null;
        this.conversationHistory = [];
        this.includeSearch = true;
        this.includeRepository = true;
        this.includePriceVolume = true;
        this.includeFundamentals = true;
        this.includeInsiderTrades = true;
        this.includeCongressTrades = true;
        this.includeEtfTrades = true;
        this.includeIntelligencePulse = true;
    }

    async init(): Promise<void> {
        console.log('[AIAssistant] init() starting...');
        console.log('[AIAssistant] Config:', this.config);
        try {
            // Disable send button and quick actions until context is ready
            this.setSendEnabled(false);
            this.setQuickActionsEnabled(false);

            this.setupEventListeners();
            console.log('[AIAssistant] Event listeners attached');
            this.loadModels();
            this.loadPortfolioTickers();
            this.loadContextItems();
            await this.loadUserPreferences();
            this.updateUI();

            // Load context after preferences so trade toggles are correct
            this.loadContext();

            // Restore server-side transcript for the current fund
            await this.loadSessionFromServer();

            // Initialize display
            this.updateModelDisplay();
            console.log('[AIAssistant] Initialized successfully');
        } catch (err) {
            console.error('[AIAssistant] init() error:', err);
        }
    }

    /**
     * Helper to initialize from a JSON config element in the DOM
     * Looks for <script id="ai-assistant-config" type="application/json">
     */
    static autoInit(): AIAssistant | null {
        const configElement = document.getElementById('ai-assistant-config');
        if (!configElement) return null;

        try {
            const config = JSON.parse(configElement.textContent || '{}');
            const assistant = new AIAssistant(config);
            assistant.init();
            return assistant;
        } catch (err) {
            console.error('[AIAssistant] Failed to parse config from DOM:', err);
            return null;
        }
    }

    setSendEnabled(enabled: boolean): void {
        const sendBtn = document.getElementById('send-btn') as HTMLButtonElement | null;
        if (sendBtn) {
            sendBtn.disabled = !enabled;
            if (!enabled) {
                sendBtn.classList.add('opacity-50', 'cursor-not-allowed');
            } else {
                sendBtn.classList.remove('opacity-50', 'cursor-not-allowed');
            }
        }
    }

    setQuickActionsEnabled(enabled: boolean): void {
        // Disable/enable all quick action buttons
        const buttonIds = [
            'research-ticker-btn',
            'analyze-ticker-btn',
            'compare-tickers-btn',
            'earnings-ticker-btn',
            'portfolio-analysis-btn',
            'market-news-btn',
            'sector-news-btn',
            'run-analysis-btn'
        ];

        buttonIds.forEach(id => {
            const btn = document.getElementById(id) as HTMLButtonElement | null;
            if (btn) {
                btn.disabled = !enabled;
                if (!enabled) {
                    btn.classList.add('opacity-50', 'cursor-not-allowed');
                } else {
                    btn.classList.remove('opacity-50', 'cursor-not-allowed');
                }
            }
        });
    }

    /**
     * Check if a model is a web-based AI model (uses webaiModels from config)
     */
    isWebAIModel(model: string): boolean {
        if (!model) return false;
        // Check against configured webai models list
        const webaiModels = this.config.webaiModels || [];
        return webaiModels.includes(model);
    }

    private formatElapsed(ms: number): string {
        const totalSec = Math.floor(ms / 1000);
        const m = Math.floor(totalSec / 60);
        const s = totalSec % 60;
        return `${m}:${s.toString().padStart(2, '0')}`;
    }

    private friendlyToolName(toolName: string): string {
        const map: Record<string, string> = {
            get_holdings_snapshot: 'portfolio holdings',
            get_trade_history: 'trade history',
            get_track_record: 'track record',
            get_theses_attention: 'theses needing attention',
            get_confluence: 'confluence signals',
            get_ideas_triage: 'ideas queue',
            get_earnings_calendar: 'earnings calendar',
            search_web: 'web search',
            search_research: 'research library',
            get_ticker_snapshot: 'ticker snapshot',
            get_price_history: 'price history',
        };
        return map[toolName] || toolName.replace(/_/g, ' ');
    }

    private loadingHint(elapsedMs: number): string {
        if (elapsedMs < 15000) return '';
        if (elapsedMs < 45000) {
            return 'Still working — first tokens can take a bit…';
        }
        if (elapsedMs < 90000) {
            return 'Still going — tool lookups and cloud models often take 1–2 minutes.';
        }
        return 'Taking longer than usual — connection is open; hang tight.';
    }

    private renderLiveLoadingHtml(): string {
        const elapsed = this.formatElapsed(Date.now() - this.loadingStartedAt);
        const hint = this.loadingHint(Date.now() - this.loadingStartedAt);
        const hintHtml = hint
            ? `<div class="text-xs text-text-secondary mt-1">${hint}</div>`
            : '';
        return (
            `<div class="flex flex-col gap-1">` +
            `<div class="flex items-center gap-2">` +
            `<div class="animate-spin rounded-full h-4 w-4 border-2 border-gray-300 dark:border-gray-600 border-t-accent"></div>` +
            `<span>${this.loadingPhase}</span>` +
            `<span class="text-xs text-text-secondary tabular-nums" data-loading-elapsed>${elapsed}</span>` +
            `</div>${hintHtml}</div>`
        );
    }

    private startLiveLoading(messageId: string, phase: string = 'Generating response…'): void {
        this.stopLiveLoading(false);
        this.loadingMessageId = messageId;
        this.loadingPhase = phase;
        this.loadingStartedAt = Date.now();
        this.updateMessage(messageId, 'assistant', this.renderLiveLoadingHtml(), true);
        this.loadingTickTimer = setInterval(() => {
            if (!this.loadingMessageId) return;
            this.updateMessage(this.loadingMessageId, 'assistant', this.renderLiveLoadingHtml(), true);
        }, 1000);
    }

    private setLiveLoadingPhase(phase: string): void {
        if (!this.loadingMessageId) return;
        this.loadingPhase = phase;
        this.updateMessage(this.loadingMessageId, 'assistant', this.renderLiveLoadingHtml(), true);
    }

    private stopLiveLoading(clearId: boolean = true): void {
        if (this.loadingTickTimer !== null) {
            clearInterval(this.loadingTickTimer);
            this.loadingTickTimer = null;
        }
        if (clearId) {
            this.loadingMessageId = null;
        }
    }

    setupEventListeners(): void {
        // Send button
        const sendBtn = document.getElementById('send-btn') as HTMLButtonElement | null;
        const chatInput = document.getElementById('chat-input') as HTMLInputElement | null;

        if (sendBtn) {
            sendBtn.addEventListener('click', () => this.sendMessage());
        }
        if (chatInput) {
            chatInput.addEventListener('keydown', (e: KeyboardEvent) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    this.sendMessage();
                }
            });
            // Update token usage as user types
            chatInput.addEventListener('input', () => {
                this.calculateContextUsage();
            });
        }

        // Initial calculation
        this.calculateContextUsage();

        // Clear chat
        const clearBtn = document.getElementById('clear-chat-btn');
        if (clearBtn) {
            clearBtn.addEventListener('click', () => this.clearChat());
        }

        // Copy context preview
        const contextCopyBtn = document.getElementById('context-copy-btn') as HTMLButtonElement | null;
        if (contextCopyBtn) {
            contextCopyBtn.addEventListener('click', () => this.copyContextPreview());
        }

        // Model selection
        const modelSelect = document.getElementById('model-select') as HTMLSelectElement | null;
        if (modelSelect) {
            modelSelect.addEventListener('change', (e: Event) => {
                const target = e.target as HTMLSelectElement;
                this.selectedModel = target.value;
                this.saveModelPreference();
                // Update current model display in footer
                this.updateModelDisplay();
                // Update model description
                this.updateModelDescription();
                // Recalculate token usage with new model limits
                this.calculateContextUsage();
            });
        }

        // Fund selection: left-nav global selector only (no duplicate settings dropdown).
        const globalFundSelect = document.getElementById('global-fund-select') as HTMLSelectElement | null;

        if (globalFundSelect && globalFundSelect.value) {
            this.selectedFund = globalFundSelect.value;
            console.log('[AIAssistant] Initial fund from global selector:', this.selectedFund);
        }

        if (globalFundSelect) {
            globalFundSelect.addEventListener('change', (e: Event) => {
                const target = e.target as HTMLSelectElement;
                this.selectedFund = target.value;
                console.log('[AIAssistant] Fund changed to:', this.selectedFund);
                this.contextReady = false;
                this.pendingPersistUser = null;
                this.isSending = false;
                this.resetPortfolioContextInjection();
                this.loadPortfolioTickers();
                this.loadContext();
                void this.loadSessionFromServer();
            });
        }

        // Persist an interrupted stub if the user navigates away mid-response.
        window.addEventListener('pagehide', () => {
            this.persistInterruptedIfNeeded();
        });

        // Context toggles
        const toggleThesis = document.getElementById('toggle-thesis') as HTMLInputElement | null;
        const toggleTrades = document.getElementById('toggle-trades') as HTMLInputElement | null;
        const togglePriceVolume = document.getElementById('toggle-price-volume') as HTMLInputElement | null;
        const toggleFundamentals = document.getElementById('toggle-fundamentals') as HTMLInputElement | null;
        const toggleSearch = document.getElementById('toggle-search') as HTMLInputElement | null;
        const toggleRepository = document.getElementById('toggle-repository') as HTMLInputElement | null;
        const toggleInsiderTrades = document.getElementById('toggle-insider-trades') as HTMLInputElement | null;
        const toggleCongressTrades = document.getElementById('toggle-congress-trades') as HTMLInputElement | null;
        const toggleEtfTrades = document.getElementById('toggle-etf-trades') as HTMLInputElement | null;
        const toggleIntelligencePulse = document.getElementById('toggle-intelligence-pulse') as HTMLInputElement | null;

        if (toggleThesis) {
            toggleThesis.addEventListener('change', (e: Event) => {
                const target = e.target as HTMLInputElement;
                this.updateContextItem('thesis', target.checked);
            });
        }
        if (toggleTrades) {
            toggleTrades.addEventListener('change', (e: Event) => {
                const target = e.target as HTMLInputElement;
                this.updateContextItem('trades', target.checked);
            });
        }
        if (togglePriceVolume) {
            togglePriceVolume.addEventListener('change', (e: Event) => {
                const target = e.target as HTMLInputElement;
                this.includePriceVolume = target.checked;
            });
        }
        if (toggleFundamentals) {
            toggleFundamentals.addEventListener('change', (e: Event) => {
                const target = e.target as HTMLInputElement;
                this.includeFundamentals = target.checked;
            });
        }
        if (toggleSearch) {
            toggleSearch.addEventListener('change', (e: Event) => {
                const target = e.target as HTMLInputElement;
                this.includeSearch = target.checked;
                // Save preference when toggle changes
                this.saveIncludeSearchPreference(target.checked);
            });
        }
        if (toggleRepository) {
            toggleRepository.addEventListener('change', (e: Event) => {
                const target = e.target as HTMLInputElement;
                this.includeRepository = target.checked;
            });
        }
        if (toggleInsiderTrades) {
            toggleInsiderTrades.addEventListener('change', (e: Event) => {
                const target = e.target as HTMLInputElement;
                this.includeInsiderTrades = target.checked;
                this.saveInsiderTradesPreference(target.checked);
                this.loadContext(); // Reload context when toggle changes
            });
        }
        if (toggleCongressTrades) {
            toggleCongressTrades.addEventListener('change', (e: Event) => {
                const target = e.target as HTMLInputElement;
                this.includeCongressTrades = target.checked;
                this.saveCongressTradesPreference(target.checked);
                this.loadContext(); // Reload context when toggle changes
            });
        }
        if (toggleEtfTrades) {
            toggleEtfTrades.addEventListener('change', (e: Event) => {
                const target = e.target as HTMLInputElement;
                this.includeEtfTrades = target.checked;
                this.saveEtfTradesPreference(target.checked);
                this.loadContext(); // Reload context when toggle changes
            });
        }
        if (toggleIntelligencePulse) {
            toggleIntelligencePulse.addEventListener('change', (e: Event) => {
                const target = e.target as HTMLInputElement;
                this.includeIntelligencePulse = target.checked;
                this.saveIntelligencePulsePreference(target.checked);
                this.loadContext();
            });
        }

        // Clear context
        const clearContextBtn = document.getElementById('clear-context-btn');
        if (clearContextBtn) {
            clearContextBtn.addEventListener('click', () => this.clearContext());
        }

        // Retry last response button
        const retryBtn = document.getElementById('retry-btn');
        if (retryBtn) {
            retryBtn.addEventListener('click', () => this.retryLastMessage());
        }

        // Portfolio Intelligence button (optional)
        const portfolioIntelligenceBtn = document.getElementById('portfolio-intelligence-btn');
        if (portfolioIntelligenceBtn) {
            portfolioIntelligenceBtn.addEventListener('click', () => this.checkPortfolioNews());
        }

        // Quick research buttons (optional - may not all exist)
        const researchTickerBtn = document.getElementById('research-ticker-btn');
        const analyzeTickerBtn = document.getElementById('analyze-ticker-btn');
        const compareTickersBtn = document.getElementById('compare-tickers-btn');
        const earningsTickerBtn = document.getElementById('earnings-ticker-btn');
        const portfolioAnalysisBtn = document.getElementById('portfolio-analysis-btn');
        const marketNewsBtn = document.getElementById('market-news-btn');
        const sectorNewsBtn = document.getElementById('sector-news-btn');

        if (researchTickerBtn) researchTickerBtn.addEventListener('click', () => this.quickResearch('research'));
        if (analyzeTickerBtn) analyzeTickerBtn.addEventListener('click', () => this.quickResearch('analyze'));
        if (compareTickersBtn) compareTickersBtn.addEventListener('click', () => this.quickResearch('compare'));
        if (earningsTickerBtn) earningsTickerBtn.addEventListener('click', () => this.quickResearch('earnings'));
        if (portfolioAnalysisBtn) portfolioAnalysisBtn.addEventListener('click', () => this.quickResearch('portfolio'));
        if (marketNewsBtn) marketNewsBtn.addEventListener('click', () => this.quickResearch('market'));
        if (sectorNewsBtn) sectorNewsBtn.addEventListener('click', () => this.quickResearch('sector'));

        // Ticker selection (optional)
        const tickerSelect = document.getElementById('ticker-select') as HTMLSelectElement | null;
        const customTicker = document.getElementById('custom-ticker') as HTMLInputElement | null;
        if (tickerSelect) {
            tickerSelect.addEventListener('change', () => this.updateTickerActions());
        }
        if (customTicker) {
            customTicker.addEventListener('input', () => this.updateTickerActions());
        }

        // Suggested prompt handlers (optional)
        const sendEditedPromptBtn = document.getElementById('send-edited-prompt-btn');
        const cancelEditedPromptBtn = document.getElementById('cancel-edited-prompt-btn');
        const runAnalysisBtn = document.getElementById('run-analysis-btn');

        if (sendEditedPromptBtn) {
            sendEditedPromptBtn.addEventListener('click', () => {
                const editablePrompt = document.getElementById('editable-prompt') as HTMLTextAreaElement | null;
                const suggestedPromptArea = document.getElementById('suggested-prompt-area');
                if (suggestedPromptArea) suggestedPromptArea.classList.add('hidden');
                if (editablePrompt && editablePrompt.value) {
                    this.sendMessage(editablePrompt.value);
                }
            });
        }
        if (cancelEditedPromptBtn) {
            cancelEditedPromptBtn.addEventListener('click', () => {
                const suggestedPromptArea = document.getElementById('suggested-prompt-area');
                if (suggestedPromptArea) suggestedPromptArea.classList.add('hidden');
            });
        }
        if (runAnalysisBtn) {
            runAnalysisBtn.addEventListener('click', () => {
                const initialPrompt = document.getElementById('initial-prompt') as HTMLTextAreaElement | null;
                const startAnalysisArea = document.getElementById('start-analysis-area');
                if (startAnalysisArea) startAnalysisArea.classList.add('hidden');
                if (initialPrompt && initialPrompt.value) {
                    this.sendMessage(initialPrompt.value);
                }
            });
        }

        // Auto-reload context when toggles change
        ['toggle-thesis', 'toggle-trades', 'toggle-price-volume', 'toggle-fundamentals'].forEach(id => {
            const element = document.getElementById(id);
            if (element) {
                element.addEventListener('change', () => this.loadContext());
            }
        });

        // AI drawer toggle + tabs
        this.setupDrawerToggle();
        this.setupDrawerTabs();
    }

    /**
     * Setup AI drawer toggle functionality
     */
    setupDrawerToggle(): void {
        const toggleBtn = document.getElementById('ai-drawer-toggle');
        const closeBtn = document.getElementById('ai-drawer-close');
        const drawer = document.getElementById('ai-drawer');
        const backdrop = document.getElementById('ai-drawer-backdrop');

        if (toggleBtn?.dataset.bound === 'true') {
            return;
        }

        if (toggleBtn) {
            toggleBtn.dataset.bound = 'true';
        }

        // Load saved drawer state (default: visible on desktop, hidden on mobile)
        const isMobile = window.innerWidth < 768;
        const savedState = localStorage.getItem('ai-assistant-drawer-open');
        const shouldBeOpen = savedState !== null ? savedState === 'true' : !isMobile;

        // Initialize drawer state immediately
        this.updateDrawerClasses(shouldBeOpen, isMobile);
        this.updateDrawerToggleIcon(shouldBeOpen);

        if (toggleBtn) {
            toggleBtn.addEventListener('click', () => {
                const isOpen = drawer?.classList.contains('drawer-open') || false;
                this.setDrawerOpen(!isOpen, true);
            });
        }

        if (closeBtn) {
            closeBtn.addEventListener('click', () => {
                this.setDrawerOpen(false, true);
            });
        }

        // Close drawer when clicking backdrop (mobile only)
        if (backdrop) {
            backdrop.addEventListener('click', () => {
                if (window.innerWidth < 768) {
                    this.setDrawerOpen(false, true);
                }
            });
        }

        // Handle window resize to adjust drawer behavior
        let resizeTimeout: number | null = null;
        window.addEventListener('resize', () => {
            if (resizeTimeout) clearTimeout(resizeTimeout);
            resizeTimeout = window.setTimeout(() => {
                const isMobileNow = window.innerWidth < 768;
                const isOpen = drawer?.classList.contains('drawer-open') || false;

                if (isMobileNow && isOpen) {
                    this.updateDrawerClasses(true, true);
                } else if (!isMobileNow && !isOpen) {
                    this.updateDrawerClasses(false, false);
                } else if (!isMobileNow && isOpen) {
                    this.updateDrawerClasses(true, false);
                }
            }, 150);
        });
    }

    updateDrawerToggleIcon(isOpen: boolean): void {
        const toggleIcon = document.getElementById('ai-drawer-toggle-icon');
        if (toggleIcon) {
            toggleIcon.className = isOpen ? 'fas fa-times' : 'fas fa-sliders-h';
        }
    }

    /**
     * Set drawer open/closed state
     */
    setDrawerOpen(isOpen: boolean, saveToStorage: boolean): void {
        const isMobile = window.innerWidth < 768;
        const drawer = document.getElementById('ai-drawer');

        if (!drawer) return;

        const currentlyOpen = drawer.classList.contains('drawer-open');
        if (currentlyOpen === isOpen) {
            return;
        }

        if (saveToStorage) {
            localStorage.setItem('ai-assistant-drawer-open', isOpen.toString());
        }

        this.updateDrawerClasses(isOpen, isMobile);
        this.updateDrawerToggleIcon(isOpen);
    }

    /**
     * Update drawer CSS classes based on state
     */
    updateDrawerClasses(isOpen: boolean, isMobile: boolean): void {
        const drawer = document.getElementById('ai-drawer');
        const backdrop = document.getElementById('ai-drawer-backdrop');

        if (!drawer) return;

        // Toggle unified state classes (Responsive prefixes handle mobile/desktop differences)
        // Mobile Closed: translate-x-full (hidden off-screen)
        // Desktop Closed: md:w-0 md:opacity-0 (collapsed)
        const closedClasses = ['translate-x-full', 'md:w-0', 'md:opacity-0', 'md:pl-0', 'md:border-none', 'md:overflow-hidden'];

        // Mobile Open: translate-x-0 (slide in)
        // Desktop Open: md:w-80 md:opacity-100 (expanded)
        const openClasses = ['translate-x-0', 'md:w-80', 'md:opacity-100', 'md:pl-4', 'md:border-l', 'md:border-border'];

        if (isOpen) {
            drawer.classList.remove(...closedClasses);
            drawer.classList.add(...openClasses);
            drawer.classList.add('drawer-open'); // Add state tracking class
            if (backdrop) backdrop.classList.remove('hidden');
        } else {
            drawer.classList.remove(...openClasses);
            drawer.classList.add(...closedClasses);
            drawer.classList.remove('drawer-open'); // Remove state tracking class
            if (backdrop) backdrop.classList.add('hidden');
        }
    }

    /**
     * Setup AI drawer tabs
     */
    setupDrawerTabs(): void {
        const tabButtons = Array.from(document.querySelectorAll('[data-drawer-tab]')) as HTMLButtonElement[];
        const panels = Array.from(document.querySelectorAll('[data-drawer-panel]')) as HTMLElement[];
        const drawer = document.getElementById('ai-drawer');

        if (drawer?.dataset.tabsBound === 'true') {
            return;
        }

        if (drawer) {
            drawer.dataset.tabsBound = 'true';
        }

        if (tabButtons.length === 0 || panels.length === 0) return;

        const activeClasses = [
            "text-accent",
            "border-accent"
        ];
        const inactiveClasses = [
            "border-transparent",
            "text-text-secondary",
            "hover:text-text-primary",
            "hover:border-border"
        ];

        const setActive = (tabId: string): void => {
            tabButtons.forEach((btn) => {
                const isActive = btn.dataset.drawerTab === tabId;
                btn.setAttribute('aria-selected', isActive.toString());
                activeClasses.forEach((cls) => btn.classList.toggle(cls, isActive));
                inactiveClasses.forEach((cls) => btn.classList.toggle(cls, !isActive));
            });

            panels.forEach((panel) => {
                panel.classList.toggle('hidden', panel.dataset.drawerPanel !== tabId);
            });

            localStorage.setItem('ai-assistant-drawer-tab', tabId);
        };

        const savedTab = localStorage.getItem('ai-assistant-drawer-tab');
        const defaultTab = savedTab && tabButtons.some((btn) => btn.dataset.drawerTab === savedTab)
            ? savedTab
            : 'quick';
        setActive(defaultTab);

        tabButtons.forEach((btn) => {
            btn.addEventListener('click', () => {
                setActive(btn.dataset.drawerTab || 'quick');
            });
        });
    }

    /**
     * Load context from backend and cache it.
     * This is the single source of truth for context - called on init and when config changes.
     * Enables send button when ready.
     */
    async loadContext(): Promise<void> {
        // Prevent duplicate requests
        if (this.contextLoading) {
            this.contextReloadQueued = true;
            console.log('[AIAssistant] Context already loading, queueing refresh...');
            return;
        }

        const contentArea = document.getElementById('context-preview-content');
        const charBadge = document.getElementById('context-char-badge');

        // Mark as loading
        this.contextLoading = true;
        this.contextReady = false;
        this.setSendEnabled(false);

        if (!this.selectedFund) {
            if (contentArea) contentArea.textContent = 'Please select a fund to load context.';
            if (charBadge) charBadge.textContent = '(0 chars)';
            this.contextLoading = false;
            return;
        }

        // Set up timeout with AbortController (30 seconds)
        const controller = new AbortController();
        const timeout = setTimeout(() => controller.abort(), 30000);

        try {
            if (contentArea) contentArea.textContent = 'Loading context...';

            // Gather current toggles
            const toggleThesis = document.getElementById('toggle-thesis') as HTMLInputElement | null;
            const toggleTrades = document.getElementById('toggle-trades') as HTMLInputElement | null;
            const togglePriceVolume = document.getElementById('toggle-price-volume') as HTMLInputElement | null;
            const toggleFundamentals = document.getElementById('toggle-fundamentals') as HTMLInputElement | null;

            const includeThesis = toggleThesis?.checked || false;
            const includeTrades = toggleTrades?.checked || false;
            const includePriceVolume = togglePriceVolume?.checked || false;
            const includeFundamentals = toggleFundamentals?.checked || false;
            const includeInsiderTrades = this.includeInsiderTrades;
            const includeCongressTrades = this.includeCongressTrades;
            const includeEtfTrades = this.includeEtfTrades;
            const includeIntelligencePulse = this.includeIntelligencePulse;

            const cacheKey = [
                this.selectedFund,
                includeThesis,
                includeTrades,
                includePriceVolume,
                includeFundamentals,
                includeInsiderTrades,
                includeCongressTrades,
                includeEtfTrades,
                includeIntelligencePulse
            ].join('|');

            const cached = this.contextCache.get(cacheKey);
            if (cached) {
                this.contextString = cached.context || null;
                this.contextReady = true;

                if (contentArea) {
                    contentArea.textContent = cached.context || '';
                }
                if (charBadge) {
                    charBadge.textContent = `(${cached.charCount.toLocaleString()} chars)`;
                }

                this.setSendEnabled(true);
                this.setQuickActionsEnabled(true);
                return;
            }

            console.log('[AIAssistant] Fetching context for fund:', this.selectedFund);

            const response = await fetch('/api/v2/ai/preview_context', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', ...getCsrfHeaders() },
                body: JSON.stringify({
                    fund: this.selectedFund,
                    include_thesis: includeThesis,
                    include_trades: includeTrades,
                    include_price_volume: includePriceVolume,
                    include_fundamentals: includeFundamentals,
                    include_insider_trades: includeInsiderTrades,
                    include_congress_trades: includeCongressTrades,
                    include_etf_trades: includeEtfTrades,
                    include_intelligence_pulse: includeIntelligencePulse
                }),
                signal: controller.signal
            });

            if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);

            const data: ContextPreviewResponse = await response.json();

            if (data.success) {
                // Log performance timings to console for debugging
                if (data.timings) {
                    console.log('[AIAssistant] ⏱️ Context Generation Performance (ms):');
                    console.table({
                        '📊 Data Fetch': data.timings.data_fetch || {},
                        '📝 Formatting': data.timings.formatting || {}
                    });
                    // Also log as formatted text for easy reading
                    const df = data.timings.data_fetch || {};
                    const ft = data.timings.formatting || {};
                    console.log(`[AIAssistant] ⏱️ DATA FETCH BREAKDOWN:
  - positions: ${df.positions ?? 'N/A'}ms
  - trades: ${df.trades ?? 'N/A'}ms
  - metrics+portfolio: ${df['metrics+portfolio'] ?? 'N/A'}ms
  - cash: ${df.cash ?? 'N/A'}ms
  - thesis: ${df.thesis ?? 'N/A'}ms
  - insider_trades: ${df.insider_trades ?? 'N/A'}ms
  - congress_trades: ${df.congress_trades ?? 'N/A'}ms
  - etf_context: ${df.etf_context ?? df.etf_trades ?? 'N/A'}ms
  → TOTAL DATA FETCH: ${df.total_data_fetch ?? 'N/A'}ms`);
                    console.log(`[AIAssistant] ⏱️ FORMATTING BREAKDOWN:
  - format_holdings: ${ft.format_holdings ?? 'N/A'}ms
  - format_metrics: ${ft.format_metrics ?? 'N/A'}ms
  - format_cash: ${ft.format_cash ?? 'N/A'}ms
  - format_thesis: ${ft.format_thesis ?? 'N/A'}ms
  - format_trades: ${ft.format_trades ?? 'N/A'}ms
  - format_insider_trades: ${ft.format_insider_trades ?? 'N/A'}ms
  - format_congress_trades: ${ft.format_congress_trades ?? 'N/A'}ms
  - format_etf_context: ${ft.format_etf_context ?? ft.format_etf_trades ?? 'N/A'}ms
  → TOTAL FORMAT: ${ft.total_format ?? 'N/A'}ms`);
                }
                
                // Cache the context string for use in chat
                this.contextString = data.context || null;
                this.contextReady = true;

                // Update display - convert HTML to plain text for <pre>
                if (contentArea && data.context) {
                    // Create temp element to decode HTML entities and convert <br> to newlines
                    const temp = document.createElement('div');
                    temp.innerHTML = data.context;
                    contentArea.textContent = temp.textContent || temp.innerText || '';
                }
                if (charBadge && data.char_count !== undefined) {
                    charBadge.textContent = `(${data.char_count.toLocaleString()} chars)`;
                }

                // Cache for instant reuse across toggle changes
                this.contextCache.set(cacheKey, {
                    context: data.context || '',
                    charCount: data.char_count || 0
                });

                // Enable send button and quick actions
                this.setSendEnabled(true);
                this.setQuickActionsEnabled(true);
            } else {
                this.contextString = null;
                this.contextReady = false;
                if (contentArea) contentArea.textContent = `Error: ${data.error || 'Unknown error'}`;
                if (charBadge) charBadge.textContent = '(error)';
            }
        } catch (err) {
            console.error('[AIAssistant] Error loading context:', err);
            this.contextString = null;
            this.contextReady = false;

            // Handle timeout specifically
            if (err instanceof Error && err.name === 'AbortError') {
                if (contentArea) contentArea.textContent = 'Context loading timed out. Please try again.';
                if (charBadge) charBadge.textContent = '(timeout)';
            } else {
                const errorMessage = err instanceof Error ? err.message : 'Unknown error';
                if (contentArea) contentArea.textContent = `Failed to load context: ${errorMessage}`;
                if (charBadge) charBadge.textContent = '(error)';
            }
        } finally {
            clearTimeout(timeout);
            this.contextLoading = false;

            if (this.contextReloadQueued) {
                this.contextReloadQueued = false;
                this.loadContext();
            }
        }
    }

    // Alias for backwards compatibility
    refreshContextPreview(): Promise<void> {
        return this.loadContext();
    }

    async copyContextPreview(): Promise<void> {
        const contentArea = document.getElementById('context-preview-content');
        const copyBtn = document.getElementById('context-copy-btn') as HTMLButtonElement | null;
        const previewText = contentArea?.textContent?.trim() || '';

        if (!copyBtn) return;

        const originalLabel = copyBtn.innerHTML;
        const setButtonLabel = (html: string): void => {
            copyBtn.innerHTML = html;
        };

        if (!previewText || previewText.toLowerCase().includes('loading context')) {
            setButtonLabel('<i class="fas fa-exclamation-circle mr-1"></i>No text');
            setTimeout(() => setButtonLabel(originalLabel), 1400);
            return;
        }

        try {
            await navigator.clipboard.writeText(previewText);
            setButtonLabel('<i class="fas fa-check mr-1"></i>Copied');
        } catch (err) {
            console.warn('[AIAssistant] Clipboard API failed, trying fallback:', err);
            try {
                const tempTextarea = document.createElement('textarea');
                tempTextarea.value = previewText;
                tempTextarea.setAttribute('readonly', '');
                tempTextarea.classList.add('sr-only');
                document.body.appendChild(tempTextarea);
                tempTextarea.select();
                const copied = document.execCommand('copy');
                document.body.removeChild(tempTextarea);
                if (!copied) {
                    throw new Error('document.execCommand(copy) returned false');
                }
                setButtonLabel('<i class="fas fa-check mr-1"></i>Copied');
            } catch (fallbackErr) {
                console.error('[AIAssistant] Failed to copy context preview:', fallbackErr);
                setButtonLabel('<i class="fas fa-times mr-1"></i>Failed');
            }
        }

        setTimeout(() => setButtonLabel(originalLabel), 1400);
    }

    loadModels(): void {
        console.log('Fetching models from API...');
        fetch('/api/v2/ai/models')
            .then((res: Response) => {
                if (!res.ok) throw new Error(`HTTP error! status: ${res.status}`);
                return res.json();
            })
            .then((data: ModelsResponse) => {
                console.log('Models API response:', data);
                const select = document.getElementById('model-select') as HTMLSelectElement | null;
                if (!select) return;

                // Only clear and repopulate if we have valid data
                if (data.models && Array.isArray(data.models) && data.models.length > 0) {
                    select.innerHTML = '';
                    data.models.forEach(model => {
                        const option = document.createElement('option');
                        option.value = model.id;
                        option.textContent = model.name; // API handles display names
                        select.appendChild(option);
                    });

                    const preferredId = this.selectedModel || data.default_model || this.config.defaultModel;
                    const preferredOption = preferredId
                        ? Array.from(select.options).find((option) => option.value === preferredId)
                        : null;
                    if (preferredOption) {
                        select.value = preferredOption.value;
                    } else if (select.options.length > 0) {
                        select.value = select.options[0].value;
                    }

                    const previousModel = this.selectedModel;
                    this.selectedModel = select.value;
                    if (previousModel !== this.selectedModel) {
                        this.updateModelDisplay();
                        this.saveModelPreference();
                    }

                    this.updateModelDescription();
                } else {
                    console.error('Invalid models format received:', data);
                    this.showError('No AI models available. Check Ollama connection.');
                }
            })
            .catch((err: Error) => {
                console.error('Error loading models:', err);
                // Don't clear existing options on error - keep fallback
                this.showError('Failed to load AI models. Using cached models if available.');
            });
    }

    loadContextItems(): void {
        fetch('/api/v2/ai/context')
            .then((res: Response) => res.json())
            .then((data: ContextResponse) => {
                this.contextItems = data.items || [];
                this.updateContextUI();
            })
            .catch((err: Error) => console.error('Error loading context:', err));
    }

    updateContextItem(itemType: string, enabled: boolean): void {
        const action = enabled ? 'add' : 'remove';
        const metadata = itemType === 'trades' ? { limit: 50 } : {};

        fetch('/api/v2/ai/context', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...getCsrfHeaders() },
            body: JSON.stringify({
                action: action,
                item_type: itemType,
                fund: this.selectedFund,
                metadata: metadata
            })
        })
            .then((res: Response) => res.json())
            .then((data: ContextResponse) => {
                if (data.success) {
                    this.loadContextItems();
                }
            })
            .catch((err: Error) => console.error('Error updating context:', err));
    }

    clearContext(): void {
        fetch('/api/v2/ai/context', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...getCsrfHeaders() },
            body: JSON.stringify({ action: 'clear' })
        })
            .then((res: Response) => res.json())
            .then((data: ContextResponse) => {
                if (data.success) {
                    this.contextItems = [];
                    this.updateContextUI();
                    // Uncheck all toggles
                    const toggleThesis = document.getElementById('toggle-thesis') as HTMLInputElement | null;
                    const toggleTrades = document.getElementById('toggle-trades') as HTMLInputElement | null;
                    if (toggleThesis) toggleThesis.checked = false;
                    if (toggleTrades) toggleTrades.checked = false;
                }
            })
            .catch((err: Error) => console.error('Error clearing context:', err));
    }

    calculateContextUsage(): void {
        const usageElement = document.getElementById('context-usage');
        if (!usageElement) return;

        // Estimate tokens (roughly 4 chars per token)
        // Includes: Context items, Conversation history, System prompt, and Current user input
        const contextLen = this.contextString ? this.contextString.length : 0;
        const historyLen = JSON.stringify(this.conversationHistory || []).length;
        const systemPromptEst = 1000;

        // Get current input if available
        const inputElement = document.getElementById('chat-input') as HTMLInputElement;
        const inputLen = inputElement ? inputElement.value.length : 0;

        const totalChars = contextLen + historyLen + systemPromptEst + inputLen;
        const usedTokens = Math.round(totalChars / 4);

        // Get model limit
        const modelSelect = document.getElementById('model-select') as HTMLSelectElement;
        const currentModel = modelSelect ? modelSelect.value : (this.selectedModel || this.config.defaultModel);

        let configuredCtx = 4096; // Default safe fallback
        let labelSuffix = '';

        // Check WebAI limits first (full usable window — not Ollama half-split)
        if (this.config.hasWebai && this.config.webaiModels && this.config.webaiModels.includes(currentModel)) {
            if (currentModel.toLowerCase().includes('flash')) {
                configuredCtx = 1000000; // ~1M for Flash models
            } else if (currentModel.toLowerCase().includes('pro')) {
                configuredCtx = 2000000; // ~2M for Pro models
            } else {
                configuredCtx = 128000; // Conservative default for other WebAI
            }
        }
        // Check Ollama / model_config
        else if (this.config.modelConfig && this.config.modelConfig.models) {
            const modelSettings = this.config.modelConfig.models[currentModel];
            if (modelSettings && modelSettings.num_ctx) {
                configuredCtx = modelSettings.num_ctx;
            } else if (this.config.modelConfig.default_config && this.config.modelConfig.default_config.num_ctx) {
                configuredCtx = this.config.modelConfig.default_config.num_ctx;
            }
        }

        // Ollama: usable prompt ≈ num_ctx/2 (Qwen3.8 soft-cap 28k). Do not show full num_ctx.
        const maxTokens = usablePromptTokenBudget(configuredCtx, currentModel);
        if (
            maxTokens > 0 &&
            maxTokens < configuredCtx &&
            !(this.config.hasWebai && this.config.webaiModels?.includes(currentModel))
        ) {
            labelSuffix = ` <span class="text-text-secondary text-[0.7rem]">(prompt budget; num_ctx ${configuredCtx.toLocaleString()})</span>`;
        }

        const percentage = maxTokens > 0
            ? Math.min(100, Math.round((usedTokens / maxTokens) * 100))
            : 0;

        // Color coding against usable prompt budget (not full num_ctx)
        let colorClass = 'text-green-600 dark:text-green-400';
        if (percentage > 80) colorClass = 'text-red-600 dark:text-red-400';
        else if (percentage > 50) colorClass = 'text-yellow-600 dark:text-yellow-400';

        usageElement.innerHTML =
            `Context: <span class="${colorClass}">${usedTokens.toLocaleString()} / ${maxTokens.toLocaleString()} tokens (${percentage}%)</span>${labelSuffix}`;
    }

    updateContextUI(): void {
        const summary = document.getElementById('context-summary');
        const contextItemsElement = document.getElementById('context-items');

        // Count actual enabled toggles
        const toggleThesis = document.getElementById('toggle-thesis') as HTMLInputElement | null;
        const toggleTrades = document.getElementById('toggle-trades') as HTMLInputElement | null;
        const togglePriceVolume = document.getElementById('toggle-price-volume') as HTMLInputElement | null;
        const toggleFundamentals = document.getElementById('toggle-fundamentals') as HTMLInputElement | null;
        const toggleInsiderTrades = document.getElementById('toggle-insider-trades') as HTMLInputElement | null;
        const toggleCongressTrades = document.getElementById('toggle-congress-trades') as HTMLInputElement | null;
        const toggleEtfTrades = document.getElementById('toggle-etf-trades') as HTMLInputElement | null;
        const toggleIntelligencePulse = document.getElementById('toggle-intelligence-pulse') as HTMLInputElement | null;

        let enabledCount = 0;
        if (toggleThesis?.checked) enabledCount++;
        if (toggleTrades?.checked) enabledCount++;
        if (togglePriceVolume?.checked) enabledCount++;
        if (toggleFundamentals?.checked) enabledCount++;
        if (toggleInsiderTrades?.checked) enabledCount++;
        if (toggleCongressTrades?.checked) enabledCount++;
        if (toggleEtfTrades?.checked) enabledCount++;
        if (toggleIntelligencePulse?.checked) enabledCount++;

        if (summary) {
            if (enabledCount === 0) {
                summary.textContent = 'No context items selected';
            } else {
                summary.textContent = `✅ ${enabledCount} data source(s) selected`;
            }
        }
        if (contextItemsElement) {
            contextItemsElement.textContent = `Context Items: ${enabledCount}`;
        }

        // Update token usage
        this.calculateContextUsage();
    }

    updateModelDisplay(): void {
        const currentModelElement = document.getElementById('current-model');
        if (currentModelElement) {
            currentModelElement.textContent = this.selectedModel || '-';
        }
    }

    updateModelDescription(): void {
        const model = this.selectedModel;
        const desc = document.getElementById('model-description');
        if (!desc) return;

        if (this.isWebAIModel(model)) {
            desc.textContent = 'Web-based AI model with persistent conversations';
        } else {
            desc.textContent = 'Local Ollama model';
        }
    }

    updateTickerActions(): void {
        const select = document.getElementById('ticker-select') as HTMLSelectElement | null;
        const custom = document.getElementById('custom-ticker') as HTMLInputElement | null;
        if (!select) return;

        const customValue = custom ? custom.value.trim().toUpperCase() : '';
        const selected = Array.from(select.selectedOptions).map(opt => opt.value);
        const activeTickers = customValue ? [...selected, customValue] : selected;

        const actionsDiv = document.getElementById('ticker-actions');
        if (actionsDiv) {
            if (activeTickers.length > 0) {
                actionsDiv.classList.remove('hidden');
                const compareBtn = document.getElementById('compare-tickers-btn');
                if (compareBtn) {
                    compareBtn.classList.toggle('hidden', activeTickers.length < 2);
                }
            } else {
                actionsDiv.classList.add('hidden');
            }
        }
    }

    async sendMessage(userQuery: string | null = null): Promise<void> {
        const chatInput = document.getElementById('chat-input') as HTMLInputElement | null;
        const query = userQuery || (chatInput ? chatInput.value.trim() : '');
        if (!query) return;

        // Check if already sending a message
        if (this.isSending) {
            this.showError('Please wait for the current message to finish before sending another.');
            return;
        }

        // Mark as sending
        this.isSending = true;

        // Disable send button and input during sending
        const sendBtn = document.getElementById('send-btn') as HTMLButtonElement | null;
        if (sendBtn) sendBtn.disabled = true;
        if (chatInput) chatInput.disabled = true;

        // Clear input
        if (chatInput) chatInput.value = '';

        // Add user message
        this.addMessage('user', query);
        this.conversationHistory.push({ role: 'user', content: query });
        this.pendingPersistUser = query;

        // Hide start analysis area and retry button
        const startAnalysisArea = document.getElementById('start-analysis-area');
        const retryButtonContainer = document.getElementById('retry-button-container');
        if (startAnalysisArea) startAnalysisArea.classList.add('hidden');
        if (retryButtonContainer) retryButtonContainer.classList.add('hidden');

        // Live loading indicator (elapsed timer + phase updates while waiting)
        const loadingId = this.addMessage('assistant', '', true);
        this.startLiveLoading(loadingId, 'Generating response…');

        // Perform search if enabled (legacy prefetch for non-GLM models).
        // GLM uses on-demand search_web / search_research tools instead.
        let searchResults: any = null;
        let repositoryArticles: any = null;
        const modelUsesTools = (this.selectedModel || '').toLowerCase().startsWith('glm-');

        if (!modelUsesTools && this.includeSearch && this.config.searxngAvailable) {
            try {
                this.setLiveLoadingPhase('Searching the web…');
                searchResults = await this.performSearch(query);
                // Display search results if any
                if (searchResults && searchResults.results && searchResults.results.length > 0) {
                    this.displaySearchResults(searchResults);
                }
            } catch (err) {
                console.error('Search error:', err);
            }
        }

        if (!modelUsesTools && this.includeRepository && this.config.ollamaAvailable) {
            try {
                this.setLiveLoadingPhase('Searching research library…');
                repositoryArticles = await this.performRepositorySearch(query);
                // Display repository articles if any
                if (repositoryArticles && repositoryArticles.length > 0) {
                    this.displayRepositoryArticles(repositoryArticles);
                }
            } catch (err) {
                console.error('Repository search error:', err);
            }
        }

        // Back to generating after any prefetch work
        this.setLiveLoadingPhase('Generating response…');

        // Wait for portfolio context when this turn will attach it.
        const needsContextAttach = this.shouldAttachPortfolioContext();

        if (needsContextAttach && !this.contextReady && this.contextLoading) {
            // Wait for context to load (poll every 100ms for up to 10 seconds)
            this.setLiveLoadingPhase('Waiting for portfolio data…');

            let attempts = 0;
            while (!this.contextReady && attempts < 100) {
                await new Promise(resolve => setTimeout(resolve, 100));
                attempts++;
            }

            if (!this.contextReady) {
                console.warn('[AIAssistant] Context load timed out, sending partial/empty context');
            } else {
                this.setLiveLoadingPhase('Generating response…');
            }
        }

        // Portfolio context only on first turn (or when the history window dropped it).
        // Follow-ups expand the anchor user turn with the snapshot instead of re-sending.
        const attachContext = this.shouldAttachPortfolioContext();
        const cachedContext = attachContext ? this.getCachedContext() : '';
        const contextString = cachedContext;
        if (attachContext && cachedContext) {
            this.portfolioContextSnapshot = cachedContext;
            this.portfolioContextAnchorIndex = this.conversationHistory.length - 1;
        }
        const priorHistory = this.buildPriorHistoryForApi();

        console.log(
            '[AIAssistant] Sending message with context length:',
            contextString?.length || 0,
            'attachContext:',
            attachContext,
            'prior history turns:',
            priorHistory.length,
            'contextAnchor:',
            this.portfolioContextAnchorIndex
        );

        // Build request
        const requestData: ChatRequest = {
            query: query,
            model: this.selectedModel,
            fund: this.selectedFund,
            context_items: this.contextItems,
            context_string: contextString,
            conversation_history: priorHistory,
            include_search: this.includeSearch,
            include_repository: this.includeRepository,
            include_price_volume: this.includePriceVolume,
            include_fundamentals: this.includeFundamentals,
            include_insider_trades: this.includeInsiderTrades,
            include_congress_trades: this.includeCongressTrades,
            include_etf_trades: this.includeEtfTrades,
            include_intelligence_pulse: this.includeIntelligencePulse,
            search_results: searchResults,
            repository_articles: repositoryArticles
        };

        // Check if streaming (Ollama) or non-streaming (WebAI)
        if (this.isWebAIModel(this.selectedModel)) {
            // WebAI - non-streaming
            this.sendWebAIMessage(requestData, loadingId);
        } else {
            // Ollama - streaming
            this.sendStreamingMessage(requestData, loadingId);
        }
    }

    /**
     * Get the cached context string (already loaded by loadContext)
     * This is synchronous now - no API call needed since context was pre-loaded
     */
    getCachedContext(): string {
        // Context was already loaded by loadContext() on init
        // Just return it - no need to call API again
        if (!this.contextReady) {
            console.warn('[AIAssistant] getCachedContext called but context not ready yet');
            return '';
        }
        return this.contextString || '';
    }

    /** Clear first-turn portfolio injection state (clear chat / fund / session restore). */
    resetPortfolioContextInjection(): void {
        this.portfolioContextSnapshot = null;
        this.portfolioContextAnchorIndex = null;
    }

    /**
     * True when we should attach the portfolio blob to the current user turn:
     * never injected yet, or the 20-turn window dropped the anchor turn.
     */
    shouldAttachPortfolioContext(): boolean {
        if (this.portfolioContextAnchorIndex === null) {
            return true;
        }
        const priorAll = this.conversationHistory.slice(0, -1);
        const windowStart = Math.max(0, priorAll.length - AIAssistant.HISTORY_WINDOW);
        return this.portfolioContextAnchorIndex < windowStart;
    }

    /**
     * Prior turns for the model API (last HISTORY_WINDOW). Expands the anchor
     * user turn with the portfolio snapshot so follow-ups still see holdings.
     */
    buildPriorHistoryForApi(): Message[] {
        const priorAll = this.conversationHistory.slice(0, -1);
        const windowed = priorAll.slice(-AIAssistant.HISTORY_WINDOW);
        const windowStart = priorAll.length - windowed.length;
        const snapshot = this.portfolioContextSnapshot;
        const anchor = this.portfolioContextAnchorIndex;

        return windowed.map((msg, i) => {
            const absIndex = windowStart + i;
            if (
                msg.role === 'user' &&
                snapshot &&
                anchor !== null &&
                absIndex === anchor
            ) {
                return { role: 'user', content: `${snapshot}\n\n${msg.content}` };
            }
            return { role: msg.role, content: msg.content };
        });
    }

    async performSearch(query: string): Promise<any> {
        // Extract tickers from query (simple implementation)
        const tickers = this.extractTickers(query);

        const response = await fetch('/api/v2/ai/search', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...getCsrfHeaders() },
            body: JSON.stringify({
                query: query,
                tickers: tickers,
                time_range: 'day',
                min_relevance_score: 0.3
            })
        });

        if (!response.ok) {
            throw new Error('Search failed');
        }

        const data: SearchResponse = await response.json();
        return data;
    }

    async performRepositorySearch(query: string): Promise<any[]> {
        const response = await fetch('/api/v2/ai/repository', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...getCsrfHeaders() },
            body: JSON.stringify({
                query: query,
                max_results: 3,
                min_similarity: 0.6
            })
        });

        if (!response.ok) {
            throw new Error('Repository search failed');
        }

        const data: RepositoryResponse = await response.json();
        return data.articles || [];
    }

    extractTickers(query: string): string[] {
        // Simple ticker extraction (uppercase words that look like tickers)
        const words = query.toUpperCase().split(/\s+/);
        const tickers = words.filter(word =>
            word.length <= 5 &&
            /^[A-Z]+$/.test(word) &&
            word.length >= 1
        );
        return tickers;
    }

    sendWebAIMessage(requestData: ChatRequest, loadingId: string): void {
        fetch('/api/v2/ai/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...getCsrfHeaders() },
            body: JSON.stringify(requestData)
        })
            .then((res: Response) => {
                if (!res.ok) {
                    const contentType = res.headers.get('content-type');
                    if (contentType && contentType.includes('application/json')) {
                        return res.json();
                    } else {
                        throw new Error(`HTTP error! status: ${res.status}`);
                    }
                }
                return res.json();
            })
            .then((data: ChatResponse) => {
                const sendBtn = document.getElementById('send-btn') as HTMLButtonElement | null;
                const chatInput = document.getElementById('chat-input') as HTMLInputElement | null;

                this.stopLiveLoading();
                if (data.error) {
                    this.updateMessage(loadingId, 'assistant', `Error: ${data.error}`);
                    this.pendingPersistUser = null;
                } else {
                    this.updateMessage(loadingId, 'assistant', data.response || '');
                    this.recordAssistantReply(data.response || '');
                }
                // Re-enable send button and input
                this.isSending = false;
                if (sendBtn) sendBtn.disabled = false;
                if (chatInput) chatInput.disabled = false;
            })
            .catch((err: Error) => {
                console.error('Chat error:', err);
                this.stopLiveLoading();
                this.updateMessage(loadingId, 'assistant', `Error: ${err.message}`);
                // Re-enable send button and input
                this.isSending = false;
                const sendBtn = document.getElementById('send-btn') as HTMLButtonElement | null;
                const chatInput = document.getElementById('chat-input') as HTMLInputElement | null;
                if (sendBtn) sendBtn.disabled = false;
                if (chatInput) chatInput.disabled = false;
            });
    }

    sendStreamingMessage(requestData: ChatRequest, loadingId: string): void {
        fetch('/api/v2/ai/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...getCsrfHeaders() },
            body: JSON.stringify(requestData)
        })
            .then((res: Response) => {
                if (!res.ok) {
                    // Check if response is JSON before parsing
                    const contentType = res.headers.get('content-type');
                    if (contentType && contentType.includes('application/json')) {
                        return res.json().then((data: ChatResponse) => {
                            throw new Error(data.error || `HTTP error! status: ${res.status}`);
                        });
                    } else {
                        // Response is HTML or other non-JSON
                        throw new Error(`HTTP error! status: ${res.status}`);
                    }
                }

                // Check if response is SSE (text/event-stream) or JSON
                const contentType = res.headers.get('content-type');
                if (contentType && contentType.includes('text/event-stream')) {
                    // SSE streaming
                    const reader = res.body?.getReader();
                    if (!reader) {
                        throw new Error('Response body is not readable');
                    }

                    const decoder = new TextDecoder();
                    let buffer = '';
                    let fullResponse = '';

                    const finishStream = (text: string): void => {
                        this.stopLiveLoading();
                        this.updateMessage(loadingId, 'assistant', text);
                        this.recordAssistantReply(text);
                        this.updateRetryButton();
                        this.isSending = false;
                        const sendBtn = document.getElementById('send-btn') as HTMLButtonElement | null;
                        const chatInput = document.getElementById('chat-input') as HTMLInputElement | null;
                        if (sendBtn) sendBtn.disabled = false;
                        if (chatInput) chatInput.disabled = false;
                    };

                    const failStream = (message: string): void => {
                        this.stopLiveLoading();
                        const partial = fullResponse.trim();
                        if (partial) {
                            // Keep what already streamed — late proxy/network drops are common on long Ollama replies.
                            const kept =
                                `${partial}\n\n---\n*(Stream interrupted: ${message}. Partial reply kept above.)*`;
                            this.updateMessage(loadingId, 'assistant', kept);
                            this.recordAssistantReply(kept);
                        } else {
                            this.updateMessage(loadingId, 'assistant', `❌ Error: ${message}`);
                            this.pendingPersistUser = null;
                        }
                        this.updateRetryButton();
                        this.isSending = false;
                        const sendBtn = document.getElementById('send-btn') as HTMLButtonElement | null;
                        const chatInput = document.getElementById('chat-input') as HTMLInputElement | null;
                        if (sendBtn) sendBtn.disabled = false;
                        if (chatInput) chatInput.disabled = false;
                    };

                    const readChunk = (): void => {
                        reader.read().then(({ done, value }) => {
                            if (done) {
                                finishStream(fullResponse);
                                return;
                            }

                            buffer += decoder.decode(value, { stream: true });
                            const lines = buffer.split('\n');
                            buffer = lines.pop() || ''; // Keep incomplete line in buffer

                            for (const line of lines) {
                                if (line.trim() === '') continue;
                                if (line.startsWith('data: ')) {
                                    try {
                                        const data: ChatResponse = JSON.parse(line.slice(6));
                                        if (data.done) {
                                            finishStream(fullResponse);
                                            return;
                                        }
                                        if (data.status === 'thinking') {
                                            const phase = (data as ChatResponse & { phase?: string }).phase;
                                            if (phase === 'waiting_on_ollama' || phase === 'accepted') {
                                                this.setLiveLoadingPhase('Waiting on Ollama…');
                                            } else if (phase === 'waiting_on_model') {
                                                this.setLiveLoadingPhase('Waiting on model…');
                                            } else if (phase === 'synthesizing') {
                                                this.setLiveLoadingPhase('Synthesizing answer…');
                                            } else {
                                                this.setLiveLoadingPhase('Generating response…');
                                            }
                                        }
                                        if (data.status === 'tool' && data.name) {
                                            const label = this.friendlyToolName(data.name);
                                            this.setLiveLoadingPhase(`Looking up ${label}…`);
                                        }
                                        if (data.chunk) {
                                            // First token: stop the waiting chrome, show live text
                                            this.stopLiveLoading();
                                            fullResponse += data.chunk;
                                            this.updateMessage(loadingId, 'assistant', fullResponse + '<span class="inline-block w-2 h-4 bg-gray-500 dark:bg-gray-400 ml-1 animate-pulse">▌</span>');
                                        }
                                        if (data.error) {
                                            failStream(data.error);
                                            return;
                                        }
                                    } catch (e) {
                                        console.error('Error parsing SSE data:', e, 'Line:', line);
                                    }
                                }
                            }

                            readChunk();
                        }).catch((err: Error) => {
                            failStream(err.message);
                        });
                    };

                    readChunk();
                } else {
                    // Non-streaming JSON response (fallback)
                    return res.json().then((data: ChatResponse) => {
                        const sendBtn = document.getElementById('send-btn') as HTMLButtonElement | null;
                        const chatInput = document.getElementById('chat-input') as HTMLInputElement | null;

                        this.stopLiveLoading();
                        if (data.error) {
                            this.updateMessage(loadingId, 'assistant', `❌ Error: ${data.error}`);
                            this.updateRetryButton();
                            this.pendingPersistUser = null;
                        } else {
                            this.updateMessage(loadingId, 'assistant', data.response || data.chunk || '');
                            this.recordAssistantReply(data.response || data.chunk || '');
                            this.updateRetryButton();
                        }
                        // Re-enable send button and input
                        this.isSending = false;
                        if (sendBtn) sendBtn.disabled = false;
                        if (chatInput) chatInput.disabled = false;
                    });
                }
            })
            .catch((err: Error) => {
                console.error('Chat error:', err);
                this.stopLiveLoading();
                this.updateMessage(loadingId, 'assistant', `Error: ${err.message}`);
                // Re-enable send button and input
                this.isSending = false;
                const sendBtn = document.getElementById('send-btn') as HTMLButtonElement | null;
                const chatInput = document.getElementById('chat-input') as HTMLInputElement | null;
                if (sendBtn) sendBtn.disabled = false;
                if (chatInput) chatInput.disabled = false;
            });
    }

    addMessage(role: 'user' | 'assistant', content: string, isLoading: boolean = false): string {
        const messagesDiv = document.getElementById('chat-messages');
        if (!messagesDiv) return '';

        const messageId = `msg-${Date.now()}-${Math.random()}`;

        // Create message container with Flowbite/Tailwind structure
        const messageDiv = document.createElement('div');
        messageDiv.id = messageId;

        if (role === 'user') {
            // User message: aligned right
            messageDiv.className = 'flex gap-3 justify-end mb-4';

            const bubbleContainer = document.createElement('div');
            bubbleContainer.className = 'flex flex-col max-w-[80%]';

            const bubble = document.createElement('div');
            bubble.className = 'message-bubble bg-dashboard-surface-alt text-text-primary border border-accent/30 rounded-lg rounded-br-sm px-4 py-3 shadow-xs';

            const contentDiv = document.createElement('div');
            contentDiv.className = 'message-content leading-relaxed text-white';
            if (isLoading) {
                contentDiv.innerHTML = content;
            } else {
                contentDiv.innerHTML = this.renderMarkdown(content);
            }

            bubble.appendChild(contentDiv);
            bubbleContainer.appendChild(bubble);
            messageDiv.appendChild(bubbleContainer);
        } else {
            // Assistant message: aligned left with avatar placeholder
            messageDiv.className = 'flex gap-3 mb-4';

            // Avatar placeholder
            const avatarDiv = document.createElement('div');
            avatarDiv.className = 'flex-shrink-0';
            const avatar = document.createElement('div');
            avatar.className = 'w-8 h-8 rounded-full bg-dashboard-surface-alt flex items-center justify-center text-text-secondary text-sm font-semibold';
            avatar.textContent = 'AI';
            avatarDiv.appendChild(avatar);

            const bubbleContainer = document.createElement('div');
            bubbleContainer.className = 'flex-1';

            const bubble = document.createElement('div');
            bubble.className = 'message-bubble bg-dashboard-surface-alt text-text-primary rounded-lg rounded-bl-sm px-4 py-3 shadow-xs';

            const contentDiv = document.createElement('div');
            contentDiv.className = 'message-content leading-relaxed [&>p]:my-2 [&>p:first-child]:mt-0 [&>p:last-child]:mb-0';
            if (isLoading) {
                contentDiv.innerHTML = content;
            } else {
                contentDiv.innerHTML = this.renderMarkdown(content);
            }

            bubble.appendChild(contentDiv);
            bubbleContainer.appendChild(bubble);
            messageDiv.appendChild(avatarDiv);
            messageDiv.appendChild(bubbleContainer);
        }

        messagesDiv.appendChild(messageDiv);
        // Stick to bottom for new user turns / loading bubble; streaming updates stay sticky-only.
        this.scrollToBottom(role === 'user' || isLoading);

        return messageId;
    }

    updateMessage(messageId: string, role: 'user' | 'assistant', content: string, isHtml: boolean = false): void {
        const messageDiv = document.getElementById(messageId);
        if (!messageDiv) return;

        const contentDiv = messageDiv.querySelector('.message-content');
        const bubble = messageDiv.querySelector('.message-bubble') as HTMLElement | null;

        if (contentDiv && bubble) {
            // Check if this is an error message
            if (content.includes('Error:') || content.includes('error:') || content.includes('❌')) {
                // Update bubble styling for error
                bubble.className = 'bg-theme-error-bg/20 text-theme-error-text border border-theme-error-text/30 rounded-lg px-4 py-3 shadow-xs';
                if (role === 'user') {
                    bubble.className += ' rounded-br-sm';
                } else {
                    bubble.className += ' rounded-bl-sm';
                }
                messageDiv.classList.add('error-message');
            }

            if (isHtml) {
                contentDiv.innerHTML = content;
            } else {
                contentDiv.innerHTML = this.renderMarkdown(content);
            }
        }

        this.scrollToBottom();
    }

    renderMarkdown(text: string): string {
        const windowAny = window as any;
        if (typeof window !== 'undefined' && windowAny.marked) {
            const html = windowAny.marked.parse(text);
            // Sanitize HTML to prevent XSS attacks
            if (windowAny.DOMPurify) {
                return windowAny.DOMPurify.sanitize(html, {
                    ALLOWED_TAGS: ['p', 'br', 'strong', 'em', 'u', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'ul', 'ol', 'li', 'blockquote', 'code', 'pre', 'a'],
                    ALLOWED_ATTR: ['href', 'title']
                });
            }
            return html;
        }
        // Fallback: simple text rendering (escape HTML)
        return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\n/g, '<br>');
    }

    /** True when the chat viewport is already near the bottom (sticky-follow zone). */
    private isChatNearBottom(thresholdPx: number = 120): boolean {
        const container = document.getElementById('chat-container');
        if (!container) return true;
        const distance =
            container.scrollHeight - container.scrollTop - container.clientHeight;
        return distance <= thresholdPx;
    }

    /**
     * Scroll chat to bottom. By default only if the user is already near the bottom,
     * so reading earlier messages while a reply streams is not yanked down.
     * Pass force=true after sending a message or restoring a session.
     */
    scrollToBottom(force: boolean = false): void {
        const container = document.getElementById('chat-container');
        if (!container) return;
        if (!force && !this.isChatNearBottom()) return;
        container.scrollTop = container.scrollHeight;
    }

    clearChat(): void {
        const fund = this.selectedFund;
        if (fund) {
            fetch('/api/v2/ai/chat/clear', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', ...getCsrfHeaders() },
                body: JSON.stringify({ fund }),
                keepalive: true,
            }).catch((err: Error) => console.warn('[AIAssistant] clear session failed:', err));
        }
        this.pendingPersistUser = null;
        this.messages = [];
        this.conversationHistory = [];
        this.resetPortfolioContextInjection();
        const messagesDiv = document.getElementById('chat-messages');
        if (messagesDiv) messagesDiv.innerHTML = '';
        const retryButtonContainer = document.getElementById('retry-button-container');
        if (retryButtonContainer) retryButtonContainer.classList.add('hidden');

        // Show start analysis area if context items exist
        if (this.contextItems.length > 0) {
            this.showStartAnalysis();
        }
    }

    /** Hydrate UI + conversationHistory from server for the current fund. */
    async loadSessionFromServer(): Promise<void> {
        const fund = this.selectedFund;
        if (!fund) return;
        try {
            const res = await fetch(
                `/api/v2/ai/chat/session?fund=${encodeURIComponent(fund)}`,
                { headers: { ...getCsrfHeaders() } },
            );
            if (!res.ok) {
                console.warn('[AIAssistant] session load HTTP', res.status);
                return;
            }
            const data = await res.json();
            const messages = Array.isArray(data.messages) ? data.messages : [];
            this.applySessionMessages(messages);
        } catch (err) {
            console.warn('[AIAssistant] session load failed:', err);
        }
    }

    applySessionMessages(messages: Array<{ role?: string; content?: string }>): void {
        this.messages = [];
        this.conversationHistory = [];
        this.pendingPersistUser = null;
        // Session rows are bare turns (no portfolio blob). Next send re-injects context.
        this.resetPortfolioContextInjection();
        const messagesDiv = document.getElementById('chat-messages');
        if (messagesDiv) messagesDiv.innerHTML = '';

        for (const raw of messages) {
            const role = raw.role === 'assistant' ? 'assistant' : 'user';
            const content = String(raw.content || '');
            if (!content.trim()) continue;
            this.addMessage(role, content);
            this.conversationHistory.push({ role, content });
        }

        if (this.conversationHistory.length === 0 && this.contextItems.length > 0) {
            this.showStartAnalysis();
        } else {
            const startAnalysisArea = document.getElementById('start-analysis-area');
            if (startAnalysisArea) startAnalysisArea.classList.add('hidden');
        }
        this.updateRetryButton();
        this.scrollToBottom(true);
    }

    recordAssistantReply(content: string): void {
        this.conversationHistory.push({ role: 'assistant', content });
        const userText = this.pendingPersistUser;
        this.pendingPersistUser = null;
        if (userText) {
            void this.persistTurns([
                { role: 'user', content: userText },
                { role: 'assistant', content },
            ]);
        }
    }

    persistTurns(turns: Message[], keepalive: boolean = false): void {
        const fund = this.selectedFund;
        if (!fund || !turns.length) return;
        const payload = {
            fund,
            model: this.selectedModel,
            turns: turns.map((t) => ({
                role: t.role,
                content: t.content,
                ts: new Date().toISOString(),
            })),
        };
        fetch('/api/v2/ai/chat/append', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...getCsrfHeaders() },
            body: JSON.stringify(payload),
            keepalive,
        }).catch((err: Error) => console.warn('[AIAssistant] append session failed:', err));
    }

    persistInterruptedIfNeeded(): void {
        if (!this.isSending || !this.pendingPersistUser || !this.selectedFund) return;
        const userText = this.pendingPersistUser;
        this.pendingPersistUser = null;
        this.persistTurns(
            [
                { role: 'user', content: userText },
                {
                    role: 'assistant',
                    content: '*(Response interrupted — navigated away before the reply finished.)*',
                },
            ],
            true,
        );
    }

    showStartAnalysis(): void {
        const area = document.getElementById('start-analysis-area');
        if (!area) return;

        area.classList.remove('hidden');
        // Generate default prompt
        const prompt = this.generateDefaultPrompt();
        const initialPrompt = document.getElementById('initial-prompt') as HTMLTextAreaElement | null;
        if (initialPrompt) initialPrompt.value = prompt;
    }

    generateDefaultPrompt(): string {
        if (this.contextItems.length === 0) {
            return "Please help me analyze my portfolio.";
        }

        const itemTypes = this.contextItems.map(item => item.item_type);
        if (itemTypes.includes('holdings') && itemTypes.includes('thesis')) {
            return "Based on the portfolio holdings and investment thesis provided above, analyze how well the current positions align with the stated investment strategy and pillars.";
        } else if (itemTypes.includes('trades')) {
            return "Based on the trading activity data provided above, analyze recent trades and review trade patterns.";
        } else if (itemTypes.includes('metrics')) {
            return "Based on the performance metrics data provided above, analyze portfolio performance over time.";
        } else {
            return "Based on the portfolio data provided above, provide a comprehensive analysis.";
        }
    }

    quickResearch(action: string): void {
        const select = document.getElementById('ticker-select') as HTMLSelectElement | null;
        const custom = document.getElementById('custom-ticker') as HTMLInputElement | null;
        if (!select) return;

        const customValue = custom ? custom.value.trim().toUpperCase() : '';
        const selected = Array.from(select.selectedOptions).map(opt => opt.value);
        const activeTickers = customValue ? [...selected, customValue] : selected;

        let prompt = '';

        switch (action) {
            case 'research':
                if (activeTickers.length === 1) {
                    prompt = `Research ${activeTickers[0]} - latest news and analysis`;
                } else {
                    prompt = `Research the following stocks: ${activeTickers.join(', ')}. Provide latest news for each.`;
                }
                break;
            case 'analyze':
                if (activeTickers.length === 1) {
                    prompt = `Analyze ${activeTickers[0]} stock - recent performance and outlook`;
                } else {
                    prompt = `Analyze and compare the outlooks for: ${activeTickers.join(', ')}`;
                }
                break;
            case 'compare':
                prompt = `Compare ${activeTickers.join(' and ')} stocks. Which is a better investment?`;
                break;
            case 'earnings':
                if (activeTickers.length === 1) {
                    prompt = `Find recent earnings news for ${activeTickers[0]}`;
                } else {
                    prompt = `Find recent earnings reports for: ${activeTickers.join(', ')}`;
                }
                break;
            case 'portfolio':
                prompt = this.generateDefaultPrompt();
                break;
            case 'market':
                prompt = "What's the latest stock market news today?";
                break;
            case 'sector':
                prompt = "What's happening in the stock market sectors today?";
                break;
        }

        if (prompt) {
            // Start a new conversation for quick actions
            this.clearChat();

            // Turbo Mode: Send immediately
            this.sendMessage(prompt);

            // Hide any open editing areas
            const suggestedPromptArea = document.getElementById('suggested-prompt-area');
            if (suggestedPromptArea) suggestedPromptArea.classList.add('hidden');
        }
    }

    saveModelPreference(): void {
        // Save model preference to user settings
        fetch('/api/settings/ai_model', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...getCsrfHeaders() },
            body: JSON.stringify({ model: this.selectedModel })
        }).catch((err: Error) => console.error('Error saving model preference:', err));
    }

    updateUI(): void {
        const currentModel = document.getElementById('current-model');
        if (currentModel) currentModel.textContent = this.selectedModel;
        this.updateContextUI();

        // Load portfolio tickers for quick research
        if (this.selectedFund) {
            this.loadPortfolioTickers();
        }
    }

    async loadPortfolioTickers(): Promise<void> {
        if (!this.selectedFund) return;

        try {
            // Fetch portfolio positions to get tickers
            const response = await fetch(`/api/portfolio?fund=${encodeURIComponent(this.selectedFund)}`);
            if (response.ok) {
                const data: AIAssistantPortfolioResponse = await response.json();
                const tickers = data.positions?.map(pos => pos.ticker).filter(Boolean) || [];
                const select = document.getElementById('ticker-select') as HTMLSelectElement | null;
                if (select) {
                    select.innerHTML = '';
                    // Filter out empty/falsy tickers and deduplicate
                    const validTickers = [...new Set(tickers)]
                        .filter((t): t is string => Boolean(t && t.trim()))
                        .sort();
                    validTickers.forEach(ticker => {
                        const option = document.createElement('option');
                        option.value = ticker;
                        option.textContent = ticker;
                        select.appendChild(option);
                    });
                }
            }
        } catch (err) {
            const errorMessage = err instanceof Error ? err.message : 'Unknown error';
            this.showError('Error loading portfolio tickers: ' + errorMessage);
        }
    }

    retryLastMessage(): void {
        // Find last user message
        const lastUserMsg = this.conversationHistory.filter(msg => msg.role === 'user').pop();
        if (!lastUserMsg) {
            this.showError('No previous message to retry');
            return;
        }

        const messagesDiv = document.getElementById('chat-messages');

        // Remove last assistant message if it exists
        if (this.conversationHistory.length > 0 &&
            this.conversationHistory[this.conversationHistory.length - 1].role === 'assistant') {
            this.conversationHistory.pop();
            // Remove from UI
            if (messagesDiv?.lastElementChild) {
                messagesDiv.lastElementChild.remove();
            }
        }

        // Also remove the last user message from history (sendMessage will re-add it)
        if (this.conversationHistory.length > 0 &&
            this.conversationHistory[this.conversationHistory.length - 1].role === 'user') {
            this.conversationHistory.pop();
            // Remove from UI
            if (messagesDiv?.lastElementChild) {
                messagesDiv.lastElementChild.remove();
            }
        }

        // Hide retry button
        const retryButtonContainer = document.getElementById('retry-button-container');
        if (retryButtonContainer) retryButtonContainer.classList.add('hidden');

        // Re-send the last user message (this will re-add it to history and UI)
        this.sendMessage(lastUserMsg.content);
    }

    async checkPortfolioNews(): Promise<void> {
        if (!this.selectedFund) {
            this.showError('Please select a fund first');
            return;
        }

        try {
            const response = await fetch('/api/v2/ai/portfolio-intelligence', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', ...getCsrfHeaders() },
                body: JSON.stringify({ fund: this.selectedFund })
            });

            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }

            const data: PortfolioIntelligenceResponse = await response.json();

            if (data.matching_articles && data.matching_articles.length > 0) {
                // Format article context
                let articleContext = "Here are recent research articles found for the user's portfolio holdings:\n\n";
                data.matching_articles.slice(0, 10).forEach((art, i) => {
                    articleContext += `${i + 1}. Title: ${art.title || 'Untitled'}\n`;
                    articleContext += `   Holdings: ${art.matched_holdings?.join(', ') || 'N/A'}\n`;
                    articleContext += `   Summary: ${art.summary || 'No summary'}\n`;
                    articleContext += `   Conclusion: ${art.conclusion || 'N/A'}\n\n`;
                });

                const prompt = "Review the following recent research articles about my portfolio holdings. " +
                    "Identify any noteworthy events, risks, or opportunities that strictly require my attention.\n\n" +
                    articleContext;

                const suggestedPromptArea = document.getElementById('suggested-prompt-area');
                const editablePrompt = document.getElementById('editable-prompt') as HTMLTextAreaElement | null;
                if (suggestedPromptArea) suggestedPromptArea.classList.remove('hidden');
                if (editablePrompt) editablePrompt.value = prompt;
            } else {
                this.showError(`No recent articles found in the repository for your holdings (past 7 days).`);
            }
        } catch (err) {
            const errorMessage = err instanceof Error ? err.message : 'Unknown error';
            this.showError('Failed to check portfolio news: ' + errorMessage);
        }
    }

    showError(message: string): void {
        // Show error in chat UI with proper styling
        const errorId = this.addMessage('assistant', `❌ Error: ${message}`);
        // Error styling is handled in updateMessage, but ensure it's applied
        setTimeout(() => {
            const messageDiv = document.getElementById(errorId);
            if (messageDiv) {
                const bubble = messageDiv.querySelector('.bg-dashboard-surface-alt, .bg-accent') as HTMLElement | null;
                if (bubble) {
                    bubble.className = 'bg-theme-error-bg/20 text-theme-error-text border border-theme-error-text/30 rounded-lg rounded-bl-sm px-4 py-3 shadow-xs';
                }
            }
        }, 10);
    }

    updateRetryButton(): void {
        const retryContainer = document.getElementById('retry-button-container');
        if (retryContainer) {
            if (this.conversationHistory.length > 0 &&
                this.conversationHistory[this.conversationHistory.length - 1].role === 'assistant') {
                retryContainer.classList.remove('hidden');
            } else {
                retryContainer.classList.add('hidden');
            }
        }
    }

    displaySearchResults(searchData: any): void {
        if (!searchData || !searchData.results || searchData.results.length === 0) return;
        const chatMessages = document.getElementById('chat-messages');
        if (!chatMessages) return;

        const resultsDiv = document.createElement('div');
        resultsDiv.className = 'mb-4 border rounded-lg border-theme-info-text/30 bg-theme-info-bg/10';

        const randomId = Math.random().toString(36).substring(2, 9);
        const header = document.createElement('button');
        header.type = 'button';
        header.className = 'w-full text-left p-3 flex justify-between items-center rounded-t-lg hover:bg-theme-info-bg/20 transition-colors focus:ring-4 focus:ring-theme-info-text/20 focus:outline-none';
        header.setAttribute('data-collapse-toggle', `search-results-${randomId}`);
        header.setAttribute('aria-expanded', 'false');
        header.setAttribute('aria-controls', `search-results-${randomId}`);
        header.innerHTML = `<span class="font-semibold text-theme-info-text">🔍 Search Results (${searchData.results.length} found)</span><svg data-accordion-icon class="w-3 h-3 shrink-0 transition-transform text-theme-info-text" aria-hidden="true" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 10 6"><path stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5 5 1 1 5"/></svg>`;

        const content = document.createElement('div');
        content.id = `search-results-${randomId}`;
        content.className = 'hidden p-3 border-t border-theme-info-text/30 space-y-2';

        const maxResults = Math.min(5, searchData.results.length);
        searchData.results.slice(0, maxResults).forEach((result: any, idx: number) => {
            const resultItem = document.createElement('div');
            resultItem.className = 'p-2 rounded border bg-dashboard-surface border-border';
            const title = result.title || 'Untitled';
            const url = result.url || '#';
            const snippet = result.content || result.snippet || '';
            resultItem.innerHTML = `<div class="font-semibold text-sm mb-1"><a href="${url}" target="_blank" rel="noopener noreferrer" class="text-accent hover:underline">${idx + 1}. ${title}</a></div>${snippet ? `<div class="text-xs text-text-secondary">${snippet.substring(0, 200)}...</div>` : ''}`;
            content.appendChild(resultItem);
        });

        resultsDiv.appendChild(header);
        resultsDiv.appendChild(content);
        chatMessages.appendChild(resultsDiv);
        // Flowbite only auto-binds at DOMContentLoaded; bind this new subtree.
        initCollapsesIn(resultsDiv);
        this.scrollToBottom();
        header.click();
    }

    displayRepositoryArticles(articles: any[]): void {
        if (!articles || articles.length === 0) return;
        const chatMessages = document.getElementById('chat-messages');
        if (!chatMessages) return;

        const articlesDiv = document.createElement('div');
        articlesDiv.className = 'mb-4 border rounded-lg border-accent/30 bg-accent/10';

        const randomId = Math.random().toString(36).substring(2, 9);
        const header = document.createElement('button');
        header.type = 'button';
        header.className = 'w-full text-left p-3 flex justify-between items-center rounded-t-lg hover:bg-accent/20 transition-colors focus:ring-4 focus:ring-accent/20 focus:outline-none';
        header.setAttribute('data-collapse-toggle', `research-articles-${randomId}`);
        header.setAttribute('aria-expanded', 'false');
        header.setAttribute('aria-controls', `research-articles-${randomId}`);
        header.innerHTML = `<span class="font-semibold text-accent">🧠 Research Articles (${articles.length} found)</span><svg data-accordion-icon class="w-3 h-3 shrink-0 transition-transform text-accent" aria-hidden="true" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 10 6"><path stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5 5 1 1 5"/></svg>`;

        const content = document.createElement('div');
        content.id = `research-articles-${randomId}`;
        content.className = 'hidden p-3 border-t border-accent/30 space-y-2';

        articles.forEach((article: any, idx: number) => {
            const articleItem = document.createElement('div');
            articleItem.className = 'p-2 rounded border bg-dashboard-surface border-border';
            const title = article.title || 'Untitled';
            const summary = article.summary || '';
            const similarity = article.similarity || 0;
            const articleId = article.id || article.article_id;
            const sourceUrl = article.url || article.source_url;

            // Create clickable link - prefer local research page, fallback to source URL
            let titleHtml = title;
            if (articleId) {
                titleHtml = `<a href="/research?highlight=${articleId}" class="text-accent hover:underline">${title}</a>`;
            } else if (sourceUrl) {
                titleHtml = `<a href="${sourceUrl}" target="_blank" rel="noopener noreferrer" class="text-accent hover:underline">${title}</a>`;
            }

            articleItem.innerHTML = `<div class="font-semibold text-sm mb-1">${idx + 1}. ${titleHtml} <span class="text-xs text-text-tertiary">(${(similarity * 100).toFixed(0)}% match)</span></div>${summary ? `<div class="text-xs text-text-secondary">${summary.substring(0, 200)}...</div>` : ''}`;
            content.appendChild(articleItem);
        });

        articlesDiv.appendChild(header);
        articlesDiv.appendChild(content);
        chatMessages.appendChild(articlesDiv);
        initCollapsesIn(articlesDiv);
        this.scrollToBottom();
        header.click();
    }

    /**
     * Load user preferences (including includeSearch and trade toggles)
     */
    async loadUserPreferences(): Promise<void> {
        try {
            // Load preferences
            const response = await fetch('/api/settings/preferences');
            if (response.ok) {
                const data = await response.json();
                if (data.preferences) {
                    // Load includeSearch preference
                    if (typeof data.preferences.ai_include_search === 'boolean') {
                        this.includeSearch = data.preferences.ai_include_search;
                        const toggleSearch = document.getElementById('toggle-search') as HTMLInputElement | null;
                        if (toggleSearch) {
                            toggleSearch.checked = this.includeSearch;
                        }
                        console.log('[AIAssistant] Loaded includeSearch preference:', this.includeSearch);
                    }
                    
                    // Load insider trades preference (defaults to true)
                    if (typeof data.preferences.ai_include_insider_trades === 'boolean') {
                        this.includeInsiderTrades = data.preferences.ai_include_insider_trades;
                        const toggleInsiderTrades = document.getElementById('toggle-insider-trades') as HTMLInputElement | null;
                        if (toggleInsiderTrades) {
                            toggleInsiderTrades.checked = this.includeInsiderTrades;
                        }
                        console.log('[AIAssistant] Loaded includeInsiderTrades preference:', this.includeInsiderTrades);
                    }
                    
                    // Load congress trades preference (defaults to true)
                    if (typeof data.preferences.ai_include_congress_trades === 'boolean') {
                        this.includeCongressTrades = data.preferences.ai_include_congress_trades;
                        const toggleCongressTrades = document.getElementById('toggle-congress-trades') as HTMLInputElement | null;
                        if (toggleCongressTrades) {
                            toggleCongressTrades.checked = this.includeCongressTrades;
                        }
                        console.log('[AIAssistant] Loaded includeCongressTrades preference:', this.includeCongressTrades);
                    }
                    
                    // Load ETF trades preference (defaults to true)
                    if (typeof data.preferences.ai_include_etf_trades === 'boolean') {
                        this.includeEtfTrades = data.preferences.ai_include_etf_trades;
                        const toggleEtfTrades = document.getElementById('toggle-etf-trades') as HTMLInputElement | null;
                        if (toggleEtfTrades) {
                            toggleEtfTrades.checked = this.includeEtfTrades;
                        }
                        console.log('[AIAssistant] Loaded includeEtfTrades preference:', this.includeEtfTrades);
                    }

                    // Load intelligence pulse preference (defaults to true)
                    if (typeof data.preferences.ai_include_intelligence_pulse === 'boolean') {
                        this.includeIntelligencePulse = data.preferences.ai_include_intelligence_pulse;
                        const togglePulse = document.getElementById('toggle-intelligence-pulse') as HTMLInputElement | null;
                        if (togglePulse) {
                            togglePulse.checked = this.includeIntelligencePulse;
                        }
                        console.log('[AIAssistant] Loaded includeIntelligencePulse preference:', this.includeIntelligencePulse);
                    }
                }
            }
        } catch (err) {
            console.warn('[AIAssistant] Could not load user preferences, using defaults:', err);
        }
    }

    /**
     * Save includeSearch preference to backend
     */
    async saveIncludeSearchPreference(includeSearch: boolean): Promise<void> {
        try {
            const response = await fetch('/api/settings/ai_include_search', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', ...getCsrfHeaders() },
                body: JSON.stringify({ include_search: includeSearch })
            });

            if (response.ok) {
                const result = await response.json();
                if (result.success) {
                    console.log('[AIAssistant] Saved includeSearch preference:', includeSearch);
                } else {
                    console.warn('[AIAssistant] Failed to save preference:', result.error);
                }
            } else {
                console.warn('[AIAssistant] Failed to save preference, status:', response.status);
            }
        } catch (err) {
            console.error('[AIAssistant] Error saving includeSearch preference:', err);
        }
    }

    /**
     * Save insider trades preference to backend
     */
    async saveInsiderTradesPreference(includeInsiderTrades: boolean): Promise<void> {
        try {
            const response = await fetch('/api/settings/ai_include_insider_trades', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', ...getCsrfHeaders() },
                body: JSON.stringify({ include_insider_trades: includeInsiderTrades })
            });

            if (response.ok) {
                const result = await response.json();
                if (result.success) {
                    console.log('[AIAssistant] Saved includeInsiderTrades preference:', includeInsiderTrades);
                } else {
                    console.warn('[AIAssistant] Failed to save preference:', result.error);
                }
            } else {
                console.warn('[AIAssistant] Failed to save preference, status:', response.status);
            }
        } catch (err) {
            console.error('[AIAssistant] Error saving includeInsiderTrades preference:', err);
        }
    }

    /**
     * Save congress trades preference to backend
     */
    async saveCongressTradesPreference(includeCongressTrades: boolean): Promise<void> {
        try {
            const response = await fetch('/api/settings/ai_include_congress_trades', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', ...getCsrfHeaders() },
                body: JSON.stringify({ include_congress_trades: includeCongressTrades })
            });

            if (response.ok) {
                const result = await response.json();
                if (result.success) {
                    console.log('[AIAssistant] Saved includeCongressTrades preference:', includeCongressTrades);
                } else {
                    console.warn('[AIAssistant] Failed to save preference:', result.error);
                }
            } else {
                console.warn('[AIAssistant] Failed to save preference, status:', response.status);
            }
        } catch (err) {
            console.error('[AIAssistant] Error saving includeCongressTrades preference:', err);
        }
    }

    /**
     * Save ETF trades preference to backend
     */
    async saveEtfTradesPreference(includeEtfTrades: boolean): Promise<void> {
        try {
            const response = await fetch('/api/settings/ai_include_etf_trades', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', ...getCsrfHeaders() },
                body: JSON.stringify({ include_etf_trades: includeEtfTrades })
            });

            if (response.ok) {
                const result = await response.json();
                if (result.success) {
                    console.log('[AIAssistant] Saved includeEtfTrades preference:', includeEtfTrades);
                } else {
                    console.warn('[AIAssistant] Failed to save preference:', result.error);
                }
            } else {
                console.warn('[AIAssistant] Failed to save preference, status:', response.status);
            }
        } catch (err) {
            console.error('[AIAssistant] Error saving includeEtfTrades preference:', err);
        }
    }

    async saveIntelligencePulsePreference(includePulse: boolean): Promise<void> {
        try {
            const response = await fetch('/api/settings/ai_include_intelligence_pulse', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', ...getCsrfHeaders() },
                body: JSON.stringify({ include_intelligence_pulse: includePulse })
            });

            if (response.ok) {
                const result = await response.json();
                if (result.success) {
                    console.log('[AIAssistant] Saved includeIntelligencePulse preference:', includePulse);
                } else {
                    console.warn('[AIAssistant] Failed to save preference:', result.error);
                }
            } else {
                console.warn('[AIAssistant] Failed to save preference, status:', response.status);
            }
        } catch (err) {
            console.error('[AIAssistant] Error saving includeIntelligencePulse preference:', err);
        }
    }
}

// Make AIAssistant available globally for template usage
(window as any).AIAssistant = AIAssistant;

// Auto-initialize if config is present
document.addEventListener('DOMContentLoaded', () => {
    AIAssistant.autoInit();
});
