export { }; // Ensure file is treated as a module

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
    sentiment?: string;
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
    transaction_date?: string;
    politician?: string;
    chamber?: string;
    type?: string;
    amount?: string;
    party?: string;
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

// Congress trades pagination state
let allCongressTrades: CongressTickerTrade[] = [];
let congressTradesCurrentPage: number = 0;
const congressTradesPerPage: number = 25;

// Initialize page on load
document.addEventListener('DOMContentLoaded', function (): void {
    // Get ticker from URL query parameter
    const urlParams = new URLSearchParams(window.location.search);
    const tickerParam = urlParams.get('ticker');

    // Load ticker list first
    loadTickerList().then(() => {
        // If ticker in URL, load it
        if (tickerParam) {
            currentTicker = tickerParam.toUpperCase();
            const select = document.getElementById('ticker-select') as HTMLSelectElement | null;
            if (select) {
                select.value = currentTicker;
            }
            loadTickerData(currentTicker);
        } else {
            // Show placeholder
            showPlaceholder();
        }
    });

    // Set up ticker dropdown change handler
    const select = document.getElementById('ticker-select') as HTMLSelectElement | null;
    if (select) {
        select.addEventListener('change', handleTickerSearch);
    }

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

    // Set up signals refresh button
    const signalsRefreshBtn = document.getElementById('signals-refresh-btn') as HTMLButtonElement | null;
    if (signalsRefreshBtn) {
        signalsRefreshBtn.addEventListener('click', () => {
            if (currentTicker) {
                loadSignals(currentTicker, true);
            }
        });
    }
});

// Load ticker list for dropdown
async function loadTickerList(): Promise<void> {
    try {
        const response = await fetch('/api/v2/ticker/list', {
            credentials: 'include'
        });

        if (!response.ok) {
            throw new Error('Failed to load ticker list');
        }

        const data: TickerListResponse = await response.json();
        tickerList = data.tickers || [];

        // Populate dropdown
        const select = document.getElementById('ticker-select') as HTMLSelectElement | null;
        if (!select) return;

        // Clear existing options except first one
        while (select.options.length > 1) {
            select.remove(1);
        }

        // Add tickers
        tickerList.forEach(ticker => {
            const option = document.createElement('option');
            option.value = ticker;
            option.textContent = ticker;
            select.appendChild(option);
        });
    } catch (error) {
        console.error('Error loading ticker list:', error);
    }
}

// Handle ticker search dropdown change
function handleTickerSearch(): void {
    const select = document.getElementById('ticker-select') as HTMLSelectElement | null;
    if (!select) return;

    const selectedTicker = select.value.toUpperCase().trim();

    if (selectedTicker) {
        // Update URL without reload
        const url = new URL(window.location.href);
        url.searchParams.set('ticker', selectedTicker);
        window.history.pushState({}, '', url);

        currentTicker = selectedTicker;
        loadTickerData(selectedTicker);
    } else {
        // Clear URL and show placeholder
        const url = new URL(window.location.href);
        url.searchParams.delete('ticker');
        window.history.pushState({}, '', url);
        showPlaceholder();
    }
}

