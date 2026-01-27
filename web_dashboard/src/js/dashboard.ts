/**
 * Dashboard V2 - Matches dashboard.html template
 * Uses /api/dashboard/* endpoints
 * 
 * IMPORTANT: This is a TypeScript SOURCE file.
 * - Edit this file: web_dashboard/src/js/dashboard.ts
 * - Compiled output: web_dashboard/static/js/dashboard.js (auto-generated)
 * - DO NOT edit the compiled .js file - it will be overwritten on build
 * - Run `npm run build:ts` to compile changes
 * 
 * See web_dashboard/src/js/README.md for development guidelines.
 */

// Make this a module
export { };

import { FormatterCache } from './formatters.js';

// Global types are declared in globals.d.ts

console.log('[Dashboard] dashboard.ts file loaded and executing...');

// Type definitions
interface DashboardSummary {
    total_value: number;
    cash_balance: number;
    day_change: number;
    day_change_pct: number;
    unrealized_pnl: number;
    unrealized_pnl_pct: number;
    display_currency: string;
    thesis?: {
        title: string;
        overview: string;
        pillars?: Array<{
            name: string;
            allocation: string;
            thesis: string;
        }>;
    };
    investor_count?: number;
    holdings_count?: number;
    first_trade_date?: string | null;
    from_cache: boolean;
    processing_time: number;
}

interface DividendData {
    metrics: {
        total_dividends: number;
        total_us_tax: number;
        largest_dividend: number;
        largest_ticker: string;
        reinvested_shares: number;
        payout_events: number;
    };
    log: Array<{
        date: string;
        ticker: string;
        company_name?: string;
        type: string;
        amount: number;
        gross: number;
        _logo_url?: string;
        tax: number;
        shares: number;
        drip_price: number;
    }>;
    currency: string;
}

interface PerformanceChartData {
    data: any[]; // Plotly trace data
    layout: any; // Plotly layout
}

interface AllocationChartData {
    data: any[]; // Plotly trace data
    layout: any; // Plotly layout
}

interface PnlChartData {
    data: any[]; // Plotly trace data
    layout: any; // Plotly layout
}

interface IndividualHoldingsChartData {
    data: any[]; // Plotly trace data
    layout: any; // Plotly layout
    metadata?: {
        num_stocks: number;
        sectors: string[];
        industries: string[];
        days: number;
        filter: string;
    };
}

interface HoldingsData {
    data: Array<{
        ticker: string;
        name: string;
        sector: string;
        quantity: number;
        price: number;
        value: number;
        day_change: number;
        day_change_pct: number;
        total_return: number;
        total_return_pct: number;
        _logo_url?: string;
    }>;
}

interface ActivityData {
    data: Array<{
        date: string;
        ticker: string;
        company_name?: string | null;
        action: 'BUY' | 'SELL' | 'DRIP';
        reason?: string | null;
        shares: number;
        price: number;
        pnl?: number | null;
        amount: number;
        display_amount: number;
        _logo_url?: string;
    }>;
}

interface MoverItem {
    ticker: string;
    company_name?: string;
    daily_pnl_pct?: number;
    daily_pnl?: number;
    five_day_pnl_pct?: number;
    five_day_pnl?: number;
    total_return_pct?: number;
    total_pnl?: number;
    current_price?: number;
    market_value?: number;
    _logo_url?: string;
}

interface MoversData {
    gainers: MoverItem[];
    losers: MoverItem[];
    display_currency: string;
    processing_time: number;
}

interface ExchangeRateData {
    current_rate: number | null;
    rate_label: string;
    rate_help: string;
    inverse: boolean;
    chart: AllocationChartData | null;
}

interface Fund {
    name: string;
}

// Global state
const state = {
    currentFund: typeof window !== 'undefined' && window.INITIAL_FUND ? window.INITIAL_FUND : '',
    timeRange: 'ALL' as '1M' | '3M' | 'ALL',
    useSolidLines: false, // Solid lines checkbox state
    pnlChartView: 'top_bottom' as 'top_bottom' | 'winners' | 'losers',
    charts: {} as Record<string, any>, // Charts now use Plotly (no longer ApexCharts)
    gridApi: null as any, // AG Grid API
    // Individual holdings state
    showIndividualHoldings: false,
    individualHoldingsDays: 7,
    individualHoldingsFilter: 'all',
    // Exchange rate state
    inverseExchangeRate: false
};

// Helper to get effective theme
function getEffectiveTheme(): string {
    const htmlElement = document.documentElement;
    const dataTheme = htmlElement.getAttribute('data-theme') || 'system';

    if (dataTheme === 'dark' || dataTheme === 'light' || dataTheme === 'midnight-tokyo' || dataTheme === 'abyss') {
        return dataTheme;
    }

    if (dataTheme === 'system') {
        // For 'system', check if page is actually in dark mode via CSS
        const bodyBg = window.getComputedStyle(document.body).backgroundColor;
        const isDark = bodyBg && (
            bodyBg.includes('rgb(31, 41, 55)') ||  // --bg-primary dark
            bodyBg.includes('rgb(17, 24, 39)') ||  // --bg-secondary dark
            bodyBg.includes('rgb(55, 65, 81)')     // --bg-tertiary dark
        );
        return isDark ? 'dark' : 'light';
    }

    return 'light'; // default
}

// Initialize theme sync for charts
function initThemeSync(): void {
    // Import chart theme utilities
    const themeManager = (window as Window & { themeManager?: { addListener: (callback: (theme: string) => void) => void } }).themeManager;
    if (themeManager) {
        themeManager.addListener((theme: string) => {
            console.log('[Dashboard] Theme changed, refreshing charts...', { theme });
            // Update AG Grid theme
            updateGridTheme();
            // Re-fetch charts with new theme
            fetchPerformanceChart().catch(err => console.error('[Dashboard] Error refreshing performance chart on theme change:', err));
            fetchSectorChart().catch(err => console.error('[Dashboard] Error refreshing sector chart on theme change:', err));
            fetchCurrencyChart().catch(err => console.error('[Dashboard] Error refreshing currency chart on theme change:', err));
            fetchExchangeRateData().catch(err => console.error('[Dashboard] Error refreshing exchange rate chart on theme change:', err));
            // Refresh individual holdings chart if visible
            if (state.showIndividualHoldings) {
                fetchIndividualHoldingsChart().catch(err => console.error('[Dashboard] Error refreshing individual holdings chart on theme change:', err));
            }
        });
    } else {
        console.warn('[Dashboard] ThemeManager not found. Chart theme synchronization disabled.');
    }
}

// Initialize
document.addEventListener('DOMContentLoaded', (): void => {
    console.log('[Dashboard] DOMContentLoaded event fired, initializing dashboard...');

    // Init components
    initTimeDisplay();
    initFundSelector();
    initTimeRangeControls();
    initSolidLinesCheckbox();
    initIndividualHoldingsControls();
    initExchangeRateControls();
    initPnlChartControls();
    initGrid(); // Initialize empty grid
    initThemeSync(); // Initialize theme synchronization

    // Fetch Data
    refreshDashboard();

    // Auto-refresh every 60s (optional)
    // setInterval(refreshDashboard, 60000);
});

// --- Initialization Functions ---

async function initTimeDisplay(): Promise<void> {
    const el = document.getElementById('last-updated-text');
    if (!el) return;

    try {
        // Fetch latest timestamp from API (same as Streamlit)
        const fund = state.currentFund || '';
        const response = await fetch(`/api/dashboard/latest-timestamp?fund=${encodeURIComponent(fund)}`);

        if (response.ok) {
            const data = await response.json();
            if (data.timestamp) {
                // Parse ISO timestamp and format in local timezone with long format
                const timestamp = new Date(data.timestamp);
                const formatted = timestamp.toLocaleString('en-US', {
                    weekday: 'long',
                    year: 'numeric',
                    month: 'long',
                    day: 'numeric',
                    hour: 'numeric',
                    minute: '2-digit',
                    second: '2-digit',
                    hour12: true
                });
                el.textContent = `Last updated: ${formatted}`;
                return;
            }
        }
    } catch (error) {
        console.warn('[Dashboard] Failed to fetch latest timestamp:', error);
    }

    // Fallback to current time if API fails
    const now = new Date();
    const formatted = now.toLocaleString('en-US', {
        weekday: 'long',
        year: 'numeric',
        month: 'long',
        day: 'numeric',
        hour: 'numeric',
        minute: '2-digit',
        second: '2-digit',
        hour12: true
    });
    el.textContent = 'Last updated: ' + formatted;
}

async function initFundSelector(): Promise<void> {
    const selector = document.getElementById('global-fund-select') as HTMLSelectElement | null;
    console.log('[Dashboard] Initializing navigation fund selector...', {
        found: !!selector,
        current_state_fund: state.currentFund
    });

    if (!selector) {
        console.warn('[Dashboard] Global fund selector not found in sidebar!');
        return;
    }

    // Read fund from URL parameter first (for persistence across refreshes)
    const urlParams = new URLSearchParams(window.location.search);
    const urlFund = urlParams.get('fund');

    if (urlFund) {
        // URL parameter takes precedence
        state.currentFund = urlFund;
        selector.value = urlFund;
        console.log('[Dashboard] Initial state set from URL parameter:', state.currentFund);
    } else if (!state.currentFund) {
        // Fall back to selector value if no URL param and no state
        state.currentFund = selector.value;
        console.log('[Dashboard] Initial state set from selector value:', state.currentFund);
    } else {
        // Sync selector with state (e.g. if set from INITIAL_FUND)
        if (selector.value !== state.currentFund) {
            console.log('[Dashboard] Syncing selector value to state:', state.currentFund);
            selector.value = state.currentFund;
        }
    }

    // Listen for changes
    selector.addEventListener('change', (e: Event): void => {
        const target = e.target as HTMLSelectElement;
        state.currentFund = target.value;
        console.log('[Dashboard] Global fund changed to:', state.currentFund);

        // Update URL to persist selection across page refreshes
        const url = new URL(window.location.href);
        if (state.currentFund && state.currentFund.toLowerCase() !== 'all') {
            url.searchParams.set('fund', state.currentFund);
        } else {
            url.searchParams.delete('fund');
        }
        // Use pushState to update URL without page reload
        window.history.pushState({ fund: state.currentFund }, '', url.toString());

        refreshDashboard();
    });
}

function initTimeRangeControls(): void {
    document.querySelectorAll('.range-btn').forEach(btn => {
        btn.addEventListener('click', (e: Event): void => {
            const target = e.target as HTMLElement;

            // Update UI
            document.querySelectorAll('.range-btn').forEach(b => {
                b.classList.remove('active', 'ring-2', 'ring-blue-700', 'text-blue-700', 'z-10');
                b.classList.add('text-gray-900', 'hover:text-blue-700', 'dark:text-white');
                b.setAttribute('aria-pressed', 'false');
            });
            target.classList.add('active', 'ring-2', 'ring-blue-700', 'text-blue-700', 'z-10');
            target.setAttribute('aria-pressed', 'true');

            // Update State
            const range = target.dataset.range as '1M' | '3M' | 'ALL';
            if (range) {
                state.timeRange = range;
                console.log('[Dashboard] Time range changed to:', state.timeRange);

                // Refresh Charts only
                fetchPerformanceChart();
            }
        });
    });
}

function initSolidLinesCheckbox(): void {
    const checkbox = document.getElementById('use-solid-lines') as HTMLInputElement | null;
    if (!checkbox) {
        console.warn('[Dashboard] Solid lines checkbox not found');
        return;
    }

    // Set initial state
    checkbox.checked = state.useSolidLines;

    // Listen for changes
    checkbox.addEventListener('change', (): void => {
        state.useSolidLines = checkbox.checked;
        console.log('[Dashboard] Solid lines changed to:', state.useSolidLines);
        // Refresh performance chart only
        fetchPerformanceChart();
        // Also refresh individual holdings if visible
        if (state.showIndividualHoldings) {
            fetchIndividualHoldingsChart();
        }
    });
}

