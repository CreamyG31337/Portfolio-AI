// TODO: Fix bugs documented in docs/TICKER_DETAILS_BUGS.md (chevron toggle, stale state, race conditions, theme classes, XSS)
export { }; // Ensure file is treated as a module

// ticker_autocomplete import removed -- ticker details now uses search-on-Enter via /api/v2/ticker/search
import { getCsrfHeaders } from './csrf.js';

// API Response interfaces
interface TickerListResponse {
    tickers: string[];
}

interface BasicInfo {
    ticker?: string;
    company_name?: string;
    sector?: string;
    industry?: string;
    currency?: string;
    exchange?: string;
    logo_url?: string;
    use_alt_logo?: boolean;
    trailing_pe?: number;
    description?: string;  // Company description for stocks, fund description for ETFs
}

interface TickerPosition {
    fund?: string;
    shares?: number;
    price?: number;
    cost_basis?: number;
    pnl?: number;
    date?: string;
}

interface TickerTrade {
    date?: string;
    action?: string;
    shares?: number;
    price?: number;
    fund?: string;
    reason?: string;
}

/** Prefer persisted trade_log.action; otherwise infer from reason (legacy rows). */
function inferTickerTradeAction(trade: TickerTrade): string {
    const a = (trade.action || '').trim().toUpperCase();
    if (a === 'BUY' || a === 'SELL' || a === 'DIVIDEND') return a;
    const reason = (trade.reason || '').toLowerCase();
    if (reason.includes('sell') || reason.includes('sold')) return 'SELL';
    if (reason.includes('drip') || reason.includes('dividend')) return 'DIVIDEND';
    return 'BUY';
}

interface TickerPortfolioData {
    has_positions?: boolean;
    has_trades?: boolean;
    positions?: TickerPosition[];
    trades?: TickerTrade[];
}

interface ResearchArticle {
    id?: string;
    title?: string;
    summary?: string;
    url?: string;
    source?: string;
    published_at?: string;
    fetched_at?: string;
    sentiment?: string;
    sentiment_score?: number;
    relevance_score?: number;
    article_type?: string;
}

interface SentimentMetric {
    platform?: string;
    sentiment_label?: string;
    sentiment_score?: number;
    volume?: number;
    bull_bear_ratio?: number | null;
    created_at?: string;
}

interface SentimentAlert {
    platform?: string;
    sentiment_label?: string;
    sentiment_score?: number;
}

interface SocialSentiment {
    latest_metrics?: SentimentMetric[];
    alerts?: SentimentAlert[];
}

interface CongressTickerTrade {
    id?: number;
    transaction_date?: string;
    politician?: string;
    chamber?: string;
    type?: string;
    amount?: string;
    party?: string;
    state?: string;
    owner?: string;
    score_display?: string;
    analysis_reasoning?: string;
    analysis_reasoning_short?: string;
}

interface InsiderTrade {
    ticker?: string;
    company_name?: string;
    insider_name?: string;
    insider_title?: string;
    transaction_date?: string;
    disclosure_date?: string;
    type?: string;
    shares?: number | null;
    price_per_share?: number | null;
    value?: number | null;
    shares_held_after?: number | null;
    percent_change?: number | null;
    notes?: string | null;
    created_at?: string;
    _logo_url?: string | null;
}

interface EtfHoldingTrade {
    trade_date?: string;
    etf_ticker?: string;
    holding_ticker?: string;
    trade_type?: string;
    shares_change?: number;
    shares_after?: number;
}

interface WatchlistStatus {
    is_active?: boolean;
    priority_tier?: string;
    source?: string;
}

interface TickerAnalysis {
    ticker?: string;
    analysis_type?: string;
    analysis_date?: string;
    data_start_date?: string;
    data_end_date?: string;
    sentiment?: string;
    sentiment_score?: number;
    confidence_score?: number;
    themes?: string[];
    summary?: string;
    analysis_text?: string;
    reasoning?: string;
    input_context?: string;
    etf_changes_count?: number;
    congress_trades_count?: number;
    research_articles_count?: number;
    created_at?: string;
    updated_at?: string;
    model_used?: string;
    requested_by?: string;
}

interface TickerAnalysisContextResponse {
    ticker?: string;
    context?: string;
}

interface TickerAnalysisApiResponse {
    analysis?: TickerAnalysis | null;
}

/** Row from ticker_meta_analysis (second-order synthesis). */
interface TickerMetaAnalysisRow {
    id?: string;
    ticker?: string;
    unified_conviction?: string;
    confidence_adjusted?: number;
    contradictions?: unknown;
    what_changed_vs_last_run?: string;
    action_items?: string[];
    narrative?: string;
    /**
     * Raw JSONB payload returned by the meta LLM. Holds the full Phase 1 contract
     * fields (``stance``, ``horizon``, ``key_drivers``, ``risk_flags``,
     * ``actionability_score``, ``confidence``) that aren't promoted to top-level
     * columns. ``renderTickerMetaAnalysisContent`` reads from ``full_result`` to
     * surface the entire stance package, not just the legacy promoted fields.
     */
    full_result?: Record<string, unknown>;
    model_used?: string;
    requested_by?: string;
    artifact_bundle_digest?: string;
    updated_at?: string;
    source_analysis_id?: string;
}

interface SignalAnalysis {
    ticker?: string;
    structure?: {
        trend?: string;
        pullback?: boolean;
        breakout?: boolean;
        price?: number;
        ma_short?: number;
        ma_long?: number;
    };
    timing?: {
        volume_ok?: boolean;
        rsi?: number;
        rsi_ok?: boolean;
        cci?: number;
        cci_ok?: boolean;
        timing_ok?: boolean;
    };
    fear_risk?: {
        fear_level?: string;
        risk_score?: number;
        recommendation?: string;
    };
    momentum?: {
        bias?: string;
        composite_score?: number;
        trend_following?: any;
        momentum?: any;
        mean_reversion?: any;
        volatility?: any;
        oscillators?: any;
    };
    fundamental?: {
        quality?: string;
        composite_score?: number;
        metrics_available?: number;
        profitability?: any;
        growth?: any;
        health?: any;
        valuation?: any;
    };
    overall_signal?: string;
    confidence?: number;
    analysis_date?: string;
    explanation?: string;
}

interface TickerInfoResponse {
    basic_info?: BasicInfo;
    portfolio_data?: TickerPortfolioData;
    research_articles?: ResearchArticle[];
    social_sentiment?: SocialSentiment;
    congress_trades?: CongressTickerTrade[];
    insider_trades?: InsiderTrade[];
    watchlist_status?: WatchlistStatus;
}

interface ChartData {
    data: any[];
    layout: any;
}

interface PriceHistoryData {
    data?: Array<{ price?: number }>;
}

interface ErrorResponse {
    error?: string;
}

let currentTicker: string = '';
let tickerList: string[] = [];
let selectedModel: string = '';
let contextCharCount: number = 0;
let modelSyncInProgress: boolean = false;
const tickerDetailsConfig = (window as any).tickerDetailsConfig || {};
const modelConfig = tickerDetailsConfig.modelConfig || {};
selectedModel = tickerDetailsConfig.defaultModel || '';

function getSelectedFund(): string | null {
    const selector = document.getElementById('global-fund-select') as HTMLSelectElement | null;
    const rawFund = selector ? selector.value : '';

    if (!rawFund) return null;
    const normalized = rawFund.trim();
    if (!normalized || normalized.toLowerCase() === 'all') return null;
    return normalized;
}

function appendFundParam(url: string): string {
    const fund = getSelectedFund();
    if (!fund) return url;
    const separator = url.includes('?') ? '&' : '?';
    return `${url}${separator}fund=${encodeURIComponent(fund)}`;
}

/** Extra query params for chart/price APIs: Yahoo vs portfolio, optional calendar years. */
function buildTickerChartExtraQuery(): string {
    const psEl = document.getElementById('chart-price-source') as HTMLSelectElement | null;
    const priceSource = psEl ? psEl.value : 'auto';
    const yfEl = document.getElementById('chart-year-from') as HTMLSelectElement | null;
    const ytEl = document.getElementById('chart-year-to') as HTMLSelectElement | null;
    const yf = yfEl?.value?.trim() ?? '';
    const yt = ytEl?.value?.trim() ?? '';
    let q = `&price_source=${encodeURIComponent(priceSource)}`;
    if (yf !== '' && yt !== '') {
        q += `&year_from=${encodeURIComponent(yf)}&year_to=${encodeURIComponent(yt)}`;
    }
    return q;
}

function buildTickerYearQuery(): string {
    const yfEl = document.getElementById('chart-year-from') as HTMLSelectElement | null;
    const ytEl = document.getElementById('chart-year-to') as HTMLSelectElement | null;
    const yf = yfEl?.value?.trim() ?? '';
    const yt = ytEl?.value?.trim() ?? '';
    if (yf !== '' && yt !== '') {
        return `&year_from=${encodeURIComponent(yf)}&year_to=${encodeURIComponent(yt)}`;
    }
    return '';
}

function getChartPeriodChangeLabel(range: string): string {
    const yfEl = document.getElementById('chart-year-from') as HTMLSelectElement | null;
    const ytEl = document.getElementById('chart-year-to') as HTMLSelectElement | null;
    const yfs = yfEl?.value?.trim() ?? '';
    const yts = ytEl?.value?.trim() ?? '';
    if (yfs !== '' && yts !== '') {
        const a = Math.min(parseInt(yfs, 10), parseInt(yts, 10));
        const b = Math.max(parseInt(yfs, 10), parseInt(yts, 10));
        if (!Number.isNaN(a) && !Number.isNaN(b)) {
            return `Change (${a}–${b})`;
        }
    }
    const rangeLabels: { [key: string]: string } = {
        '3m': 'Change (3M)',
        '6m': 'Change (6M)',
        '1y': 'Change (1Y)',
        '5y': 'Change (5Y)',
    };
    return rangeLabels[range] || 'Change (3M)';
}

function populateChartYearSelects(): void {
    const yf = document.getElementById('chart-year-from') as HTMLSelectElement | null;
    const yt = document.getElementById('chart-year-to') as HTMLSelectElement | null;
    if (!yf || !yt) return;
    const currentY = new Date().getFullYear();
    const minY = 1990;
    const parts: string[] = ['<option value="">—</option>'];
    for (let i = currentY; i >= minY; i--) {
        parts.push(`<option value="${i}">${i}</option>`);
    }
    const html = parts.join('');
    yf.innerHTML = html;
    yt.innerHTML = html;
}

function getRecordTimestamp<T, K extends keyof T>(
    record: T,
    dateFields: ReadonlyArray<K>
): number {
    for (const field of dateFields) {
        const rawValue = record[field] as unknown;
        if (typeof rawValue !== "string" || !rawValue) {
            continue;
        }

        const parsed = Date.parse(rawValue);
        if (!Number.isNaN(parsed)) {
            return parsed;
        }
    }

    return Number.NEGATIVE_INFINITY;
}

function sortRecordsByDateDesc<T, K extends keyof T>(
    records: T[],
    dateFields: ReadonlyArray<K>
): T[] {
    return [...records].sort((a, b) =>
        getRecordTimestamp(b, dateFields) - getRecordTimestamp(a, dateFields)
    );
}

// Congress trades pagination state
let allCongressTrades: CongressTickerTrade[] = [];
let congressTradesCurrentPage: number = 0;
const congressTradesPerPage: number = 20;
let allInsiderTrades: InsiderTrade[] = [];
let insiderTradesCurrentPage: number = 0;
const insiderTradesPerPage: number = 20;

// ETF trades pagination state
let allEtfTrades: EtfHoldingTrade[] = [];
let etfTradesCurrentPage: number = 0;
const etfTradesPerPage: number = 20;
let loadSeq: number = 0;
/** Bumps on each chart fetch so superseded requests do not hide the loading spinner. */
let chartLoadSeq: number = 0;

function showChartLoadingSpinner(): void {
    const el = document.getElementById('chart-loading');
    if (!el) return;
    el.classList.remove('hidden');
    el.style.removeProperty('display');
}

function hideChartLoadingSpinner(): void {
    const el = document.getElementById('chart-loading');
    if (!el) return;
    el.classList.add('hidden');
}

function shouldApplyChartResult(myChartSeq: number, tickerForLoad: string, expectedLoadSeq?: number): boolean {
    if (myChartSeq !== chartLoadSeq) {
        return false;
    }
    if (expectedLoadSeq !== undefined && isStaleLoad(expectedLoadSeq, tickerForLoad)) {
        return false;
    }
    return true;
}

// Initialize page on load
document.addEventListener('DOMContentLoaded', function (): void {
    // Get ticker from URL query parameter
    const urlParams = new URLSearchParams(window.location.search);
    const tickerParam = urlParams.get('ticker');

    // If ticker in URL, load it
    if (tickerParam) {
        currentTicker = tickerParam.toUpperCase();
        loadTickerData(currentTicker);
    } else {
        // Show placeholder
        showPlaceholder();
    }

    // Set up ticker search (Enter to search by company name or symbol)
    setupTickerSearch();

    // Set up chart controls
    const checkbox = document.getElementById('solid-lines-checkbox') as HTMLInputElement | null;
    if (checkbox) {
        checkbox.addEventListener('change', function (this: HTMLInputElement): void {
            if (currentTicker) {
                const rangeSelector = document.getElementById('chart-range-selector') as HTMLSelectElement | null;
                const range = rangeSelector ? rangeSelector.value : '3m';
                loadAndRenderChart(currentTicker, this.checked, range);
            }
        });
    }

    // Set up range selector
    const rangeSelector = document.getElementById('chart-range-selector') as HTMLSelectElement | null;
    if (rangeSelector) {
        rangeSelector.addEventListener('change', function (this: HTMLSelectElement): void {
            if (currentTicker) {
                const checkbox = document.getElementById('solid-lines-checkbox') as HTMLInputElement | null;
                const useSolid = checkbox ? checkbox.checked : false;
                loadAndRenderChart(currentTicker, useSolid, this.value);
            }
        });
    }

    populateChartYearSelects();
    const reloadChartFromDataControls = (): void => {
        if (!currentTicker) return;
        const rs = document.getElementById('chart-range-selector') as HTMLSelectElement | null;
        const range = rs ? rs.value : '3m';
        const cb = document.getElementById('solid-lines-checkbox') as HTMLInputElement | null;
        const useSolid = cb ? cb.checked : false;
        loadAndRenderChart(currentTicker, useSolid, range);
    };
    const chartPriceSourceEl = document.getElementById('chart-price-source') as HTMLSelectElement | null;
    const chartYearFromEl = document.getElementById('chart-year-from') as HTMLSelectElement | null;
    const chartYearToEl = document.getElementById('chart-year-to') as HTMLSelectElement | null;
    if (chartPriceSourceEl) {
        chartPriceSourceEl.addEventListener('change', reloadChartFromDataControls);
    }
    if (chartYearFromEl) {
        chartYearFromEl.addEventListener('change', reloadChartFromDataControls);
    }
    if (chartYearToEl) {
        chartYearToEl.addEventListener('change', reloadChartFromDataControls);
    }

    // Set up signals refresh button
    const signalsRefreshBtn = document.getElementById('signals-refresh-btn') as HTMLButtonElement | null;
    if (signalsRefreshBtn) {
        signalsRefreshBtn.addEventListener('click', () => {
            if (currentTicker) {
                loadSignals(currentTicker, true);
            }
        });
    }

    initModelSelect();
    initSignalsModelSelect();

    // Reload ticker data when global fund selector changes
    window.addEventListener('fundChanged', () => {
        if (currentTicker) {
            loadTickerData(currentTicker);
        } else {
            showPlaceholder();
        }
    });
});

// Search result interface
interface TickerSearchResult {
    symbol: string;
    name: string;
    exchange: string;
    type: string;
}

interface TickerSearchResponse {
    results: TickerSearchResult[];
    exact_match: boolean;
    error?: string;
}