// Load all ticker data
async function loadTickerData(ticker: string): Promise<void> {
    hideAllSections();
    showLoading();
    hideTickerError();
    hidePlaceholder();

    try {
        const response = await fetch(`/api/v2/ticker/info?ticker=${encodeURIComponent(ticker)}`, {
            credentials: 'include'
        });

        if (!response.ok) {
            const errorData: ErrorResponse = await response.json();
            throw new Error(errorData.error || 'Failed to load ticker data');
        }

        const data: TickerInfoResponse = await response.json();

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
        if (data.watchlist_status) {
            renderWatchlistStatus(data.watchlist_status);
        }

        // Load signals
        await loadSignals(ticker);

        // Load AI analysis
        await loadTickerAnalysis(ticker);

        // Load and render chart
        const checkbox = document.getElementById('solid-lines-checkbox') as HTMLInputElement | null;
        const useSolid = checkbox ? checkbox.checked : false;
        const rangeSelector = document.getElementById('chart-range-selector') as HTMLSelectElement | null;
        const range = rangeSelector ? rangeSelector.value : '3m';
        loadAndRenderChart(ticker, useSolid, range);

        hideLoading();
    } catch (error) {
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
        const placeholder = 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" width="256" height="256"%3E%3C/svg%3E';

        // Clear any existing error handlers and reset state
        tickerLogo.onerror = null;
        tickerLogo.onload = null;

        // Set alt text
        tickerLogo.alt = `${ticker} logo`;

        if (basicInfo.logo_url) {
            // Use higher resolution for larger display (size=256 instead of 64)
            const largeLogoUrl = basicInfo.logo_url.replace('size=64', 'size=256');

            // Handle image load errors gracefully - try fallback (matches dashboard pattern)
            let fallbackAttempted = false;
            tickerLogo.onerror = function () {
                if (fallbackAttempted) {
                    // Already tried fallback, use transparent placeholder
                    tickerLogo.src = placeholder;
                    tickerLogo.onerror = null;
                    return;
                }

                // Mark that we've attempted fallback
                fallbackAttempted = true;

                // Try Yahoo Finance as fallback if Parqet fails
                const yahooUrl = `https://s.yimg.com/cv/apiv2/default/images/logos/${ticker}.png`;
                if (tickerLogo.src !== yahooUrl) {
                    tickerLogo.src = yahooUrl;
                } else {
                    // Same URL, use placeholder
                    tickerLogo.src = placeholder;
                    tickerLogo.onerror = null;
                }
            };

            // Set src AFTER error handler is attached
            tickerLogo.classList.remove('hidden');
            tickerLogo.src = largeLogoUrl;
        } else {
            // No logo URL provided, show placeholder
            tickerLogo.classList.remove('hidden');
            tickerLogo.src = placeholder;
        }
    }

    if (sector) sector.textContent = basicInfo.sector || 'N/A';
    if (industry) industry.textContent = basicInfo.industry || 'N/A';
    if (currency) currency.textContent = basicInfo.currency || 'USD';

    if (exchangeInfo) {
        if (basicInfo.exchange && basicInfo.exchange !== 'N/A') {
            exchangeInfo.textContent = `Exchange: ${basicInfo.exchange}`;
            exchangeInfo.style.display = 'block';
        } else {
            exchangeInfo.style.display = 'none';
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
        const response = await fetch(`/api/v2/ticker/external-links?ticker=${encodeURIComponent(basicInfo.ticker)}${exchange ? `&exchange=${encodeURIComponent(exchange)}` : ''}`, {
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
                if (!latestTickerPositions[fund] || (pos.date && pos.date > (latestTickerPositions[fund].date || ''))) {
                    latestTickerPositions[fund] = pos;
                }
            });

            Object.values(latestTickerPositions).forEach(pos => {
                const row = document.createElement('tr');
                row.innerHTML = `
                    <td class="px-6 py-4 whitespace-nowrap text-sm text-text-primary">${pos.fund || 'N/A'}</td>
                    <td class="px-6 py-4 whitespace-nowrap text-sm text-text-primary">${formatNumber(pos.shares || 0, 2)}</td>
                    <td class="px-6 py-4 whitespace-nowrap text-sm text-text-primary">${formatCurrency(pos.price || 0)}</td>
                    <td class="px-6 py-4 whitespace-nowrap text-sm text-text-primary">${formatCurrency(pos.cost_basis || 0)}</td>
                    <td class="px-6 py-4 whitespace-nowrap text-sm ${(pos.pnl || 0) >= 0 ? 'text-theme-success-text' : 'text-theme-error-text'}">${formatCurrency(pos.pnl || 0)}</td>
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

            portfolioData.trades.slice(0, 20).forEach(trade => {
                const row = document.createElement('tr');
                row.innerHTML = `
                    <td class="px-6 py-4 whitespace-nowrap text-sm text-text-primary">${formatDate(trade.date)}</td>
                    <td class="px-6 py-4 whitespace-nowrap text-sm text-text-primary">${trade.action || 'N/A'}</td>
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
async function loadAndRenderChart(ticker: string, useSolid: boolean, range: string = '3m'): Promise<void> {
    // Show loading indicator
    const chartLoading = document.getElementById('chart-loading');
    const chartContainer = document.getElementById('chart-container');

    if (!chartContainer || !chartLoading) return;

    // Clear any existing chart
    chartContainer.innerHTML = '';
    chartLoading.classList.remove('hidden');

    // Show chart section (but with loading indicator)
    const chartSection = document.getElementById('chart-section');
    if (chartSection) chartSection.classList.remove('hidden');

    try {
        // Detect actual theme from page
        const htmlElement = document.documentElement;
        const dataTheme = htmlElement.getAttribute('data-theme') || 'system';
        let theme: string = 'light'; // default

        // For specialized themes, pass them directly to the backend
        if (dataTheme === 'midnight-tokyo' || dataTheme === 'abyss') {
            theme = dataTheme;
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

        const response = await fetch(`/api/v2/ticker/chart?ticker=${encodeURIComponent(ticker)}&use_solid=${useSolid}&theme=${encodeURIComponent(theme)}&range=${encodeURIComponent(range)}`, {
            credentials: 'include'
        });

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

        // Validate chart data structure
        if (!chartData || !chartData.data || !chartData.layout) {
            throw new Error('Invalid chart data received from server');
        }

        // Render with Plotly
        const Plotly = (window as any).Plotly;
        if (Plotly) {
            Plotly.newPlot('chart-container', chartData.data, chartData.layout, { responsive: true });
        }

        // Hide loading indicator AFTER successful rendering
        chartLoading.classList.add('hidden');
        chartLoading.style.display = 'none';

        // Load price history for metrics
        loadPriceHistoryMetrics(ticker, range);

        // Load ETF holding trades for table
        loadEtfTrades(ticker, range);
    } catch (error) {
        console.error('Error loading chart:', error);
        // Hide loading indicator
        chartLoading.classList.add('hidden');
        // Show error message to user
        const errorMessage = error instanceof Error ? error.message : 'Unknown error';
        showTickerError(`Failed to load chart: ${errorMessage}`);
        // Hide chart section on error
        const chartSection = document.getElementById('chart-section');
        if (chartSection) chartSection.classList.add('hidden');
    }
}

// Load ETF holding trades for table
async function loadEtfTrades(ticker: string, range: string = '3m'): Promise<void> {
    try {
        const response = await fetch(`/api/v2/ticker/etf-trades?ticker=${encodeURIComponent(ticker)}&range=${encodeURIComponent(range)}`, {
            credentials: 'include'
        });

        if (!response.ok) {
            throw new Error(`Failed to load ETF trades (${response.status})`);
        }

        const data = await response.json();
        renderEtfTrades((data && data.data) ? data.data : []);
    } catch (error) {
        console.error('Error loading ETF trades:', error);
        renderEtfTrades([]);
    }
}

function renderEtfTrades(trades: EtfHoldingTrade[]): void {
    const section = document.getElementById('etf-trades-section');
    const tbody = document.getElementById('etf-trades-tbody');
    const emptyState = document.getElementById('etf-trades-empty');
    const countEl = document.getElementById('etf-trades-count');

    if (!section || !tbody || !emptyState || !countEl) return;

    tbody.innerHTML = '';
    const hasTrades = Array.isArray(trades) && trades.length > 0;

    if (!hasTrades) {
        section.classList.remove('hidden');
        emptyState.classList.remove('hidden');
        countEl.textContent = '0 records';
        return;
    }

    emptyState.classList.add('hidden');
    section.classList.remove('hidden');
    countEl.textContent = `${trades.length} record${trades.length === 1 ? '' : 's'}`;

    trades.forEach(trade => {
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
}

// Load price history for metrics
async function loadPriceHistoryMetrics(ticker: string, range: string = '3m'): Promise<void> {
    try {
        // Convert range to days
        const rangeDays: { [key: string]: number } = {
            '3m': 90,
            '6m': 180,
            '1y': 365,
            '2y': 730,
            '5y': 1825
        };
        const days = rangeDays[range] || 90;

        // Update metric label based on range
        const changeLabelEl = document.querySelector('#chart-metrics .metric-card:last-child .text-sm');
        if (changeLabelEl) {
            const rangeLabels: { [key: string]: string } = {
                '3m': 'Change (3M)',
                '6m': 'Change (6M)',
                '1y': 'Change (1Y)',
                '2y': 'Change (2Y)',
                '5y': 'Change (5Y)'
            };
            changeLabelEl.textContent = rangeLabels[range] || 'Change (3M)';
        }

        const response = await fetch(`/api/v2/ticker/price-history?ticker=${encodeURIComponent(ticker)}&days=${days}`, {
            credentials: 'include'
        });

        if (!response.ok) {
            return;
        }

        const data: PriceHistoryData = await response.json();
        const prices = data.data || [];

        if (prices.length > 0) {
            const firstPrice = prices[0].price || 0;
            const lastPrice = prices[prices.length - 1].price || 0;
            const priceChange = lastPrice - firstPrice;
            const priceChangePct = firstPrice > 0 ? (priceChange / firstPrice * 100) : 0;

            const firstPriceEl = document.getElementById('first-price');
            const lastPriceEl = document.getElementById('last-price');
            const changeEl = document.getElementById('price-change');

            if (firstPriceEl) firstPriceEl.textContent = formatCurrency(firstPrice);
            if (lastPriceEl) lastPriceEl.textContent = formatCurrency(lastPrice);
            if (changeEl) {
                changeEl.textContent = `${priceChangePct >= 0 ? '+' : ''}${priceChangePct.toFixed(2)}%`;
                changeEl.className = `text-xl font-semibold ${priceChangePct >= 0 ? 'text-theme-success-text' : 'text-theme-error-text'}`;
            }
        }
    } catch (error) {
        console.error('Error loading price history metrics:', error);
    }
}

// Render research articles
function renderResearchArticles(articles: ResearchArticle[]): void {
    if (!articles || articles.length === 0) {
        return;
    }

    const section = document.getElementById('research-section');
    if (!section) return;

    section.classList.remove('hidden');

    const countEl = document.getElementById('research-count');
    if (countEl) countEl.textContent = `Found ${articles.length} articles mentioning ${currentTicker} (last 30 days)`;

    const list = document.getElementById('research-articles-list');
    if (!list) return;

    list.innerHTML = '';

    articles.slice(0, 10).forEach(article => {
        const articleDiv = document.createElement('div');
        articleDiv.className = 'border-b border-gray-200 py-4';

        const title = article.title || 'Untitled';
        const summary = article.summary || '';
        const url = article.url || '#';
        const source = article.source || 'Unknown';
        const publishedAt = formatDate(article.published_at);
        const sentiment = article.sentiment || 'N/A';

        const summaryId = `summary-${article.id || Math.random().toString(36).substr(2, 9)}`;
        const isLongSummary = summary.length > 500;
        const shortSummary = isLongSummary ? summary.substring(0, 500) + '...' : summary;

        articleDiv.innerHTML = `
            <details class="cursor-pointer">
                <summary class="font-semibold text-accent hover:text-accent-hover">${title}</summary>
                <div class="mt-2 pl-4">
                    <div id="${summaryId}-short" class="text-text-primary mb-2">${shortSummary}</div>
                    ${isLongSummary ? `
                        <div id="${summaryId}-full" class="hidden text-text-primary mb-2 whitespace-pre-wrap">${summary}</div>
                        <button onclick="window.toggleSummary('${summaryId}')" class="text-accent hover:text-accent-hover text-sm font-medium mb-2">
                            <span id="${summaryId}-toggle">Show Full Summary</span>
                        </button>
                    ` : ''}
                    <div class="flex justify-between items-center text-sm text-text-secondary">
                        <div>
                            <span>Source: ${source}</span>
                            ${publishedAt ? `<span class="ml-4">Published: ${publishedAt}</span>` : ''}
                            ${sentiment !== 'N/A' ? `<span class="ml-4">Sentiment: ${sentiment}</span>` : ''}
                        </div>
                        <a href="${url}" target="_blank" rel="noopener noreferrer" class="text-accent hover:text-accent-hover">Read Full Article →</a>
                    </div>
                </div>
            </details>
        `;
        list.appendChild(articleDiv);
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

            sentiment.latest_metrics.forEach(metric => {
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
        return;
    }

    // Store all trades for pagination
    allCongressTrades = trades;
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
        row.innerHTML = `
            <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900 dark:text-white">${formatDate(trade.transaction_date)}</td>
            <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900 dark:text-white">${trade.politician || 'N/A'}</td>
            <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900 dark:text-white">${trade.chamber || 'N/A'}</td>
            <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900 dark:text-white">${trade.type || 'N/A'}</td>
            <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900 dark:text-white">${trade.amount || 'N/A'}</td>
            <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900 dark:text-white">${trade.party || 'N/A'}</td>
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
async function loadSignals(ticker: string, forceRefresh: boolean = false): Promise<void> {
    try {
        const section = document.getElementById('signals-section');
        if (section) section.classList.remove('hidden');
        const updatedEl = document.getElementById('signals-last-updated');
        if (updatedEl) updatedEl.textContent = '-';
        setSignalsLoading(true, forceRefresh ? 'Refreshing signals...' : 'Loading signals...');
        const aiParam = forceRefresh ? 'include_ai=1' : 'include_ai=0';
        const response = await fetch(`/api/signals/analyze/${ticker}?${aiParam}`, {
            credentials: 'include'
        });
        if (!response.ok) {
            if (response.status === 404) {
                // No price data available for signals
                setSignalsLoading(false, 'No price data available');
                return;
            }
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        const result = await response.json();
        if (result.success && result.data) {
            renderSignals(result.data);
        } else {
            setSignalsLoading(false, 'No signals available');
            return;
        }
        setSignalsLoading(false, '');
    } catch (error) {
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
        let badgeClass = 'px-4 py-2 rounded-lg font-semibold ';
        let badgeText = overallSignal;

        switch (overallSignal) {
            case 'BUY':
                badgeClass += 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200';
                break;
            case 'SELL':
                badgeClass += 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200';
                break;
            case 'WATCH':
                badgeClass += 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200';
                break;
            default:
                badgeClass += 'bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-200';
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
                fearClass += 'text-red-600 dark:text-red-400';
                break;
            case 'HIGH':
                fearClass += 'text-orange-600 dark:text-orange-400';
                break;
            case 'MODERATE':
                fearClass += 'text-yellow-600 dark:text-yellow-400';
                break;
            default:
                fearClass += 'text-green-600 dark:text-green-400';
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
                recClass += 'text-red-600 dark:text-red-400';
                break;
            case 'RISKY':
                recClass += 'text-orange-600 dark:text-orange-400';
                break;
            case 'CAUTION':
                recClass += 'text-yellow-600 dark:text-yellow-400';
                break;
            default:
                recClass += 'text-green-600 dark:text-green-400';
        }
        recommendationEl.className = recClass;
        recommendationEl.textContent = recommendation;
    }

    // AI explanation
    const explanationEl = document.getElementById('signals-explanation');
    if (explanationEl) {
        if (signals.explanation) {
            explanationEl.textContent = signals.explanation;
        } else {
            explanationEl.innerHTML = '<span class="text-gray-500 dark:text-gray-400">No AI explanation available yet.</span>';
        }
    }
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
async function loadTickerAnalysis(ticker: string): Promise<void> {
    try {
        const response = await fetch(`/api/v2/ticker/${ticker}/analysis`, {
            credentials: 'include'
        });

        if (!response.ok) {
            if (response.status === 404) {
                // No analysis available yet
                return;
            }
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        const analysis: TickerAnalysis | null = await response.json();
        if (analysis) {
            renderTickerAnalysis(analysis, ticker);
        }
    } catch (error) {
        console.error('Error loading ticker analysis:', error);
        // Don't show error to user - analysis is optional
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

    // Render debug panel if input_context exists
    if (analysis.input_context) {
        renderDebugPanel(analysis.input_context);
    }

    // Setup re-analyze button
    const reanalyzeBtn = document.getElementById('reanalyze-btn');
    if (reanalyzeBtn) {
        reanalyzeBtn.onclick = () => requestReanalysis(ticker);
    }
}

// Render debug panel with AI input context
function renderDebugPanel(inputContext: string): void {
    const container = document.getElementById('ai-debug-container');
    if (!container) return;

    container.innerHTML = `
        <details class="border border-gray-200 dark:border-gray-700 rounded-lg">
            <summary class="cursor-pointer p-3 bg-gray-50 dark:bg-gray-800 rounded-t-lg text-sm font-medium text-text-primary">
                🔍 Debug: AI Input Context (click to expand)
            </summary>
            <pre class="p-4 bg-gray-100 dark:bg-gray-900 text-xs overflow-auto max-h-96 whitespace-pre-wrap text-text-primary">${escapeHtml(inputContext)}</pre>
        </details>
    `;
}

// Request re-analysis
async function requestReanalysis(ticker: string): Promise<void> {
    const btn = document.getElementById('reanalyze-btn') as HTMLButtonElement;
    if (!btn) return;

    const originalText = btn.textContent;
    btn.disabled = true;
    btn.textContent = 'Queuing...';

    try {
        const response = await fetch(`/api/v2/ticker/${ticker}/reanalyze`, {
            method: 'POST',
            credentials: 'include'
        });

        if (response.ok) {
            const data = await response.json();
            showToast(data.message || 'Re-analysis queued. Refresh in a few minutes.', 'success');
            // Refresh analysis after a delay
            setTimeout(() => {
                loadTickerAnalysis(ticker);
            }, 5000);
        } else {
            const errorData = await response.json();
            showToast(errorData.error || 'Failed to queue re-analysis', 'error');
        }
    } catch (error) {
        console.error('Error requesting re-analysis:', error);
        showToast('Failed to queue re-analysis', 'error');
    } finally {
        btn.disabled = false;
        btn.textContent = originalText || '🔄 Re-Analyze';
    }
}

// Helper to escape HTML
function escapeHtml(text: string | null | undefined): string {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Helper to show toast notifications
function showToast(message: string, type: 'success' | 'error' | 'info' = 'info'): void {
    // Simple toast implementation - you can enhance this
    const toast = document.createElement('div');
    toast.className = `fixed top-4 right-4 px-4 py-2 rounded shadow-lg z-50 ${
        type === 'success' ? 'bg-green-500 text-white' :
        type === 'error' ? 'bg-red-500 text-white' :
        'bg-blue-500 text-white'
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
        'watchlist-section',
        'signals-section',
        'ai-analysis-section'
    ];

    sections.forEach(id => {
        const section = document.getElementById(id);
        if (section) section.classList.add('hidden');
    });
}