function initIndividualHoldingsControls(): void {
    const showCheckbox = document.getElementById('show-individual-holdings') as HTMLInputElement | null;
    const container = document.getElementById('individual-holdings-container');
    const rangeButtons = document.querySelectorAll('.individual-range-btn');
    const filterSelect = document.getElementById('individual-stock-filter') as HTMLSelectElement | null;

    if (!showCheckbox || !container) {
        console.warn('[Dashboard] Individual holdings controls not found');
        return;
    }

    // Toggle container visibility
    showCheckbox.addEventListener('change', (): void => {
        state.showIndividualHoldings = showCheckbox.checked;
        if (showCheckbox.checked) {
            container.classList.remove('hidden');
            // Fetch chart if fund is selected (not "All")
            if (state.currentFund && state.currentFund.toLowerCase() !== 'all') {
                fetchIndividualHoldingsChart();
            } else {
                const chartEl = document.getElementById('individual-holdings-chart');
                if (chartEl) {
                    chartEl.innerHTML = '<div class="text-center text-gray-500 py-8">Select a specific fund to view individual stock performance</div>';
                }
            }
        } else {
            container.classList.add('hidden');
        }
    });

    // Date range buttons
    rangeButtons.forEach(btn => {
        btn.addEventListener('click', (e): void => {
            const target = e.currentTarget as HTMLElement;
            const days = parseInt(target.dataset.days || '7', 10);

            // Update visual state
            rangeButtons.forEach(b => {
                b.classList.remove('bg-blue-600', 'text-white');
                b.classList.add('bg-gray-100', 'dark:bg-gray-700', 'text-gray-700', 'dark:text-gray-300');
            });
            target.classList.remove('bg-gray-100', 'dark:bg-gray-700', 'text-gray-700', 'dark:text-gray-300');
            target.classList.add('bg-blue-600', 'text-white');

            // Update state and fetch
            state.individualHoldingsDays = days;
            if (state.showIndividualHoldings && state.currentFund && state.currentFund.toLowerCase() !== 'all') {
                fetchIndividualHoldingsChart();
            }
        });
    });

    // Filter dropdown
    if (filterSelect) {
        filterSelect.addEventListener('change', (): void => {
            state.individualHoldingsFilter = filterSelect.value;
            if (state.showIndividualHoldings && state.currentFund && state.currentFund.toLowerCase() !== 'all') {
                fetchIndividualHoldingsChart();
            }
        });
    }
}

function initExchangeRateControls(): void {
    const checkbox = document.getElementById('inverse-exchange-rate') as HTMLInputElement | null;

    if (!checkbox) {
        console.warn('[Dashboard] Exchange rate toggle not found');
        return;
    }

    // Set initial state from localStorage if available
    const savedPref = localStorage.getItem('inverse_exchange_rate');
    if (savedPref !== null) {
        state.inverseExchangeRate = savedPref === 'true';
        checkbox.checked = state.inverseExchangeRate;
    }

    // Listen for changes
    checkbox.addEventListener('change', (): void => {
        state.inverseExchangeRate = checkbox.checked;
        // Save preference to localStorage
        localStorage.setItem('inverse_exchange_rate', String(checkbox.checked));
        // Refresh exchange rate display
        fetchExchangeRateData();
    });
}

function initPnlChartControls(): void {
    const buttons = document.querySelectorAll<HTMLButtonElement>('.pnl-view-btn');
    if (!buttons.length) {
        return;
    }

    buttons.forEach((button) => {
        button.addEventListener('click', () => {
            const view = button.getAttribute('data-pnl-view') || 'top_bottom';
            if (view === state.pnlChartView) {
                return;
            }
            state.pnlChartView = view as 'top_bottom' | 'winners' | 'losers';
            updatePnlChartViewButtons();
            loadPnlChart(state.currentFund);
        });
    });

    updatePnlChartViewButtons();
}

function updatePnlChartViewButtons(): void {
    const buttons = document.querySelectorAll<HTMLButtonElement>('.pnl-view-btn');
    buttons.forEach((button) => {
        const view = button.getAttribute('data-pnl-view') || 'top_bottom';
        const isActive = view === state.pnlChartView;
        button.setAttribute('aria-pressed', isActive ? 'true' : 'false');
        button.classList.toggle('ring-2', isActive);
        button.classList.toggle('ring-accent', isActive);
        button.classList.toggle('z-10', isActive);
        button.classList.toggle('text-accent', isActive);
    });
}

// Global cache of tickers that don't have logos (to avoid repeated 404s)
const failedLogoCache = new Set<string>();

/**
 * Creates a logo image element with fallback handling.
 * 
 * @param ticker - The ticker symbol
 * @param logoUrl - The primary logo URL (from API)
 * @param options - Optional configuration
 * @returns HTMLImageElement configured with error handling and fallback logic
 */
function createLogoElement(
    ticker: string,
    logoUrl: string,
    options?: {
        className?: string;
        size?: number;
    }
): HTMLImageElement {
    const className = options?.className || 'inline-block w-6 h-6 mr-2 object-contain rounded';
    const size = options?.size || 24;
    const placeholder = `data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}"%3E%3C/svg%3E`;
    
    // Clean ticker for fallback lookup (remove spaces and exchange suffixes)
    const cleanTicker = ticker.replace(/\s+/g, '').replace(/\.(TO|V|CN|TSX|TSXV|NE|NEO)$/i, '');
    const cacheKey = cleanTicker.toUpperCase();
    
    // Create image element
    const img = document.createElement('img');
    img.className = className;
    img.style.verticalAlign = 'middle';
    img.alt = ticker;
    
    // Set up error handler BEFORE setting src
    let fallbackAttempted = false;
    img.onerror = function () {
        if (fallbackAttempted) {
            // Already tried fallback, use transparent placeholder for alignment
            this.src = placeholder;
            this.onerror = null;
            failedLogoCache.add(cacheKey);
            return;
        }
        
        // Mark that we've attempted fallback
        fallbackAttempted = true;
        
        // Try Yahoo Finance fallback
        const yahooUrl = `https://s.yimg.com/cv/apiv2/default/images/logos/${cleanTicker}.png`;
        if (this.src !== yahooUrl) {
            this.src = yahooUrl;
        } else {
            // Same URL, use transparent placeholder for alignment
            this.src = placeholder;
            this.onerror = null;
            failedLogoCache.add(cacheKey);
        }
    };
    
    // Set the src (error handler is already attached)
    if (logoUrl && !failedLogoCache.has(cacheKey)) {
        img.src = logoUrl;
    } else if (!failedLogoCache.has(cacheKey)) {
        // No logo URL provided, try Yahoo Finance directly
        img.src = `https://s.yimg.com/cv/apiv2/default/images/logos/${cleanTicker}.png`;
    } else {
        // Known to fail, use placeholder immediately
        img.src = placeholder;
        img.onerror = null;
    }
    
    return img;
}

// Update AG Grid theme class based on current theme
// Ticker cell renderer - makes ticker clickable
interface AgGridCellRendererParams {
    value: string | null;
    data?: any;
}

interface AgGridCellRenderer {
    init(params: AgGridCellRendererParams): void;
    getGui(): HTMLElement;
}

class TickerCellRenderer implements AgGridCellRenderer {
    private eGui!: HTMLElement;

    init(params: AgGridCellRendererParams): void {
        this.eGui = document.createElement('div');
        this.eGui.style.display = 'flex';
        this.eGui.style.alignItems = 'center';
        this.eGui.style.gap = '6px';

        if (params.value && params.value !== 'N/A') {
            const ticker = params.value;
            const logoUrl = params.data?._logo_url;

            // Check cache first - skip if we know this ticker doesn't have a logo
            const cleanTicker = ticker.replace(/\s+/g, '').replace(/\.(TO|V|CN|TSX|TSXV|NE|NEO)$/i, '');
            const cacheKey = cleanTicker.toUpperCase();

            // Always add logo image (or transparent placeholder) for consistent alignment
            const img = document.createElement('img');
            img.style.width = '24px';
            img.style.height = '24px';
            img.style.objectFit = 'contain';
            img.style.borderRadius = '4px';
            img.style.flexShrink = '0';

            // Check if logo is already known to fail
            if (failedLogoCache.has(cacheKey) || !logoUrl) {
                // Use transparent placeholder for consistent spacing
                img.src = 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" width="24" height="24"%3E%3C/svg%3E';
                img.alt = '';
            } else {
                // Try to load logo
                img.src = logoUrl;
                img.alt = ticker;

                // Handle image load errors gracefully - try fallback
                let fallbackAttempted = false;
                img.onerror = function () {
                    if (fallbackAttempted) {
                        // Already tried fallback, use transparent placeholder for alignment
                        failedLogoCache.add(cacheKey);
                        // Use a transparent 24x24 SVG placeholder to maintain spacing
                        img.src = 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" width="24" height="24"%3E%3C/svg%3E';
                        img.alt = '';
                        img.onerror = null;
                        return;
                    }

                    // Mark that we've attempted fallback
                    fallbackAttempted = true;

                    // Try Yahoo Finance as fallback if Parqet fails
                    const yahooUrl = `https://s.yimg.com/cv/apiv2/default/images/logos/${cleanTicker}.png`;
                    if (img.src !== yahooUrl) {
                        img.src = yahooUrl;
                    } else {
                        // Same URL, use transparent placeholder for alignment
                        failedLogoCache.add(cacheKey);
                        img.src = 'data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" width="24" height="24"%3E%3C/svg%3E';
                        img.alt = '';
                        img.onerror = null;
                    }
                };
            }

            this.eGui.appendChild(img);

            // Add ticker text
            const tickerSpan = document.createElement('span');
            tickerSpan.innerText = ticker;
            tickerSpan.style.color = 'var(--color-accent)';
            tickerSpan.style.fontWeight = 'bold';
            tickerSpan.style.textDecoration = 'underline';
            tickerSpan.style.cursor = 'pointer';
            tickerSpan.addEventListener('click', function (e: Event) {
                e.stopPropagation();
                if (ticker && ticker !== 'N/A') {
                    window.location.href = `/ticker?ticker=${encodeURIComponent(ticker)}`;
                }
            });
            this.eGui.appendChild(tickerSpan);
        } else {
            this.eGui.innerText = params.value || 'N/A';
        }
    }

    getGui(): HTMLElement {
        return this.eGui;
    }
}

function updateGridTheme(): void {
    const gridEl = document.getElementById('holdings-grid');
    if (!gridEl) {
        return;
    }

    const effectiveTheme = getEffectiveTheme();
    const isDark = effectiveTheme === 'dark' || effectiveTheme === 'midnight-tokyo' || effectiveTheme === 'abyss';

    // Update AG Grid theme class
    gridEl.classList.remove('ag-theme-alpine', 'ag-theme-alpine-dark');
    if (isDark) {
        gridEl.classList.add('ag-theme-alpine-dark');
    } else {
        gridEl.classList.add('ag-theme-alpine');
    }
}