// Set up ticker search with Enter-to-search (company name or symbol via yfinance)
function setupTickerSearch(): void {
    const input = document.getElementById('ticker-search-input') as HTMLInputElement | null;
    const resultsPanel = document.getElementById('ticker-search-results') as HTMLDivElement | null;
    const spinner = document.getElementById('ticker-search-spinner') as HTMLDivElement | null;

    if (!input || !resultsPanel) {
        console.error('Ticker search: could not find input or results panel');
        return;
    }

    // Set initial value from URL
    const urlParams = new URLSearchParams(window.location.search);
    const tickerParam = urlParams.get('ticker');
    if (tickerParam) {
        input.value = tickerParam.toUpperCase();
    }

    // Select a ticker from search results
    function selectTicker(symbol: string): void {
        input!.value = symbol;
        hideResults();

        // Update URL without reload
        const url = new URL(window.location.href);
        url.searchParams.set('ticker', symbol);
        window.history.pushState({}, '', url);

        currentTicker = symbol;
        loadTickerData(symbol);
    }

    function hideResults(): void {
        resultsPanel!.classList.add('hidden');
        resultsPanel!.innerHTML = '';
    }

    function showResults(results: TickerSearchResult[]): void {
        resultsPanel!.innerHTML = '';

        if (results.length === 0) {
            const noResults = document.createElement('div');
            noResults.className = 'px-4 py-3 text-text-secondary text-sm';
            noResults.textContent = 'No results found. Try a different search term.';
            resultsPanel!.appendChild(noResults);
            resultsPanel!.classList.remove('hidden');
            return;
        }

        results.forEach((result, idx) => {
            const item = document.createElement('div');
            item.className = 'px-4 py-3 cursor-pointer hover:bg-dashboard-background border-b border-border last:border-b-0 flex items-center gap-3';
            item.dataset.symbol = result.symbol;

            // Symbol badge
            const symbolSpan = document.createElement('span');
            symbolSpan.className = 'font-semibold text-accent bg-accent/10 px-2 py-0.5 rounded text-sm min-w-[60px] text-center';
            symbolSpan.textContent = result.symbol;
            item.appendChild(symbolSpan);

            // Name and exchange wrapper
            const infoDiv = document.createElement('div');
            infoDiv.className = 'flex flex-col min-w-0';

            const nameSpan = document.createElement('span');
            nameSpan.className = 'text-text-primary text-sm truncate';
            nameSpan.textContent = result.name || result.symbol;
            infoDiv.appendChild(nameSpan);

            if (result.exchange || result.type) {
                const metaSpan = document.createElement('span');
                metaSpan.className = 'text-text-secondary text-xs';
                const parts: string[] = [];
                if (result.exchange) parts.push(result.exchange);
                if (result.type) parts.push(result.type);
                metaSpan.textContent = parts.join(' \u00b7 ');
                infoDiv.appendChild(metaSpan);
            }

            item.appendChild(infoDiv);

            item.addEventListener('mousedown', (e) => {
                e.preventDefault();
                selectTicker(result.symbol);
            });

            // Keyboard highlight support
            item.dataset.idx = String(idx);
            resultsPanel!.appendChild(item);
        });

        resultsPanel!.classList.remove('hidden');
    }

    // Perform search via API
    async function performSearch(query: string): Promise<void> {
        if (!query) return;

        // Show spinner
        if (spinner) spinner.classList.remove('hidden');

        try {
            let searchUrl = `/api/v2/ticker/search?q=${encodeURIComponent(query)}`;
            searchUrl = appendFundParam(searchUrl);

            const response = await fetch(searchUrl, { credentials: 'include' });
            if (!response.ok) {
                throw new Error(`Search failed: ${response.status}`);
            }

            const data: TickerSearchResponse = await response.json();

            // If exact match, go directly to that ticker
            if (data.exact_match && data.results.length > 0) {
                selectTicker(data.results[0].symbol);
                return;
            }

            // Show results panel
            showResults(data.results);
        } catch (error) {
            console.error('Ticker search error:', error);
            resultsPanel!.innerHTML = '';
            const errDiv = document.createElement('div');
            errDiv.className = 'px-4 py-3 text-theme-error-text text-sm';
            errDiv.textContent = 'Search failed. Please try again.';
            resultsPanel!.appendChild(errDiv);
            resultsPanel!.classList.remove('hidden');
        } finally {
            if (spinner) spinner.classList.add('hidden');
        }
    }

    // Keyboard navigation state
    let selectedIdx = -1;

    // Handle Enter and keyboard nav
    input.addEventListener('keydown', (e) => {
        const items = resultsPanel!.querySelectorAll('[data-symbol]');

        if (e.key === 'ArrowDown') {
            e.preventDefault();
            if (!resultsPanel!.classList.contains('hidden') && items.length > 0) {
                selectedIdx = Math.min(selectedIdx + 1, items.length - 1);
                updateHighlight(items);
            }
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            if (!resultsPanel!.classList.contains('hidden') && items.length > 0) {
                selectedIdx = Math.max(selectedIdx - 1, -1);
                updateHighlight(items);
            }
        } else if (e.key === 'Enter') {
            e.preventDefault();
            // If an item is highlighted in results, select it
            if (selectedIdx >= 0 && items[selectedIdx]) {
                const sym = (items[selectedIdx] as HTMLElement).dataset.symbol || '';
                selectTicker(sym);
            } else {
                // Perform search
                const query = input.value.trim();
                if (query) {
                    selectedIdx = -1;
                    performSearch(query);
                }
            }
        } else if (e.key === 'Escape') {
            hideResults();
            selectedIdx = -1;
        }
    });

    function updateHighlight(items: NodeListOf<Element>): void {
        items.forEach((item, idx) => {
            if (idx === selectedIdx) {
                item.classList.add('bg-dashboard-background');
            } else {
                item.classList.remove('bg-dashboard-background');
            }
        });
        if (selectedIdx >= 0 && items[selectedIdx]) {
            items[selectedIdx].scrollIntoView({ block: 'nearest' });
        }
    }

    // Hide results when clicking outside
    document.addEventListener('click', (e) => {
        if (!input.contains(e.target as Node) && !resultsPanel!.contains(e.target as Node)) {
            hideResults();
            selectedIdx = -1;
        }
    });
}

function initModelSelect(): void {
    const select = document.getElementById('ticker-model-select') as HTMLSelectElement | null;
    if (!select) return;

    select.addEventListener('change', () => {
        selectedModel = select.value;
        updateContextUsage();
        saveModelPreference(selectedModel);
        syncModelSelects('ticker');
    });

    loadModelOptions();
}

function initSignalsModelSelect(): void {
    const select = document.getElementById('signals-model-select') as HTMLSelectElement | null;
    if (!select) return;

    select.addEventListener('change', () => {
        syncModelSelects('signals');
    });

    loadSignalsModelOptions();
}

function syncModelSelects(source: 'ticker' | 'signals'): void {
    if (modelSyncInProgress) return;
    modelSyncInProgress = true;

    const tickerSelect = document.getElementById('ticker-model-select') as HTMLSelectElement | null;
    const signalsSelect = document.getElementById('signals-model-select') as HTMLSelectElement | null;

    if (source === 'ticker' && tickerSelect && signalsSelect) {
        const nextValue = tickerSelect.value;
        if (nextValue && Array.from(signalsSelect.options).some(option => option.value === nextValue)) {
            signalsSelect.value = nextValue;
        }
    }

    if (source === 'signals' && signalsSelect && tickerSelect) {
        const nextValue = signalsSelect.value;
        if (nextValue && Array.from(tickerSelect.options).some(option => option.value === nextValue)) {
            tickerSelect.value = nextValue;
            selectedModel = nextValue;
            updateContextUsage();
            saveModelPreference(selectedModel);
        }
    }

    modelSyncInProgress = false;
}

async function loadSignalsModelOptions(): Promise<void> {
    const select = document.getElementById('signals-model-select') as HTMLSelectElement | null;
    if (!select) return;

    try {
        const response = await fetch('/api/v2/ai/models', {
            credentials: 'include'
        });

        if (!response.ok) {
            throw new Error('Failed to load AI models');
        }

        const data = await response.json();
        const models = data.models || [];

        select.innerHTML = '';
        if (!Array.isArray(models) || models.length === 0) {
            select.innerHTML = '<option value="">No models available</option>';
            return;
        }

        models.forEach((model: { id: string; name: string; type?: string }) => {
            const option = document.createElement('option');
            option.value = model.id;
            option.textContent = model.name;
            select.appendChild(option);
        });

        const preferredModel = tickerDetailsConfig.defaultModel || '';
        const preferredOption = preferredModel
            ? Array.from(select.options).find(option => option.value === preferredModel)
            : null;

        if (preferredOption) {
            select.value = preferredOption.value;
        } else if (select.options.length > 0) {
            // Select the first model by default
            select.value = select.options[0].value;
        }
    } catch (error) {
        console.error('Error loading signals AI models:', error);
        select.innerHTML = '<option value="">Error loading models</option>';
    }
}

function saveModelPreference(model: string): void {
    if (!model) return;

    fetch('/api/settings/ai_model', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...getCsrfHeaders() },
        body: JSON.stringify({ model: model })
    }).catch((err: Error) => {
        console.error('Error saving model preference:', err);
    });
}

async function loadModelOptions(): Promise<void> {
    const select = document.getElementById('ticker-model-select') as HTMLSelectElement | null;
    if (!select) return;

    try {
        const response = await fetch('/api/v2/ai/models', {
            credentials: 'include'
        });

        if (!response.ok) {
            throw new Error('Failed to load AI models');
        }

        const data = await response.json();
        const models = data.models || [];

        select.innerHTML = '';
        if (!Array.isArray(models) || models.length === 0) {
            select.innerHTML = '<option value="">No models available</option>';
            return;
        }

        models.forEach((model: { id: string; name: string; type?: string }) => {
            const option = document.createElement('option');
            option.value = model.id;
            option.textContent = model.name;
            select.appendChild(option);
        });

        if (selectedModel) {
            select.value = selectedModel;
        } else if (select.options.length > 0) {
            select.value = select.options[0].value;
            selectedModel = select.value;
        }

        updateContextUsage();
    } catch (error) {
        console.error('Error loading AI models:', error);
        select.innerHTML = '<option value="">Error loading models</option>';
    }
}



// Load all ticker data
async function loadTickerData(ticker: string): Promise<void> {
    const seq = ++loadSeq;
    allCongressTrades = [];
    congressTradesCurrentPage = 0;
    allInsiderTrades = [];
    insiderTradesCurrentPage = 0;
    allEtfTrades = [];
    etfTradesCurrentPage = 0;

    hideAllSections();
    showLoading();
    hideTickerError();
    hidePlaceholder();
    contextCharCount = 0;
    updateContextUsage();

    try {
        const response = await fetch(appendFundParam(`/api/v2/ticker/info?ticker=${encodeURIComponent(ticker)}`), {
            credentials: 'include'
        });
        if (isStaleLoad(seq, ticker)) return;

        if (!response.ok) {
            const errorData: ErrorResponse = await response.json();
            throw new Error(errorData.error || 'Failed to load ticker data');
        }

        const data: TickerInfoResponse = await response.json();
        if (isStaleLoad(seq, ticker)) return;

        // Render all sections
        if (data.basic_info) {
            renderBasicInfo(data.basic_info);
            renderExternalLinks(data.basic_info);
        }
        if (data.portfolio_data) {
            renderTickerPortfolioData(data.portfolio_data);
        }
        if (data.research_articles) {
            renderResearchArticles(data.research_articles);
        }
        if (data.social_sentiment) {
            renderSocialSentiment(data.social_sentiment);
        }
        if (data.congress_trades) {
            renderCongressTickerTrades(data.congress_trades);
        }
        if (data.insider_trades) {
            renderInsiderTrades(data.insider_trades);
        }
        if (data.watchlist_status) {
            renderWatchlistStatus(data.watchlist_status);
        }

        // Load signals
        await loadSignals(ticker, false, seq);
        if (isStaleLoad(seq, ticker)) return;

        // Load AI analysis
        await loadTickerAnalysis(ticker, seq);
        if (isStaleLoad(seq, ticker)) return;
        await loadTickerAnalysisContext(ticker, seq);
        if (isStaleLoad(seq, ticker)) return;

        // Load and render chart
        populateChartYearSelects();
        const checkbox = document.getElementById('solid-lines-checkbox') as HTMLInputElement | null;
        const useSolid = checkbox ? checkbox.checked : false;
        const rangeSelector = document.getElementById('chart-range-selector') as HTMLSelectElement | null;
        const range = rangeSelector ? rangeSelector.value : '3m';
        loadAndRenderChart(ticker, useSolid, range, seq);

        hideLoading();
    } catch (error) {
        if (isStaleLoad(seq, ticker)) return;
        console.error('Error loading ticker data:', error);
        const errorMessage = error instanceof Error ? error.message : 'Unknown error';
        showTickerError(errorMessage);
        hideLoading();
    }
}

// Render basic info section
function renderBasicInfo(basicInfo: BasicInfo): void {
    if (!basicInfo) {
        return;
    }

    const section = document.getElementById('basic-info-section');
    if (!section) return;

    section.classList.remove('hidden');

    const companyName = document.getElementById('company-name');
    const tickerSymbol = document.getElementById('ticker-symbol');
    const tickerLogo = document.getElementById('ticker-logo') as HTMLImageElement | null;
    const sector = document.getElementById('sector');
    const industry = document.getElementById('industry');
    const currency = document.getElementById('currency');
    const exchangeInfo = document.getElementById('exchange-info');

    if (companyName) companyName.textContent = basicInfo.company_name || 'N/A';
    if (tickerSymbol) tickerSymbol.textContent = basicInfo.ticker || '';

    // Display logo if available (larger size for ticker details page - 160px)
    if (tickerLogo) {
        const ticker = basicInfo.ticker || '';
        const isAltLogo = !!basicInfo.use_alt_logo;
        const placeholder = 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" width="256" height="256"%3E%3C/svg%3E';

        // Clear any existing error handlers and reset state
        tickerLogo.onerror = null;
        tickerLogo.onload = null;

        // Set alt text
        tickerLogo.alt = `${ticker} logo`;

        if (basicInfo.logo_url) {
            // For default Parqet URLs, upscale to 256; alt-logo URLs pass through as-is
            const primaryUrl = isAltLogo
                ? basicInfo.logo_url
                : basicInfo.logo_url.replace('size=64', 'size=256');

            // Build fallback chain depending on logo source:
            //   Alt (Clearbit)  -> Parqet candidates -> Yahoo candidates -> placeholder
            //   Default (Parqet) -> Yahoo candidates -> placeholder
            const cleanTicker = ticker.replace(/\s+/g, '').toUpperCase();
            const baseNoSuffix = cleanTicker.replace(/\.(TO|V|CN|TSX|TSXV|NE|NEO)$/i, '');
            const classShareMatch = baseNoSuffix.match(/^([A-Z0-9]+)\.([A-Z])$/);
            const normalizedTicker = classShareMatch
                ? `${classShareMatch[1]}-${classShareMatch[2]}`
                : baseNoSuffix;

            // Include likely TSX variant for class-share tickers without explicit suffix (e.g. TECK.B -> TECK-B.TO)
            const parqetCandidates = [normalizedTicker];
            if (classShareMatch && !cleanTicker.match(/\.(TO|V|CN|TSX|TSXV|NE|NEO)$/i)) {
                parqetCandidates.push(`${normalizedTicker}.TO`);
            }

            const fallbackUrls: string[] = [];
            if (isAltLogo) {
                for (const candidate of parqetCandidates) {
                    fallbackUrls.push(
                        `https://assets.parqet.com/logos/symbol/${candidate}?format=png&size=256`
                    );
                }
            }
            for (const candidate of parqetCandidates) {
                fallbackUrls.push(
                    `https://s.yimg.com/cv/apiv2/default/images/logos/${candidate}.png`
                );
            }

            let fallbackIndex = 0;
            tickerLogo.onerror = function () {
                if (fallbackIndex < fallbackUrls.length) {
                    tickerLogo.src = fallbackUrls[fallbackIndex];
                    fallbackIndex++;
                } else {
                    tickerLogo.src = placeholder;
                    tickerLogo.onerror = null;
                }
            };

            // Set src AFTER error handler is attached
            tickerLogo.classList.remove('hidden');
            tickerLogo.src = primaryUrl;
        } else {
            // No logo URL provided, show placeholder
            tickerLogo.classList.remove('hidden');
            tickerLogo.src = placeholder;
        }
    }

    if (sector) sector.textContent = basicInfo.sector || 'N/A';
    if (industry) industry.textContent = basicInfo.industry || 'N/A';
    if (currency) currency.textContent = basicInfo.currency || 'USD';

    // P/E Ratio
    const peRatio = document.getElementById('pe-ratio');
    if (peRatio) {
        if (basicInfo.trailing_pe && basicInfo.trailing_pe > 0) {
            peRatio.textContent = basicInfo.trailing_pe.toFixed(2);
        } else {
            peRatio.textContent = 'N/A';
        }
    }

    if (exchangeInfo) {
        if (basicInfo.exchange && basicInfo.exchange !== 'N/A') {
            exchangeInfo.textContent = `Exchange: ${basicInfo.exchange}`;
            exchangeInfo.style.display = 'block';
        } else {
            exchangeInfo.style.display = 'none';
        }
    }

    // Display company/fund description if available
    const descriptionContainer = document.getElementById('company-description-container');
    const descriptionElement = document.getElementById('company-description');

    if (descriptionContainer && descriptionElement) {
        if (basicInfo.description && basicInfo.description.trim()) {
            descriptionElement.textContent = basicInfo.description.trim();
            descriptionContainer.classList.remove('hidden');
        } else {
            descriptionContainer.classList.add('hidden');
        }
    }
}

