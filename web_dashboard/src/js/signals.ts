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

            if (logoUrl && !failedLogoCache.has(cacheKey)) {
                const img = document.createElement('img');
                img.src = logoUrl;
                img.alt = ticker;
                img.style.width = '24px';
                img.style.height = '24px';
                img.style.objectFit = 'contain';
                img.style.borderRadius = '4px';
                img.style.flexShrink = '0';
                let fallbackAttempted = false;
                img.onerror = function () {
                    if (fallbackAttempted) {
                        failedLogoCache.add(cacheKey);
                        img.style.display = 'none';
                        img.onerror = null;
                        return;
                    }
                    fallbackAttempted = true;
                    const yahooUrl = `https://s.yimg.com/cv/apiv2/default/images/logos/${cleanTicker}.png`;
                    if (img.src !== yahooUrl) {
                        img.src = yahooUrl;
                    } else {
                        failedLogoCache.add(cacheKey);
                        img.style.display = 'none';
                        img.onerror = null;
                    }
                };
                this.eGui.appendChild(img);
            }

            const tickerSpan = document.createElement('span');
            tickerSpan.innerText = ticker;
            tickerSpan.className = 'text-accent hover:text-accent-hover font-bold underline cursor-pointer';
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
            width: 100,
            cellRenderer: TickerCellRenderer,
            pinned: 'left'
        },
        {
            field: 'company_name',
            headerName: 'Company',
            width: 220,
            valueFormatter: (params: any) => {
                return params.value || 'N/A';
            }
        },
        {
            field: 'analyzed',
            headerName: 'Analyzed',
            width: 110,
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
            width: 100,
            cellRenderer: (params: any) => {
                const signal = params.value || 'HOLD';
                let badgeClass = 'px-2 py-1 rounded text-xs font-semibold border ';
                switch (signal) {
                    case 'BUY':
                        badgeClass += 'bg-theme-success-bg text-theme-success-text border-theme-success-text';
                        break;
                    case 'SELL':
                        badgeClass += 'bg-theme-error-bg text-theme-error-text border-theme-error-text';
                        break;
                    case 'WATCH':
                        badgeClass += 'bg-theme-warning-bg text-theme-warning-text border-theme-warning-text';
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
            width: 120,
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
            width: 130,
            cellRenderer: (params: any) => {
                const level = params.value || 'LOW';
                let textClass = 'font-semibold ';
                switch (level) {
                    case 'EXTREME':
                        textClass += 'text-theme-error-text';
                        break;
                    case 'HIGH':
                        textClass += 'text-orange-500';
                        break;
                    case 'MODERATE':
                        textClass += 'text-theme-warning-text';
                        break;
                    default:
                        textClass += 'text-theme-success-text';
                }
                return `<span class="${textClass}">${level}</span>`;
            }
        },
        {
            field: 'risk_score',
            headerName: 'Risk Score',
            width: 120,
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
            width: 120,
            cellRenderer: (params: any) => {
                const trend = params.value || 'NEUTRAL';
                let textClass = 'font-semibold ';
                switch (trend) {
                    case 'UPTREND':
                        textClass += 'text-theme-success-text';
                        break;
                    case 'DOWNTREND':
                        textClass += 'text-theme-error-text';
                        break;
                    default:
                        textClass += 'text-text-secondary';
                }
                return `<span class="${textClass}">${trend}</span>`;
            }
        },
        {
            field: 'analysis_date',
            headerName: 'Last Updated',
            width: 180,
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
            resizable: true
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

    // Check if dark mode is enabled
    const isDark = document.documentElement.classList.contains('dark') ||
        (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches);

    if (isDark) {
        gridDiv.classList.add('ag-theme-alpine-dark');
    }

    const gridInstance = new (window as any).agGrid.Grid(gridDiv, gridOptions);
    signalsGridApi = gridInstance.api;
    signalsGridColumnApi = gridInstance.columnApi;

    if (signalsGridApi && signalsGridColumnApi) {
        signalsGridApi.addEventListener('firstDataRendered', () => {
            setTimeout(() => {
                autoSizeSignalsColumns();
            }, 300);
        });

        let resizeTimeout: number | null = null;
        window.addEventListener('resize', () => {
            if (resizeTimeout) {
                clearTimeout(resizeTimeout);
            }
            resizeTimeout = window.setTimeout(() => {
                autoSizeSignalsColumns();
            }, 150);
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