function initGrid(): void {
    console.log('[Dashboard] Initializing AG Grid...');
    const gridEl = document.getElementById('holdings-grid');
    if (!gridEl) {
        console.warn('[Dashboard] Holdings grid element not found');
        return;
    }

    // Apply theme before initializing
    updateGridTheme();

    const columnDefs = [
        { field: 'ticker', headerName: 'Ticker', width: 100, minWidth: 80, maxWidth: 120, pinned: 'left', cellRenderer: TickerCellRenderer },
        { field: 'name', headerName: 'Company', flex: 1.5, minWidth: 150, maxWidth: 300 },
        { field: 'sector', headerName: 'Sector', flex: 1, minWidth: 100, maxWidth: 200 },
        { field: 'opened', headerName: 'Opened', width: 100, minWidth: 80, maxWidth: 120 },
        { field: 'shares', headerName: 'Shares', flex: 0.8, minWidth: 90, maxWidth: 130, type: 'numericColumn', valueFormatter: (params: any) => (params.value || 0).toFixed(2) },
        { field: 'avg_price', headerName: 'Avg Price', flex: 0.9, minWidth: 90, maxWidth: 140, type: 'numericColumn', valueFormatter: (params: any) => formatMoney(params.value) },
        { field: 'price', headerName: 'Current', flex: 0.9, minWidth: 90, maxWidth: 140, type: 'numericColumn', valueFormatter: (params: any) => formatMoney(params.value) },
        { field: 'value', headerName: 'Value', flex: 1, minWidth: 100, maxWidth: 160, type: 'numericColumn', valueFormatter: (params: any) => formatMoney(params.value) },
        {
            field: 'total_return',
            headerName: 'Total P&L',
            flex: 1.2,
            minWidth: 130,
            maxWidth: 180,
            type: 'numericColumn',
            valueFormatter: (params: any) => {
                const val = params.value || 0;
                const pct = params.data?.total_return_pct || 0;
                const isNegative = val < 0;
                const absVal = Math.abs(val);
                const absPct = Math.abs(pct);

                if (isNegative) {
                    // Negative: Red color (handled by style), no negative sign
                    return `${formatMoney(absVal)} ${absPct.toFixed(1)}%`;
                } else {
                    // Positive: Green color, no + sign
                    return `${formatMoney(val)} ${pct.toFixed(1)}%`;
                }
            },
            cellStyle: (params: any) => {
                const val = params.value || 0;
                if (val > 0) return { color: '#10b981', fontWeight: 'bold', textAlign: 'right' };
                if (val < 0) return { color: '#ef4444', fontWeight: 'bold', textAlign: 'right' };
                return { textAlign: 'right' };
            }
        },
        {
            field: 'day_change',
            headerName: '1-Day P&L',
            flex: 1.2,
            minWidth: 130,
            maxWidth: 180,
            type: 'numericColumn',
            valueFormatter: (params: any) => {
                const val = params.value || 0;
                const pct = params.data?.day_change_pct || 0;
                const isNegative = val < 0;
                const absVal = Math.abs(val);
                const absPct = Math.abs(pct);

                if (isNegative) {
                    // Negative: Red color (handled by style), no negative sign
                    return `${formatMoney(absVal)} ${absPct.toFixed(1)}%`;
                } else {
                    // Positive: Green color, no + sign
                    return `${formatMoney(val)} ${pct.toFixed(1)}%`;
                }
            },
            cellStyle: (params: any) => {
                const val = params.value || 0;
                if (val > 0) return { color: '#10b981', fontWeight: 'bold', textAlign: 'right' };
                if (val < 0) return { color: '#ef4444', fontWeight: 'bold', textAlign: 'right' };
                return { textAlign: 'right' };
            }
        },
        {
            field: 'five_day_pnl',
            headerName: '5-Day P&L',
            flex: 1.2,
            minWidth: 130,
            maxWidth: 180,
            type: 'numericColumn',
            valueFormatter: (params: any) => {
                const val = params.value || 0;
                const pct = params.data?.five_day_pnl_pct || 0;
                const isNegative = val < 0;
                const absVal = Math.abs(val);
                const absPct = Math.abs(pct);

                if (isNegative) {
                    // Negative: Red color (handled by style), no negative sign
                    return `${formatMoney(absVal)} ${absPct.toFixed(1)}%`;
                } else {
                    // Positive: Green color, no + sign
                    return `${formatMoney(val)} ${pct.toFixed(1)}%`;
                }
            },
            cellStyle: (params: any) => {
                const val = params.value || 0;
                if (val > 0) return { color: '#10b981', fontWeight: 'bold', textAlign: 'right' };
                if (val < 0) return { color: '#ef4444', fontWeight: 'bold', textAlign: 'right' };
                return { textAlign: 'right' };
            }
        },
        { field: 'weight', headerName: 'Weight', flex: 0.6, minWidth: 70, maxWidth: 100, type: 'numericColumn', valueFormatter: (params: any) => (params.value || 0).toFixed(1) + '%' }
    ];

    const gridOptions = {
        columnDefs: columnDefs,
        defaultColDef: {
            sortable: true,
            filter: true,
            resizable: true,
            wrapHeaderText: true,
            autoHeaderHeight: true
        },
        rowData: [],
        animateRows: true
    };

    // agGrid is loaded from CDN and available globally
    if (typeof (window as any).agGrid === 'undefined') {
        console.error('[Dashboard] AG Grid not loaded');
        return;
    }

    const agGrid = (window as any).agGrid;

    // Debug: Log what's available in agGrid
    console.log('[Dashboard] AG Grid object check:', {
        agGrid_available: !!agGrid,
        agGrid_type: typeof agGrid,
        has_createGrid: typeof agGrid.createGrid === 'function',
        has_Grid: typeof agGrid.Grid !== 'undefined',
        agGrid_keys: agGrid ? Object.keys(agGrid).slice(0, 20) : []
    });

    // AG Grid v31+ recommends createGrid() which returns the API directly
    // Check for createGrid first (v31+)
    if (typeof agGrid.createGrid === 'function') {
        console.log('[Dashboard] createGrid() is available, attempting to use it...');
        try {
            const gridApi = agGrid.createGrid(gridEl, gridOptions);
            if (gridApi && typeof gridApi.setRowData === 'function') {
                state.gridApi = gridApi;
                // Set default sort by weight descending (matching console app)
                // AG Grid v31+ uses applyColumnState instead of sortModel
                if (typeof gridApi.applyColumnState === 'function') {
                    gridApi.applyColumnState({
                        state: [{ colId: 'weight', sort: 'desc' }],
                        defaultState: { sort: null }
                    });
                }
                console.log('[Dashboard] AG Grid initialized with createGrid()', {
                    has_api: !!state.gridApi,
                    has_setRowData: typeof state.gridApi.setRowData === 'function',
                    gridApi_type: typeof state.gridApi,
                    gridApi_keys: state.gridApi ? Object.keys(state.gridApi).slice(0, 10) : []
                });
                return; // Success, exit early
            } else {
                console.error('[Dashboard] createGrid() returned invalid API:', {
                    gridApi,
                    has_setRowData: gridApi && typeof gridApi.setRowData === 'function'
                });
            }
        } catch (createError) {
            console.error('[Dashboard] Error creating grid with createGrid():', createError);
        }
    }

    console.error('[Dashboard] AG Grid createGrid() not available', {
        agGrid_available: typeof agGrid !== 'undefined',
        agGrid_keys: agGrid ? Object.keys(agGrid) : [],
        has_createGrid: typeof agGrid.createGrid === 'function'
    });
}

async function refreshDashboard(): Promise<void> {
    console.log('[Dashboard] Starting dashboard refresh...', {
        fund: state.currentFund,
        timeRange: state.timeRange,
        timestamp: new Date().toISOString()
    });

    // Hide any previous errors
    const errorContainer = document.getElementById('dashboard-error-container');
    if (errorContainer) {
        errorContainer.classList.add('hidden');
    }

    const startTime = performance.now();

    try {
        await Promise.all([
            fetchSummary(),
            fetchPerformanceChart(),
            fetchSectorChart(),
            fetchCurrencyChart(),
            fetchExchangeRateData(),
            loadPnlChart(state.currentFund),
            fetchMovers(),
            fetchHoldings(),
            fetchActivity(),
            fetchDividends()
        ]);

        // Refresh individual holdings chart if visible
        if (state.showIndividualHoldings) {
            await fetchIndividualHoldingsChart();
        }

        const duration = performance.now() - startTime;
        console.log('[Dashboard] Dashboard refresh completed successfully', {
            duration: `${duration.toFixed(2)}ms`,
            timestamp: new Date().toISOString()
        });

        // Update Time
        await initTimeDisplay();
    } catch (error) {
        const duration = performance.now() - startTime;
        const traceback = (error as any)?.traceback;
        console.error('[Dashboard] Error refreshing dashboard:', {
            error: error,
            message: error instanceof Error ? error.message : String(error),
            stack: error instanceof Error ? error.stack : undefined,
            traceback: traceback ? 'present' : 'missing',
            duration: `${duration.toFixed(2)}ms`,
            timestamp: new Date().toISOString()
        });
        showDashboardError(error, traceback);
    }
}

/**
 * Extract error information from API response, including traceback if available
 */
function extractErrorInfo(errorData: any): { message: string; traceback?: string } {
    const message = errorData.error || errorData.message || 'Unknown error';
    const traceback = errorData.traceback || undefined;
    return { message, traceback };
}

function showDashboardError(error: unknown, traceback?: string): void {
    const errorContainer = document.getElementById('dashboard-error-container');
    const errorMessage = document.getElementById('dashboard-error-message');

    if (errorContainer && errorMessage) {
        const errorText = error instanceof Error ? error.message : String(error);
        const errorStack = error instanceof Error && error.stack ? `<pre class="mt-2 text-xs overflow-auto bg-gray-100 dark:bg-gray-800 p-2 rounded">${error.stack}</pre>` : '';

        // Include server traceback if available (from API response)
        const serverTraceback = traceback ? `<div class="mt-4"><h4 class="text-sm font-semibold mb-2">Server Stack Trace:</h4><pre class="text-xs overflow-auto bg-gray-100 dark:bg-gray-800 p-2 rounded whitespace-pre-wrap">${traceback}</pre></div>` : '';

        errorMessage.innerHTML = `<p class="font-semibold">${errorText}</p>${errorStack}${serverTraceback}`;
        errorContainer.classList.remove('hidden');
    }
}

// --- Spinner Helpers ---

function showSpinner(spinnerId: string): void {
    let spinner = document.getElementById(spinnerId);
    if (!spinner) {
        // Spinner doesn't exist (might have been removed by Plotly), create it
        const chartEl = document.getElementById(spinnerId.replace('-spinner', ''));
        if (chartEl) {
            spinner = document.createElement('div');
            spinner.id = spinnerId;
            if (spinnerId === 'sector-chart-spinner') {
                spinner.className = 'flex items-center justify-center h-full';
            } else {
                spinner.className = 'absolute inset-0 flex items-center justify-center bg-dashboard-surface z-10';
            }
            spinner.innerHTML = '<div class="animate-spin rounded-full h-12 w-12 border-b-2 border-accent"></div>';
            chartEl.appendChild(spinner);
        } else {
            return; // Can't create spinner without parent element
        }
    }
    spinner.classList.remove('hidden');
}

function hideSpinner(spinnerId: string): void {
    const spinner = document.getElementById(spinnerId);
    if (spinner) {
        spinner.classList.add('hidden');
    }
}

// --- Data Fetching ---

