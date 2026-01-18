/**
 * AI Assistant TypeScript
 * Handles chat interface, streaming responses, context management, and search
 */

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
}

interface ModelsResponse {
    models?: Array<{ id: string; name: string }>;
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
    search_results: any;
    repository_articles: any;
}

interface ChatResponse {
    response?: string;
    chunk?: string;
    done?: boolean;
    error?: string;
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

    // Context caching - calculate once, use for all messages
    private contextString: string | null = null;  // The actual context text to send to LLM
    private contextReady: boolean = false;  // True when context is loaded and ready
    private contextLoading: boolean = false; // True while loading (prevent duplicate requests)
    private isSending: boolean = false; // True while a message is being sent (prevent duplicate sends)

    constructor(config: AIAssistantConfig) {
        this.config = config;
        this.messages = [];
        this.contextItems = [];
        this.selectedModel = config.defaultModel || 'granite3.2:8b';
        this.selectedFund = config.availableFunds?.[0] || null;
        this.conversationHistory = [];
        this.includeSearch = true;
        this.includeRepository = true;
        this.includePriceVolume = true;
        this.includeFundamentals = true;
    }

    init(): void {
        console.log('[AIAssistant] init() starting...');
        console.log('[AIAssistant] Config:', this.config);
        try {
            // Disable send button until context is ready
            this.setSendEnabled(false);

            this.setupEventListeners();
            console.log('[AIAssistant] Event listeners attached');
            this.loadModels();
            this.loadFunds();
            this.loadPortfolioTickers();
            this.loadContextItems();
            this.updateUI();

            // Eagerly load context - this enables the send button when done
            this.loadContext();

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

    /**
     * Check if a model is a web-based AI model (uses webaiModels from config)
     */
    isWebAIModel(model: string): boolean {
        if (!model) return false;
        // Check against configured webai models list
        const webaiModels = this.config.webaiModels || [];
        return webaiModels.includes(model);
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

        // Model selection
        const modelSelect = document.getElementById('model-select') as HTMLSelectElement | null;
        if (modelSelect) {
            modelSelect.addEventListener('change', (e: Event) => {
                const target = e.target as HTMLSelectElement;
                this.selectedModel = target.value;
                this.saveModelPreference();
                // Update current model display in footer
                this.updateModelDisplay();
                // Recalculate token usage with new model limits
                this.calculateContextUsage();
            });
        }

        // Fund selection - use global selector from left nav (or fallback to right sidebar)
        const globalFundSelect = document.getElementById('global-fund-select') as HTMLSelectElement | null;
        const rightSidebarFundSelect = document.getElementById('fund-select') as HTMLSelectElement | null;

        // Read initial fund from global selector
        if (globalFundSelect && globalFundSelect.value) {
            this.selectedFund = globalFundSelect.value;
            console.log('[AIAssistant] Initial fund from global selector:', this.selectedFund);
        }

        // Listen to global fund selector (left nav)
        if (globalFundSelect) {
            globalFundSelect.addEventListener('change', (e: Event) => {
                const target = e.target as HTMLSelectElement;
                this.selectedFund = target.value;
                console.log('[AIAssistant] Fund changed to:', this.selectedFund);
                this.contextReady = false; // Reset context state
                this.loadPortfolioTickers(); // Reload tickers for new fund
                this.loadContext(); // Reload context for new fund
                // Sync right sidebar selector if exists
                if (rightSidebarFundSelect) {
                    rightSidebarFundSelect.value = target.value;
                }
            });
        }

        // Also listen to right sidebar fund selector (for backwards compat)
        if (rightSidebarFundSelect) {
            rightSidebarFundSelect.addEventListener('change', (e: Event) => {
                const target = e.target as HTMLSelectElement;
                this.selectedFund = target.value;
                console.log('[AIAssistant] Fund changed (sidebar) to:', this.selectedFund);
                this.contextReady = false;
                this.loadPortfolioTickers();
                this.loadContext();
                // Sync global selector if exists
                if (globalFundSelect) {
                    globalFundSelect.value = target.value;
                }
            });
        }

        // Context toggles
        const toggleThesis = document.getElementById('toggle-thesis') as HTMLInputElement | null;
        const toggleTrades = document.getElementById('toggle-trades') as HTMLInputElement | null;
        const togglePriceVolume = document.getElementById('toggle-price-volume') as HTMLInputElement | null;
        const toggleFundamentals = document.getElementById('toggle-fundamentals') as HTMLInputElement | null;
        const toggleSearch = document.getElementById('toggle-search') as HTMLInputElement | null;
        const toggleRepository = document.getElementById('toggle-repository') as HTMLInputElement | null;

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
            });
        }
        if (toggleRepository) {
            toggleRepository.addEventListener('change', (e: Event) => {
                const target = e.target as HTMLInputElement;
                this.includeRepository = target.checked;
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
    }

    /**
     * Load context from backend and cache it.
     * This is the single source of truth for context - called on init and when config changes.
     * Enables send button when ready.
     */
    async loadContext(): Promise<void> {
        // Prevent duplicate requests
        if (this.contextLoading) {
            console.log('[AIAssistant] Context already loading, skipping...');
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

            console.log('[AIAssistant] Fetching context for fund:', this.selectedFund);

            const response = await fetch('/api/v2/ai/preview_context', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    fund: this.selectedFund,
                    include_thesis: includeThesis,
                    include_trades: includeTrades,
                    include_price_volume: includePriceVolume,
                    include_fundamentals: includeFundamentals
                })
            });

            if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);

