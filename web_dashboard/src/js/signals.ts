export { }; // Ensure file is treated as a module

// Interfaces
interface SignalRow {
    ticker: string;
    overall_signal: string;
    confidence: number;
    fear_level: string;
    risk_score: number;
    trend: string;
    analysis_date?: string;
    cached?: boolean;
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
let refreshKey = 0;

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
    loadSignalsData(refreshKey);
    
    // Set up refresh button
    const refreshBtn = document.getElementById('refresh-btn');
    if (refreshBtn) {
        refreshBtn.addEventListener('click', refreshData);
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

    const columnDefs = [
        {
            field: 'ticker',
            headerName: 'Ticker',
            width: 100,
            cellRenderer: (params: any) => {
                const ticker = params.value;
                return `<a href="/ticker?ticker=${ticker}" class="text-blue-600 hover:text-blue-800 dark:text-blue-400 dark:hover:text-blue-300 font-semibold">${ticker}</a>`;
            },
            pinned: 'left'
        },
        {
            field: 'overall_signal',
            headerName: 'Signal',
            width: 100,
            cellRenderer: (params: any) => {
                const signal = params.value || 'HOLD';
                let badgeClass = 'px-2 py-1 rounded text-xs font-semibold ';
                switch (signal) {
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
                    return { color: '#16a34a' }; // green
                } else if (val >= 0.5) {
                    return { color: '#ca8a04' }; // yellow
                } else {
                    return { color: '#dc2626' }; // red
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
                        textClass += 'text-red-600 dark:text-red-400';
                        break;
                    case 'HIGH':
                        textClass += 'text-orange-600 dark:text-orange-400';
                        break;
                    case 'MODERATE':
                        textClass += 'text-yellow-600 dark:text-yellow-400';
                        break;
                    default:
                        textClass += 'text-green-600 dark:text-green-400';
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
                    return { color: '#dc2626' }; // red
                } else if (val >= 50) {
                    return { color: '#ea580c' }; // orange
                } else if (val >= 30) {
                    return { color: '#ca8a04' }; // yellow
                } else {
                    return { color: '#16a34a' }; // green
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
                        textClass += 'text-green-600 dark:text-green-400';
                        break;
                    case 'DOWNTREND':
                        textClass += 'text-red-600 dark:text-red-400';
                        break;
                    default:
                        textClass += 'text-gray-600 dark:text-gray-400';
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
        suppressCellFocus: true
    };

    // Check if dark mode is enabled
    const isDark = document.documentElement.classList.contains('dark') ||
                   (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches);
    
    if (isDark) {
        gridDiv.classList.add('ag-theme-alpine-dark');
    }

    const gridInstance = new (window as any).agGrid.Grid(gridDiv, gridOptions);
    signalsGridApi = gridInstance.api;

    if (signalsGridApi) {
        signalsGridApi.sizeColumnsToFit();
    }
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