async function fetchSummary(): Promise<void> {
    const url = `/api/dashboard/summary?fund=${encodeURIComponent(state.currentFund)}`;
    const startTime = performance.now();

    console.log('[Dashboard] Fetching summary...', { url, fund: state.currentFund });

    try {
        const response = await fetch(url, { credentials: 'include' });
        const duration = performance.now() - startTime;

        console.log('[Dashboard] Summary response received', {
            status: response.status,
            statusText: response.statusText,
            ok: response.ok,
            duration: `${duration.toFixed(2)}ms`,
            url: url
        });

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({ error: `HTTP ${response.status}: ${response.statusText}` }));
            const errorInfo = extractErrorInfo(errorData);
            console.error('[Dashboard] Summary API error:', {
                status: response.status,
                errorData: errorData,
                traceback: errorInfo.traceback ? 'present' : 'missing',
                url: url
            });
            // Create error with traceback attached
            const error = new Error(errorInfo.message || `HTTP ${response.status}: ${response.statusText}`);
            (error as any).traceback = errorInfo.traceback;
            throw error;
        }

        const data: DashboardSummary = await response.json();
        console.log('[Dashboard] Summary data received', {
            total_value: data.total_value,
            cash_balance: data.cash_balance,
            day_change: data.day_change,
            unrealized_pnl: data.unrealized_pnl,
            display_currency: data.display_currency,
            has_thesis: !!data.thesis,
            has_pillars: !!data.thesis?.pillars,
            investors: data.investor_count,
            holdings: data.holdings_count,
            first_trade_date: data.first_trade_date,
            processing_time: data.processing_time,
            from_cache: data.from_cache
        });

        // Update Metrics
        updateMetric('metric-total-value', data.total_value, data.display_currency, true);
        updateMetric('metric-cash', data.cash_balance, data.display_currency, true);

        updateChangeMetric('metric-day-change', 'metric-day-pct', data.day_change, data.day_change_pct, data.display_currency);
        updateChangeMetric('metric-total-pnl', 'metric-total-pnl-pct', data.unrealized_pnl, data.unrealized_pnl_pct, data.display_currency);

        const currencyEl = document.getElementById('metric-currency');
        if (currencyEl) {
            currencyEl.textContent = data.display_currency;
        }

        // Update Fund Stats & Rates
        if (data.investor_count !== undefined) {
            const investorContainer = document.getElementById('investor-metric-container');
            if (investorContainer) {
                // Hide Investors metric if count <= 1 (single-investor or no-investor funds)
                if (data.investor_count <= 1) {
                    investorContainer.classList.add('hidden');
                } else {
                    investorContainer.classList.remove('hidden');
                    updateMetric('metric-investors', data.investor_count, '', false);
                }
            }
        }
        if (data.holdings_count !== undefined) updateMetric('metric-holdings-count', data.holdings_count, '', false);

        // Update First Trade Date
        if (data.first_trade_date) {
            const firstTradeDateEl = document.getElementById('metric-first-trade-date');
            if (firstTradeDateEl) {
                // Format date as MM/DD/YYYY
                const date = new Date(data.first_trade_date);
                const formattedDate = date.toLocaleDateString('en-US', {
                    year: 'numeric',
                    month: '2-digit',
                    day: '2-digit'
                });
                firstTradeDateEl.textContent = formattedDate;
            }
        } else {
            const firstTradeDateEl = document.getElementById('metric-first-trade-date');
            if (firstTradeDateEl) {
                firstTradeDateEl.textContent = '--';
            }
        }

        // Update Thesis
        const thesisContainer = document.getElementById('thesis-container');
        if (data.thesis && data.thesis.title) {
            if (thesisContainer) {
                thesisContainer.classList.remove('hidden');
            }
            const titleEl = document.getElementById('thesis-title');
            const contentEl = document.getElementById('thesis-content');
            if (titleEl) titleEl.textContent = data.thesis.title;
            if (contentEl) {
                // Use marked.js if available, otherwise plain text
                if (typeof (window as any).marked !== 'undefined') {
                    contentEl.innerHTML = (window as any).marked.parse(data.thesis.overview || '');
                } else {
                    contentEl.textContent = data.thesis.overview || '';
                }
            }
            // Render Pillars
            if (data.thesis.pillars && data.thesis.pillars.length > 0) {
                renderPillars(data.thesis.pillars);
            }
        } else {
            if (thesisContainer) {
                thesisContainer.classList.add('hidden');
            }
        }

    } catch (error) {
        const duration = performance.now() - startTime;
        console.error('[Dashboard] Error fetching summary:', {
            error: error,
            message: error instanceof Error ? error.message : String(error),
            stack: error instanceof Error ? error.stack : undefined,
            url: url,
            fund: state.currentFund,
            duration: `${duration.toFixed(2)}ms`,
            timestamp: new Date().toISOString()
        });

        const errorMsg = error instanceof Error ? error.message : 'Unknown error';
        // Show error in metrics
        const totalValueEl = document.getElementById('metric-total-value');
        const dayChangeEl = document.getElementById('metric-day-change');
        const totalPnlEl = document.getElementById('metric-total-pnl');
        const cashEl = document.getElementById('metric-cash');

        if (totalValueEl) totalValueEl.textContent = 'Error';
        if (dayChangeEl) dayChangeEl.textContent = 'Error';
        if (totalPnlEl) totalPnlEl.textContent = 'Error';
        if (cashEl) cashEl.textContent = 'Error';

        // Show error in UI (include traceback if available)
        const traceback = (error as any)?.traceback;
        showDashboardError(new Error(`Failed to load summary: ${errorMsg}`), traceback);
        throw error; // Re-throw so refreshDashboard can catch it
    }
}

async function fetchPerformanceChart(): Promise<void> {
    // Show spinner
    showSpinner('performance-chart-spinner');

    const theme = getEffectiveTheme();

    // Match Streamlit: use_solid_lines parameter from checkbox
    const url = `/api/dashboard/charts/performance?fund=${encodeURIComponent(state.currentFund)}&range=${state.timeRange}&use_solid=${state.useSolidLines}&theme=${encodeURIComponent(theme)}`;
    const startTime = performance.now();

    console.log('[Dashboard] Fetching performance chart...', { url, fund: state.currentFund, range: state.timeRange, use_solid: state.useSolidLines });

    try {
        const response = await fetch(url, { credentials: 'include' });
        const duration = performance.now() - startTime;

        console.log('[Dashboard] Performance chart response received', {
            status: response.status,
            ok: response.ok,
            duration: `${duration.toFixed(2)}ms`
        });

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({ error: `HTTP ${response.status}: ${response.statusText}` }));
            const errorInfo = extractErrorInfo(errorData);
            console.error('[Dashboard] Performance chart API error:', {
                status: response.status,
                statusText: response.statusText,
                error: errorInfo.message,
                traceback: errorInfo.traceback ? 'present' : 'missing',
                errorData: JSON.stringify(errorData),
                url: url
            });
            const error = new Error(errorInfo.message || `HTTP ${response.status}: ${response.statusText}`);
            (error as any).traceback = errorInfo.traceback;
            throw error;
        }

        const data: PerformanceChartData = await response.json();
        console.log('[Dashboard] Performance chart data received', {
            has_data: !!data.data,
            has_layout: !!data.layout,
            trace_count: data.data ? data.data.length : 0
        });

        renderPerformanceChart(data);
        hideSpinner('performance-chart-spinner');

    } catch (error) {
        hideSpinner('performance-chart-spinner');
        const duration = performance.now() - startTime;
        const errorMsg = error instanceof Error ? error.message : String(error);
        const errorStack = error instanceof Error ? error.stack : undefined;
        console.error('[Dashboard] Error fetching performance chart:', {
            error: errorMsg,
            stack: errorStack,
            url: url,
            duration: `${duration.toFixed(2)}ms`,
            errorObject: JSON.stringify(error, Object.getOwnPropertyNames(error))
        });
        const chartEl = document.getElementById('performance-chart');
        if (chartEl) {
            const traceback = (error as any)?.traceback;
            const tracebackHtml = traceback ? `<details class="mt-2 text-left"><summary class="cursor-pointer text-xs text-gray-600 dark:text-gray-400">Show stack trace</summary><pre class="mt-2 text-xs overflow-auto bg-gray-100 dark:bg-gray-800 p-2 rounded whitespace-pre-wrap">${traceback}</pre></details>` : '';
            chartEl.innerHTML = `<div class="text-center text-red-500 py-8"><p>Error loading chart: ${errorMsg}</p>${tracebackHtml}</div>`;
        }
    }
}

async function fetchSectorChart(): Promise<void> {
    // Show spinner
    showSpinner('sector-chart-spinner');

    const theme = getEffectiveTheme();

    const url = `/api/dashboard/charts/allocation?fund=${encodeURIComponent(state.currentFund)}&theme=${encodeURIComponent(theme)}`;
    const startTime = performance.now();

    console.log('[Dashboard] Fetching sector chart...', { url, fund: state.currentFund, theme });

    try {
        const response = await fetch(url, { credentials: 'include' });
        const duration = performance.now() - startTime;

        console.log('[Dashboard] Sector chart response received', {
            status: response.status,
            ok: response.ok,
            duration: `${duration.toFixed(2)}ms`
        });

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({ error: `HTTP ${response.status}: ${response.statusText}` }));
            const errorInfo = extractErrorInfo(errorData);
            console.error('[Dashboard] Sector chart API error:', {
                status: response.status,
                errorData: errorData,
                traceback: errorInfo.traceback ? 'present' : 'missing',
                url: url
            });
            const error = new Error(errorInfo.message || `HTTP ${response.status}: ${response.statusText}`);
            (error as any).traceback = errorInfo.traceback;
            throw error;
        }

        const data: AllocationChartData = await response.json();
        console.log('[Dashboard] Sector chart data received', {
            has_data: !!data.data,
            has_layout: !!data.layout,
            trace_count: data.data ? data.data.length : 0
        });

        renderSectorChart(data);

    } catch (error) {
        const duration = performance.now() - startTime;
        const traceback = (error as any)?.traceback;
        console.error('[Dashboard] Error fetching sector chart:', {
            error: error,
            message: error instanceof Error ? error.message : String(error),
            traceback: traceback ? 'present' : 'missing',
            url: url,
            duration: `${duration.toFixed(2)}ms`
        });
        const chartEl = document.getElementById('sector-chart');
        if (chartEl) {
            const errorMsg = error instanceof Error ? error.message : 'Unknown error';
            const tracebackHtml = traceback ? `<details class="mt-2 text-left"><summary class="cursor-pointer text-xs text-gray-600 dark:text-gray-400">Show stack trace</summary><pre class="mt-2 text-xs overflow-auto bg-gray-100 dark:bg-gray-800 p-2 rounded whitespace-pre-wrap">${traceback}</pre></details>` : '';
            chartEl.innerHTML = `<div class="text-center text-red-500 py-8"><p>Error loading sector chart: ${errorMsg}</p>${tracebackHtml}</div>`;
        }
    }
}