            const data: ContextPreviewResponse = await response.json();

            if (data.success) {
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

                // Enable send button
                this.setSendEnabled(true);
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
            const errorMessage = err instanceof Error ? err.message : 'Unknown error';
            if (contentArea) contentArea.textContent = `Failed to load context: ${errorMessage}`;
            if (charBadge) charBadge.textContent = '(error)';
        } finally {
            this.contextLoading = false;
        }
    }

    // Alias for backwards compatibility
    refreshContextPreview(): Promise<void> {
        return this.loadContext();
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

                select.innerHTML = '';

                if (data.models && Array.isArray(data.models)) {
                    data.models.forEach(model => {
                        const option = document.createElement('option');
                        option.value = model.id;
                        option.textContent = model.name; // API handles display names
                        if (model.id === this.selectedModel) {
                            option.selected = true;
                        }
                        select.appendChild(option);
                    });
                } else {
                    console.error('Invalid models format received:', data);
                    this.showError('Failed to load models: Invalid data format');
                }
                this.updateModelDescription();
            })
            .catch((err: Error) => {
                console.error('Error loading models:', err);
                this.showError('Failed to load AI models. Please check connection.');
            });
    }

    loadFunds(): void {
        const select = document.getElementById('fund-select') as HTMLSelectElement | null;
        if (!select || !this.config.availableFunds) return;

        this.config.availableFunds.forEach(fund => {
            const option = document.createElement('option');
            option.value = fund;
            option.textContent = fund;
            if (fund === this.selectedFund) {
                option.selected = true;
            }
            select.appendChild(option);
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
            headers: { 'Content-Type': 'application/json' },
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
            headers: { 'Content-Type': 'application/json' },
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
        const inputElement = document.getElementById('user-input') as HTMLTextAreaElement;
        const inputLen = inputElement ? inputElement.value.length : 0;

        const totalChars = contextLen + historyLen + systemPromptEst + inputLen;
        const usedTokens = Math.round(totalChars / 4);

        // Get model limit
        const modelSelect = document.getElementById('model-select') as HTMLSelectElement;
        const currentModel = modelSelect ? modelSelect.value : (this.selectedModel || this.config.defaultModel);

        let maxTokens = 4096; // Default safe fallback

        // Check WebAI limits first
        if (this.config.hasWebai && this.config.webaiModels && this.config.webaiModels.includes(currentModel)) {
            if (currentModel.toLowerCase().includes('flash')) {
                maxTokens = 1000000; // ~1M for Flash models
            } else if (currentModel.toLowerCase().includes('pro')) {
                maxTokens = 2000000; // ~2M for Pro models
            } else {
                maxTokens = 128000; // Conservative default for other WebAI
            }
        }
        // Check Ollama config
        else if (this.config.modelConfig && this.config.modelConfig.models) {
            const modelSettings = this.config.modelConfig.models[currentModel];
            if (modelSettings && modelSettings.num_ctx) {
                maxTokens = modelSettings.num_ctx;
            } else if (this.config.modelConfig.default_config && this.config.modelConfig.default_config.num_ctx) {
                maxTokens = this.config.modelConfig.default_config.num_ctx;
            }
        }

        const percentage = Math.min(100, Math.round((usedTokens / maxTokens) * 100));

        // Color coding
        let colorClass = 'text-green-600 dark:text-green-400';
        if (percentage > 80) colorClass = 'text-red-600 dark:text-red-400';
        else if (percentage > 50) colorClass = 'text-yellow-600 dark:text-yellow-400';

        usageElement.innerHTML = `Context: <span class="${colorClass}">${usedTokens.toLocaleString()} / ${maxTokens.toLocaleString()} tokens (${percentage}%)</span>`;
    }

    updateContextUI(): void {
        const summary = document.getElementById('context-summary');
        const contextItemsElement = document.getElementById('context-items');

        // Count actual enabled toggles
        const toggleThesis = document.getElementById('toggle-thesis') as HTMLInputElement | null;
        const toggleTrades = document.getElementById('toggle-trades') as HTMLInputElement | null;
        const togglePriceVolume = document.getElementById('toggle-price-volume') as HTMLInputElement | null;
        const toggleFundamentals = document.getElementById('toggle-fundamentals') as HTMLInputElement | null;

        let enabledCount = 0;
        if (toggleThesis?.checked) enabledCount++;
        if (toggleTrades?.checked) enabledCount++;
        if (togglePriceVolume?.checked) enabledCount++;
        if (toggleFundamentals?.checked) enabledCount++;

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

        // Hide start analysis area and retry button
        const startAnalysisArea = document.getElementById('start-analysis-area');
        const retryButtonContainer = document.getElementById('retry-button-container');
        if (startAnalysisArea) startAnalysisArea.classList.add('hidden');
        if (retryButtonContainer) retryButtonContainer.classList.add('hidden');

        // Show loading indicator with Tailwind spinner
        const loadingId = this.addMessage('assistant', '<div class="flex items-center gap-2"><div class="animate-spin rounded-full h-4 w-4 border-2 border-gray-300 dark:border-gray-600 border-t-accent"></div><span>Generating response...</span></div>', true);

        // Perform search if enabled
        let searchResults: any = null;
        let repositoryArticles: any = null;

        if (this.includeSearch && this.config.searxngAvailable) {
            try {
                searchResults = await this.performSearch(query);
                // Display search results if any
                if (searchResults && searchResults.results && searchResults.results.length > 0) {
                    this.displaySearchResults(searchResults);
                }
            } catch (err) {
                console.error('Search error:', err);
            }
        }

        if (this.includeRepository && this.config.ollamaAvailable) {
            try {
                repositoryArticles = await this.performRepositorySearch(query);
                // Display repository articles if any
                if (repositoryArticles && repositoryArticles.length > 0) {
                    this.displayRepositoryArticles(repositoryArticles);
                }
            } catch (err) {
                console.error('Repository search error:', err);
            }
        }

        // Get pre-loaded context (synchronous - no API call)
        // Only send context with the FIRST message of a conversation
        const isFirstMessage = this.conversationHistory.length === 1; // After adding user message
        const contextString = isFirstMessage ? this.getCachedContext() : null;

        // Debug logging
        if (isFirstMessage) {
            console.log('[AIAssistant] First message - including context, length:', contextString?.length || 0);
        } else {
            console.log('[AIAssistant] Subsequent message - context already in conversation history');
        }

        // Build request
        const requestData: ChatRequest = {
            query: query,
            model: this.selectedModel,
            fund: this.selectedFund,
            context_items: this.contextItems,
            context_string: contextString, // Only sent with first message
            conversation_history: this.conversationHistory.slice(-20), // Last 20 messages
            include_search: this.includeSearch,
            include_repository: this.includeRepository,
            include_price_volume: this.includePriceVolume,
            include_fundamentals: this.includeFundamentals,
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

    async performSearch(query: string): Promise<any> {
        // Extract tickers from query (simple implementation)
        const tickers = this.extractTickers(query);

        const response = await fetch('/api/v2/ai/search', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
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
            headers: { 'Content-Type': 'application/json' },
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
            headers: { 'Content-Type': 'application/json' },
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

                if (data.error) {
                    this.updateMessage(loadingId, 'assistant', `Error: ${data.error}`);
                } else {
                    this.updateMessage(loadingId, 'assistant', data.response || '');
                    this.conversationHistory.push({ role: 'assistant', content: data.response || '' });
                }
                // Re-enable send button and input
                this.isSending = false;
                if (sendBtn) sendBtn.disabled = false;
                if (chatInput) chatInput.disabled = false;
            })
            .catch((err: Error) => {
                console.error('Chat error:', err);
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
            headers: { 'Content-Type': 'application/json' },
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

                    const readChunk = (): void => {
                        reader.read().then(({ done, value }) => {
                            if (done) {
                                // Remove streaming indicator and finalize
                                this.updateMessage(loadingId, 'assistant', fullResponse);
                                this.conversationHistory.push({ role: 'assistant', content: fullResponse });
                                this.updateRetryButton();
                                // Re-enable send button and input
                                this.isSending = false;
                                const sendBtn = document.getElementById('send-btn') as HTMLButtonElement | null;
                                const chatInput = document.getElementById('chat-input') as HTMLInputElement | null;
                                if (sendBtn) sendBtn.disabled = false;
                                if (chatInput) chatInput.disabled = false;
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
                                            this.updateMessage(loadingId, 'assistant', fullResponse);
                                            this.conversationHistory.push({ role: 'assistant', content: fullResponse });
                                            this.updateRetryButton();
                                            // Re-enable send button and input
                                            this.isSending = false;
                                            const sendBtn = document.getElementById('send-btn') as HTMLButtonElement | null;
                                            const chatInput = document.getElementById('chat-input') as HTMLInputElement | null;
                                            if (sendBtn) sendBtn.disabled = false;
                                            if (chatInput) chatInput.disabled = false;
                                            return;
                                        }
                                        if (data.chunk) {
                                            fullResponse += data.chunk;
                                            this.updateMessage(loadingId, 'assistant', fullResponse + '<span class="inline-block w-2 h-4 bg-gray-500 dark:bg-gray-400 ml-1 animate-pulse">▌</span>');
                                        }
                                        if (data.error) {
                                            this.updateMessage(loadingId, 'assistant', `❌ Error: ${data.error}`);
                                            this.updateRetryButton();
                                            // Re-enable send button and input
                                            this.isSending = false;
                                            const sendBtn = document.getElementById('send-btn') as HTMLButtonElement | null;
                                            const chatInput = document.getElementById('chat-input') as HTMLInputElement | null;
                                            if (sendBtn) sendBtn.disabled = false;
                                            if (chatInput) chatInput.disabled = false;
                                            return;
                                        }
                                    } catch (e) {
                                        console.error('Error parsing SSE data:', e, 'Line:', line);
                                    }
                                }
                            }

                            readChunk();
                        }).catch((err: Error) => {
                            this.updateMessage(loadingId, 'assistant', `❌ Error: ${err.message}`);
                            this.updateRetryButton();
                            // Re-enable send button and input
                            this.isSending = false;
                            const sendBtn = document.getElementById('send-btn') as HTMLButtonElement | null;
                            const chatInput = document.getElementById('chat-input') as HTMLInputElement | null;
                            if (sendBtn) sendBtn.disabled = false;
                            if (chatInput) chatInput.disabled = false;
                        });
                    };

                    readChunk();
                } else {
                    // Non-streaming JSON response (fallback)
                    return res.json().then((data: ChatResponse) => {
                        const sendBtn = document.getElementById('send-btn') as HTMLButtonElement | null;
                        const chatInput = document.getElementById('chat-input') as HTMLInputElement | null;

                        if (data.error) {
                            this.updateMessage(loadingId, 'assistant', `❌ Error: ${data.error}`);
                            this.updateRetryButton();
                        } else {
                            this.updateMessage(loadingId, 'assistant', data.response || data.chunk || '');
                            this.conversationHistory.push({ role: 'assistant', content: data.response || data.chunk || '' });
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
            bubble.className = 'bg-accent text-white rounded-lg rounded-br-sm px-4 py-3 shadow-sm';

            const contentDiv = document.createElement('div');
            contentDiv.className = 'message-content text-white';
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
            avatar.className = 'w-8 h-8 rounded-full bg-gray-300 dark:bg-dashboard-surface-alt flex items-center justify-center text-text-secondary text-sm font-semibold';
            avatar.textContent = 'AI';
            avatarDiv.appendChild(avatar);

            const bubbleContainer = document.createElement('div');
            bubbleContainer.className = 'flex-1';

            const bubble = document.createElement('div');
            bubble.className = 'bg-gray-100 dark:bg-dashboard-surface-alt text-text-primary rounded-lg rounded-bl-sm px-4 py-3 shadow-sm';

            const contentDiv = document.createElement('div');
            contentDiv.className = 'message-content';
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
        this.scrollToBottom();

        return messageId;
    }

    updateMessage(messageId: string, role: 'user' | 'assistant', content: string): void {
        const messageDiv = document.getElementById(messageId);
        if (!messageDiv) return;

        const contentDiv = messageDiv.querySelector('.message-content');
        const bubble = messageDiv.querySelector('.bg-blue-600, .bg-accent, .bg-gray-100, .dark\\:bg-dashboard-surface-alt') as HTMLElement | null;

        if (contentDiv && bubble) {
            // Check if this is an error message
            if (content.includes('Error:') || content.includes('error:') || content.includes('❌')) {
                // Update bubble styling for error
                bubble.className = 'bg-red-100 dark:bg-red-900/30 text-red-800 dark:text-red-200 border border-red-300 dark:border-red-800 rounded-lg px-4 py-3 shadow-sm';
                if (role === 'user') {
                    bubble.className += ' rounded-br-sm';
                } else {
                    bubble.className += ' rounded-bl-sm';
                }
                messageDiv.classList.add('error-message');
            }
            contentDiv.innerHTML = this.renderMarkdown(content);
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

    scrollToBottom(): void {
        const container = document.getElementById('chat-container');
        if (container) {
            container.scrollTop = container.scrollHeight;
        }
    }

    clearChat(): void {
        this.messages = [];
        this.conversationHistory = [];
        const messagesDiv = document.getElementById('chat-messages');
        if (messagesDiv) messagesDiv.innerHTML = '';
        const retryButtonContainer = document.getElementById('retry-button-container');
        if (retryButtonContainer) retryButtonContainer.classList.add('hidden');

        // Show start analysis area if context items exist
        if (this.contextItems.length > 0) {
            this.showStartAnalysis();
        }
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
            headers: { 'Content-Type': 'application/json' },
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
                    [...new Set(tickers)].sort().forEach(ticker => {
                        const option = document.createElement('option');
                        option.value = ticker || '';
                        option.textContent = ticker || '';
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

        // Remove last assistant message if it exists
        if (this.conversationHistory.length > 0 &&
            this.conversationHistory[this.conversationHistory.length - 1].role === 'assistant') {
            this.conversationHistory.pop();
            // Remove last message from UI
            const messagesDiv = document.getElementById('chat-messages');
            if (messagesDiv) {
                const lastMessage = messagesDiv.lastElementChild;
                if (lastMessage) {
                    lastMessage.remove();
                }
            }
        }

        // Hide retry button
        const retryButtonContainer = document.getElementById('retry-button-container');
        if (retryButtonContainer) retryButtonContainer.classList.add('hidden');

        // Re-send the last user message
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
                headers: { 'Content-Type': 'application/json' },
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
                const bubble = messageDiv.querySelector('.bg-gray-100, .dark\\:bg-gray-700, .bg-blue-600, .bg-accent') as HTMLElement | null;
                if (bubble) {
                    bubble.className = 'bg-red-100 dark:bg-red-900/30 text-red-800 dark:text-red-200 border border-red-300 dark:border-red-800 rounded-lg rounded-bl-sm px-4 py-3 shadow-sm';
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
        resultsDiv.className = 'mb-4 border rounded-lg border-blue-300 dark:border-blue-600 bg-blue-50 dark:bg-blue-950/50';

        const header = document.createElement('div');
        header.className = 'p-3 cursor-pointer rounded-t-lg hover:bg-blue-100 dark:hover:bg-blue-900/40 transition-colors';
        header.innerHTML = `<div class="flex justify-between items-center"><span class="font-semibold text-blue-800 dark:text-blue-300">🔍 Search Results (${searchData.results.length} found)</span><span class="text-blue-600 dark:text-blue-400 text-sm">Click to expand ▼</span></div>`;

        const content = document.createElement('div');
        content.className = 'hidden p-3 border-t border-blue-300 dark:border-blue-600 space-y-2';

        const maxResults = Math.min(5, searchData.results.length);
        searchData.results.slice(0, maxResults).forEach((result: any, idx: number) => {
            const resultItem = document.createElement('div');
            resultItem.className = 'p-2 rounded border bg-dashboard-surface border-border';
            const title = result.title || 'Untitled';
            const url = result.url || '#';
            const snippet = result.content || result.snippet || '';
            resultItem.innerHTML = `<div class="font-semibold text-sm mb-1"><a href="${url}" target="_blank" rel="noopener noreferrer" class="text-blue-600 dark:text-blue-400 hover:underline">${idx + 1}. ${title}</a></div>${snippet ? `<div class="text-xs text-gray-600 dark:text-gray-400">${snippet.substring(0, 200)}...</div>` : ''}`;
            content.appendChild(resultItem);
        });

        header.addEventListener('click', () => {
            content.classList.toggle('hidden');
            const arrow = header.querySelector('span:last-child');
            if (arrow) arrow.textContent = content.classList.contains('hidden') ? 'Click to expand ▼' : 'Click to collapse ▲';
        });

        resultsDiv.appendChild(header);
        resultsDiv.appendChild(content);
        chatMessages.appendChild(resultsDiv);
        this.scrollToBottom();
        header.click();
    }

    displayRepositoryArticles(articles: any[]): void {
        if (!articles || articles.length === 0) return;
        const chatMessages = document.getElementById('chat-messages');
        if (!chatMessages) return;

        const articlesDiv = document.createElement('div');
        articlesDiv.className = 'mb-4 border rounded-lg border-purple-300 dark:border-purple-600 bg-purple-50 dark:bg-purple-950/50';

        const header = document.createElement('div');
        header.className = 'p-3 cursor-pointer rounded-t-lg hover:bg-purple-100 dark:hover:bg-purple-900/40 transition-colors';
        header.innerHTML = `<div class="flex justify-between items-center"><span class="font-semibold text-purple-800 dark:text-purple-300">🧠 Research Articles (${articles.length} found)</span><span class="text-purple-600 dark:text-purple-400 text-sm">Click to expand ▼</span></div>`;

        const content = document.createElement('div');
        content.className = 'hidden p-3 border-t border-purple-300 dark:border-purple-600 space-y-2';

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
                titleHtml = `<a href="/research?highlight=${articleId}" class="text-purple-700 dark:text-purple-300 hover:underline">${title}</a>`;
            } else if (sourceUrl) {
                titleHtml = `<a href="${sourceUrl}" target="_blank" rel="noopener noreferrer" class="text-purple-700 dark:text-purple-300 hover:underline">${title}</a>`;
            }

            articleItem.innerHTML = `<div class="font-semibold text-sm mb-1">${idx + 1}. ${titleHtml} <span class="text-xs text-text-tertiary">(${(similarity * 100).toFixed(0)}% match)</span></div>${summary ? `<div class="text-xs text-text-secondary">${summary.substring(0, 200)}...</div>` : ''}`;
            content.appendChild(articleItem);
        });

        header.addEventListener('click', () => {
            content.classList.toggle('hidden');
            const arrow = header.querySelector('span:last-child');
            if (arrow) arrow.textContent = content.classList.contains('hidden') ? 'Click to expand ▼' : 'Click to collapse ▲';
        });

        articlesDiv.appendChild(header);
        articlesDiv.appendChild(content);
        chatMessages.appendChild(articlesDiv);
        this.scrollToBottom();
        header.click();
    }
}

// Make AIAssistant available globally for template usage
(window as any).AIAssistant = AIAssistant;

// Auto-initialize if config is present
document.addEventListener('DOMContentLoaded', () => {
    AIAssistant.autoInit();
});