// Render external links
async function renderExternalLinks(basicInfo: BasicInfo): Promise<void> {
    if (!basicInfo || !basicInfo.ticker) {
        return;
    }

    try {
        const exchange = basicInfo.exchange || null;
        const response = await fetch(appendFundParam(`/api/v2/ticker/external-links?ticker=${encodeURIComponent(basicInfo.ticker)}${exchange ? `&exchange=${encodeURIComponent(exchange)}` : ''}`), {
            credentials: 'include'
        });

        if (!response.ok) {
            return;
        }

        const links: Record<string, string> = await response.json();
        const grid = document.getElementById('external-links-grid');
        if (!grid) return;

        grid.innerHTML = '';

        Object.entries(links).forEach(([name, url]) => {
            const link = document.createElement('a');
            link.href = url;
            link.target = '_blank';
            link.rel = 'noopener noreferrer';
            link.className = 'flex items-center justify-center gap-2 px-4 py-2 text-sm font-medium text-text-primary bg-dashboard-background border border-border rounded-lg hover:bg-dashboard-hover hover:text-accent hover:border-accent transition-colors duration-200';

            // Create icon element
            const icon = document.createElement('i');
            icon.className = 'fas fa-external-link-alt text-xs text-text-tertiary';

            // Create text span
            const text = document.createElement('span');
            text.textContent = name;

            link.appendChild(text);
            link.appendChild(icon);
            grid.appendChild(link);
        });

        const section = document.getElementById('external-links-section');
        if (section && Object.keys(links).length > 0) {
            section.classList.remove('hidden');
        }
    } catch (error) {
        console.error('Error loading external links:', error);
    }
}

/** Unrealized P&L as % of cost basis; em dash when basis is unusable. */
function formatPositionPnlPct(costBasis: number | undefined, pnl: number | undefined): string {
    const cb = Number(costBasis);
    const p = Number(pnl);
    if (!Number.isFinite(cb) || cb <= 0) {
        return "—";
    }
    if (!Number.isFinite(p)) {
        return "—";
    }
    const pct = (p / cb) * 100;
    const sign = pct >= 0 ? "+" : "";
    return `${sign}${pct.toFixed(2)}%`;
}

// Render portfolio data
function renderTickerPortfolioData(portfolioData: TickerPortfolioData): void {
    if (!portfolioData || (!portfolioData.has_positions && !portfolioData.has_trades)) {
        return;
    }

    const section = document.getElementById('portfolio-section');
    if (!section) return;

    section.classList.remove('hidden');

    // Render positions
    if (portfolioData.has_positions && portfolioData.positions && portfolioData.positions.length > 0) {
        const tbody = document.getElementById('positions-tbody');
        if (tbody) {
            tbody.innerHTML = '';

            // Get latest position per fund
            const latestTickerPositions: Record<string, TickerPosition> = {};
            portfolioData.positions.forEach(pos => {
                const fund = pos.fund || 'Unknown';
                if (
                    !latestTickerPositions[fund]
                    || getRecordTimestamp(pos, ["date"]) > getRecordTimestamp(latestTickerPositions[fund], ["date"])
                ) {
                    latestTickerPositions[fund] = pos;
                }
            });

            Object.values(latestTickerPositions).forEach(pos => {
                const pnlPct = formatPositionPnlPct(pos.cost_basis, pos.pnl);
                const pnlPctClass =
                    pnlPct === "—"
                        ? "text-text-secondary"
                        : pos.pnl !== undefined && pos.pnl >= 0
                            ? "text-theme-success-text"
                            : "text-theme-error-text";
                const row = document.createElement('tr');
                row.innerHTML = `
                    <td class="px-6 py-4 whitespace-nowrap text-sm text-text-primary">${pos.fund || 'N/A'}</td>
                    <td class="px-6 py-4 whitespace-nowrap text-sm text-text-primary">${formatNumber(pos.shares || 0, 2)}</td>
                    <td class="px-6 py-4 whitespace-nowrap text-sm text-text-primary">${formatCurrency(pos.price || 0)}</td>
                    <td class="px-6 py-4 whitespace-nowrap text-sm text-text-primary">${formatCurrency(pos.cost_basis || 0)}</td>
                    <td class="px-6 py-4 whitespace-nowrap text-sm ${(pos.pnl || 0) >= 0 ? 'text-theme-success-text' : 'text-theme-error-text'}">${formatCurrency(pos.pnl || 0)}</td>
                    <td class="px-6 py-4 whitespace-nowrap text-sm ${pnlPctClass}">${pnlPct}</td>
                    <td class="px-6 py-4 whitespace-nowrap text-sm text-text-secondary">${formatDate(pos.date)}</td>
                `;
                tbody.appendChild(row);
            });

            const container = document.getElementById('positions-container');
            if (container) container.style.display = 'block';
        }
    } else {
        const container = document.getElementById('positions-container');
        if (container) container.style.display = 'none';
    }

    // Render trades
    if (portfolioData.has_trades && portfolioData.trades && portfolioData.trades.length > 0) {
        const tbody = document.getElementById('trades-tbody');
        if (tbody) {
            tbody.innerHTML = '';

            const sortedTrades = sortRecordsByDateDesc(portfolioData.trades, ["date"]);
            sortedTrades.slice(0, 20).forEach(trade => {
                const row = document.createElement('tr');
                row.innerHTML = `
                    <td class="px-6 py-4 whitespace-nowrap text-sm text-text-primary">${formatDate(trade.date)}</td>
                    <td class="px-6 py-4 whitespace-nowrap text-sm text-text-primary">${inferTickerTradeAction(trade)}</td>
                    <td class="px-6 py-4 whitespace-nowrap text-sm text-text-primary">${formatNumber(trade.shares || 0, 2)}</td>
                    <td class="px-6 py-4 whitespace-nowrap text-sm text-text-primary">${formatCurrency(trade.price || 0)}</td>
                    <td class="px-6 py-4 whitespace-nowrap text-sm text-text-primary">${trade.fund || 'N/A'}</td>
                    <td class="px-6 py-4 text-sm text-text-secondary">${(trade.reason || 'N/A').substring(0, 50)}</td>
                `;
                tbody.appendChild(row);
            });
        }
    }
}

// Load and render chart
async function loadAndRenderChart(
    ticker: string,
    useSolid: boolean,
    range: string = '3m',
    expectedLoadSeq?: number
): Promise<void> {
    const myChartSeq = ++chartLoadSeq;
    const chartLoading = document.getElementById('chart-loading');
    const chartContainer = document.getElementById('chart-container');

    if (!chartContainer || !chartLoading) return;

    // Clear any existing chart and show loading indicator (must reset inline display from prior loads)
    chartContainer.innerHTML = '';
    showChartLoadingSpinner();

    // Show chart section (but with loading indicator)
    const chartSection = document.getElementById('chart-section');
    if (chartSection) chartSection.classList.remove('hidden');

    try {
        // Detect actual theme from page
        const htmlElement = document.documentElement;
        const dataTheme = htmlElement.getAttribute('data-theme') || 'system';
        let theme: string = 'light'; // default

        // Custom dark themes map to dark for backend compatibility.
        if (dataTheme === 'midnight-tokyo' || dataTheme === 'abyss') {
            theme = 'dark';
        } else if (dataTheme === 'dark') {
            theme = 'dark';
        } else if (dataTheme === 'light') {
            theme = 'light';
        } else if (dataTheme === 'system') {
            // For 'system', check if page is actually in dark mode via CSS
            const bodyBg = window.getComputedStyle(document.body).backgroundColor;
            // Check for dark mode background colors
            const isDark = bodyBg && (
                bodyBg.includes('rgb(31, 41, 55)') ||  // --bg-primary dark
                bodyBg.includes('rgb(17, 24, 39)') ||  // --bg-secondary dark  
                bodyBg.includes('rgb(55, 65, 81)')     // --bg-tertiary dark
            );
            theme = isDark ? 'dark' : 'light';
        }

        console.log('Detected theme:', theme, 'from data-theme:', dataTheme);

        const response = await fetch(appendFundParam(`/api/v2/ticker/chart?ticker=${encodeURIComponent(ticker)}&use_solid=${useSolid}&theme=${encodeURIComponent(theme)}&range=${encodeURIComponent(range)}${buildTickerChartExtraQuery()}`), {
            credentials: 'include'
        });
        if (!shouldApplyChartResult(myChartSeq, ticker, expectedLoadSeq)) return;

        // Check if response is JSON
        const contentType = response.headers.get('content-type');
        const isJson = contentType && contentType.includes('application/json');

        if (!response.ok) {
            let errorMessage = `Failed to load chart (${response.status})`;
            if (isJson) {
                try {
                    const errorData: ErrorResponse = await response.json();
                    errorMessage = errorData.error || errorMessage;
                } catch (e) {
                    // If JSON parsing fails, use default message
                }
            } else {
                // Response is HTML (likely an error page)
                errorMessage = `Server error: ${response.status} ${response.statusText}`;
            }
            throw new Error(errorMessage);
        }

        if (!isJson) {
            throw new Error('Server returned non-JSON response. Please check your authentication.');
        }

        const chartData: ChartData = await response.json();
        if (!shouldApplyChartResult(myChartSeq, ticker, expectedLoadSeq)) return;

        // Validate chart data structure
        if (!chartData || !chartData.data || !chartData.layout) {
            throw new Error('Invalid chart data received from server');
        }

        // Render with Plotly
        const Plotly = (window as any).Plotly;
        if (Plotly) {
            Plotly.newPlot('chart-container', chartData.data, chartData.layout, { responsive: true });
        }
        if (!shouldApplyChartResult(myChartSeq, ticker, expectedLoadSeq)) return;

        // Hide loading indicator AFTER successful rendering
        hideChartLoadingSpinner();

        // Load price history for metrics
        loadPriceHistoryMetrics(ticker, range, expectedLoadSeq);

        // Load ETF holding trades for table
        loadEtfTrades(ticker, range, expectedLoadSeq);
    } catch (error) {
        if (!shouldApplyChartResult(myChartSeq, ticker, expectedLoadSeq)) return;
        console.error('Error loading chart:', error);
        // Hide loading indicator
        hideChartLoadingSpinner();
        // Show error message to user
        const errorMessage = error instanceof Error ? error.message : 'Unknown error';
        showTickerError(`Failed to load chart: ${errorMessage}`);
        // Hide chart section on error
        const chartSection = document.getElementById('chart-section');
        if (chartSection) chartSection.classList.add('hidden');
    }
}

// Load ETF holding trades for table
async function loadEtfTrades(
    ticker: string,
    range: string = '3m',
    expectedLoadSeq?: number
): Promise<void> {
    try {
        const response = await fetch(appendFundParam(`/api/v2/ticker/etf-trades?ticker=${encodeURIComponent(ticker)}&range=${encodeURIComponent(range)}${buildTickerYearQuery()}`), {
            credentials: 'include'
        });
        if (isStaleLoad(expectedLoadSeq, ticker)) return;

        if (!response.ok) {
            throw new Error(`Failed to load ETF trades (${response.status})`);
        }

        const data = await response.json();
        if (isStaleLoad(expectedLoadSeq, ticker)) return;
        renderEtfTrades((data && data.data) ? data.data : []);
    } catch (error) {
        if (isStaleLoad(expectedLoadSeq, ticker)) return;
        console.error('Error loading ETF trades:', error);
        renderEtfTrades([]);
    }
}

function renderEtfTrades(trades: EtfHoldingTrade[]): void {
    const section = document.getElementById('etf-trades-section');
    const emptyState = document.getElementById('etf-trades-empty');
    const countEl = document.getElementById('etf-trades-count');

    if (!section || !emptyState || !countEl) return;

    const hasTrades = Array.isArray(trades) && trades.length > 0;

    if (!hasTrades) {
        section.classList.remove('hidden');
        emptyState.classList.remove('hidden');
        countEl.textContent = '0 records';
        allEtfTrades = [];
        etfTradesCurrentPage = 0;
        const tbody = document.getElementById('etf-trades-tbody');
        if (tbody) tbody.innerHTML = '';
        const pagination = document.getElementById('etf-trades-pagination');
        if (pagination) pagination.innerHTML = '';
        return;
    }

    emptyState.classList.add('hidden');
    section.classList.remove('hidden');
    allEtfTrades = sortRecordsByDateDesc(trades, ["trade_date"]);
    etfTradesCurrentPage = 0;
    renderEtfTradesPage();
}

function renderEtfTradesPage(): void {
    const tbody = document.getElementById('etf-trades-tbody');
    const countEl = document.getElementById('etf-trades-count');

    if (!tbody || !allEtfTrades || allEtfTrades.length === 0) return;

    const totalPages = Math.ceil(allEtfTrades.length / etfTradesPerPage);
    const start = (etfTradesCurrentPage * etfTradesPerPage) + 1;
    const end = Math.min((etfTradesCurrentPage + 1) * etfTradesPerPage, allEtfTrades.length);

    if (countEl) {
        countEl.textContent = `${allEtfTrades.length} record${allEtfTrades.length === 1 ? '' : 's'} (Showing ${start}-${end})`;
    }

    tbody.innerHTML = '';

    const startIndex = etfTradesCurrentPage * etfTradesPerPage;
    const endIndex = Math.min(startIndex + etfTradesPerPage, allEtfTrades.length);
    const pageTrades = allEtfTrades.slice(startIndex, endIndex);

    pageTrades.forEach(trade => {
        const row = document.createElement('tr');
        const change = Number(trade.shares_change ?? 0);
        const after = Number(trade.shares_after ?? 0);
        const changeDecimals = Math.abs(change) >= 1 ? 0 : 4;
        const afterDecimals = Math.abs(after) >= 1 ? 0 : 4;
        const changeText = change >= 0 ? `+${formatNumber(change, changeDecimals)}` : formatNumber(change, changeDecimals);
        const tradeType = trade.trade_type || 'N/A';

        row.innerHTML = `
            <td class="px-6 py-4 whitespace-nowrap text-sm text-text-primary">${formatDate(trade.trade_date)}</td>
            <td class="px-6 py-4 whitespace-nowrap text-sm text-text-primary">${trade.etf_ticker || 'N/A'}</td>
            <td class="px-6 py-4 whitespace-nowrap text-sm text-text-primary">${tradeType}</td>
            <td class="px-6 py-4 whitespace-nowrap text-sm text-text-primary text-right">${changeText}</td>
            <td class="px-6 py-4 whitespace-nowrap text-sm text-text-primary text-right">${formatNumber(after, afterDecimals)}</td>
        `;
        tbody.appendChild(row);
    });

    renderEtfTradesPagination();
}