async function fetchHoldings(): Promise<void> {
    // Show spinner
    showSpinner('holdings-grid-spinner');

    const url = `/api/dashboard/holdings?fund=${encodeURIComponent(state.currentFund)}`;
    const startTime = performance.now();

    console.log('[Dashboard] Fetching holdings...', { url, fund: state.currentFund });

    try {
        const response = await fetch(url, { credentials: 'include' });
        const duration = performance.now() - startTime;

        console.log('[Dashboard] Holdings response received', {
            status: response.status,
            ok: response.ok,
            duration: `${duration.toFixed(2)}ms`
        });

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({ error: `HTTP ${response.status}: ${response.statusText}` }));
            const errorInfo = extractErrorInfo(errorData);
            console.error('[Dashboard] Holdings API error:', {
                status: response.status,
                statusText: response.statusText,
                error: errorInfo.message,
                traceback: errorInfo.traceback ? 'present' : 'missing',
                errorData: JSON.stringify(errorData),
                url: url
            });
            const error = new Error(errorInfo.message || `HTTP ${response.status}: ${response.statusText}`);
            (error as any).traceback = errorInfo.traceback;
            throw error;
        }

        const data: HoldingsData = await response.json();
        const rowCount = data.data ? data.data.length : 0;
        console.log('[Dashboard] Holdings data received', {
            row_count: rowCount,
            has_grid_api: !!state.gridApi
        });

        if (state.gridApi && typeof state.gridApi.setRowData === 'function') {
            state.gridApi.setRowData(data.data || []);
            console.log('[Dashboard] Holdings grid updated with', rowCount, 'rows');
            // Auto-size columns to fit content better
            if (typeof state.gridApi.autoSizeColumns === 'function') {
                // Auto-size all columns except pinned ticker
                const allColumns = state.gridApi.getColumns();
                if (allColumns && allColumns.length > 0) {
                    const columnsToAutoSize = allColumns.filter((col: any) => col.getColId() !== 'ticker');
                    if (columnsToAutoSize.length > 0) {
                        state.gridApi.autoSizeColumns(columnsToAutoSize, false);
                    }
                }
            } else if (typeof state.gridApi.sizeColumnsToFit === 'function') {
                // Fallback to sizeColumnsToFit if autoSizeColumns is not available
                setTimeout(() => {
                    state.gridApi.sizeColumnsToFit();
                }, 100);
            }
        } else {
            console.error('[Dashboard] Grid API not available for updating holdings', {
                has_gridApi: !!state.gridApi,
                gridApi_type: typeof state.gridApi,
                has_setRowData: state.gridApi && typeof state.gridApi.setRowData === 'function',
                gridApi_keys: state.gridApi ? Object.keys(state.gridApi).slice(0, 10) : []
            });
            // Try to reinitialize the grid
            console.log('[Dashboard] Attempting to reinitialize grid...');
            initGrid();
            // Try again after a short delay
            setTimeout(() => {
                if (state.gridApi && typeof state.gridApi.setRowData === 'function') {
                    state.gridApi.setRowData(data.data || []);
                    console.log('[Dashboard] Holdings grid updated after reinitialization');
                    // Auto-size columns after reinitialization
                    if (typeof state.gridApi.autoSizeColumns === 'function') {
                        const allColumns = state.gridApi.getColumns();
                        if (allColumns && allColumns.length > 0) {
                            const columnsToAutoSize = allColumns.filter((col: any) => col.getColId() !== 'ticker');
                            if (columnsToAutoSize.length > 0) {
                                state.gridApi.autoSizeColumns(columnsToAutoSize, false);
                            }
                        }
                    } else if (typeof state.gridApi.sizeColumnsToFit === 'function') {
                        state.gridApi.sizeColumnsToFit();
                    }
                }
            }, 100);
        }
        hideSpinner('holdings-grid-spinner');

    } catch (error) {
        hideSpinner('holdings-grid-spinner');
        const duration = performance.now() - startTime;
        const errorMsg = error instanceof Error ? error.message : String(error);
        const errorStack = error instanceof Error ? error.stack : undefined;
        const traceback = (error as any)?.traceback;
        console.error('[Dashboard] Error fetching holdings:', {
            error: errorMsg,
            stack: errorStack,
            traceback: traceback ? 'present' : 'missing',
            url: url,
            duration: `${duration.toFixed(2)}ms`,
            errorObject: JSON.stringify(error, Object.getOwnPropertyNames(error))
        });
        const gridEl = document.getElementById('holdings-grid');
        if (gridEl) {
            const tracebackHtml = traceback ? `<details class="mt-2 text-left"><summary class="cursor-pointer text-xs text-gray-600 dark:text-gray-400">Show stack trace</summary><pre class="mt-2 text-xs overflow-auto bg-gray-100 dark:bg-gray-800 p-2 rounded whitespace-pre-wrap">${traceback}</pre></details>` : '';
            gridEl.innerHTML = `<div class="text-center text-red-500 py-8"><p>Error loading holdings: ${errorMsg}</p>${tracebackHtml}</div>`;
        }
    }
}

async function fetchActivity(): Promise<void> {
    // Show spinner
    showSpinner('activity-table-spinner');

    const url = `/api/dashboard/activity?fund=${encodeURIComponent(state.currentFund)}&limit=100`;
    const startTime = performance.now();

    console.log('[Dashboard] Fetching activity...', { url, fund: state.currentFund });

    try {
        const response = await fetch(url, { credentials: 'include' });
        const duration = performance.now() - startTime;

        console.log('[Dashboard] Activity response received', {
            status: response.status,
            ok: response.ok,
            duration: `${duration.toFixed(2)}ms`
        });

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({ error: `HTTP ${response.status}: ${response.statusText}` }));
            const errorInfo = extractErrorInfo(errorData);
            console.error('[Dashboard] Activity API error:', {
                status: response.status,
                errorData: errorData,
                traceback: errorInfo.traceback ? 'present' : 'missing',
                url: url
            });
            const error = new Error(errorInfo.message || `HTTP ${response.status}: ${response.statusText}`);
            (error as any).traceback = errorInfo.traceback;
            throw error;
        }

        const data: ActivityData = await response.json();
        const activityCount = data.data ? data.data.length : 0;
        console.log('[Dashboard] Activity data received', {
            activity_count: activityCount
        });

        const tbody = document.getElementById('activity-table-body');
        if (!tbody) {
            console.warn('[Dashboard] Activity table body not found');
            return;
        }

        tbody.innerHTML = '';

        if (!data.data || data.data.length === 0) {
            tbody.innerHTML = '<tr class="bg-dashboard-surface border-b border-border"><td colspan="7" class="px-6 py-4 text-center text-text-secondary">No recent activity</td></tr>';
        } else {
            data.data.forEach(row => {
                const tr = document.createElement('tr');
                tr.className = 'bg-dashboard-surface border-b border-border hover:bg-dashboard-surface-alt';

                // Action badge with DRIP support
                let actionBadge: string;
                if (row.action === 'DRIP') {
                    actionBadge = '<span class="bg-blue-100 text-blue-800 text-xs font-medium px-2.5 py-0.5 rounded dark:bg-blue-900 dark:text-blue-300">DRIP</span>';
                } else if (row.action === 'SELL') {
                    actionBadge = '<span class="bg-red-100 text-red-800 text-xs font-medium px-2.5 py-0.5 rounded dark:bg-red-900 dark:text-red-300">SELL</span>';
                } else {
                    actionBadge = '<span class="bg-green-100 text-green-800 text-xs font-medium px-2.5 py-0.5 rounded dark:bg-green-900 dark:text-green-300">BUY</span>';
                }

                // Format shares to 4 decimal places
                const sharesFormatted = row.shares.toFixed(4);

                // Use display_amount (P&L for sells, amount for buys/drips)
                const displayAmount = row.display_amount || row.amount || (row.shares * row.price);

                // Company name (or empty string)
                const companyName = row.company_name || '';

                // Create logo image using shared helper function
                const logoImg = createLogoElement(row.ticker, row._logo_url || '');

                // Build table row using DOM methods for better control
                const dateCell = document.createElement('td');
                dateCell.className = 'px-6 py-4 whitespace-nowrap';
                dateCell.textContent = row.date;
                tr.appendChild(dateCell);

                const tickerCell = document.createElement('td');
                tickerCell.className = 'px-6 py-4 font-bold text-blue-600 dark:text-blue-400';
                tickerCell.appendChild(logoImg);
                const tickerLink = document.createElement('a');
                tickerLink.href = `/ticker?ticker=${encodeURIComponent(row.ticker)}`;
                tickerLink.className = 'hover:underline';
                tickerLink.textContent = row.ticker;
                tickerCell.appendChild(tickerLink);
                tr.appendChild(tickerCell);

                const companyCell = document.createElement('td');
                companyCell.className = 'px-6 py-4 text-gray-700 dark:text-gray-300';
                companyCell.textContent = companyName;
                tr.appendChild(companyCell);

                const actionCell = document.createElement('td');
                actionCell.className = 'px-6 py-4';
                actionCell.innerHTML = actionBadge;
                tr.appendChild(actionCell);

                const sharesCell = document.createElement('td');
                sharesCell.className = 'px-6 py-4 text-right';
                sharesCell.textContent = sharesFormatted;
                tr.appendChild(sharesCell);

                const priceCell = document.createElement('td');
                priceCell.className = 'px-6 py-4 text-right format-currency';
                priceCell.textContent = formatMoney(row.price);
                tr.appendChild(priceCell);

                const amountCell = document.createElement('td');
                // Color coding: green for BUY/DRIP, green for SELL profit, red for SELL loss
                let amountColorClass = '';
                if (row.action === 'BUY' || row.action === 'DRIP') {
                    // Purchases are always green
                    amountColorClass = 'text-theme-success-text';
                } else if (row.action === 'SELL') {
                    // For sells, display_amount is P&L: green if profit, red if loss
                    if (displayAmount > 0) {
                        amountColorClass = 'text-theme-success-text';
                    } else if (displayAmount < 0) {
                        amountColorClass = 'text-theme-error-text';
                    }
                }
                amountCell.className = `px-6 py-4 text-right format-currency font-medium ${amountColorClass}`;
                amountCell.textContent = formatMoney(displayAmount);
                tr.appendChild(amountCell);

                tbody.appendChild(tr);
            });
        }
        hideSpinner('activity-table-spinner');

    } catch (error) {
        hideSpinner('activity-table-spinner');
        const duration = performance.now() - startTime;
        const traceback = (error as any)?.traceback;
        console.error('[Dashboard] Error fetching activity:', {
            error: error,
            message: error instanceof Error ? error.message : String(error),
            traceback: traceback ? 'present' : 'missing',
            url: url,
            duration: `${duration.toFixed(2)}ms`
        });
        const tableBody = document.getElementById('activity-table-body');
        if (tableBody) {
            const errorMsg = error instanceof Error ? error.message : 'Unknown error';
            const tracebackHtml = traceback ? `<details class="mt-2 text-left"><summary class="cursor-pointer text-xs text-gray-600 dark:text-gray-400">Show stack trace</summary><pre class="mt-2 text-xs overflow-auto bg-gray-100 dark:bg-gray-800 p-2 rounded whitespace-pre-wrap">${traceback}</pre></details>` : '';
            tableBody.innerHTML = `<tr><td colspan="6" class="text-center text-red-500 py-4"><p>Error loading activity: ${errorMsg}</p>${tracebackHtml}</td></tr>`;
        }
    }
}

async function fetchMovers(): Promise<void> {
    showSpinner('gainers-spinner');
    showSpinner('losers-spinner');

    const url = `/api/dashboard/movers?fund=${encodeURIComponent(state.currentFund)}&limit=10`;
    const startTime = performance.now();

    console.log('[Dashboard] Fetching movers...', { url, fund: state.currentFund });

    try {
        const response = await fetch(url, { credentials: 'include' });
        const duration = performance.now() - startTime;

        console.log('[Dashboard] Movers response received', {
            status: response.status,
            ok: response.ok,
            duration: `${duration.toFixed(2)}ms`
        });

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({ error: `HTTP ${response.status}: ${response.statusText}` }));
            const errorInfo = extractErrorInfo(errorData);
            console.error('[Dashboard] Movers API error:', {
                status: response.status,
                errorData: errorData,
                traceback: errorInfo.traceback ? 'present' : 'missing',
                url: url
            });
            const error = new Error(errorInfo.message || `HTTP ${response.status}: ${response.statusText}`);
            (error as any).traceback = errorInfo.traceback;
            throw error;
        }

        const data: MoversData = await response.json();
        console.log('[Dashboard] Movers data received', {
            gainers_count: data.gainers ? data.gainers.length : 0,
            losers_count: data.losers ? data.losers.length : 0
        });

        renderMovers(data);
        hideSpinner('gainers-spinner');
        hideSpinner('losers-spinner');

    } catch (error) {
        hideSpinner('gainers-spinner');
        hideSpinner('losers-spinner');
        const duration = performance.now() - startTime;
        const traceback = (error as any)?.traceback;
        const errorMsg = error instanceof Error ? error.message : 'Unknown error';
        console.error('[Dashboard] Error fetching movers:', {
            error: error,
            message: errorMsg,
            traceback: traceback ? 'present' : 'missing',
            url: url,
            duration: `${duration.toFixed(2)}ms`
        });
        const tracebackHtml = traceback ? `<details class="mt-2 text-left"><summary class="cursor-pointer text-xs text-text-secondary">Show stack trace</summary><pre class="mt-2 text-xs overflow-auto bg-dashboard-surface-alt p-2 rounded whitespace-pre-wrap text-text-primary">${traceback}</pre></details>` : '';

        const gainersBody = document.getElementById('gainers-table-body');
        if (gainersBody) {
            gainersBody.innerHTML = `<tr><td colspan="4" class="text-center text-theme-error-text py-4"><p>Error: ${errorMsg}</p>${tracebackHtml}</td></tr>`;
        }

        const losersBody = document.getElementById('losers-table-body');
        if (losersBody) {
            losersBody.innerHTML = `<tr><td colspan="4" class="text-center text-theme-error-text py-4"><p>Error: ${errorMsg}</p>${tracebackHtml}</td></tr>`;
        }
    }
}

