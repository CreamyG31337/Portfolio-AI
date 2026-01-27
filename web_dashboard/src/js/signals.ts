export { }; // Ensure file is treated as a module

// Interfaces
interface SignalRow {
    _logo_url?: string;
    ticker: string;
    company_name?: string | null;
    overall_signal: string;
    confidence: number;
    fear_level: string;
    risk_score: number;
    trend: string;
    analysis_date?: string;
    cached?: boolean;
    analyzed?: boolean;
    explanation?: string | null;
}

interface SignalsResponse {
    success: boolean;
    data: SignalRow[];
    summary?: {
        total: number;
        buy: number;
        sell: number;
        hold: number;
        watch: number;
        fear_low: number;
        fear_moderate: number;
        fear_high: number;
        fear_extreme: number;
    };
    error?: string;
}

// Global variables
let signalsGridApi: any = null;
let signalsGridColumnApi: any = null;
let refreshKey = 0;
let activeModalTicker: string | null = null;

// Global cache of tickers that don't have logos (to avoid repeated 404s)
const failedLogoCache = new Set<string>();

// Theme detection helpers
function getCurrentTheme(): string {
    const themeManager = (window as any).themeManager;
    if (themeManager?.getTheme) {
        return themeManager.getTheme();
    }
    return document.documentElement.getAttribute("data-theme") || "system";
}

function isDarkTheme(theme: string): boolean {
    if (theme === "system") {
        return window.matchMedia("(prefers-color-scheme: dark)").matches;
    }
    return ["dark", "midnight-tokyo", "abyss"].includes(theme);
}

function applyAgGridTheme(container: HTMLElement): void {
    const theme = getCurrentTheme();
    const useDark = isDarkTheme(theme);
    container.classList.toggle("ag-theme-alpine-dark", useDark);
    container.classList.toggle("ag-theme-alpine", !useDark);
}

// Ticker cell renderer - makes ticker clickable with logo
class TickerCellRenderer {
    private eGui!: HTMLElement;