function renderEtfTradesPagination(): void {
    const container = document.getElementById("etf-trades-pagination");
    if (!container) return;

    const totalPages = Math.ceil(allEtfTrades.length / etfTradesPerPage);

    if (totalPages <= 1) {
        container.innerHTML = "";
        return;
    }

    container.innerHTML = "";

    const prevLi = document.createElement("li");
    prevLi.innerHTML = `
        <a href="#" class="flex items-center justify-center px-3 h-8 ms-0 leading-tight text-text-secondary bg-dashboard-surface border border-border rounded-s-lg hover:bg-dashboard-surface-alt hover:text-text-primary ${etfTradesCurrentPage === 0 ? "pointer-events-none opacity-50" : ""}">
            <span class="sr-only">Previous</span>
            <svg class="w-2.5 h-2.5 rtl:rotate-180" aria-hidden="true" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 6 10">
              <path stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 1 1 5l4 4"/>
            </svg>
        </a>
    `;
    prevLi.onclick = (e) => {
        e.preventDefault();
        if (etfTradesCurrentPage > 0) {
            etfTradesCurrentPage--;
            renderEtfTradesPage();
        }
    };
    container.appendChild(prevLi);

    const maxVisiblePages = 7;
    let startPage = Math.max(0, etfTradesCurrentPage - Math.floor(maxVisiblePages / 2));
    let endPage = Math.min(totalPages - 1, startPage + maxVisiblePages - 1);

    if (endPage - startPage < maxVisiblePages - 1) {
        startPage = Math.max(0, endPage - maxVisiblePages + 1);
    }

    if (startPage > 0) {
        const firstLi = document.createElement("li");
        firstLi.innerHTML = `
            <a href="#" class="flex items-center justify-center px-3 h-8 leading-tight text-text-secondary bg-dashboard-surface border border-border hover:bg-dashboard-surface-alt hover:text-text-primary">1</a>
        `;
        firstLi.onclick = (e) => {
            e.preventDefault();
            etfTradesCurrentPage = 0;
            renderEtfTradesPage();
        };
        container.appendChild(firstLi);

        if (startPage > 1) {
            const ellipsisLi = document.createElement("li");
            ellipsisLi.innerHTML = `
                <span class="flex items-center justify-center px-3 h-8 leading-tight text-text-secondary bg-dashboard-surface border border-border">...</span>
            `;
            container.appendChild(ellipsisLi);
        }
    }

    for (let i = startPage; i <= endPage; i++) {
        const pageLi = document.createElement("li");
        pageLi.innerHTML = `
            <a href="#" class="flex items-center justify-center px-3 h-8 leading-tight text-text-secondary bg-dashboard-surface border border-border hover:bg-dashboard-surface-alt hover:text-text-primary ${i === etfTradesCurrentPage ? "bg-accent text-white" : ""}">${i + 1}</a>
        `;
        pageLi.onclick = (e) => {
            e.preventDefault();
            etfTradesCurrentPage = i;
            renderEtfTradesPage();
        };
        container.appendChild(pageLi);
    }

    if (endPage < totalPages - 1) {
        if (endPage < totalPages - 2) {
            const ellipsisLi = document.createElement("li");
            ellipsisLi.innerHTML = `
                <span class="flex items-center justify-center px-3 h-8 leading-tight text-text-secondary bg-dashboard-surface border border-border">...</span>
            `;
            container.appendChild(ellipsisLi);
        }

        const lastLi = document.createElement("li");
        lastLi.innerHTML = `
            <a href="#" class="flex items-center justify-center px-3 h-8 leading-tight text-text-secondary bg-dashboard-surface border border-border hover:bg-dashboard-surface-alt hover:text-text-primary">${totalPages}</a>
        `;
        lastLi.onclick = (e) => {
            e.preventDefault();
            etfTradesCurrentPage = totalPages - 1;
            renderEtfTradesPage();
        };
        container.appendChild(lastLi);
    }

    const nextLi = document.createElement("li");
    nextLi.innerHTML = `
        <a href="#" class="flex items-center justify-center px-3 h-8 leading-tight text-text-secondary bg-dashboard-surface border border-border rounded-e-lg hover:bg-dashboard-surface-alt hover:text-text-primary ${etfTradesCurrentPage === totalPages - 1 ? "pointer-events-none opacity-50" : ""}">
            <span class="sr-only">Next</span>
            <svg class="w-2.5 h-2.5 rtl:rotate-180" aria-hidden="true" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 6 10">
              <path stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M1 9l4-4-4-4"/>
            </svg>
        </a>
    `;
    nextLi.onclick = (e) => {
        e.preventDefault();
        if (etfTradesCurrentPage < totalPages - 1) {
            etfTradesCurrentPage++;
            renderEtfTradesPage();
        }
    };
    container.appendChild(nextLi);
}

// Load price history for metrics
async function loadPriceHistoryMetrics(
    ticker: string,
    range: string = '3m',
    expectedLoadSeq?: number
): Promise<void> {
    if (isStaleLoad(expectedLoadSeq, ticker)) return;

    try {
        // Update metric label based on range or calendar years
        const changeLabelEl = document.getElementById('period-change-label');
        if (changeLabelEl) {
            changeLabelEl.textContent = getChartPeriodChangeLabel(range);
        }

        const response = await fetch(appendFundParam(`/api/v2/ticker/price-history?ticker=${encodeURIComponent(ticker)}&range=${encodeURIComponent(range)}${buildTickerChartExtraQuery()}`), {
            credentials: 'include'
        });
        if (isStaleLoad(expectedLoadSeq, ticker)) return;

        if (!response.ok) {
            return;
        }

        const data: PriceHistoryData = await response.json();
        if (isStaleLoad(expectedLoadSeq, ticker)) return;
        const prices = data.data || [];

        if (prices.length > 0) {
            const priceValues = prices
                .map((point) => Number(point.price || 0))
                .filter((value) => value > 0);

            if (priceValues.length === 0) {
                return;
            }

            const firstPrice = priceValues[0];
            const currentPrice = priceValues[priceValues.length - 1];
            const previousPrice = priceValues.length >= 2 ? priceValues[priceValues.length - 2] : null;
            const periodLow = Math.min(...priceValues);
            const periodHigh = Math.max(...priceValues);
            const priceChange = currentPrice - firstPrice;
            const priceChangePct = firstPrice > 0 ? (priceChange / firstPrice * 100) : 0;
            const dayChangePct = previousPrice && previousPrice > 0
                ? ((currentPrice - previousPrice) / previousPrice) * 100
                : null;

            const firstPriceEl = document.getElementById('first-price');
            const currentPriceEl = document.getElementById('current-price');
            const dayChangeEl = document.getElementById('day-change');
            const rangeLowEl = document.getElementById('range-low');
            const rangeHighEl = document.getElementById('range-high');
            const changeEl = document.getElementById('price-change');

            if (firstPriceEl) firstPriceEl.textContent = formatCurrency(firstPrice);
            if (currentPriceEl) currentPriceEl.textContent = formatCurrency(currentPrice);
            if (rangeLowEl) rangeLowEl.textContent = formatCurrency(periodLow);
            if (rangeHighEl) rangeHighEl.textContent = formatCurrency(periodHigh);
            if (dayChangeEl) {
                if (dayChangePct === null) {
                    dayChangeEl.textContent = "N/A";
                    dayChangeEl.className = "text-xl font-semibold text-text-primary";
                } else {
                    dayChangeEl.textContent = `${dayChangePct >= 0 ? '+' : ''}${dayChangePct.toFixed(2)}%`;
                    dayChangeEl.className = `text-xl font-semibold ${dayChangePct >= 0 ? 'text-theme-success-text' : 'text-theme-error-text'}`;
                }
            }
            if (changeEl) {
                changeEl.textContent = `${priceChangePct >= 0 ? '+' : ''}${priceChangePct.toFixed(2)}%`;
                changeEl.className = `text-xl font-semibold ${priceChangePct >= 0 ? 'text-theme-success-text' : 'text-theme-error-text'}`;
            }
        }
    } catch (error) {
        if (isStaleLoad(expectedLoadSeq, ticker)) return;
        console.error('Error loading price history metrics:', error);
    }
}

// Helper: format a sentiment value into a colored badge HTML string
function sentimentBadge(sentiment: string | undefined): string {
    if (!sentiment) return '';
    const s = sentiment.toLowerCase();
    if (['positive', 'bullish', 'very_bullish'].includes(s)) {
        const label = s === 'very_bullish' ? 'Very Bullish' : 'Bullish';
        return `<span class="inline-flex items-center text-[11px] font-medium px-1.5 py-0.5 rounded bg-theme-success-bg text-theme-success-text border border-theme-success-text"><i class="fas fa-arrow-up mr-0.5 text-[9px]"></i>${label}</span>`;
    }
    if (['negative', 'bearish', 'very_bearish'].includes(s)) {
        const label = s === 'very_bearish' ? 'Very Bearish' : 'Bearish';
        return `<span class="inline-flex items-center text-[11px] font-medium px-1.5 py-0.5 rounded bg-theme-error-bg text-theme-error-text border border-theme-error-text"><i class="fas fa-arrow-down mr-0.5 text-[9px]"></i>${label}</span>`;
    }
    if (['neutral', 'mixed'].includes(s)) {
        return `<span class="inline-flex items-center text-[11px] font-medium px-1.5 py-0.5 rounded bg-theme-warning-bg text-theme-warning-text border border-theme-warning-text">${escapeHtml(sentiment.charAt(0).toUpperCase() + sentiment.slice(1))}</span>`;
    }
    return `<span class="inline-flex items-center text-[11px] font-medium px-1.5 py-0.5 rounded bg-dashboard-surface-alt text-text-primary border border-border">${escapeHtml(sentiment.charAt(0).toUpperCase() + sentiment.slice(1))}</span>`;
}

// Helper: relative time string (e.g. "2d ago", "5h ago")
function relativeTime(dateStr: string | undefined): string {
    if (!dateStr) return '';
    try {
        const date = new Date(dateStr);
        const now = new Date();
        const diffMs = now.getTime() - date.getTime();
        const diffMins = Math.floor(diffMs / 60000);
        if (diffMins < 60) return `${diffMins}m ago`;
        const diffHours = Math.floor(diffMins / 60);
        if (diffHours < 24) return `${diffHours}h ago`;
        const diffDays = Math.floor(diffHours / 24);
        if (diffDays < 30) return `${diffDays}d ago`;
        return formatDate(dateStr);
    } catch {
        return formatDate(dateStr);
    }
}

// Render research articles — compact row-based layout
function renderResearchArticles(articles: ResearchArticle[]): void {
    if (!articles || articles.length === 0) {
        return;
    }

    const section = document.getElementById('research-section');
    if (!section) return;

    section.classList.remove('hidden');

    const countEl = document.getElementById('research-count');
    if (countEl) countEl.textContent = `${articles.length} articles for ${currentTicker} (last 30 days)`;

    const list = document.getElementById('research-articles-list');
    if (!list) return;

    // Build a compact table-like list
    list.innerHTML = '';
    list.className = 'divide-y divide-border rounded-lg border border-border overflow-hidden';

    articles.slice(0, 15).forEach(article => {
        const title = article.title || 'Untitled';
        const summary = article.summary || '';
        const url = sanitizeHttpUrl(article.url || '');
        const source = article.source || '';
        const articleType = article.article_type || '';
        const dateStr = article.published_at || article.fetched_at || '';
        const relTime = relativeTime(dateStr);
        const sentBadge = sentimentBadge(article.sentiment);
        const rawArticleId = String(article.id || Math.random().toString(36).slice(2, 11));
        const cleanedArticleId = rawArticleId.replace(/[^a-zA-Z0-9_-]/g, '') || Math.random().toString(36).slice(2, 11);
        const rowId = `article-row-${cleanedArticleId}`;

        // Truncate summary for the expandable preview
        const previewSummary = summary.length > 300 ? summary.substring(0, 300) + '...' : summary;
        const escapedTitle = escapeHtml(title);
        const escapedSource = escapeHtml(source);
        const escapedArticleType = escapeHtml(articleType);
        const escapedRelTime = escapeHtml(relTime);
        const escapedSummary = escapeHtml(previewSummary);
        const escapedDate = escapeHtml(formatDate(dateStr));

        const row = document.createElement('div');
        row.className = 'bg-dashboard-surface hover:bg-dashboard-surface-alt transition-colors duration-150';

        row.innerHTML = `
            <div class="research-row-toggle flex items-center gap-2 px-3 py-2 cursor-pointer select-none">
                <i id="${rowId}-chevron" class="fas fa-chevron-right text-[10px] text-text-tertiary transition-transform duration-200 w-3 shrink-0"></i>
                ${source ? `<span class="text-[11px] font-medium px-1.5 py-0.5 rounded bg-theme-info-bg text-theme-info-text border border-theme-info-text shrink-0">${escapedSource}</span>` : ''}
                ${articleType ? `<span class="text-[11px] font-medium px-1.5 py-0.5 rounded bg-dashboard-surface-alt text-text-secondary border border-border shrink-0">${escapedArticleType}</span>` : ''}
                ${sentBadge}
                <span class="text-sm font-medium text-text-primary truncate flex-1 min-w-0">${url ? `<a href="${url}" target="_blank" rel="noopener noreferrer" class="hover:text-accent hover:underline" onclick="event.stopPropagation()">${escapedTitle}</a>` : escapedTitle}</span>
                <span class="text-[11px] text-text-tertiary whitespace-nowrap shrink-0 ml-auto">${escapedRelTime}</span>
                ${url ? `<a href="${url}" target="_blank" rel="noopener noreferrer" class="text-text-tertiary hover:text-accent shrink-0 ml-1" onclick="event.stopPropagation()" title="Open article"><i class="fas fa-external-link-alt text-[10px]"></i></a>` : ''}
            </div>
            <div id="${rowId}" class="hidden px-3 pb-3 pt-0">
                <div class="ml-5 pl-3 border-l-2 border-border">
                    ${summary ? `<p class="text-sm text-text-secondary leading-relaxed whitespace-pre-line">${escapedSummary}</p>` : '<p class="text-sm text-text-tertiary italic">No summary available.</p>'}
                    <div class="flex items-center gap-3 mt-2 text-[11px] text-text-tertiary">
                        ${dateStr ? `<span><i class="far fa-calendar-alt mr-1"></i>${escapedDate}</span>` : ''}
                        ${article.sentiment_score != null ? `<span>Score: ${(article.sentiment_score * 100).toFixed(0)}%</span>` : ''}
                        ${article.relevance_score != null ? `<span>Relevance: ${(article.relevance_score * 100).toFixed(0)}%</span>` : ''}
                        ${url ? `<a href="${url}" target="_blank" rel="noopener noreferrer" class="text-accent hover:text-accent-hover hover:underline ml-auto">Read full article <i class="fas fa-arrow-right text-[9px] ml-0.5"></i></a>` : ''}
                    </div>
                </div>
            </div>
        `;

        // Toggle row details and keep chevron aligned with final state.
        row.querySelector('.research-row-toggle')?.addEventListener('click', () => {
            const chevron = document.getElementById(`${rowId}-chevron`);
            const detail = document.getElementById(rowId);
            if (chevron && detail) {
                detail.classList.toggle('hidden');
                if (detail.classList.contains('hidden')) {
                    chevron.style.transform = '';
                } else {
                    chevron.style.transform = 'rotate(90deg)';
                }
            }
        });

        list.appendChild(row);
    });
}

// Render social sentiment
function renderSocialSentiment(sentiment: SocialSentiment): void {
    if (!sentiment) {
        return;
    }

    const section = document.getElementById('sentiment-section');
    if (!section) return;

    section.classList.remove('hidden');

    // Render metrics
    if (sentiment.latest_metrics && sentiment.latest_metrics.length > 0) {
        const tbody = document.getElementById('sentiment-tbody');
        if (tbody) {
            tbody.innerHTML = '';

            const sortedMetrics = sortRecordsByDateDesc(sentiment.latest_metrics, ["created_at"]);
            sortedMetrics.forEach(metric => {
                const row = document.createElement('tr');
                row.innerHTML = `
                    <td class="px-6 py-4 whitespace-nowrap text-sm text-text-primary">${(metric.platform || 'N/A').charAt(0).toUpperCase() + (metric.platform || '').slice(1)}</td>
                    <td class="px-6 py-4 whitespace-nowrap text-sm text-text-primary">${metric.sentiment_label || 'N/A'}</td>
                    <td class="px-6 py-4 whitespace-nowrap text-sm text-text-primary">${(metric.sentiment_score || 0).toFixed(2)}</td>
                    <td class="px-6 py-4 whitespace-nowrap text-sm text-text-primary">${metric.volume || 0}</td>
                    <td class="px-6 py-4 whitespace-nowrap text-sm text-text-primary">${metric.bull_bear_ratio !== null && metric.bull_bear_ratio !== undefined ? metric.bull_bear_ratio.toFixed(2) : 'N/A'}</td>
                    <td class="px-6 py-4 whitespace-nowrap text-sm text-text-secondary">${formatDate(metric.created_at)}</td>
                `;
                tbody.appendChild(row);
            });

            const container = document.getElementById('sentiment-metrics-container');
            if (container) container.style.display = 'block';
        }
    } else {
        const container = document.getElementById('sentiment-metrics-container');
        if (container) container.style.display = 'none';
    }

    // Render alerts
    if (sentiment.alerts && sentiment.alerts.length > 0) {
        const alertsList = document.getElementById('sentiment-alerts-list');
        if (alertsList) {
            alertsList.innerHTML = '';

            sentiment.alerts.forEach(alert => {
                const alertDiv = document.createElement('div');
                const platform = (alert.platform || 'Unknown').charAt(0).toUpperCase() + (alert.platform || '').slice(1);
                const sentimentLabel = alert.sentiment_label || 'N/A';
                const score = (alert.sentiment_score || 0).toFixed(2);

                let alertClass = 'bg-theme-info-bg border-theme-info-text text-theme-info-text';
                if (sentimentLabel === 'EUPHORIC') {
                    alertClass = 'bg-theme-success-bg border-theme-success-text text-theme-success-text';
                } else if (sentimentLabel === 'FEARFUL') {
                    alertClass = 'bg-theme-error-bg border-theme-error-text text-theme-error-text';
                } else if (sentimentLabel === 'BULLISH') {
                    alertClass = 'bg-theme-info-bg border-theme-info-text text-theme-info-text';
                }

                alertDiv.className = `border px-4 py-3 rounded mb-2 ${alertClass}`;
                alertDiv.textContent = `${platform} - ${sentimentLabel} (Score: ${score})`;
                alertsList.appendChild(alertDiv);
            });

            const container = document.getElementById('sentiment-alerts-container');
            if (container) container.style.display = 'block';
        }
    } else {
        const container = document.getElementById('sentiment-alerts-container');
        if (container) container.style.display = 'none';
    }
}