function renderPillars(pillars: Array<{ name: string; allocation: string; thesis: string; }>): void {
    const container = document.getElementById('thesis-pillars');
    if (!container) return;

    container.innerHTML = '';
    container.classList.remove('hidden');

    pillars.forEach(pillar => {
        const div = document.createElement('div');
        div.className = 'flex flex-col gap-2';

        // Parse markdown for thesis text if available
        let thesisHtml = pillar.thesis || '';
        if (typeof (window as any).marked !== 'undefined') {
            thesisHtml = (window as any).marked.parse(thesisHtml);
        }

        div.innerHTML = `
            <div class="font-bold text-text-primary border-b border-border pb-1 mb-1 flex justify-between">
                <span>${pillar.name}</span>
                <span class="text-xs font-normal text-text-secondary bg-dashboard-surface-alt px-2 py-0.5 rounded">${pillar.allocation || 'N/A'}</span>
            </div>
            <div class="text-sm text-text-secondary prose dark:prose-invert max-w-none text-xs">
                ${thesisHtml}
            </div>
        `;
        container.appendChild(div);
    });
}

async function fetchDividends(): Promise<void> {
    const url = `/api/dashboard/dividends?fund=${encodeURIComponent(state.currentFund)}`;
    console.log('[Dashboard] Fetching dividends...', { url });

    try {
        const response = await fetch(url, { credentials: 'include' });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data: DividendData = await response.json();

        renderDividends(data);
    } catch (error) {
        console.error('[Dashboard] Error fetching dividends:', error);
        // Set values to error state
        ['div-total', 'div-tax', 'div-largest', 'div-reinvested', 'div-events'].forEach(id => {
            const el = document.getElementById(id);
            if (el) el.textContent = 'Error';
        });
    }
}

function renderDividends(data: DividendData): void {
    const currency = data.currency || 'USD';

    // Update Metrics - use formatMoney to avoid currency code prefix
    updateMetricText('div-total', formatMoney(data.metrics.total_dividends, currency));
    updateMetricText('div-tax', formatMoney(data.metrics.total_us_tax, currency));
    updateMetricText('div-largest', formatMoney(data.metrics.largest_dividend, currency));
    updateMetricText('div-reinvested', data.metrics.reinvested_shares.toFixed(4));
    updateMetricText('div-events', data.metrics.payout_events.toString());

    const largestTickerEl = document.getElementById('div-largest-ticker');
    if (largestTickerEl) largestTickerEl.textContent = data.metrics.largest_ticker;

    // Update Log Table
    const tbody = document.getElementById('dividend-log-body');
    if (tbody) {
        tbody.innerHTML = '';
        if (data.log.length === 0) {
            tbody.innerHTML = '<tr><td colspan="7" class="px-4 py-2 text-center text-text-secondary">No dividend history</td></tr>';
        } else {
            data.log.forEach(row => {
                const tr = document.createElement('tr');
                tr.className = 'bg-dashboard-surface border-b border-border hover:bg-dashboard-surface-alt';

                // Pay Date
                const dateCell = document.createElement('td');
                dateCell.className = 'px-4 py-2 font-medium text-gray-900 dark:text-white whitespace-nowrap';
                dateCell.textContent = row.date;
                tr.appendChild(dateCell);

                // Ticker (clickable) with logo
                const tickerCell = document.createElement('td');
                tickerCell.className = 'px-4 py-2 text-blue-600 dark:text-blue-400 font-bold cursor-pointer hover:underline';
                tickerCell.style.cursor = 'pointer';

                // Create logo image using shared helper function (always create for consistent alignment)
                const logoUrl = (row as any)._logo_url || '';
                const img = createLogoElement(row.ticker, logoUrl);
                tickerCell.appendChild(img);

                const tickerLink = document.createElement('a');
                tickerLink.href = `/ticker?ticker=${encodeURIComponent(row.ticker)}`;
                tickerLink.className = 'hover:underline';
                tickerLink.textContent = row.ticker;
                tickerLink.addEventListener('click', (e) => {
                    e.stopPropagation();
                });
                tickerCell.appendChild(tickerLink);

                tickerCell.addEventListener('click', (e) => {
                    e.stopPropagation();
                    if (row.ticker && row.ticker !== 'N/A') {
                        window.location.href = `/ticker?ticker=${encodeURIComponent(row.ticker)}`;
                    }
                });
                tr.appendChild(tickerCell);

                // Company Name
                const companyCell = document.createElement('td');
                companyCell.className = 'px-4 py-2 text-gray-700 dark:text-gray-300';
                companyCell.textContent = row.company_name || '';
                tr.appendChild(companyCell);

                // Gross ($)
                const grossCell = document.createElement('td');
                grossCell.className = 'px-4 py-2 text-right text-gray-700 dark:text-gray-300';
                grossCell.textContent = formatMoney(row.gross || 0, currency);
                tr.appendChild(grossCell);

                // Net ($)
                const netCell = document.createElement('td');
                netCell.className = 'px-4 py-2 text-right font-medium text-green-600 dark:text-green-400';
                netCell.textContent = formatMoney(row.amount, currency);
                tr.appendChild(netCell);

                // Reinvested Shares
                const sharesCell = document.createElement('td');
                sharesCell.className = 'px-4 py-2 text-right text-gray-700 dark:text-gray-300';
                sharesCell.textContent = (row.shares || 0).toFixed(4);
                tr.appendChild(sharesCell);

                // DRIP Price ($)
                const dripPriceCell = document.createElement('td');
                dripPriceCell.className = 'px-4 py-2 text-right text-gray-700 dark:text-gray-300';
                dripPriceCell.textContent = row.drip_price > 0 ? formatMoney(row.drip_price, currency) : 'N/A';
                tr.appendChild(dripPriceCell);

                tbody.appendChild(tr);
            });
        }
    }
}

function updateMetricText(id: string, text: string): void {
    const el = document.getElementById(id);
    if (el) el.textContent = text;
}

async function fetchCurrencyChart(): Promise<void> {
    showSpinner('currency-chart-spinner');

    const theme = getEffectiveTheme();

    const url = `/api/dashboard/charts/currency?fund=${encodeURIComponent(state.currentFund)}&theme=${encodeURIComponent(theme)}`;
    console.log('[Dashboard] Fetching currency chart...', { url });

    try {
        const response = await fetch(url, { credentials: 'include' });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);

        const data: AllocationChartData = await response.json();
        renderCurrencyChart(data);
    } catch (error) {
        console.error('[Dashboard] Error fetching currency chart:', error);
        const chartEl = document.getElementById('currency-chart');
        if (chartEl) chartEl.innerHTML = '<div class="text-center text-gray-500 py-8"><p>Error loading chart</p></div>';
    } finally {
        hideSpinner('currency-chart-spinner');
    }
}

function renderCurrencyChart(data: AllocationChartData): void {
    const chartEl = document.getElementById('currency-chart');
    if (!chartEl) return;

    const Plotly = (window as any).Plotly;
    if (!Plotly) return;

    const layout = { ...data.layout };
    // Constrain height to container size, with max of 400px
    const containerHeight = Math.min(chartEl.offsetHeight || 350, 400);
    layout.height = containerHeight;
    layout.autosize = true;
    layout.margin = { l: 20, r: 20, t: 30, b: 20 };
    // Ensure chart doesn't overflow
    layout.width = chartEl.offsetWidth || undefined;

    try {
        Plotly.newPlot('currency-chart', data.data, layout, {
            responsive: true,
            displayModeBar: false,
            useResizeHandler: true
        });

        // Add resize handler
        if (!(window as any).__currencyChartResizeHandler) {
            const resizeHandler = () => {
                const el = document.getElementById('currency-chart');
                if (el) {
                    // Constrain to container size
                    const maxHeight = Math.min(el.offsetHeight || 350, 400);
                    Plotly.relayout('currency-chart', {
                        height: maxHeight,
                        width: el.offsetWidth
                    });
                }
            };
            (window as any).__currencyChartResizeHandler = resizeHandler;
            window.addEventListener('resize', resizeHandler);
        }
    } catch (error) {
        console.error('[Dashboard] Error rendering currency chart:', error);
    }
}

async function fetchExchangeRateData(): Promise<void> {
    showSpinner('exchange-rate-chart-spinner');

    const theme = getEffectiveTheme();

    const url = `/api/dashboard/exchange-rate?inverse=${state.inverseExchangeRate}&theme=${encodeURIComponent(theme)}`;
    console.log('[Dashboard] Fetching exchange rate data...', { url });

    try {
        const response = await fetch(url, { credentials: 'include' });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);

        const data: ExchangeRateData = await response.json();
        renderExchangeRateData(data);
    } catch (error) {
        console.error('[Dashboard] Error fetching exchange rate data:', error);
        const valueEl = document.getElementById('exchange-rate-value');
        if (valueEl) valueEl.textContent = '--';
    } finally {
        hideSpinner('exchange-rate-chart-spinner');
    }
}

function renderExchangeRateData(data: ExchangeRateData): void {
    // Update metric display
    const labelEl = document.getElementById('exchange-rate-label');
    const valueEl = document.getElementById('exchange-rate-value');
    const helpEl = document.getElementById('exchange-rate-help');

    if (labelEl) labelEl.textContent = data.rate_label;
    if (valueEl) valueEl.textContent = data.current_rate !== null ? data.current_rate.toFixed(4) : '--';
    if (helpEl) helpEl.textContent = data.rate_help;

    // Render historical chart
    if (data.chart) {
        const chartEl = document.getElementById('exchange-rate-chart');
        if (!chartEl) return;

        const Plotly = (window as any).Plotly;
        if (!Plotly) return;

        const layout = { ...data.chart.layout };
        layout.height = 200;
        layout.autosize = true;

        try {
            Plotly.newPlot('exchange-rate-chart', data.chart.data, layout, {
                responsive: true,
                displayModeBar: false
            });

            // Add resize handler
            if (!(window as any).__exchangeRateChartResizeHandler) {
                const resizeHandler = () => {
                    if (document.getElementById('exchange-rate-chart')) {
                        Plotly.Plots.resize('exchange-rate-chart');
                    }
                };
                (window as any).__exchangeRateChartResizeHandler = resizeHandler;
                window.addEventListener('resize', resizeHandler);
            }
        } catch (error) {
            console.error('[Dashboard] Error rendering exchange rate chart:', error);
        }
    }
}

const MOVERS_COLUMN_COUNT = 7;