    init(params: any): void {
        this.eGui = document.createElement('div');
        this.eGui.style.display = 'flex';
        this.eGui.style.alignItems = 'center';
        this.eGui.style.gap = '6px';

        if (params.value && params.value !== 'N/A') {
            const ticker = params.value;
            const logoUrl = params.data?._logo_url;
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


            const tickerSpan = document.createElement('span');
            tickerSpan.innerText = ticker;
            tickerSpan.className = 'text-link hover:text-link-hover font-bold underline cursor-pointer';
            tickerSpan.addEventListener('click', function (e: Event) {
                e.stopPropagation();
                window.location.href = `/ticker?ticker=${encodeURIComponent(ticker)}`;
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

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
    loadSignalsData(refreshKey);

    // Set up refresh button
    const refreshBtn = document.getElementById('refresh-btn');
    if (refreshBtn) {
        refreshBtn.addEventListener('click', refreshData);
    }

    const modalRefreshBtn = document.getElementById('signals-modal-refresh');
    if (modalRefreshBtn) {
        modalRefreshBtn.addEventListener('click', () => {
            if (activeModalTicker) {
                setModalStatus('Regenerating AI explanation...');
                loadModalDetails(activeModalTicker, true);
            }
        });
    }

    // Listen for theme changes
    const themeManager = (window as any).themeManager;
    if (themeManager && typeof themeManager.addListener === 'function') {
        themeManager.addListener(() => {
            updateSignalsGridTheme();
        });
    } else {
        // Fallback: Use MutationObserver to watch for data-theme attribute changes
        const observer = new MutationObserver((mutations) => {
            mutations.forEach((mutation) => {
                if (mutation.type === 'attributes' && mutation.attributeName === 'data-theme') {
                    updateSignalsGridTheme();
                }
            });
        });
        observer.observe(document.documentElement, {
            attributes: true,
            attributeFilter: ['data-theme']
        });
    }
});

// Refresh data
function refreshData(): void {
    refreshKey = Date.now();
    loadSignalsData(refreshKey);

    // Update last updated time
    const lastUpdated = document.getElementById('last-updated');
    if (lastUpdated) {
        const now = new Date();
        lastUpdated.textContent = now.toLocaleString();
    }
}

// Initialize signals grid
function initializeSignalsGrid(data: SignalRow[]): void {
    const gridDiv = document.querySelector('#signals-grid') as HTMLElement;
    if (!gridDiv) {
        console.error('Signals grid container not found');
        return;
    }

    if (signalsGridApi && signalsGridColumnApi) {
        signalsGridApi.setGridOption('rowData', data);
        autoSizeSignalsColumns();
        return;
    }

    const columnDefs = [
        {
            field: 'ticker',
            headerName: 'Ticker',
            minWidth: 130,
            cellRenderer: TickerCellRenderer,
            pinned: 'left'
        },
        {
            field: 'company_name',
            headerName: 'Company',
            minWidth: 220,
            valueFormatter: (params: any) => {
                return params.value || 'N/A';
            }
        },
        {
            field: 'analyzed',
            headerName: 'Analyzed',
            minWidth: 110,
            valueFormatter: (params: any) => {
                return params.value ? 'Yes' : 'No';
            },
            cellRenderer: (params: any) => {
                const val = !!params.value;
                const badgeClass = val
                    ? 'bg-dashboard-surface-alt text-theme-success-text border border-theme-success-text'
                    : 'bg-dashboard-surface-alt text-text-secondary border border-border';
                return `<span class="px-2 py-1 rounded text-xs font-semibold ${badgeClass}">${val ? 'Yes' : 'No'}</span>`;
            }
        },
        {
            field: 'overall_signal',
            headerName: 'Signal',
            minWidth: 120,
            cellRenderer: (params: any) => {
                const signal = params.value || 'HOLD';
                let badgeClass = 'px-3 py-1 rounded-full text-xs font-bold border ';
                switch (signal) {
                    case 'BUY':
                        badgeClass += 'bg-green-500/10 text-green-500 border-green-500/30';
                        break;
                    case 'SELL':
                        badgeClass += 'bg-red-500/10 text-red-500 border-red-500/30';
                        break;
                    case 'WATCH':
                        badgeClass += 'bg-orange-500/10 text-orange-500 border-orange-500/30';
                        break;
                    default:
                        badgeClass += 'bg-dashboard-surface-alt text-text-secondary border-border';
                }
                return `<span class="${badgeClass}">${signal}</span>`;
            }
        },
        {
            field: 'confidence',
            headerName: 'Confidence',
            minWidth: 120,
            valueFormatter: (params: any) => {
                const val = params.value || 0;
                return `${(val * 100).toFixed(0)}%`;
            },
            cellStyle: (params: any) => {
                const val = params.value || 0;
                if (val >= 0.7) {
                    return { color: 'var(--color-success-text)', fontWeight: 'bold' }; // green
                } else if (val >= 0.5) {
                    return { color: 'var(--color-warning-text)', fontWeight: 'bold' }; // yellow
                } else {
                    return { color: 'var(--color-error-text)', fontWeight: 'bold' }; // red
                }
            }
        },
        {
            field: 'fear_level',
            headerName: 'Fear Level',
            minWidth: 130,
            cellRenderer: (params: any) => {
                const level = params.value || 'LOW';
                let badgeClass = 'px-2 py-1 rounded text-xs font-bold ';
                switch (level) {
                    case 'EXTREME':
                        badgeClass += 'text-red-500';
                        break;
                    case 'HIGH':
                        badgeClass += 'text-orange-500';
                        break;
                    case 'MODERATE':
                        badgeClass += 'text-yellow-500';
                        break;
                    default:
                        badgeClass += 'text-green-500';
                }
                return `<span class="${badgeClass}">${level}</span>`;
            }
        },
        {
            field: 'risk_score',
            headerName: 'Risk Score',
            minWidth: 120,
            valueFormatter: (params: any) => {
                const val = params.value || 0;
                return `${val.toFixed(1)}/100`;
            },
            cellStyle: (params: any) => {
                const val = params.value || 0;
                if (val >= 70) {
                    return { color: 'var(--color-error-text)', fontWeight: 'bold' }; // red
                } else if (val >= 50) {
                    return { color: 'orange', fontWeight: 'bold' }; // orange
                } else if (val >= 30) {
                    return { color: 'var(--color-warning-text)', fontWeight: 'bold' }; // yellow
                } else {
                    return { color: 'var(--color-success-text)', fontWeight: 'bold' }; // green
                }
            }
        },
        {
            field: 'trend',
            headerName: 'Trend',
            minWidth: 120,
            cellRenderer: (params: any) => {
                const trend = params.value || 'NEUTRAL';
                let badgeClass = 'px-2.5 py-0.5 rounded text-xs font-medium border ';
                switch (trend) {
                    case 'UPTREND':
                        badgeClass += 'bg-theme-success-bg text-theme-success-text border-theme-success-text';
                        break;
                    case 'DOWNTREND':
                        badgeClass += 'bg-theme-error-bg text-theme-error-text border-theme-error-text';
                        break;
                    default:
                        badgeClass += 'bg-theme-warning-bg text-theme-warning-text border-theme-warning-text';
                }
                return `<span class="${badgeClass}">${trend}</span>`;
            }
        },
        {
            field: 'analysis_date',
            headerName: 'Last Updated',
            minWidth: 180,
            valueFormatter: (params: any) => {
                if (!params.value) return 'N/A';
                const date = new Date(params.value);
                return date.toLocaleString();
            }
        }
    ];

    const gridOptions = {
        columnDefs: columnDefs,
        rowData: data,
        defaultColDef: {
            sortable: true,
            filter: true,
            resizable: true,
            wrapHeaderText: true,
            autoHeaderHeight: true
        },
        pagination: true,
        paginationPageSize: 50,
        animateRows: true,
        rowHeight: 40,
        headerHeight: 40,
        suppressCellFocus: true,
        onRowClicked: (params: any) => {
            if (params && params.data) {
                openSignalsModal(params.data as SignalRow);
            }
        }
    };

    // Apply appropriate AgGrid theme based on current theme
    applyAgGridTheme(gridDiv);

    const gridApiInstance = (window as any).agGrid.createGrid(gridDiv, gridOptions);
    signalsGridApi = gridApiInstance;
    signalsGridColumnApi =
        typeof gridApiInstance.getColumnApi === "function"
            ? gridApiInstance.getColumnApi()
            : (gridApiInstance.columnApi ?? null);

    if (signalsGridApi && signalsGridColumnApi) {
        signalsGridApi.addEventListener('firstDataRendered', () => {
            setTimeout(() => {
                autoSizeSignalsColumns();
            }, 300);
        });
    }
}

function autoSizeSignalsColumns(): void {
    if (!signalsGridColumnApi) return;
    const allColumns = signalsGridColumnApi.getAllDisplayedColumns();
    if (allColumns && allColumns.length > 0) {
        const columnIds = allColumns.map((col: any) => col.getColId()).filter(Boolean);
        if (columnIds.length > 0) {
            signalsGridColumnApi.autoSizeColumns(columnIds, false);
        }
    }
}

// Function to update grid theme dynamically
function updateSignalsGridTheme(): void {
    const gridDiv = document.querySelector('#signals-grid') as HTMLElement | null;
    if (!gridDiv) {
        return;
    }

    // Update grid container class based on theme
    applyAgGridTheme(gridDiv);

    // Refresh grid to update cell and row styles
    if (signalsGridApi) {
        window.setTimeout(() => {
            if (!signalsGridApi) {
                return;
            }
            signalsGridApi.refreshCells();
            signalsGridApi.refreshHeader();
        }, 0);
    }
}

function openSignalsModal(row: SignalRow): void {
    const toggleBtn = document.getElementById('signals-modal-toggle') as HTMLButtonElement | null;
    if (toggleBtn) {
        toggleBtn.click();
    }

    activeModalTicker = row.ticker;

    const tickerEl = document.getElementById('signals-modal-ticker');
    const updatedEl = document.getElementById('signals-modal-updated');
    if (tickerEl) tickerEl.textContent = row.ticker;
    if (updatedEl) updatedEl.textContent = row.analysis_date ? new Date(row.analysis_date).toLocaleString() : 'N/A';

    const explanationEl = document.getElementById('signals-modal-explanation');
    if (explanationEl) {
        explanationEl.textContent = row.explanation || 'Select Regenerate to create an AI explanation.';
    }

    setModalStatus('Loading signal details...');
    loadModalDetails(row.ticker, false);
}

async function loadModalDetails(ticker: string, includeAi: boolean): Promise<void> {
    try {
        const response = await fetch(`/api/signals/analyze/${ticker}?include_ai=${includeAi ? '1' : '0'}`, {
            credentials: 'include'
        });
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        const result = await response.json();
        if (!result.success || !result.data) {
            setModalStatus('No signal details available.');
            return;
        }

        const signals = result.data;
        renderModalSignals(signals);

        if (includeAi && signals.explanation) {
            updateGridRowFromSignals(ticker, signals);
        }

        setModalStatus('');
    } catch (error) {
        console.error('Error loading signal details:', error);
        setModalStatus('Unable to load signal details.');
    }
}

function renderModalSignals(signals: any): void {
    const overallEl = document.getElementById('signals-modal-overall');
    const confidenceEl = document.getElementById('signals-modal-confidence');
    const fearEl = document.getElementById('signals-modal-fear');
    const riskEl = document.getElementById('signals-modal-risk');
    const trendEl = document.getElementById('signals-modal-trend');
    const pullbackEl = document.getElementById('signals-modal-pullback');
    const breakoutEl = document.getElementById('signals-modal-breakout');
    const volumeEl = document.getElementById('signals-modal-volume');
    const rsiEl = document.getElementById('signals-modal-rsi');
    const cciEl = document.getElementById('signals-modal-cci');
    const updatedEl = document.getElementById('signals-modal-updated');
    const explanationEl = document.getElementById('signals-modal-explanation');

    const overallSignal = signals.overall_signal || 'HOLD';
    const confidence = signals.confidence || 0;
    if (overallEl) overallEl.textContent = overallSignal;
    if (confidenceEl) confidenceEl.textContent = `${(confidence * 100).toFixed(0)}%`;

    if (updatedEl) updatedEl.textContent = signals.analysis_date ? new Date(signals.analysis_date).toLocaleString() : 'N/A';

    const fearRisk = signals.fear_risk || {};
    if (fearEl) fearEl.textContent = fearRisk.fear_level || 'LOW';
    if (riskEl) riskEl.textContent = fearRisk.risk_score !== undefined ? `${fearRisk.risk_score.toFixed(1)}/100` : 'N/A';

    const structure = signals.structure || {};
    if (trendEl) trendEl.textContent = structure.trend || 'N/A';
    if (pullbackEl) pullbackEl.textContent = structure.pullback ? 'Yes' : 'No';
    if (breakoutEl) breakoutEl.textContent = structure.breakout ? 'Yes' : 'No';

    const timing = signals.timing || {};
    if (volumeEl) volumeEl.textContent = timing.volume_ok ? 'OK' : 'Low';
    if (rsiEl) rsiEl.textContent = timing.rsi !== undefined ? timing.rsi.toFixed(1) : 'N/A';
    if (cciEl) cciEl.textContent = timing.cci !== undefined ? timing.cci.toFixed(1) : 'N/A';

    if (explanationEl && signals.explanation) {
        explanationEl.textContent = signals.explanation;
    }
}

function setModalStatus(message: string): void {
    const statusEl = document.getElementById('signals-modal-status');
    if (statusEl) {
        statusEl.textContent = message;
    }
}

function updateGridRowFromSignals(ticker: string, signals: any): void {
    if (!signalsGridApi) return;
    signalsGridApi.forEachNode((node: any) => {
        if (node.data?.ticker !== ticker) {
            return;
        }
        node.setDataValue('overall_signal', signals.overall_signal || 'HOLD');
        node.setDataValue('confidence', signals.confidence || 0);
        node.setDataValue('fear_level', signals.fear_risk?.fear_level || 'LOW');
        node.setDataValue('risk_score', signals.fear_risk?.risk_score || 0);
        node.setDataValue('trend', signals.structure?.trend || 'NEUTRAL');
        node.setDataValue('analysis_date', signals.analysis_date);
        node.setDataValue('explanation', signals.explanation || null);
        node.setDataValue('analyzed', !!signals.explanation);
    });
}

// Load signals data
async function loadSignalsData(refreshKey: number): Promise<void> {
    try {
        const response = await fetch(`/api/signals/watchlist?refresh_key=${refreshKey}`, {
            credentials: 'include'
        });
        if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);

        const result: SignalsResponse = await response.json();
        if (result.success && result.data) {
            const data = result.data as SignalRow[];

            // Update summary metrics
            if (result.summary) {
                const summary = result.summary;
                document.getElementById('signals-total')!.textContent = summary.total.toString();
                document.getElementById('signals-buy')!.textContent = summary.buy.toString();
                document.getElementById('signals-sell')!.textContent = summary.sell.toString();
                document.getElementById('signals-watch')!.textContent = summary.watch.toString();
                document.getElementById('signals-hold')!.textContent = summary.hold.toString();
                document.getElementById('fear-low')!.textContent = summary.fear_low.toString();
                document.getElementById('fear-moderate')!.textContent = summary.fear_moderate.toString();
                document.getElementById('fear-high')!.textContent = summary.fear_high.toString();
                document.getElementById('fear-extreme')!.textContent = summary.fear_extreme.toString();
            }

            // Initialize grid
            if (data.length > 0) {
                document.getElementById('signals-loading')!.classList.add('hidden');
                document.getElementById('signals-empty')!.classList.add('hidden');
                document.getElementById('signals-content')!.classList.remove('hidden');
                initializeSignalsGrid(data);
            } else {
                document.getElementById('signals-loading')!.classList.add('hidden');
                document.getElementById('signals-content')!.classList.add('hidden');
                document.getElementById('signals-empty')!.classList.remove('hidden');
            }
        }
    } catch (error) {
        console.error('Error loading signals:', error);
        document.getElementById('signals-loading')!.classList.add('hidden');
        document.getElementById('signals-content')!.classList.add('hidden');
        document.getElementById('signals-empty')!.classList.remove('hidden');
    }
}

// Make refreshData available globally for onclick handler
(window as any).refreshData = refreshData;