// Render congress trades
function renderCongressTickerTrades(trades: CongressTickerTrade[]): void {
    if (!trades || trades.length === 0) {
        allCongressTrades = [];
        congressTradesCurrentPage = 0;
        const countEl = document.getElementById('congress-count');
        if (countEl) countEl.textContent = 'Found 0 trades by politicians';
        const tbody = document.getElementById('congress-tbody');
        if (tbody) tbody.innerHTML = '';
        const pagination = document.getElementById('congress-pagination');
        if (pagination) pagination.innerHTML = '';
        return;
    }

    // Store all trades for pagination
    allCongressTrades = sortRecordsByDateDesc(trades, ["transaction_date"]);
    congressTradesCurrentPage = 0;

    const section = document.getElementById('congress-section');
    if (!section) return;

    section.classList.remove('hidden');

    // Render the current page
    renderCongressTradesPage();
}

// Render congress trades for current page
function renderCongressTradesPage(): void {
    if (!allCongressTrades || allCongressTrades.length === 0) {
        return;
    }

    const countEl = document.getElementById('congress-count');
    if (countEl) {
        const totalPages = Math.ceil(allCongressTrades.length / congressTradesPerPage);
        const start = (congressTradesCurrentPage * congressTradesPerPage) + 1;
        const end = Math.min((congressTradesCurrentPage + 1) * congressTradesPerPage, allCongressTrades.length);
        countEl.textContent = `Found ${allCongressTrades.length} trades by politicians (Showing ${start}-${end} of ${allCongressTrades.length})`;
    }

    const tbody = document.getElementById('congress-tbody');
    if (!tbody) return;

    tbody.innerHTML = '';

    // Calculate pagination
    const startIndex = congressTradesCurrentPage * congressTradesPerPage;
    const endIndex = Math.min(startIndex + congressTradesPerPage, allCongressTrades.length);
    const pageTrades = allCongressTrades.slice(startIndex, endIndex);

    // Render trades for current page
    pageTrades.forEach(trade => {
        const row = document.createElement('tr');
        const typeValue = (trade.type || 'N/A').toString();
        const typeLower = typeValue.toLowerCase();
        let typeLabel = typeValue;
        let typeClass = 'text-text-primary';

        if (typeLower === 'purchase' || typeLower === 'buy') {
            typeLabel = 'Purchase';
            typeClass = 'bg-theme-success-bg text-theme-success-text';
        } else if (typeLower === 'sale' || typeLower === 'sell') {
            typeLabel = 'Sale';
            typeClass = 'bg-theme-error-bg text-theme-error-text';
        }

        const partyValue = (trade.party || 'N/A').toString();
        const partyLower = partyValue.toLowerCase();
        let partyLabel = partyValue;
        let partyClass = 'text-text-primary';

        if (partyLower.includes('democrat') || partyLower === 'd') {
            partyLabel = '🔵 D';
            partyClass = 'text-theme-info-text font-semibold';
        } else if (partyLower.includes('republican') || partyLower === 'r') {
            partyLabel = '🔴 R';
            partyClass = 'text-theme-error-text font-semibold';
        } else if (partyLower.includes('independent') || partyLower === 'i') {
            partyLabel = '🟣 I';
            partyClass = 'text-theme-warning-text font-semibold';
        }

        const scoreDisplay = trade.score_display || '⚪ N/A';
        const reasoningText = trade.analysis_reasoning_short || trade.analysis_reasoning || 'N/A';
        const reasoningFull = trade.analysis_reasoning || reasoningText;

        row.innerHTML = `
            <td class="px-4 py-4 whitespace-nowrap text-sm text-text-primary">${formatDate(trade.transaction_date)}</td>
            <td class="px-4 py-4 whitespace-nowrap text-sm">
                <span class="inline-flex items-center rounded-full px-2 py-1 text-xs font-semibold ${typeClass}">
                    ${escapeHtml(typeLabel)}
                </span>
            </td>
            <td class="px-4 py-4 whitespace-nowrap text-sm text-text-primary text-right">${escapeHtml(trade.amount || 'N/A')}</td>
            <td class="px-4 py-4 whitespace-nowrap text-sm text-text-primary">${escapeHtml(trade.politician || 'N/A')}</td>
            <td class="px-4 py-4 whitespace-nowrap text-sm text-text-primary">${escapeHtml(trade.chamber || 'N/A')}</td>
            <td class="px-4 py-4 whitespace-nowrap text-sm ${partyClass}">${escapeHtml(partyLabel)}</td>
            <td class="px-4 py-4 whitespace-nowrap text-sm text-text-primary">${escapeHtml(trade.state || 'N/A')}</td>
            <td class="px-4 py-4 whitespace-nowrap text-sm text-text-primary">${escapeHtml(trade.owner || 'N/A')}</td>
            <td class="px-4 py-4 whitespace-nowrap text-sm text-text-primary">${escapeHtml(scoreDisplay)}</td>
            <td class="px-4 py-4 text-sm text-text-secondary max-w-xs truncate" title="${escapeHtml(reasoningFull)}">
                ${escapeHtml(reasoningText)}
            </td>
        `;
        tbody.appendChild(row);
    });

    // Render pagination controls
    renderCongressTradesPagination();
}

// Render pagination controls for congress trades
function renderCongressTradesPagination(): void {
    const container = document.getElementById('congress-pagination');
    if (!container) return;

    const totalPages = Math.ceil(allCongressTrades.length / congressTradesPerPage);

    if (totalPages <= 1) {
        container.innerHTML = '';
        return;
    }

    container.innerHTML = '';

    // Previous button
    const prevLi = document.createElement('li');
    prevLi.innerHTML = `
        <a href="#" class="flex items-center justify-center px-3 h-8 ms-0 leading-tight text-text-secondary bg-dashboard-surface border border-border rounded-s-lg hover:bg-dashboard-surface-alt hover:text-text-primary ${congressTradesCurrentPage === 0 ? 'pointer-events-none opacity-50' : ''}">
            <span class="sr-only">Previous</span>
            <svg class="w-2.5 h-2.5 rtl:rotate-180" aria-hidden="true" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 6 10">
              <path stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 1 1 5l4 4"/>
            </svg>
        </a>
    `;
    prevLi.onclick = (e) => {
        e.preventDefault();
        if (congressTradesCurrentPage > 0) {
            congressTradesCurrentPage--;
            renderCongressTradesPage();
        }
    };
    container.appendChild(prevLi);

    // Page numbers
    const maxVisiblePages = 7;
    let startPage = Math.max(0, congressTradesCurrentPage - Math.floor(maxVisiblePages / 2));
    let endPage = Math.min(totalPages - 1, startPage + maxVisiblePages - 1);

    // Adjust start if we're near the end
    if (endPage - startPage < maxVisiblePages - 1) {
        startPage = Math.max(0, endPage - maxVisiblePages + 1);
    }

    // First page
    if (startPage > 0) {
        const firstLi = document.createElement('li');
        firstLi.innerHTML = `
            <a href="#" class="flex items-center justify-center px-3 h-8 leading-tight text-text-secondary bg-dashboard-surface border border-border hover:bg-dashboard-surface-alt hover:text-text-primary">1</a>
        `;
        firstLi.onclick = (e) => {
            e.preventDefault();
            congressTradesCurrentPage = 0;
            renderCongressTradesPage();
        };
        container.appendChild(firstLi);

        if (startPage > 1) {
            const ellipsisLi = document.createElement('li');
            ellipsisLi.innerHTML = `
                <span class="flex items-center justify-center px-3 h-8 leading-tight text-text-secondary bg-dashboard-surface border border-border">...</span>
            `;
            container.appendChild(ellipsisLi);
        }
    }

    // Page number buttons
    for (let i = startPage; i <= endPage; i++) {
        const pageLi = document.createElement('li');
        pageLi.innerHTML = `
            <a href="#" class="flex items-center justify-center px-3 h-8 leading-tight text-text-secondary bg-dashboard-surface border border-border hover:bg-dashboard-surface-alt hover:text-text-primary ${i === congressTradesCurrentPage ? 'bg-accent text-white' : ''}">${i + 1}</a>
        `;
        pageLi.onclick = (e) => {
            e.preventDefault();
            congressTradesCurrentPage = i;
            renderCongressTradesPage();
        };
        container.appendChild(pageLi);
    }

    // Last page
    if (endPage < totalPages - 1) {
        if (endPage < totalPages - 2) {
            const ellipsisLi = document.createElement('li');
            ellipsisLi.innerHTML = `
                <span class="flex items-center justify-center px-3 h-8 leading-tight text-text-secondary bg-dashboard-surface border border-border">...</span>
            `;
            container.appendChild(ellipsisLi);
        }

        const lastLi = document.createElement('li');
        lastLi.innerHTML = `
            <a href="#" class="flex items-center justify-center px-3 h-8 leading-tight text-text-secondary bg-dashboard-surface border border-border hover:bg-dashboard-surface-alt hover:text-text-primary">${totalPages}</a>
        `;
        lastLi.onclick = (e) => {
            e.preventDefault();
            congressTradesCurrentPage = totalPages - 1;
            renderCongressTradesPage();
        };
        container.appendChild(lastLi);
    }

    // Next button
    const nextLi = document.createElement('li');
    nextLi.innerHTML = `
        <a href="#" class="flex items-center justify-center px-3 h-8 leading-tight text-text-secondary bg-dashboard-surface border border-border rounded-e-lg hover:bg-dashboard-surface-alt hover:text-text-primary ${congressTradesCurrentPage >= totalPages - 1 ? 'pointer-events-none opacity-50' : ''}">
            <span class="sr-only">Next</span>
            <svg class="w-2.5 h-2.5 rtl:rotate-180" aria-hidden="true" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 6 10">
              <path stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="m1 9 4-4-4-4"/>
            </svg>
        </a>
    `;
    nextLi.onclick = (e) => {
        e.preventDefault();
        if (congressTradesCurrentPage < totalPages - 1) {
            congressTradesCurrentPage++;
            renderCongressTradesPage();
        }
    };
    container.appendChild(nextLi);
}

// Render insider trades
function renderInsiderTrades(trades: InsiderTrade[]): void {
    if (!trades || trades.length === 0) {
        allInsiderTrades = [];
        insiderTradesCurrentPage = 0;
        const countEl = document.getElementById('insider-trades-count');
        if (countEl) countEl.textContent = 'Found 0 insider trades';
        const tbody = document.getElementById('insider-trades-tbody');
        if (tbody) tbody.innerHTML = '';
        const pagination = document.getElementById('insider-trades-pagination');
        if (pagination) pagination.innerHTML = '';
        return;
    }

    allInsiderTrades = sortRecordsByDateDesc(trades, ["transaction_date", "disclosure_date"]);
    insiderTradesCurrentPage = 0;

    const section = document.getElementById("insider-trades-section");
    if (!section) return;

    section.classList.remove("hidden");

    renderInsiderTradesPage();
}

function renderInsiderTradesPage(): void {
    if (!allInsiderTrades || allInsiderTrades.length === 0) {
        return;
    }

    const countEl = document.getElementById("insider-trades-count");
    if (countEl) {
        const totalPages = Math.ceil(allInsiderTrades.length / insiderTradesPerPage);
        const start = (insiderTradesCurrentPage * insiderTradesPerPage) + 1;
        const end = Math.min((insiderTradesCurrentPage + 1) * insiderTradesPerPage, allInsiderTrades.length);
        countEl.textContent = `Found ${allInsiderTrades.length} insider trades (Showing ${start}-${end} of ${allInsiderTrades.length})`;
    }

    const tbody = document.getElementById("insider-trades-tbody");
    if (!tbody) return;

    tbody.innerHTML = "";

    const startIndex = insiderTradesCurrentPage * insiderTradesPerPage;
    const endIndex = Math.min(startIndex + insiderTradesPerPage, allInsiderTrades.length);
    const pageTrades = allInsiderTrades.slice(startIndex, endIndex);

    pageTrades.forEach(trade => {
        const row = document.createElement("tr");
        const typeValue = (trade.type || "N/A").toString();
        const typeLower = typeValue.toLowerCase();
        const typeClass = typeLower === "purchase"
            ? "text-theme-success-text"
            : typeLower === "sale"
                ? "text-theme-error-text"
                : "text-text-primary";
        const insiderLabel = trade.insider_name || "N/A";
        const titleLabel = trade.insider_title ? ` (${trade.insider_title})` : "";

        row.innerHTML = `
            <td class="px-6 py-4 whitespace-nowrap text-sm text-text-primary">${formatDate(trade.transaction_date)}</td>
            <td class="px-6 py-4 whitespace-nowrap text-sm text-text-primary">${insiderLabel}${titleLabel}</td>
            <td class="px-6 py-4 whitespace-nowrap text-sm ${typeClass}">${typeValue}</td>
            <td class="px-6 py-4 whitespace-nowrap text-sm text-text-primary text-right">${formatNumber(trade.shares || 0, 2)}</td>
            <td class="px-6 py-4 whitespace-nowrap text-sm text-text-primary text-right">${formatCurrency(trade.price_per_share || 0)}</td>
            <td class="px-6 py-4 whitespace-nowrap text-sm text-text-primary text-right">${formatCurrencyWhole(trade.value || 0)}</td>
            <td class="px-6 py-4 whitespace-nowrap text-sm text-text-secondary">${formatDate(trade.disclosure_date)}</td>
        `;
        tbody.appendChild(row);
    });

    renderInsiderTradesPagination();
}

function renderInsiderTradesPagination(): void {
    const container = document.getElementById("insider-trades-pagination");
    if (!container) return;

    const totalPages = Math.ceil(allInsiderTrades.length / insiderTradesPerPage);

    if (totalPages <= 1) {
        container.innerHTML = "";
        return;
    }

    container.innerHTML = "";

    const prevLi = document.createElement("li");
    prevLi.innerHTML = `
        <a href="#" class="flex items-center justify-center px-3 h-8 ms-0 leading-tight text-text-secondary bg-dashboard-surface border border-border rounded-s-lg hover:bg-dashboard-surface-alt hover:text-text-primary ${insiderTradesCurrentPage === 0 ? "pointer-events-none opacity-50" : ""}">
            <span class="sr-only">Previous</span>
            <svg class="w-2.5 h-2.5 rtl:rotate-180" aria-hidden="true" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 6 10">
              <path stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 1 1 5l4 4"/>
            </svg>
        </a>
    `;
    prevLi.onclick = (e) => {
        e.preventDefault();
        if (insiderTradesCurrentPage > 0) {
            insiderTradesCurrentPage--;
            renderInsiderTradesPage();
        }
    };
    container.appendChild(prevLi);

    const maxVisiblePages = 7;
    let startPage = Math.max(0, insiderTradesCurrentPage - Math.floor(maxVisiblePages / 2));
    let endPage = Math.min(totalPages - 1, startPage + maxVisiblePages - 1);

    if (endPage - startPage < maxVisiblePages - 1) {
        startPage = Math.max(0, endPage - maxVisiblePages + 1);
    }

    if (startPage > 0) {
        const firstLi = document.createElement("li");
        firstLi.innerHTML = `
            <a href="#" class="flex items-center justify-center px-3 h-8 leading-tight text-text-secondary bg-dashboard-surface border border-border hover:bg-dashboard-surface-alt hover:text-text-primary">1</a>
        `;
        firstLi.onclick = (e) => {
            e.preventDefault();
            insiderTradesCurrentPage = 0;
            renderInsiderTradesPage();
        };
        container.appendChild(firstLi);

        if (startPage > 1) {
            const ellipsisLi = document.createElement("li");
            ellipsisLi.innerHTML = `
                <span class="flex items-center justify-center px-3 h-8 leading-tight text-text-secondary bg-dashboard-surface border border-border">...</span>
            `;
            container.appendChild(ellipsisLi);
        }
    }

    for (let i = startPage; i <= endPage; i++) {
        const pageLi = document.createElement("li");
        pageLi.innerHTML = `
            <a href="#" class="flex items-center justify-center px-3 h-8 leading-tight text-text-secondary bg-dashboard-surface border border-border hover:bg-dashboard-surface-alt hover:text-text-primary ${i === insiderTradesCurrentPage ? "bg-accent text-white" : ""}">${i + 1}</a>
        `;
        pageLi.onclick = (e) => {
            e.preventDefault();
            insiderTradesCurrentPage = i;
            renderInsiderTradesPage();
        };
        container.appendChild(pageLi);
    }

    if (endPage < totalPages - 1) {
        if (endPage < totalPages - 2) {
            const ellipsisLi = document.createElement("li");
            ellipsisLi.innerHTML = `
                <span class="flex items-center justify-center px-3 h-8 leading-tight text-text-secondary bg-dashboard-surface border border-border">...</span>
            `;
            container.appendChild(ellipsisLi);
        }

        const lastLi = document.createElement("li");
        lastLi.innerHTML = `
            <a href="#" class="flex items-center justify-center px-3 h-8 leading-tight text-text-secondary bg-dashboard-surface border border-border hover:bg-dashboard-surface-alt hover:text-text-primary">${totalPages}</a>
        `;
        lastLi.onclick = (e) => {
            e.preventDefault();
            insiderTradesCurrentPage = totalPages - 1;
            renderInsiderTradesPage();
        };
        container.appendChild(lastLi);
    }

    const nextLi = document.createElement("li");
    nextLi.innerHTML = `
        <a href="#" class="flex items-center justify-center px-3 h-8 leading-tight text-text-secondary bg-dashboard-surface border border-border rounded-e-lg hover:bg-dashboard-surface-alt hover:text-text-primary ${insiderTradesCurrentPage === totalPages - 1 ? "pointer-events-none opacity-50" : ""}">
            <span class="sr-only">Next</span>
            <svg class="w-2.5 h-2.5 rtl:rotate-180" aria-hidden="true" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 6 10">
              <path stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M1 9l4-4-4-4"/>
            </svg>
        </a>
    `;
    nextLi.onclick = (e) => {
        e.preventDefault();
        if (insiderTradesCurrentPage < totalPages - 1) {
            insiderTradesCurrentPage++;
            renderInsiderTradesPage();
        }
    };
    container.appendChild(nextLi);
}