function renderMovers(data: MoversData): void {
    const gainersBody = document.getElementById('gainers-table-body');
    const losersBody = document.getElementById('losers-table-body');

    // Helper to format merged P&L column: "P&L Pct%"
    // Rules:
    // - Green/Red color based on value
    // - No negative signs if red (color indicates negative)
    // - Positive values have + sign
    // - Currencies removed, percentages in brackets with 1 decimal
    const formatMergedPnl = (pnl: number | undefined | null, pct: number | undefined | null, currency: string) => {
        if (pnl == null || pct == null) return '--';

        const isNegative = pnl < 0;
        const absPnl = Math.abs(pnl);
        const absPct = Math.abs(pct);

        // formatMoney now handles removing currency code globally
        const pnlStr = formatMoney(absPnl, currency);
        // 1 decimal place, wrapped in brackets
        const pctStr = `(${absPct.toFixed(1)}%)`;

        if (isNegative) {
            // Negative: Red color (handled by class), no negative sign
            return `${pnlStr} ${pctStr}`;
        } else {
            // Positive: Green color, no + sign
            return `${pnlStr} ${pctStr}`;
        }
    };

    const getPnlColor = (val: number | null | undefined) => {
        if (val == null) return '';
        return val > 0
            ? 'text-green-600 dark:text-green-400 font-bold'
            : (val < 0 ? 'text-red-600 dark:text-red-400 font-bold' : '');
    };

    const renderTable = (tbody: HTMLElement, items: MoverItem[], isGainer: boolean) => {
        tbody.innerHTML = '';
        if (!items || items.length === 0) {
            tbody.innerHTML = `<tr class="bg-dashboard-surface"><td colspan="${MOVERS_COLUMN_COUNT}" class="px-4 py-4 text-center text-text-secondary">No ${isGainer ? 'gainers' : 'losers'} to display</td></tr>`;
            return;
        }

        items.forEach(item => {
            const tr = document.createElement('tr');
            tr.className = 'bg-dashboard-surface border-b border-border hover:bg-dashboard-surface-alt';

            // Calculate colors
            const dayColor = getPnlColor(item.daily_pnl);
            const fiveDayColor = getPnlColor(item.five_day_pnl);
            const totalColor = getPnlColor(item.total_pnl);

            // Create logo image using shared helper function
            const logoImg = createLogoElement(item.ticker, item._logo_url || '');
            const escapedTicker = item.ticker.replace(/"/g, '&quot;').replace(/'/g, '&#39;');
            const escapedCompanyName = (item.company_name || item.ticker).replace(/"/g, '&quot;').replace(/'/g, '&#39;');

            // Use font-mono for numerical columns to ensure alignment
            const tickerCell = document.createElement('td');
            tickerCell.className = 'px-4 py-3 font-bold text-blue-600 dark:text-blue-400';
            tickerCell.appendChild(logoImg);
            const tickerLink = document.createElement('a');
            tickerLink.href = `/ticker?ticker=${encodeURIComponent(item.ticker)}`;
            tickerLink.className = 'hover:underline';
            tickerLink.textContent = item.ticker;
            tickerCell.appendChild(tickerLink);
            tr.appendChild(tickerCell);

            const companyCell = document.createElement('td');
            companyCell.className = 'px-4 py-3 truncate max-w-[150px]';
            companyCell.title = item.company_name || item.ticker;
            companyCell.textContent = item.company_name || item.ticker;
            tr.appendChild(companyCell);

            const dayPnlCell = document.createElement('td');
            dayPnlCell.className = `px-4 py-3 text-right font-mono ${dayColor}`;
            dayPnlCell.textContent = formatMergedPnl(item.daily_pnl, item.daily_pnl_pct, data.display_currency);
            tr.appendChild(dayPnlCell);

            const fiveDayPnlCell = document.createElement('td');
            fiveDayPnlCell.className = `px-4 py-3 text-right font-mono ${fiveDayColor}`;
            fiveDayPnlCell.textContent = formatMergedPnl(item.five_day_pnl, item.five_day_pnl_pct, data.display_currency);
            tr.appendChild(fiveDayPnlCell);

            const totalPnlCell = document.createElement('td');
            totalPnlCell.className = `px-4 py-3 text-right font-mono ${totalColor}`;
            totalPnlCell.textContent = formatMergedPnl(item.total_pnl, item.total_return_pct, data.display_currency);
            tr.appendChild(totalPnlCell);

            const priceCell = document.createElement('td');
            priceCell.className = 'px-4 py-3 text-right font-mono';
            priceCell.textContent = formatMoney(item.current_price || 0, data.display_currency);
            tr.appendChild(priceCell);

            const valueCell = document.createElement('td');
            valueCell.className = 'px-4 py-3 text-right font-mono font-medium';
            valueCell.textContent = formatMoney(item.market_value || 0, data.display_currency);
            tr.appendChild(valueCell);

            tbody.appendChild(tr);
        });
    };

    if (gainersBody) renderTable(gainersBody, data.gainers, true);
    if (losersBody) renderTable(losersBody, data.losers, false);
}

// --- Rendering Helpers ---

// Use FormatterCache for better performance
const getUsdFormatter = () => FormatterCache.get('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
});

function formatMoney(val: number, currency?: string): string {
    if (typeof val !== 'number' || isNaN(val)) return '--';

    // Use cached formatter
    const formatted = getUsdFormatter().format(val);

    // Remove any currency code that might have been added (e.g., "CA$" -> "$")
    return formatted.replace(/^[A-Z]{2,3}\$?/, '$').replace(/\s*[A-Z]{2,3}$/, '');
}

function updateMetric(id: string, value: number, currency: string, isCurrency: boolean): void {
    const el = document.getElementById(id);
    if (el) {
        if (isCurrency) {
            // Format number with commas and 2 decimal places, with symbol but no code
            const formatted = FormatterCache.get('en-US', {
                style: 'currency',
                currency: currency || 'USD',
                currencyDisplay: 'narrowSymbol',
                minimumFractionDigits: 2,
                maximumFractionDigits: 2
            }).format(value);
            el.textContent = formatted;
        } else {
            el.textContent = String(value);
        }
    }
}

function updateChangeMetric(valId: string, pctId: string, change: number, pct: number, currency: string): void {
    const valEl = document.getElementById(valId);
    const pctEl = document.getElementById(pctId);

    if (valEl) {
        // Format number with $ sign, without currency code prefix
        const formatted = FormatterCache.get('en-US', {
            style: 'currency',
            currency: 'USD', // Use USD to get $ sign, then we'll replace if needed
            minimumFractionDigits: 2,
            maximumFractionDigits: 2
        }).format(change);
        valEl.textContent = (change >= 0 ? '+' : '') + formatted;
    }
    if (pctEl) {
        pctEl.textContent = (pct >= 0 ? '+' : '') + pct.toFixed(2) + '%';

        // Color classes
        pctEl.className = `text-sm font-medium px-2 py-0.5 rounded ${change >= 0
            ? 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-300'
            : 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-300'}`;

        if (valEl) {
            valEl.className = `text-2xl font-bold ${change >= 0 ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'}`;
        }
    }
}

function renderPerformanceChart(data: PerformanceChartData): void {
    // Clear any existing chart
    const chartEl = document.getElementById('performance-chart');
    if (!chartEl) {
        console.warn('[Dashboard] Performance chart element not found');
        return;
    }

    // Clear previous content
    chartEl.innerHTML = '';

    if (!data || !data.data || !data.layout) {
        chartEl.innerHTML = '<div class="text-center text-gray-500 py-8"><p>No performance data available</p></div>';
        return;
    }

    // Render with Plotly (same as ticker_details.ts)
    const Plotly = (window as any).Plotly;
    if (!Plotly) {
        console.error('[Dashboard] Plotly not loaded');
        chartEl.innerHTML = '<div class="text-center text-red-500 py-8"><p>Error: Plotly library not loaded</p></div>';
        return;
    }

    // Match Streamlit exactly: use_container_width=True means use full width and keep original height
    // Streamlit doesn't modify the layout at all - it just passes the figure through
    // Use the layout directly without any modifications
    try {
        // Create custom fullscreen button
        const fullscreenButton = {
            name: 'fullscreen',
            title: 'Fullscreen',
            icon: {
                'width': 857.1,
                'height': 1000,
                'path': 'M214.3 0h428.6v214.3H214.3V0zm0 642.9h428.6v357.1H214.3V642.9zM642.9 0h214.3v214.3H642.9V0zm0 642.9h214.3v357.1H642.9V642.9z',
                'transform': 'matrix(1 0 0 1 0 0)'
            },
            click: function(gd: any) {
                const chartContainer = document.getElementById('performance-chart');
                if (!chartContainer) return;

                // Check if already in fullscreen
                if (document.fullscreenElement || (document as any).webkitFullscreenElement || 
                    (document as any).mozFullScreenElement || (document as any).msFullscreenElement) {
                    // Exit fullscreen
                    if (document.exitFullscreen) {
                        document.exitFullscreen();
                    } else if ((document as any).webkitExitFullscreen) {
                        (document as any).webkitExitFullscreen();
                    } else if ((document as any).mozCancelFullScreen) {
                        (document as any).mozCancelFullScreen();
                    } else if ((document as any).msExitFullscreen) {
                        (document as any).msExitFullscreen();
                    }
                } else {
                    // Enter fullscreen
                    if (chartContainer.requestFullscreen) {
                        chartContainer.requestFullscreen();
                    } else if ((chartContainer as any).webkitRequestFullscreen) {
                        (chartContainer as any).webkitRequestFullscreen();
                    } else if ((chartContainer as any).mozRequestFullScreen) {
                        (chartContainer as any).mozRequestFullScreen();
                    } else if ((chartContainer as any).msRequestFullscreen) {
                        (chartContainer as any).msRequestFullscreen();
                    }
                }
            }
        };

        Plotly.newPlot('performance-chart', data.data, data.layout, {
            responsive: true,  // Equivalent to use_container_width=True in Streamlit
            displayModeBar: true,
            modeBarButtonsToRemove: ['pan2d', 'lasso2d'],
            modeBarButtonsToAdd: [fullscreenButton]
        });

        // Handle fullscreen change to resize chart
        const handleFullscreenChange = () => {
            setTimeout(() => {
                const Plotly = (window as any).Plotly;
                if (Plotly) {
                    Plotly.Plots.resize('performance-chart');
                }
            }, 100);
        };

        // Add event listeners for fullscreen changes (cross-browser support)
        document.addEventListener('fullscreenchange', handleFullscreenChange);
        document.addEventListener('webkitfullscreenchange', handleFullscreenChange);
        document.addEventListener('mozfullscreenchange', handleFullscreenChange);
        document.addEventListener('MSFullscreenChange', handleFullscreenChange);

        console.log('[Dashboard] Performance chart rendered with Plotly (fullscreen enabled)');
    } catch (error) {
        console.error('[Dashboard] Error rendering Plotly chart:', error);
        chartEl.innerHTML = '<div class="text-center text-red-500 py-8"><p>Error rendering chart</p></div>';
    }
}

async function fetchIndividualHoldingsChart(): Promise<void> {
    // Check if fund is selected
    if (!state.currentFund || state.currentFund.toLowerCase() === 'all') {
        const chartEl = document.getElementById('individual-holdings-chart');
        if (chartEl) {
            chartEl.innerHTML = '<div class="text-center text-gray-500 py-8">Select a specific fund to view individual stock performance</div>';
        }
        return;
    }

    // Show spinner
    showSpinner('individual-holdings-spinner');

    const theme = getEffectiveTheme();

    const url = `/api/dashboard/charts/individual-holdings?fund=${encodeURIComponent(state.currentFund)}&days=${state.individualHoldingsDays}&filter=${encodeURIComponent(state.individualHoldingsFilter)}&use_solid=${state.useSolidLines}&theme=${encodeURIComponent(theme)}`;
    const startTime = performance.now();

    console.log('[Dashboard] Fetching individual holdings chart...', { url, fund: state.currentFund, days: state.individualHoldingsDays, filter: state.individualHoldingsFilter });

    try {
        const response = await fetch(url, { credentials: 'include' });
        const duration = performance.now() - startTime;

        console.log('[Dashboard] Individual holdings chart response received', {
            status: response.status,
            ok: response.ok,
            duration: `${duration.toFixed(2)}ms`
        });

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({ error: `HTTP ${response.status}: ${response.statusText}` }));
            const errorInfo = extractErrorInfo(errorData);
            const error = new Error(errorInfo.message || `HTTP ${response.status}: ${response.statusText}`);
            (error as any).traceback = errorInfo.traceback;
            throw error;
        }

        const data: IndividualHoldingsChartData = await response.json();
        renderIndividualHoldingsChart(data);
        hideSpinner('individual-holdings-spinner');

    } catch (error) {
        hideSpinner('individual-holdings-spinner');
        const errorMsg = error instanceof Error ? error.message : String(error);
        const traceback = (error as any)?.traceback;
        console.error('[Dashboard] Error fetching individual holdings chart:', {
            error: errorMsg,
            traceback: traceback ? 'present' : 'missing'
        });
        const chartEl = document.getElementById('individual-holdings-chart');
        if (chartEl) {
            const tracebackHtml = traceback ? `<details class="mt-2 text-left"><summary class="cursor-pointer text-xs text-gray-600 dark:text-gray-400">Show stack trace</summary><pre class="mt-2 text-xs overflow-auto bg-gray-100 dark:bg-gray-800 p-2 rounded whitespace-pre-wrap">${traceback}</pre></details>` : '';
            chartEl.innerHTML = `<div class="text-center text-red-500 py-8"><p>Error loading chart: ${errorMsg}</p>${tracebackHtml}</div>`;
        }
    }
}

