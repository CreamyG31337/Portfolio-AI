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

interface WatchlistStatus {
    is_active?: boolean;
    priority_tier?: string;
    source?: string;
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
    
    // Display logo if available (bigger size for ticker details page)
    if (tickerLogo && basicInfo.logo_url) {
        tickerLogo.src = basicInfo.logo_url;
        tickerLogo.alt = `${basicInfo.ticker || ''} logo`;
        tickerLogo.classList.remove('hidden');
        // Handle image load errors gracefully - try fallback
        tickerLogo.onerror = function() {
            // Try Yahoo Finance as fallback if Parqet fails
            const ticker = basicInfo.ticker || '';
            const yahooUrl = `https://s.yimg.com/cv/apiv2/default/images/logos/${ticker}.png`;
            if (tickerLogo.src !== yahooUrl) {
                tickerLogo.src = yahooUrl;
            } else {
                // Both failed, hide the image
                tickerLogo.classList.add('hidden');
            }
        };
    } else if (tickerLogo) {
        tickerLogo.classList.add('hidden');
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
            link.className = 'block p-2 no-underline text-inherit rounded hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors';
            link.textContent = name;
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
                    <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900">${pos.fund || 'N/A'}</td>
                    <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900">${formatNumber(pos.shares || 0, 2)}</td>
                    <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900">${formatCurrency(pos.price || 0)}</td>
                    <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900">${formatCurrency(pos.cost_basis || 0)}</td>
                    <td class="px-6 py-4 whitespace-nowrap text-sm ${(pos.pnl || 0) >= 0 ? 'text-green-600' : 'text-red-600'}">${formatCurrency(pos.pnl || 0)}</td>
                    <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">${formatDate(pos.date)}</td>
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
                    <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900">${formatDate(trade.date)}</td>
                    <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900">${trade.action || 'N/A'}</td>
                    <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900">${formatNumber(trade.shares || 0, 2)}</td>
                    <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900">${formatCurrency(trade.price || 0)}</td>
                    <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900">${trade.fund || 'N/A'}</td>
                    <td class="px-6 py-4 text-sm text-gray-500">${(trade.reason || 'N/A').substring(0, 50)}</td>
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
                changeEl.className = `text-xl font-semibold ${priceChangePct >= 0 ? 'text-green-600' : 'text-red-600'}`;
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
                <summary class="font-semibold text-blue-600 hover:text-blue-800">${title}</summary>
                <div class="mt-2 pl-4">
                    <div id="${summaryId}-short" class="text-gray-700 mb-2">${shortSummary}</div>
                    ${isLongSummary ? `
                        <div id="${summaryId}-full" class="hidden text-gray-700 mb-2 whitespace-pre-wrap">${summary}</div>
                        <button onclick="window.toggleSummary('${summaryId}')" class="text-blue-600 hover:text-blue-800 text-sm font-medium mb-2">
                            <span id="${summaryId}-toggle">Show Full Summary</span>
                        </button>
                    ` : ''}
                    <div class="flex justify-between items-center text-sm text-gray-500">
                        <div>
                            <span>Source: ${source}</span>
                            ${publishedAt ? `<span class="ml-4">Published: ${publishedAt}</span>` : ''}
                            ${sentiment !== 'N/A' ? `<span class="ml-4">Sentiment: ${sentiment}</span>` : ''}
                        </div>
                        <a href="${url}" target="_blank" rel="noopener noreferrer" class="text-blue-600 hover:text-blue-800">Read Full Article →</a>
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
                    <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900">${(metric.platform || 'N/A').charAt(0).toUpperCase() + (metric.platform || '').slice(1)}</td>
                    <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900">${metric.sentiment_label || 'N/A'}</td>
                    <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900">${(metric.sentiment_score || 0).toFixed(2)}</td>
                    <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900">${metric.volume || 0}</td>
                    <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-900">${metric.bull_bear_ratio !== null && metric.bull_bear_ratio !== undefined ? metric.bull_bear_ratio.toFixed(2) : 'N/A'}</td>
                    <td class="px-6 py-4 whitespace-nowrap text-sm text-gray-500">${formatDate(metric.created_at)}</td>
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

                let alertClass = 'bg-blue-100 border-blue-400 text-blue-700';
                if (sentimentLabel === 'EUPHORIC') {
                    alertClass = 'bg-green-100 border-green-400 text-green-700';
                } else if (sentimentLabel === 'FEARFUL') {
                    alertClass = 'bg-red-100 border-red-400 text-red-700';
                } else if (sentimentLabel === 'BULLISH') {
                    alertClass = 'bg-blue-100 border-blue-400 text-blue-700';
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

    const section = document.getElementById('congress-section');
    if (!section) return;

    section.classList.remove('hidden');

    const countEl = document.getElementById('congress-count');
    if (countEl) countEl.textContent = `Found ${trades.length} trades by politicians`;

    const tbody = document.getElementById('congress-tbody');
    if (!tbody) return;

    tbody.innerHTML = '';

    // Show all trades (no limit since we're fetching all historical trades)
    trades.forEach(trade => {
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
        const response = await fetch(`/api/signals/analyze/${ticker}${forceRefresh ? '?refresh=1' : ''}`, {
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
                badgeClass += 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200';
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
        'research-section',
        'sentiment-section',
        'congress-section',
        'watchlist-section',
        'signals-section'
    ];

    sections.forEach(id => {
        const section = document.getElementById(id);
        if (section) section.classList.add('hidden');
    });
}