// Render watchlist status
function renderWatchlistStatus(status: WatchlistStatus): void {
    if (!status) {
        return;
    }

    const section = document.getElementById('watchlist-section');
    if (!section) return;

    section.classList.remove('hidden');

    const statusEl = document.getElementById('watchlist-status');
    const tierEl = document.getElementById('watchlist-tier');
    const sourceEl = document.getElementById('watchlist-source');

    if (statusEl) statusEl.textContent = status.is_active ? '✅ In Watchlist' : '❌ Not Active';
    if (tierEl) tierEl.textContent = status.priority_tier || 'N/A';
    if (sourceEl) sourceEl.textContent = status.source || 'N/A';
}

// Load signals for ticker
async function loadSignals(
    ticker: string,
    forceRefresh: boolean = false,
    expectedLoadSeq?: number
): Promise<void> {
    if (isStaleLoad(expectedLoadSeq, ticker)) return;

    try {
        const section = document.getElementById('signals-section');
        if (section) section.classList.remove('hidden');
        const updatedEl = document.getElementById('signals-last-updated');
        if (updatedEl) updatedEl.textContent = '-';
        setSignalsLoading(true, forceRefresh ? 'Analyzing signals...' : 'Loading signals...');
        const aiParam = forceRefresh ? 'include_ai=1' : 'include_ai=0';
        const forceParam = forceRefresh ? '&force=1' : '';
        const select = document.getElementById('signals-model-select') as HTMLSelectElement | null;
        const selectedModel = select?.value?.trim() || '';
        const modelParam = selectedModel ? `&model=${encodeURIComponent(selectedModel)}` : '';
        const response = await fetch(`/api/signals/analyze/${ticker}?${aiParam}${forceParam}${modelParam}`, {
            credentials: 'include'
        });
        if (isStaleLoad(expectedLoadSeq, ticker)) return;
        if (!response.ok) {
            if (response.status === 404) {
                // No price data available for signals
                setSignalsLoading(false, 'No price data available');
                return;
            }
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        const result = await response.json();
        if (isStaleLoad(expectedLoadSeq, ticker)) return;
        if (result.success && result.data) {
            renderSignals(result.data);
        } else {
            setSignalsLoading(false, 'No signals available');
            return;
        }
        setSignalsLoading(false, '');
    } catch (error) {
        if (isStaleLoad(expectedLoadSeq, ticker)) return;
        console.error('Error loading signals:', error);
        setSignalsLoading(false, 'Unable to load signals');
    }
}

// Render signals
function renderSignals(signals: SignalAnalysis): void {
    if (!signals) {
        return;
    }

    const section = document.getElementById('signals-section');
    if (!section) return;

    section.classList.remove('hidden');

    // Overall signal badge
    const overallSignal = signals.overall_signal || 'HOLD';
    const confidence = signals.confidence || 0;
    const badgeEl = document.getElementById('overall-signal-badge');
    const confidenceEl = document.getElementById('signal-confidence');

    if (badgeEl) {
        let badgeClass = 'px-4 py-2 rounded-lg font-semibold border ';
        let badgeText = overallSignal;

        switch (overallSignal) {
            case 'BUY':
                badgeClass += 'bg-theme-success-bg text-theme-success-text border-theme-success-text';
                break;
            case 'SELL':
                badgeClass += 'bg-theme-error-bg text-theme-error-text border-theme-error-text';
                break;
            case 'WATCH':
                badgeClass += 'bg-theme-info-bg text-theme-info-text border-theme-info-text';
                break;
            default:
                badgeClass += 'bg-dashboard-surface-alt text-text-primary border-border';
        }

        badgeEl.className = badgeClass;
        badgeEl.textContent = badgeText;
    }

    if (confidenceEl) {
        confidenceEl.textContent = `${(confidence * 100).toFixed(0)}%`;
    }

    // Last updated
    const updatedEl = document.getElementById('signals-last-updated');
    if (updatedEl) {
        updatedEl.textContent = signals.analysis_date ? formatDateTime(signals.analysis_date) : 'N/A';
    }

    // Structure signal
    const structure = signals.structure || {};
    const trendEl = document.getElementById('structure-trend');
    const pullbackEl = document.getElementById('structure-pullback');
    const breakoutEl = document.getElementById('structure-breakout');

    if (trendEl) trendEl.textContent = structure.trend || 'N/A';
    if (pullbackEl) pullbackEl.textContent = structure.pullback ? '✅ Yes' : '❌ No';
    if (breakoutEl) breakoutEl.textContent = structure.breakout ? '✅ Yes' : '❌ No';

    // Timing signal
    const timing = signals.timing || {};
    const volumeEl = document.getElementById('timing-volume');
    const rsiEl = document.getElementById('timing-rsi');
    const cciEl = document.getElementById('timing-cci');

    if (volumeEl) {
        volumeEl.textContent = timing.volume_ok ? '✅ OK' : '❌ Low';
    }
    if (rsiEl) {
        const rsiValue = timing.rsi !== undefined ? timing.rsi.toFixed(1) : 'N/A';
        const rsiStatus = timing.rsi_ok ? '✅' : '❌';
        rsiEl.textContent = `${rsiStatus} ${rsiValue}`;
    }
    if (cciEl) {
        const cciValue = timing.cci !== undefined ? timing.cci.toFixed(1) : 'N/A';
        const cciStatus = timing.cci_ok ? '✅' : '❌';
        cciEl.textContent = `${cciStatus} ${cciValue}`;
    }

    // Fear & Risk signal
    const fearRisk = signals.fear_risk || {};
    const fearLevelEl = document.getElementById('fear-level');
    const riskScoreEl = document.getElementById('risk-score');
    const recommendationEl = document.getElementById('risk-recommendation');

    if (fearLevelEl) {
        const fearLevel = fearRisk.fear_level || 'LOW';
        let fearClass = 'text-xl font-semibold ';
        switch (fearLevel) {
            case 'EXTREME':
                fearClass += 'text-theme-error-text';
                break;
            case 'HIGH':
                fearClass += 'text-theme-warning-text';
                break;
            case 'MODERATE':
                fearClass += 'text-theme-warning-text';
                break;
            default:
                fearClass += 'text-theme-success-text';
        }
        fearLevelEl.className = fearClass;
        fearLevelEl.textContent = fearLevel;
    }

    if (riskScoreEl) {
        const riskScore = fearRisk.risk_score || 0;
        riskScoreEl.textContent = `${riskScore.toFixed(1)}/100`;
    }

    if (recommendationEl) {
        const recommendation = fearRisk.recommendation || 'SAFE';
        let recClass = 'text-xl font-semibold ';
        switch (recommendation) {
            case 'AVOID':
                recClass += 'text-theme-error-text';
                break;
            case 'RISKY':
                recClass += 'text-theme-warning-text';
                break;
            case 'CAUTION':
                recClass += 'text-theme-warning-text';
                break;
            default:
                recClass += 'text-theme-success-text';
        }
        recommendationEl.className = recClass;
        recommendationEl.textContent = recommendation;
    }

    // Momentum signal
    const momentum = signals.momentum || {} as any;
    renderMomentumSignal(momentum);

    // Fundamental signal
    const fundamental = signals.fundamental || {} as any;
    renderFundamentalSignal(fundamental);

    // AI explanation
    const explanationEl = document.getElementById('signals-explanation');
    if (explanationEl) {
        if (signals.explanation) {
            explanationEl.textContent = signals.explanation;
        } else {
            explanationEl.innerHTML = '<span class="text-text-tertiary">No AI explanation available yet.</span>';
        }
    }
}

// Helper: color-code a score element by value
function colorScoreEl(el: HTMLElement, score: number): void {
    el.classList.remove('text-theme-success-text', 'text-theme-warning-text', 'text-theme-error-text');
    if (score >= 0.6) {
        el.classList.add('text-theme-success-text');
    } else if (score >= 0.4) {
        el.classList.add('text-theme-warning-text');
    } else {
        el.classList.add('text-theme-error-text');
    }
}

// Helper: get bar color class for a score value
function barColorClass(score: number): string {
    if (score >= 0.6) return 'bg-theme-success-bg';
    if (score >= 0.4) return 'bg-theme-warning-bg';
    return 'bg-theme-error-bg';
}

function fmtPct(v: number | undefined | null): string {
    if (v === undefined || v === null) return 'N/A';
    return `${(v * 100).toFixed(1)}%`;
}

function fmtDec(v: number | undefined | null, digits: number = 2): string {
    if (v === undefined || v === null) return 'N/A';
    return v.toFixed(digits);
}

function renderMomentumSignal(momentum: any): void {
    // Bias badge
    const biasBadge = document.getElementById('momentum-bias-badge');
    if (biasBadge) {
        const bias = momentum.bias || 'N/A';
        let badgeClass = 'px-2.5 py-0.5 rounded text-xs font-bold border ';
        switch (bias) {
            case 'BULLISH':
                badgeClass += 'bg-theme-success-bg text-theme-success-text border-theme-success-text';
                break;
            case 'BEARISH':
                badgeClass += 'bg-theme-error-bg text-theme-error-text border-theme-error-text';
                break;
            case 'NEUTRAL':
                badgeClass += 'bg-theme-warning-bg text-theme-warning-text border-theme-warning-text';
                break;
            default:
                badgeClass += 'bg-dashboard-surface-alt text-text-secondary border-border';
        }
        biasBadge.className = badgeClass;
        biasBadge.textContent = bias;
    }

    // Composite score
    const compositeEl = document.getElementById('momentum-composite');
    const compositeBar = document.getElementById('momentum-composite-bar');
    const score = momentum.composite_score ?? 0;
    if (compositeEl) {
        compositeEl.textContent = `${(score * 100).toFixed(0)}%`;
        colorScoreEl(compositeEl, score);
    }
    if (compositeBar) {
        compositeBar.style.setProperty('--bar-width', `${(score * 100).toFixed(0)}%`);
        compositeBar.classList.remove('bg-theme-success-bg', 'bg-theme-warning-bg', 'bg-theme-error-bg', 'bg-accent');
        compositeBar.classList.add(barColorClass(score));
    }

    // Trend Following
    const tf = momentum.trend_following || {};
    const trendScoreEl = document.getElementById('mom-trend-score');
    if (trendScoreEl) {
        const s = tf.score ?? 0;
        trendScoreEl.textContent = fmtPct(s);
        colorScoreEl(trendScoreEl, s);
    }
    const trendEmaEl = document.getElementById('mom-trend-ema');
    if (trendEmaEl) trendEmaEl.textContent = tf.ema_alignment || 'N/A';

    // Momentum category
    const mom = momentum.momentum || {};
    const momScoreEl = document.getElementById('mom-momentum-score');
    if (momScoreEl) {
        const s = mom.score ?? 0;
        momScoreEl.textContent = fmtPct(s);
        colorScoreEl(momScoreEl, s);
    }
    const momMacdEl = document.getElementById('mom-momentum-macd');
    if (momMacdEl) momMacdEl.textContent = fmtDec(mom.macd_histogram, 4);
    const mom1mEl = document.getElementById('mom-momentum-1m');
    if (mom1mEl) mom1mEl.textContent = fmtPct(mom.return_1m);
    const mom3mEl = document.getElementById('mom-momentum-3m');
    if (mom3mEl) mom3mEl.textContent = fmtPct(mom.return_3m);

    // Mean Reversion
    const mr = momentum.mean_reversion || {};
    const mrScoreEl = document.getElementById('mom-meanrev-score');
    if (mrScoreEl) {
        const s = mr.score ?? 0;
        mrScoreEl.textContent = fmtPct(s);
        colorScoreEl(mrScoreEl, s);
    }
    const mrZEl = document.getElementById('mom-meanrev-z');
    if (mrZEl) mrZEl.textContent = fmtDec(mr.z_score);
    const mrBbEl = document.getElementById('mom-meanrev-bb');
    if (mrBbEl) mrBbEl.textContent = fmtDec(mr.bb_percent_b);
    const mrRsiEl = document.getElementById('mom-meanrev-rsi');
    if (mrRsiEl) mrRsiEl.textContent = fmtDec(mr.rsi, 1);

    // Volatility
    const vol = momentum.volatility || {};
    const volScoreEl = document.getElementById('mom-vol-score');
    if (volScoreEl) {
        const s = vol.score ?? 0;
        volScoreEl.textContent = fmtPct(s);
        colorScoreEl(volScoreEl, s);
    }
    const volRatioEl = document.getElementById('mom-vol-ratio');
    if (volRatioEl) volRatioEl.textContent = fmtDec(vol.vol_ratio);
    const volAnnEl = document.getElementById('mom-vol-ann');
    if (volAnnEl) volAnnEl.textContent = fmtPct(vol.annualized_vol);

    // Oscillators
    const osc = momentum.oscillators || {};
    const oscScoreEl = document.getElementById('mom-osc-score');
    if (oscScoreEl) {
        const s = osc.score ?? 0;
        oscScoreEl.textContent = fmtPct(s);
        colorScoreEl(oscScoreEl, s);
    }
    const oscStochEl = document.getElementById('mom-osc-stoch');
    if (oscStochEl) oscStochEl.textContent = fmtDec(osc.stochastic_k, 1);
    const oscWrEl = document.getElementById('mom-osc-wr');
    if (oscWrEl) oscWrEl.textContent = fmtDec(osc.williams_r, 1);
    const oscRocEl = document.getElementById('mom-osc-roc');
    if (oscRocEl) oscRocEl.textContent = fmtPct(osc.roc);
}

function renderFundamentalSignal(fundamental: any): void {
    // Quality badge
    const qualityBadge = document.getElementById('fund-quality-badge');
    if (qualityBadge) {
        const quality = fundamental.quality || 'UNKNOWN';
        let badgeClass = 'px-2.5 py-0.5 rounded text-xs font-bold border ';
        switch (quality) {
            case 'STRONG':
                badgeClass += 'bg-theme-success-bg text-theme-success-text border-theme-success-text';
                break;
            case 'GOOD':
                badgeClass += 'bg-theme-info-bg text-theme-info-text border-theme-info-text';
                break;
            case 'FAIR':
                badgeClass += 'bg-theme-warning-bg text-theme-warning-text border-theme-warning-text';
                break;
            case 'WEAK':
                badgeClass += 'bg-theme-error-bg text-theme-error-text border-theme-error-text';
                break;
            default:
                badgeClass += 'bg-dashboard-surface-alt text-text-secondary border-border';
        }
        qualityBadge.className = badgeClass;
        qualityBadge.textContent = quality;
    }

    // Composite score
    const compositeEl = document.getElementById('fund-composite');
    const compositeBar = document.getElementById('fund-composite-bar');
    const score = fundamental.composite_score ?? 0;
    if (compositeEl) {
        compositeEl.textContent = `${(score * 100).toFixed(0)}%`;
        colorScoreEl(compositeEl, score);
    }
    if (compositeBar) {
        compositeBar.style.setProperty('--bar-width', `${(score * 100).toFixed(0)}%`);
        compositeBar.classList.remove('bg-theme-success-bg', 'bg-theme-warning-bg', 'bg-theme-error-bg', 'bg-accent');
        compositeBar.classList.add(barColorClass(score));
    }

    // Metrics count
    const metricsEl = document.getElementById('fund-metrics-count');
    if (metricsEl) {
        const count = fundamental.metrics_available ?? 0;
        metricsEl.textContent = `${count} metrics available`;
    }

    // Profitability
    const profit = fundamental.profitability || {};
    const profitScoreEl = document.getElementById('fund-profit-score');
    if (profitScoreEl) {
        const s = profit.score ?? 0;
        profitScoreEl.textContent = fmtPct(s);
        colorScoreEl(profitScoreEl, s);
    }
    const profitRoeEl = document.getElementById('fund-profit-roe');
    if (profitRoeEl) profitRoeEl.textContent = fmtPct(profit.return_on_equity);
    const profitMarginEl = document.getElementById('fund-profit-margin');
    if (profitMarginEl) profitMarginEl.textContent = fmtPct(profit.net_margin);
    const profitOpEl = document.getElementById('fund-profit-op');
    if (profitOpEl) profitOpEl.textContent = fmtPct(profit.operating_margin);

    // Growth
    const growth = fundamental.growth || {};
    const growthScoreEl = document.getElementById('fund-growth-score');
    if (growthScoreEl) {
        const s = growth.score ?? 0;
        growthScoreEl.textContent = fmtPct(s);
        colorScoreEl(growthScoreEl, s);
    }
    const growthRevEl = document.getElementById('fund-growth-rev');
    if (growthRevEl) growthRevEl.textContent = fmtPct(growth.revenue_growth);
    const growthEarnEl = document.getElementById('fund-growth-earn');
    if (growthEarnEl) growthEarnEl.textContent = fmtPct(growth.earnings_growth);

    // Financial Health
    const health = fundamental.health || {};
    const healthScoreEl = document.getElementById('fund-health-score');
    if (healthScoreEl) {
        const s = health.score ?? 0;
        healthScoreEl.textContent = fmtPct(s);
        colorScoreEl(healthScoreEl, s);
    }
    const healthCrEl = document.getElementById('fund-health-cr');
    if (healthCrEl) healthCrEl.textContent = fmtDec(health.current_ratio);
    const healthDeEl = document.getElementById('fund-health-de');
    if (healthDeEl) healthDeEl.textContent = fmtDec(health.debt_to_equity);
    const healthFcfEl = document.getElementById('fund-health-fcf');
    if (healthFcfEl) {
        const fcf = health.free_cash_flow;
        if (fcf !== undefined && fcf !== null) {
            // Format large numbers (e.g. 1.2B, 340M)
            const abs = Math.abs(fcf);
            let formatted: string;
            if (abs >= 1e9) formatted = `${(fcf / 1e9).toFixed(1)}B`;
            else if (abs >= 1e6) formatted = `${(fcf / 1e6).toFixed(0)}M`;
            else if (abs >= 1e3) formatted = `${(fcf / 1e3).toFixed(0)}K`;
            else formatted = fcf.toFixed(0);
            healthFcfEl.textContent = formatted;
        } else {
            healthFcfEl.textContent = 'N/A';
        }
    }

    // Valuation
    const val = fundamental.valuation || {};
    const valScoreEl = document.getElementById('fund-val-score');
    if (valScoreEl) {
        const s = val.score ?? 0;
        valScoreEl.textContent = fmtPct(s);
        colorScoreEl(valScoreEl, s);
    }
    const valPeEl = document.getElementById('fund-val-pe');
    if (valPeEl) valPeEl.textContent = fmtDec(val.trailing_pe);
    const valPbEl = document.getElementById('fund-val-pb');
    if (valPbEl) valPbEl.textContent = fmtDec(val.price_to_book);
    const valPsEl = document.getElementById('fund-val-ps');
    if (valPsEl) valPsEl.textContent = fmtDec(val.price_to_sales);
    const valPegEl = document.getElementById('fund-val-peg');
    if (valPegEl) valPegEl.textContent = fmtDec(val.peg_ratio);
}

function setSignalsLoading(isLoading: boolean, message: string): void {
    const loadingEl = document.getElementById('signals-loading');
    const statusEl = document.getElementById('signals-status');
    const refreshBtn = document.getElementById('signals-refresh-btn') as HTMLButtonElement | null;

    if (loadingEl) {
        if (isLoading) {
            loadingEl.classList.remove('hidden');
        } else {
            loadingEl.classList.add('hidden');
        }
    }

    if (statusEl) {
        statusEl.textContent = message || '';
    }

    if (refreshBtn) {
        refreshBtn.disabled = isLoading;
        refreshBtn.classList.toggle('opacity-60', isLoading);
        refreshBtn.classList.toggle('cursor-not-allowed', isLoading);
    }
}

function updateContextUsage(): void {
    const usageEl = document.getElementById('ticker-context-usage');
    if (!usageEl) return;

    const maxTokens = getMaxTokensForModel(selectedModel);
    const usedTokens = estimateTokens(contextCharCount);
    const percentage = maxTokens > 0 ? Math.min(100, Math.round((usedTokens / maxTokens) * 100)) : 0;

    usageEl.textContent = maxTokens > 0
        ? `Context: ${usedTokens.toLocaleString()} / ${maxTokens.toLocaleString()} tokens (${percentage}%)`
        : `Context: ${usedTokens.toLocaleString()} tokens`;
}

function estimateTokens(charCount: number): number {
    return Math.ceil(charCount / 4);
}

function getMaxTokensForModel(modelName: string): number {
    if (!modelName) {
        return modelConfig?.default_config?.num_ctx || 0;
    }

    if (modelName.startsWith('glm-')) {
        if (modelName.includes('flash')) {
            return 1000000;
        }
        if (modelName.includes('pro')) {
            return 2000000;
        }
        return 1000000;
    }

    if (modelConfig?.models && modelConfig.models[modelName]?.num_ctx) {
        return modelConfig.models[modelName].num_ctx;
    }

    return modelConfig?.default_config?.num_ctx || 0;
}

// Utility functions
function formatDate(dateStr?: string): string {
    if (!dateStr) return 'N/A';
    try {
        const date = new Date(dateStr);
        return date.toLocaleDateString();
    } catch (e) {
        return dateStr.substring(0, 10); // Return first 10 chars if parsing fails
    }
}

function formatDateTime(dateStr?: string): string {
    if (!dateStr) return 'N/A';
    try {
        const date = new Date(dateStr);
        return date.toLocaleString();
    } catch (e) {
        return dateStr.replace('T', ' ').slice(0, 19);
    }
}

function formatCurrency(value: number | string): string {
    return `$${parseFloat(String(value || 0)).toFixed(2)}`;
}

function formatCurrencyWhole(value: number | string): string {
    const numericValue = Number(value) || 0;
    return new Intl.NumberFormat("en-US", {
        style: "currency",
        currency: "USD",
        minimumFractionDigits: 0,
        maximumFractionDigits: 0
    }).format(numericValue);
}

function formatNumber(value: number | string, decimals: number = 2): string {
    return parseFloat(String(value || 0)).toFixed(decimals);
}

function showLoading(): void {
    const spinner = document.getElementById('loading-spinner');
    if (spinner) spinner.classList.remove('hidden');
}

function hideLoading(): void {
    const spinner = document.getElementById('loading-spinner');
    if (spinner) spinner.classList.add('hidden');
}

function showTickerError(message: string): void {
    const errorText = document.getElementById('error-text');
    const errorMessage = document.getElementById('error-message');
    if (errorText) errorText.textContent = message;
    if (errorMessage) errorMessage.classList.remove('hidden');
}

function hideTickerError(): void {
    const errorMessage = document.getElementById('error-message');
    if (errorMessage) errorMessage.classList.add('hidden');
}

function toggleSummary(summaryId: string): void {
    const shortDiv = document.getElementById(`${summaryId}-short`);
    const fullDiv = document.getElementById(`${summaryId}-full`);
    const toggleBtn = document.getElementById(`${summaryId}-toggle`);

    if (shortDiv && fullDiv && toggleBtn) {
        if (fullDiv.classList.contains('hidden')) {
            // Show full summary
            shortDiv.classList.add('hidden');
            fullDiv.classList.remove('hidden');
            toggleBtn.textContent = 'Show Less';
        } else {
            // Show short summary
            shortDiv.classList.remove('hidden');
            fullDiv.classList.add('hidden');
            toggleBtn.textContent = 'Show Full Summary';
        }
    }
}

// Load and render ticker AI analysis
async function loadTickerAnalysis(ticker: string, expectedLoadSeq?: number): Promise<void> {
    if (isStaleLoad(expectedLoadSeq, ticker)) return;

    try {
        const response = await fetch(`/api/v2/ticker/${ticker}/analysis`, {
            credentials: 'include'
        });
        if (isStaleLoad(expectedLoadSeq, ticker)) return;

        if (!response.ok) {
            if (response.status === 404) {
                hideMetaAnalysisBlock();
                // No analysis available yet - show blank section with reanalyze button
                renderEmptyAnalysis(ticker);
                return;
            }
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        const payload: TickerAnalysis | TickerAnalysisApiResponse | null = await response.json();
        if (isStaleLoad(expectedLoadSeq, ticker)) return;

        const analysis = payload && typeof payload === 'object' && 'analysis' in payload
            ? ((payload as TickerAnalysisApiResponse).analysis ?? null)
            : payload as TickerAnalysis | null;
        if (analysis) {
            renderTickerAnalysis(analysis, ticker);
            void loadTickerMetaAnalysis(ticker, expectedLoadSeq);
        } else {
            hideMetaAnalysisBlock();
            // Analysis is null - show blank section
            renderEmptyAnalysis(ticker);
        }
    } catch (error) {
        if (isStaleLoad(expectedLoadSeq, ticker)) return;
        console.error('Error loading ticker analysis:', error);
        hideMetaAnalysisBlock();
        // Show blank section even on error so user can still reanalyze
        renderEmptyAnalysis(ticker);
    }
}

function hideMetaAnalysisBlock(): void {
    const block = document.getElementById('meta-analysis-block');
    if (block) block.classList.add('hidden');
}

function showMetaAnalysisBlock(): void {
    const block = document.getElementById('meta-analysis-block');
    if (block) block.classList.remove('hidden');
}

function setupMetaRebuildHandler(ticker: string): void {
    const btn = document.getElementById('meta-rebuild-btn') as HTMLButtonElement | null;
    if (btn) {
        btn.onclick = () => requestMetaRebuild(ticker);
    }
}

/**
 * Tailwind chip classes for ticker meta ``stance`` enum values.
 * Mirrors the Phase 1 contract in ``ai_prompts.py::TICKER_META_ANALYSIS_PROMPT``:
 *   STRONG_BULLISH | BULLISH | NEUTRAL | BEARISH | STRONG_BEARISH | INSUFFICIENT_DATA
 */
function stanceChipClasses(stance: string | undefined): string {
    const base = 'inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold';
    switch ((stance || '').toUpperCase()) {
        case 'STRONG_BULLISH':
            return `${base} bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300`;
        case 'BULLISH':
            return `${base} bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300`;
        case 'NEUTRAL':
            return `${base} bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-200`;
        case 'BEARISH':
            return `${base} bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300`;
        case 'STRONG_BEARISH':
            return `${base} bg-rose-100 text-rose-800 dark:bg-rose-900/40 dark:text-rose-300`;
        case 'INSUFFICIENT_DATA':
            return `${base} bg-yellow-100 text-yellow-800 dark:bg-yellow-900/40 dark:text-yellow-300`;
        default:
            return `${base} bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300`;
    }
}

/** Tailwind chip classes for the ``horizon`` enum (INTRADAY/SWING/POSITION/UNKNOWN). */
function horizonChipClasses(horizon: string | undefined): string {
    const base = 'inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold';
    switch ((horizon || '').toUpperCase()) {
        case 'INTRADAY':
            return `${base} bg-orange-100 text-orange-800 dark:bg-orange-900/40 dark:text-orange-300`;
        case 'SWING':
            return `${base} bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-300`;
        case 'POSITION':
            return `${base} bg-violet-100 text-violet-800 dark:bg-violet-900/40 dark:text-violet-300`;
        default:
            return `${base} bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300`;
    }
}

/** Read a string field from the meta row, falling back to ``full_result``. */
function metaStringField(meta: TickerMetaAnalysisRow, key: string): string {
    const top = (meta as unknown as Record<string, unknown>)[key];
    if (typeof top === 'string' && top.trim()) return top;
    const fr = meta.full_result;
    if (fr && typeof fr[key] === 'string') {
        const val = fr[key] as string;
        if (val.trim()) return val;
    }
    return '';
}

/** Read a number-ish field from the meta row, falling back to ``full_result``. */
function metaNumberField(meta: TickerMetaAnalysisRow, key: string): number | null {
    const top = (meta as unknown as Record<string, unknown>)[key];
    if (typeof top === 'number' && Number.isFinite(top)) return top;
    if (typeof top === 'string' && top.trim() !== '') {
        const n = Number(top);
        if (Number.isFinite(n)) return n;
    }
    const fr = meta.full_result;
    if (fr && fr[key] !== undefined && fr[key] !== null) {
        if (typeof fr[key] === 'number' && Number.isFinite(fr[key] as number)) return fr[key] as number;
        if (typeof fr[key] === 'string') {
            const n = Number(fr[key]);
            if (Number.isFinite(n)) return n;
        }
    }
    return null;
}

/** Read a string[] field from the meta row, falling back to ``full_result``. */
function metaListField(meta: TickerMetaAnalysisRow, key: string): string[] {
    const top = (meta as unknown as Record<string, unknown>)[key];
    if (Array.isArray(top)) return top.map((v) => String(v)).filter((s) => s.trim());
    const fr = meta.full_result;
    if (fr && Array.isArray(fr[key])) {
        return (fr[key] as unknown[]).map((v) => String(v)).filter((s) => s.trim());
    }
    return [];
}

function renderTickerMetaAnalysisContent(meta: TickerMetaAnalysisRow): void {
    const el = document.getElementById('meta-analysis-content');
    if (!el) return;

    // Phase 1 contract: prefer `stance` from full_result; fall back to legacy
    // `unified_conviction` column. Same idea for `confidence` vs `confidence_adjusted`.
    const stance =
        metaStringField(meta, 'stance') ||
        meta.unified_conviction ||
        'N/A';
    const stanceClass = stanceChipClasses(stance);

    const horizon = metaStringField(meta, 'horizon');
    const horizonClass = horizonChipClasses(horizon);

    const confidenceRaw =
        metaNumberField(meta, 'confidence') ??
        (meta.confidence_adjusted !== null && meta.confidence_adjusted !== undefined
            ? Number(meta.confidence_adjusted)
            : null);
    const confidenceText =
        confidenceRaw === null ? 'N/A' : `${(confidenceRaw * 100).toFixed(0)}%`;

    const actionabilityRaw = metaNumberField(meta, 'actionability_score');
    const actionabilityPct =
        actionabilityRaw === null ? null : Math.max(0, Math.min(100, actionabilityRaw));

    const keyDrivers = metaListField(meta, 'key_drivers');
    const riskFlags = metaListField(meta, 'risk_flags');
    const contradictions = metaListField(meta, 'contradictions');
    const actions = metaListField(meta, 'action_items');

    const driversHtml =
        keyDrivers.length > 0
            ? `<ul class="list-disc list-inside text-sm text-text-primary space-y-1">${keyDrivers
                .map((d) => `<li>${escapeHtml(d)}</li>`)
                .join('')}</ul>`
            : '<p class="text-sm text-text-secondary">No key drivers reported.</p>';

    const risksHtml =
        riskFlags.length > 0
            ? `<ul class="list-disc list-inside text-sm text-text-primary space-y-1">${riskFlags
                .map((r) => `<li>${escapeHtml(r)}</li>`)
                .join('')}</ul>`
            : '<p class="text-sm text-text-secondary">None flagged.</p>';

    const contraHtml =
        contradictions.length > 0
            ? `<ul class="list-disc list-inside text-sm text-text-primary space-y-1">${contradictions
                .map((c) => `<li>${escapeHtml(c)}</li>`)
                .join('')}</ul>`
            : '<p class="text-sm text-text-secondary">None flagged.</p>';

    const actionsHtml =
        actions.length > 0
            ? `<ul class="list-decimal list-inside text-sm text-text-primary space-y-1">${actions
                .map((a) => `<li>${escapeHtml(a)}</li>`)
                .join('')}</ul>`
            : '';

    const actionabilityHtml =
        actionabilityPct === null
            ? ''
            : `
            <div class="min-w-[160px]">
                <span class="text-text-secondary text-xs uppercase tracking-wide">Actionability</span>
                <div class="flex items-center gap-2 mt-1">
                    <div class="font-medium text-text-primary text-sm">${actionabilityPct.toFixed(0)}/100</div>
                    <div class="flex-1 h-1.5 bg-dashboard-background rounded overflow-hidden border border-border" aria-hidden="true">
                        <div class="h-full bg-accent" style="width: ${actionabilityPct}%"></div>
                    </div>
                </div>
            </div>`;

    el.innerHTML = `
        <div class="space-y-4">
            <div class="flex flex-wrap items-center gap-x-3 gap-y-2">
                <span class="${stanceClass}" title="Phase 1 stance enum">${escapeHtml(stance)}</span>
                ${horizon ? `<span class="${horizonClass}" title="Recommended trading horizon">${escapeHtml(horizon)}</span>` : ''}
                <span class="text-sm text-text-secondary">Confidence <span class="font-semibold text-text-primary">${escapeHtml(confidenceText)}</span></span>
                ${meta.updated_at ? `<span class="text-xs text-text-tertiary">Updated ${escapeHtml(formatDate(meta.updated_at))}</span>` : ''}
            </div>
            ${actionabilityHtml}
            ${meta.narrative ? `
            <div class="bg-dashboard-background p-4 rounded-lg border border-border">
                <h4 class="font-semibold text-text-primary mb-2">Narrative</h4>
                <div class="text-text-primary whitespace-pre-wrap text-sm">${escapeHtml(meta.narrative)}</div>
            </div>` : ''}
            <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                    <h4 class="font-semibold text-text-primary mb-2">
                        <i class="fas fa-bolt mr-1 text-accent"></i>Key drivers
                    </h4>
                    ${driversHtml}
                </div>
                <div>
                    <h4 class="font-semibold text-text-primary mb-2">
                        <i class="fas fa-triangle-exclamation mr-1 text-amber-500"></i>Risk flags
                    </h4>
                    ${risksHtml}
                </div>
            </div>
            <div>
                <h4 class="font-semibold text-text-primary mb-2">
                    <i class="fas fa-scale-balanced mr-1 text-text-secondary"></i>Contradictions / tensions
                </h4>
                ${contraHtml}
            </div>
            ${meta.what_changed_vs_last_run ? `
            <div class="bg-dashboard-background p-4 rounded-lg border border-border">
                <h4 class="font-semibold text-text-primary mb-2">Change vs prior run</h4>
                <p class="text-sm text-text-primary whitespace-pre-wrap">${escapeHtml(meta.what_changed_vs_last_run)}</p>
            </div>` : ''}
            ${actionsHtml ? `<div><h4 class="font-semibold text-text-primary mb-2">Action items</h4>${actionsHtml}</div>` : ''}
            ${meta.model_used ? `<p class="text-xs text-text-tertiary">Model: ${escapeHtml(meta.model_used)}${meta.artifact_bundle_digest ? ` · bundle ${escapeHtml(String(meta.artifact_bundle_digest).slice(0, 12))}` : ''}</p>` : ''}
        </div>
    `;
}

async function loadTickerMetaAnalysis(ticker: string, expectedLoadSeq?: number): Promise<void> {
    if (isStaleLoad(expectedLoadSeq, ticker)) return;

    const content = document.getElementById('meta-analysis-content');
    const block = document.getElementById('meta-analysis-block');
    if (!content || !block) return;

    showMetaAnalysisBlock();
    content.innerHTML = '<p class="text-sm text-text-tertiary">Loading meta synthesis…</p>';

    try {
        const response = await fetch(`/api/v2/ticker/${encodeURIComponent(ticker)}/meta-analysis`, {
            credentials: 'include',
        });
        if (isStaleLoad(expectedLoadSeq, ticker)) return;

        if (response.status === 503) {
            const data = (await response.json()) as { error?: string };
            content.innerHTML = `<p class="text-sm text-amber-600 dark:text-amber-400">${escapeHtml(data.error || 'Meta analysis not available.')}</p>`;
            setupMetaRebuildHandler(ticker);
            return;
        }

        if (!response.ok) {
            content.innerHTML =
                '<p class="text-sm text-text-secondary">Could not load meta synthesis.</p>';
            setupMetaRebuildHandler(ticker);
            return;
        }

        const data = (await response.json()) as { meta: TickerMetaAnalysisRow | null };
        if (isStaleLoad(expectedLoadSeq, ticker)) return;

        if (data.meta) {
            renderTickerMetaAnalysisContent(data.meta);
        } else {
            content.innerHTML =
                '<p class="text-sm text-text-secondary">No meta synthesis yet. Click <strong>Refresh meta</strong> to generate from saved analyses.</p>';
        }
        setupMetaRebuildHandler(ticker);
    } catch (e) {
        if (isStaleLoad(expectedLoadSeq, ticker)) return;
        console.error('Error loading meta analysis:', e);
        content.innerHTML =
            '<p class="text-sm text-text-secondary">Meta synthesis unavailable.</p>';
        setupMetaRebuildHandler(ticker);
    }
}

async function requestMetaRebuild(ticker: string): Promise<void> {
    const btn = document.getElementById('meta-rebuild-btn') as HTMLButtonElement | null;
    const original = btn?.innerHTML ?? '';
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<i class="fas fa-spinner fa-spin mr-2"></i>Working…';
    }

    try {
        const response = await fetch(`/api/v2/ticker/${encodeURIComponent(ticker)}/meta-analysis/rebuild`, {
            method: 'POST',
            credentials: 'include',
            headers: {
                'Content-Type': 'application/json',
                ...getCsrfHeaders(),
            },
            body: JSON.stringify({
                model: selectedModel || undefined,
            }),
        });

        const payload = (await response.json().catch(() => ({}))) as {
            meta?: TickerMetaAnalysisRow;
            error?: string;
            status?: string;
        };

        if (response.ok && payload.meta) {
            showToast('Meta synthesis updated.', 'success');
            renderTickerMetaAnalysisContent(payload.meta);
        } else {
            showToast(payload.error || 'Meta synthesis failed', 'error');
        }
    } catch (e) {
        console.error('Meta rebuild error:', e);
        showToast('Meta synthesis failed', 'error');
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = original || '<i class="fas fa-sync-alt mr-2"></i>Refresh meta';
        }
        setupMetaRebuildHandler(ticker);
    }
}