function renderIndividualHoldingsChart(data: IndividualHoldingsChartData): void {
    const chartEl = document.getElementById('individual-holdings-chart');
    if (!chartEl) {
        console.warn('[Dashboard] Individual holdings chart element not found');
        return;
    }

    // Clear previous content
    chartEl.innerHTML = '';

    if (!data || !data.data || !data.layout) {
        chartEl.innerHTML = '<div class="text-center text-gray-500 py-8"><p>No holdings data available</p></div>';
        return;
    }

    // Render with Plotly
    const Plotly = (window as any).Plotly;
    if (!Plotly) {
        console.error('[Dashboard] Plotly not loaded');
        chartEl.innerHTML = '<div class="text-center text-red-500 py-8"><p>Error: Plotly library not loaded</p></div>';
        return;
    }

    try {
        Plotly.newPlot('individual-holdings-chart', data.data, data.layout, {
            responsive: true,
            displayModeBar: true,
            modeBarButtonsToRemove: ['pan2d', 'lasso2d']
        });
        console.log('[Dashboard] Individual holdings chart rendered with Plotly');

        // Update stock count display
        if (data.metadata) {
            const countEl = document.getElementById('individual-stock-count');
            if (countEl) {
                const daysText = data.metadata.days === 0 ? 'all time' : `last ${data.metadata.days} days`;
                countEl.textContent = `Showing ${data.metadata.num_stocks} stocks over ${daysText}`;
            }

            // Update filter dropdown with dynamic sector/industry options
            updateIndividualHoldingsFilters(data.metadata.sectors, data.metadata.industries);
        }
    } catch (error) {
        console.error('[Dashboard] Error rendering individual holdings chart:', error);
        chartEl.innerHTML = '<div class="text-center text-red-500 py-8"><p>Error rendering chart</p></div>';
    }
}

function updateIndividualHoldingsFilters(sectors: string[], industries: string[]): void {
    const filterSelect = document.getElementById('individual-stock-filter') as HTMLSelectElement | null;
    if (!filterSelect) return;

    // Get current value to preserve selection
    const currentValue = filterSelect.value;

    // Remove any existing sector/industry options
    const existingOptions = Array.from(filterSelect.options);
    let foundSeparator = false;
    for (const opt of existingOptions) {
        if (opt.value.startsWith('---') || opt.value.startsWith('sector:') || opt.value.startsWith('industry:')) {
            opt.remove();
            foundSeparator = true;
        }
    }

    // Add sector options if available
    if (sectors.length > 0) {
        const sectorSep = document.createElement('option');
        sectorSep.value = '---sectors---';
        sectorSep.textContent = '--- By Sector ---';
        sectorSep.disabled = true;
        filterSelect.appendChild(sectorSep);

        for (const sector of sectors) {
            const opt = document.createElement('option');
            opt.value = `sector:${sector}`;
            opt.textContent = `Sector: ${sector}`;
            filterSelect.appendChild(opt);
        }
    }

    // Add industry options if available
    if (industries.length > 0) {
        const industrySep = document.createElement('option');
        industrySep.value = '---industries---';
        industrySep.textContent = '--- By Industry ---';
        industrySep.disabled = true;
        filterSelect.appendChild(industrySep);

        for (const industry of industries) {
            const opt = document.createElement('option');
            opt.value = `industry:${industry}`;
            opt.textContent = `Industry: ${industry}`;
            filterSelect.appendChild(opt);
        }
    }

    // Restore selection if still valid
    if (currentValue && Array.from(filterSelect.options).some(o => o.value === currentValue)) {
        filterSelect.value = currentValue;
    }
}

function renderSectorChart(data: AllocationChartData): void {
    // Clear any existing chart
    const chartEl = document.getElementById('sector-chart');
    if (!chartEl) {
        console.warn('[Dashboard] Sector chart element not found');
        return;
    }

    // Hide spinner before rendering (Plotly will replace content)
    hideSpinner('sector-chart-spinner');

    if (!data || !data.data || !data.layout) {
        chartEl.innerHTML = '<div class="text-center text-gray-500 py-8"><p>No sector data available</p></div>';
        return;
    }

    // Render with Plotly (same as performance chart)
    const Plotly = (window as any).Plotly;
    if (!Plotly) {
        console.error('[Dashboard] Plotly not loaded');
        chartEl.innerHTML = '<div class="text-center text-red-500 py-8"><p>Error: Plotly library not loaded</p></div>';
        return;
    }

    // Update layout to be responsive
    const layout = { ...data.layout };
    layout.autosize = true;

    // Ensure proper margins for centering
    layout.margin = { l: 20, r: 20, t: 40, b: 40 };

    try {
        Plotly.newPlot('sector-chart', data.data, layout, {
            responsive: true,
            displayModeBar: true,
            modeBarButtonsToRemove: ['pan2d', 'lasso2d']
        });
        console.log('[Dashboard] Sector chart rendered with Plotly');

        // Add resize handler to redraw chart when window resizes
        if (!(window as any).__sectorChartResizeHandler) {
            let resizeTimeout: number | undefined;
            const resizeHandler = () => {
                clearTimeout(resizeTimeout);
                resizeTimeout = window.setTimeout(() => {
                    const Plotly = (window as any).Plotly;
                    const el = document.getElementById('sector-chart');
                    if (Plotly && el && (el as any).data) {
                        Plotly.Plots.resize(el);
                    }
                }, 100);
            };
            (window as any).__sectorChartResizeHandler = resizeHandler;
            window.addEventListener('resize', resizeHandler);
        }

    } catch (error) {
        console.error('[Dashboard] Error rendering Plotly sector chart:', error);
        chartEl.innerHTML = '<div class="text-center text-red-500 py-8"><p>Error rendering chart</p></div>';
    }
}

function renderPnlChart(data: PnlChartData): void {
    // Clear any existing chart
    const chartEl = document.getElementById('pnl-chart');
    if (!chartEl) {
        console.warn('[Dashboard] P&L chart element not found');
        return;
    }

    // Hide spinner before rendering (Plotly will replace content)
    hideSpinner('pnl-chart-spinner');

    if (!data || !data.data || !data.layout) {
        chartEl.innerHTML = '<div class="text-center text-gray-500 py-8"><p>No P&L data available</p></div>';
        return;
    }

    // Render with Plotly (same as sector chart)
    const Plotly = (window as any).Plotly;
    if (!Plotly) {
        console.error('[Dashboard] Plotly not loaded');
        chartEl.innerHTML = '<div class="text-center text-red-500 py-8"><p>Error: Plotly library not loaded</p></div>';
        return;
    }

    // Update layout height to match container
    const layout = { ...data.layout };

    // Get actual container height or use default
    const containerHeight = chartEl.offsetHeight || 500;
    layout.height = containerHeight;
    layout.autosize = true;

    // Ensure proper margins - increase left margin for y-axis labels
    if (!layout.margin) {
        layout.margin = { l: 80, r: 20, t: 50, b: 100 };
    } else {
        // Use larger left margin to prevent y-axis labels from being cut off
        layout.margin.l = Math.max(80, layout.margin.l || 80);
        layout.margin.r = Math.max(20, layout.margin.r || 20);
        // Increase bottom margin to prevent legend cutoff
        layout.margin.b = Math.max(100, layout.margin.b || 100);
    }

    try {
        Plotly.newPlot('pnl-chart', data.data, layout, {
            responsive: true,
            displayModeBar: true,
            modeBarButtonsToRemove: ['pan2d', 'lasso2d']
        });
        console.log('[Dashboard] P&L chart rendered with Plotly');

        // Add resize handler to redraw chart when window resizes (only once)
        if (!(window as any).__pnlChartResizeHandler) {
            const resizeHandler = () => {
                const Plotly = (window as any).Plotly;
                if (Plotly && document.getElementById('pnl-chart')) {
                    Plotly.Plots.resize('pnl-chart');
                }
            };
            (window as any).__pnlChartResizeHandler = resizeHandler;
            window.addEventListener('resize', resizeHandler);
        }

    } catch (error) {
        console.error('[Dashboard] Error rendering Plotly P&L chart:', error);
        chartEl.innerHTML = '<div class="text-center text-red-500 py-8"><p>Error rendering chart</p></div>';
    }
}

async function loadPnlChart(fund: string): Promise<void> {
    const theme = getEffectiveTheme();

    const startTime = performance.now();
    const view = state.pnlChartView || 'top_bottom';
    const url = `/api/dashboard/charts/pnl?fund=${encodeURIComponent(fund || '')}&theme=${encodeURIComponent(theme)}&view=${encodeURIComponent(view)}`;

    console.log('[Dashboard] Loading P&L chart:', { fund, theme, view, url });

    try {
        showSpinner('pnl-chart-spinner');

        const response = await fetch(url, {
            method: 'GET',
            credentials: 'include',
            headers: {
                'Accept': 'application/json'
            }
        });

        const duration = performance.now() - startTime;
        console.log('[Dashboard] P&L chart API response', {
            status: response.status,
            duration: `${duration.toFixed(2)}ms`
        });

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({ error: `HTTP ${response.status}: ${response.statusText}` }));
            const errorInfo = extractErrorInfo(errorData);
            console.error('[Dashboard] P&L chart API error:', {
                status: response.status,
                errorData: errorData,
                traceback: errorInfo.traceback ? 'present' : 'missing',
                url: url
            });
            const error = new Error(errorInfo.message || `HTTP ${response.status}: ${response.statusText}`);
            (error as any).traceback = errorInfo.traceback;
            throw error;
        }

        const data: PnlChartData = await response.json();
        console.log('[Dashboard] P&L chart data received');

        renderPnlChart(data);

    } catch (error) {
        hideSpinner('pnl-chart-spinner');
        const duration = performance.now() - startTime;
        const traceback = (error as any)?.traceback;
        console.error('[Dashboard] Error fetching P&L chart:', {
            error: error,
            message: error instanceof Error ? error.message : String(error),
            traceback: traceback ? 'present' : 'missing',
            url: url,
            duration: `${duration.toFixed(2)}ms`
        });
        const chartEl = document.getElementById('pnl-chart');
        if (chartEl) {
            const errorMsg = error instanceof Error ? error.message : 'Unknown error';
            const tracebackHtml = traceback ? `<details class="mt-2 text-left"><summary class="cursor-pointer text-xs text-gray-600 dark:text-gray-400">Show stack trace</summary><pre class="mt-2 text-xs overflow-auto bg-gray-100 dark:bg-gray-800 p-2 rounded whitespace-pre-wrap">${traceback}</pre></details>` : '';
            chartEl.innerHTML = `<div class="text-center text-red-500 py-8"><p>Error: ${errorMsg}</p>${tracebackHtml}</div>`;
        }
    }
}

// Expose refreshDashboard globally for template onclick handlers
if (typeof window !== 'undefined') {
    (window as any).refreshDashboard = refreshDashboard;
    console.log('[Dashboard] refreshDashboard function exposed globally');
}
// Force rebuild: Fix missing logos by updating backend API