// Render empty analysis state (no analysis available yet)
function renderEmptyAnalysis(ticker: string): void {
    const section = document.getElementById('ai-analysis-section');
    if (!section) return;

    section.classList.remove('hidden');

    const content = document.getElementById('ai-analysis-content');
    if (!content) return;

    renderDebugPanelMessage(
        'Loading AI context preview...',
        '🧠 AI Context Preview (click to expand)'
    );

    // Show empty state message
    content.innerHTML = `
        <div class="bg-dashboard-background p-6 rounded-lg border border-border text-center">
            <p class="text-text-secondary mb-4">No AI analysis available for this ticker yet.</p>
            <p class="text-sm text-text-tertiary">Click the "Analyze" button above to generate an analysis.</p>
        </div>
    `;

    // Setup analyze button (no analysis exists yet)
    const reanalyzeBtn = document.getElementById('reanalyze-btn') as HTMLButtonElement | null;
    if (reanalyzeBtn) {
        reanalyzeBtn.onclick = () => requestReanalysis(ticker);
        reanalyzeBtn.disabled = false;
        reanalyzeBtn.innerHTML = '<i class="fas fa-brain mr-2"></i>Analyze';
    }
}

async function loadTickerAnalysisContext(ticker: string, expectedLoadSeq?: number): Promise<void> {
    if (isStaleLoad(expectedLoadSeq, ticker)) return;

    try {
        const response = await fetch(`/api/v2/ticker/${ticker}/analysis-context`, {
            credentials: 'include'
        });
        if (isStaleLoad(expectedLoadSeq, ticker)) return;

        if (!response.ok) {
            renderDebugPanelMessage(
                'Unable to load AI context preview.',
                '🧠 AI Context Preview (click to expand)'
            );
            contextCharCount = 0;
            updateContextUsage();
            return;
        }

        const data: TickerAnalysisContextResponse = await response.json();
        if (isStaleLoad(expectedLoadSeq, ticker)) return;
        const context = data.context ? data.context.trim() : '';
        contextCharCount = context.length;

        if (context) {
            renderDebugPanel(context, '🧠 AI Context Preview (click to expand)');
        } else {
            renderDebugPanelMessage(
                'No context data available for this ticker yet.',
                '🧠 AI Context Preview (click to expand)'
            );
        }
        updateContextUsage();
    } catch (error) {
        if (isStaleLoad(expectedLoadSeq, ticker)) return;
        console.error('Error loading ticker analysis context:', error);
        renderDebugPanelMessage(
            'Unable to load AI context preview.',
            '🧠 AI Context Preview (click to expand)'
        );
        contextCharCount = 0;
        updateContextUsage();
    }
}

// Render ticker AI analysis
function renderTickerAnalysis(analysis: TickerAnalysis, ticker: string): void {
    const section = document.getElementById('ai-analysis-section');
    if (!section) return;

    section.classList.remove('hidden');

    const content = document.getElementById('ai-analysis-content');
    if (!content) return;

    // Format dates
    const analysisDate = formatDate(analysis.analysis_date);
    const updatedAt = formatDate(analysis.updated_at);
    const dataStart = formatDate(analysis.data_start_date);
    const dataEnd = formatDate(analysis.data_end_date);

    // Sentiment badge color
    const sentiment = analysis.sentiment || 'NEUTRAL';
    let sentimentColor = 'bg-gray-500';
    if (sentiment === 'BULLISH') sentimentColor = 'bg-green-500';
    else if (sentiment === 'BEARISH') sentimentColor = 'bg-red-500';
    else if (sentiment === 'MIXED') sentimentColor = 'bg-yellow-500';

    // Themes
    const themes = analysis.themes || [];
    const themesHtml = themes.length > 0
        ? themes.map(t => `<span class="px-2 py-1 bg-dashboard-background rounded text-sm text-text-primary">${escapeHtml(t)}</span>`).join(' ')
        : '<span class="text-text-secondary">None identified</span>';

    content.innerHTML = `
        <div class="space-y-4">
            <!-- Summary -->
            ${analysis.summary ? `
                <div class="bg-dashboard-background p-4 rounded-lg border border-border">
                    <h3 class="font-semibold mb-2 text-text-primary">Summary</h3>
                    <p class="text-text-primary">${escapeHtml(analysis.summary)}</p>
                </div>
            ` : ''}

            <!-- Analysis Text -->
            ${analysis.analysis_text ? `
                <div class="bg-dashboard-background p-4 rounded-lg border border-border">
                    <h3 class="font-semibold mb-2 text-text-primary">Full Analysis</h3>
                    <div class="text-text-primary whitespace-pre-wrap">${escapeHtml(analysis.analysis_text)}</div>
                </div>
            ` : ''}

            <!-- Metadata -->
            <div class="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
                <div>
                    <div class="text-text-secondary">Sentiment</div>
                    <div class="flex items-center gap-2 mt-1">
                        <span class="px-2 py-1 ${sentimentColor} text-white rounded text-xs">${sentiment}</span>
                        ${analysis.sentiment_score !== null && analysis.sentiment_score !== undefined
            ? `<span class="text-text-primary">${(analysis.sentiment_score * 100).toFixed(0)}%</span>`
            : ''}
                    </div>
                </div>
                <div>
                    <div class="text-text-secondary">Confidence</div>
                    <div class="text-text-primary mt-1">
                        ${analysis.confidence_score !== null && analysis.confidence_score !== undefined
            ? `${(analysis.confidence_score * 100).toFixed(0)}%`
            : 'N/A'}
                    </div>
                </div>
                <div>
                    <div class="text-text-secondary">Analysis Date</div>
                    <div class="text-text-primary mt-1">${analysisDate || 'N/A'}</div>
                </div>
                <div>
                    <div class="text-text-secondary">Data Period</div>
                    <div class="text-text-primary mt-1">${dataStart} to ${dataEnd}</div>
                </div>
            </div>

            <!-- Themes -->
            <div>
                <div class="text-text-secondary text-sm mb-2">Key Themes</div>
                <div class="flex flex-wrap gap-2">${themesHtml}</div>
            </div>

            <!-- Data Sources -->
            <div class="text-sm text-text-secondary">
                <div>Data sources: ${analysis.etf_changes_count || 0} ETF changes, ${analysis.congress_trades_count || 0} congress trades, ${analysis.research_articles_count || 0} articles</div>
                ${updatedAt ? `<div class="mt-1">Last updated: ${updatedAt}</div>` : ''}
                ${analysis.requested_by ? `<div class="mt-1">Requested by: ${escapeHtml(analysis.requested_by)}</div>` : ''}
            </div>
        </div>
    `;

    // Setup re-analyze button (analysis exists)
    const reanalyzeBtn = document.getElementById('reanalyze-btn') as HTMLButtonElement | null;
    if (reanalyzeBtn) {
        reanalyzeBtn.onclick = () => requestReanalysis(ticker);
        reanalyzeBtn.innerHTML = '<i class="fas fa-redo mr-2"></i>Re-Analyze';
    }
}

// Render debug panel with AI input context
function renderDebugPanel(inputContext: string, title: string = '🔍 Debug: AI Input Context (click to expand)'): void {
    const container = document.getElementById('ai-debug-container');
    if (!container) return;

    container.innerHTML = `
        <details class="border border-border rounded-lg">
            <summary class="cursor-pointer p-3 bg-dashboard-surface-alt rounded-t-lg text-sm font-medium text-text-primary">
                ${escapeHtml(title)}
            </summary>
            <pre class="p-4 bg-dashboard-background text-xs overflow-auto max-h-96 whitespace-pre-wrap text-text-primary">${escapeHtml(inputContext)}</pre>
        </details>
    `;
}

function renderDebugPanelMessage(message: string, title: string): void {
    const container = document.getElementById('ai-debug-container');
    if (!container) return;

    container.innerHTML = `
        <details class="border border-border rounded-lg">
            <summary class="cursor-pointer p-3 bg-dashboard-surface-alt rounded-t-lg text-sm font-medium text-text-primary">
                ${escapeHtml(title)}
            </summary>
            <div class="p-4 bg-dashboard-background text-xs text-text-secondary">
                ${escapeHtml(message)}
            </div>
        </details>
    `;
}

// Request re-analysis
async function requestReanalysis(ticker: string): Promise<void> {
    const btn = document.getElementById('reanalyze-btn') as HTMLButtonElement;
    if (!btn) return;

    const originalHTML = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin mr-2"></i>Analyzing...';

    try {
        const response = await fetch(`/api/v2/ticker/${ticker}/reanalyze`, {
            method: 'POST',
            credentials: 'include',
            headers: {
                'Content-Type': 'application/json',
                ...getCsrfHeaders()
            },
            body: JSON.stringify({
                model: selectedModel || undefined
            })
        });

        if (response.ok) {
            const data = await response.json();
            showToast(data.message || 'Analysis completed.', 'success');
            // Reload analysis - this will update button text appropriately
            loadTickerAnalysis(ticker);
        } else {
            const errorData = await response.json();
            showToast(errorData.error || 'Failed to queue analysis', 'error');
            // Restore original button text on error
            btn.innerHTML = originalHTML;
        }
    } catch (error) {
        console.error('Error requesting analysis:', error);
        showToast('Failed to queue analysis', 'error');
        // Restore original button text on error
        btn.innerHTML = originalHTML;
    } finally {
        btn.disabled = false;
        // Note: If successful, loadTickerAnalysis will update button text
        // If error, we already restored it above
    }
}

// Helper to escape HTML
function escapeHtml(text: string | null | undefined): string {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function sanitizeHttpUrl(rawUrl: string | null | undefined): string {
    if (!rawUrl) return '';
    try {
        const parsed = new URL(rawUrl, window.location.origin);
        if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
            return '';
        }
        return parsed.toString();
    } catch {
        return '';
    }
}

function isStaleLoad(expectedLoadSeq: number | undefined, ticker: string): boolean {
    if (ticker !== currentTicker) return true;
    if (expectedLoadSeq === undefined) return false;
    return expectedLoadSeq !== loadSeq;
}

// Helper to show toast notifications
function showToast(message: string, type: 'success' | 'error' | 'info' = 'info'): void {
    // Simple toast implementation - you can enhance this
    const toast = document.createElement('div');
    toast.className = `fixed top-4 right-4 px-4 py-2 rounded shadow-lg z-50 border ${type === 'success' ? 'bg-theme-success-bg text-theme-success-text border-theme-success-text' :
        type === 'error' ? 'bg-theme-error-bg text-theme-error-text border-theme-error-text' :
            'bg-theme-info-bg text-theme-info-text border-theme-info-text'
        }`;
    toast.textContent = message;
    document.body.appendChild(toast);
    setTimeout(() => {
        toast.remove();
    }, 5000);
}

// Make toggleSummary available globally
(window as any).toggleSummary = toggleSummary;

function showPlaceholder(): void {
    const placeholder = document.getElementById('placeholder-message');
    if (placeholder) placeholder.classList.remove('hidden');
    hideAllSections();
}

function hidePlaceholder(): void {
    const placeholder = document.getElementById('placeholder-message');
    if (placeholder) placeholder.classList.add('hidden');
}

function hideAllSections(): void {
    const sections = [
        'basic-info-section',
        'external-links-section',
        'portfolio-section',
        'chart-section',
        'etf-trades-section',
        'research-section',
        'sentiment-section',
        'congress-section',
        'insider-trades-section',
        'watchlist-section',
        'signals-section',
        'ai-analysis-section'
    ];

    sections.forEach(id => {
        const section = document.getElementById(id);
        if (section) section.classList.add('hidden');
    });
}
