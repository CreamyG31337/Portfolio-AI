/**
 * Congress Closed Positions Page
 * ==============================
 *
 * Displays politician leaderboard and position-level detail for
 * buy/sell round-trips.
 */

// ── Types ────────────────────────────────────────────────────────────

interface LeaderboardEntry {
    politician_id: number;
    politician: string;
    party: string;
    chamber: string;
    positions: number;
    wins: number;
    losses: number;
    win_pct: number;
    avg_return_pct: number;
    total_est_invested: number;
    total_est_pnl: number;
    best_position: { ticker: string; pct_return: number; est_pnl: number } | null;
    worst_position: { ticker: string; pct_return: number; est_pnl: number } | null;
}

interface Position {
    id: number;
    politician: string;
    party: string;
    chamber: string;
    ticker: string;
    buy_count: number;
    sell_count: number;
    first_buy_date: string;
    last_sell_date: string;
    avg_buy_price: number | null;
    avg_sell_price: number | null;
    pct_return: number | null;
    est_invested: number | null;
    est_pnl: number | null;
    days_held: number | null;
    spy_pct_change: number | null;
}

// ── State ────────────────────────────────────────────────────────────

let currentPeriod = 'last_12m';
let currentMinPositions = 3;
let currentSort = 'total_est_pnl';
let positionsGridApi: any = null;

// ── Helpers ──────────────────────────────────────────────────────────

function formatDollars(val: number | null): string {
    if (val === null || val === undefined) return '--';
    const abs = Math.abs(val);
    const sign = val < 0 ? '-' : val > 0 ? '+' : '';
    if (abs >= 1_000_000) return `${sign}$${(abs / 1_000_000).toFixed(1)}M`;
    if (abs >= 1_000) return `${sign}$${(abs / 1_000).toFixed(0)}K`;
    return `${sign}$${abs.toFixed(0)}`;
}

function formatPct(val: number | null): string {
    if (val === null || val === undefined) return '--';
    const sign = val > 0 ? '+' : '';
    return `${sign}${val.toFixed(1)}%`;
}

function partyColor(party: string): string {
    if (party === 'Republican') return 'text-red-400';
    if (party === 'Democrat') return 'text-blue-400';
    return 'text-gray-400';
}

function partyBadge(party: string): string {
    const letter = party === 'Republican' ? 'R' : party === 'Democrat' ? 'D' : 'I';
    const color = party === 'Republican' ? 'bg-red-500/20 text-red-400' :
                  party === 'Democrat' ? 'bg-blue-500/20 text-blue-400' :
                  'bg-gray-500/20 text-gray-400';
    return `<span class="inline-flex items-center justify-center w-6 h-6 rounded-full text-xs font-bold ${color}">${letter}</span>`;
}

function pnlColor(val: number | null): string {
    if (val === null || val === undefined) return '';
    return val > 0 ? 'text-green-400' : val < 0 ? 'text-red-400' : 'text-text-secondary';
}

// ── Dark mode detection ──────────────────────────────────────────────

function isDarkMode(): boolean {
    return document.documentElement.classList.contains('dark') ||
           document.body.classList.contains('dark-mode') ||
           window.matchMedia('(prefers-color-scheme: dark)').matches;
}

// ── Leaderboard ──────────────────────────────────────────────────────

async function loadLeaderboard(): Promise<void> {
    const loading = document.getElementById('leaderboard-loading');
    const container = document.getElementById('leaderboard-container');
    const empty = document.getElementById('leaderboard-empty');
    if (!loading || !container || !empty) return;

    loading.classList.remove('hidden');
    container.classList.add('hidden');
    empty.classList.add('hidden');

    try {
        const params = new URLSearchParams({
            period: currentPeriod,
            min_positions: currentMinPositions.toString(),
            sort_by: currentSort,
            limit: '50',
        });

        const resp = await fetch(`/api/congress_trades/positions/leaderboard?${params}`);
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data = await resp.json();

        const entries: LeaderboardEntry[] = data.leaderboard || [];

        if (entries.length === 0) {
            loading.classList.add('hidden');
            empty.classList.remove('hidden');
            return;
        }

        const tbody = document.getElementById('leaderboard-body');
        if (!tbody) return;

        tbody.innerHTML = entries.map((e, i) => {
            const pnlCls = pnlColor(e.total_est_pnl);
            const returnCls = pnlColor(e.avg_return_pct);
            const bestStr = e.best_position ?
                `<a href="/ticker?ticker=${e.best_position.ticker}" class="ticker-link text-green-400 hover:text-green-300 font-medium underline" title="${e.best_position.ticker} — ${formatPct(e.best_position.pct_return)} return, ${formatDollars(e.best_position.est_pnl)} est. P&amp;L">${e.best_position.ticker}</a> &nbsp;<span class="text-text-tertiary">${formatPct(e.best_position.pct_return)}</span>` : '--';
            const worstStr = e.worst_position ?
                `<a href="/ticker?ticker=${e.worst_position.ticker}" class="ticker-link text-red-400 hover:text-red-300 font-medium underline" title="${e.worst_position.ticker} — ${formatPct(e.worst_position.pct_return)} return, ${formatDollars(e.worst_position.est_pnl)} est. P&amp;L">${e.worst_position.ticker}</a> &nbsp;<span class="text-text-tertiary">${formatPct(e.worst_position.pct_return)}</span>` : '--';

            return `<tr class="border-b border-border/50 hover:bg-dashboard-surface-alt/50 cursor-pointer" data-politician="${e.politician}">
                <td class="py-3 pr-4 text-text-tertiary">${i + 1}</td>
                <td class="py-3 pr-4 font-medium text-text-primary">${e.politician}</td>
                <td class="py-3 pr-4">${partyBadge(e.party)}</td>
                <td class="py-3 pr-4 text-text-secondary text-xs">${e.chamber}</td>
                <td class="py-3 pr-4 text-right text-text-primary">${e.positions}</td>
                <td class="py-3 pr-4 text-right"><span class="text-green-400">${e.wins}</span> / <span class="text-red-400">${e.losses}</span></td>
                <td class="py-3 pr-4 text-right ${e.win_pct >= 50 ? 'text-green-400' : 'text-red-400'}">${e.win_pct.toFixed(1)}%</td>
                <td class="py-3 pr-4 text-right ${returnCls}">${formatPct(e.avg_return_pct)}</td>
                <td class="py-3 pr-4 text-right text-text-secondary">${formatDollars(e.total_est_invested)}</td>
                <td class="py-3 pr-6 text-right font-semibold whitespace-nowrap ${pnlCls}">${formatDollars(e.total_est_pnl)}</td>
                <td class="py-3 pr-6 text-xs whitespace-nowrap">${bestStr}</td>
                <td class="py-3 text-xs whitespace-nowrap">${worstStr}</td>
            </tr>`;
        }).join('');

        loading.classList.add('hidden');
        container.classList.remove('hidden');

        // Click row to filter positions grid (but not if clicking a ticker link)
        tbody.querySelectorAll('tr[data-politician]').forEach(row => {
            row.addEventListener('click', (evt: Event) => {
                const target = evt.target as HTMLElement;
                // Don't intercept clicks on ticker links
                if (target.tagName === 'A' || target.closest('a.ticker-link')) {
                    return;
                }
                const name = row.getAttribute('data-politician') || '';
                const filterInput = document.getElementById('politician-filter') as HTMLInputElement;
                if (filterInput) {
                    filterInput.value = name;
                    filterInput.dispatchEvent(new Event('input'));
                }
            });
        });

    } catch (err) {
        console.error('Failed to load leaderboard:', err);
        loading.classList.add('hidden');
        empty.classList.remove('hidden');
    }
}

// ── Positions Grid ───────────────────────────────────────────────────

function initPositionsGrid(): void {
    const gridDiv = document.getElementById('positions-grid');
    if (!gridDiv) return;

    // Apply dark theme
    if (isDarkMode()) {
        gridDiv.classList.remove('ag-theme-alpine');
        gridDiv.classList.add('ag-theme-alpine-dark');
    }

    const columnDefs = [
        {
            headerName: 'Politician',
            field: 'politician',
            minWidth: 180,
            filter: true,
        },
        {
            headerName: 'Party',
            field: 'party',
            maxWidth: 80,
            cellRenderer: (params: any) => {
                if (!params.value) return '';
                return partyBadge(params.value);
            },
        },
        {
            headerName: 'Ticker',
            field: 'ticker',
            maxWidth: 100,
            filter: true,
            cellRenderer: (params: any) => {
                if (!params.value) return '';
                return `<a href="/ticker?ticker=${params.value}" class="text-blue-400 hover:text-blue-300 font-medium">${params.value}</a>`;
            },
        },
        {
            headerName: 'Buys',
            field: 'buy_count',
            maxWidth: 75,
            type: 'numericColumn',
        },
        {
            headerName: 'Sells',
            field: 'sell_count',
            maxWidth: 75,
            type: 'numericColumn',
        },
        {
            headerName: 'First Buy',
            field: 'first_buy_date',
            maxWidth: 120,
        },
        {
            headerName: 'Last Sell',
            field: 'last_sell_date',
            maxWidth: 120,
        },
        {
            headerName: 'Days',
            field: 'days_held',
            maxWidth: 80,
            type: 'numericColumn',
        },
        {
            headerName: 'Avg Buy',
            field: 'avg_buy_price',
            maxWidth: 100,
            type: 'numericColumn',
            valueFormatter: (params: any) => params.value != null ? `$${params.value.toFixed(2)}` : '--',
        },
        {
            headerName: 'Avg Sell',
            field: 'avg_sell_price',
            maxWidth: 100,
            type: 'numericColumn',
            valueFormatter: (params: any) => params.value != null ? `$${params.value.toFixed(2)}` : '--',
        },
        {
            headerName: 'Return %',
            field: 'pct_return',
            maxWidth: 100,
            type: 'numericColumn',
            sort: 'desc',
            cellRenderer: (params: any) => {
                if (params.value == null) return '--';
                const val = params.value;
                const color = val > 0 ? '#4ade80' : val < 0 ? '#f87171' : '#9ca3af';
                const sign = val > 0 ? '+' : '';
                return `<span style="color: ${color}; font-weight: 600;">${sign}${val.toFixed(1)}%</span>`;
            },
        },
        {
            headerName: 'Est. Invested',
            field: 'est_invested',
            maxWidth: 130,
            type: 'numericColumn',
            valueFormatter: (params: any) => params.value != null ? formatDollars(params.value) : '--',
        },
        {
            headerName: 'Est. P&L',
            field: 'est_pnl',
            maxWidth: 120,
            type: 'numericColumn',
            cellRenderer: (params: any) => {
                if (params.value == null) return '--';
                const val = params.value;
                const color = val > 0 ? '#4ade80' : val < 0 ? '#f87171' : '#9ca3af';
                return `<span style="color: ${color}; font-weight: 600;">${formatDollars(val)}</span>`;
            },
        },
        {
            headerName: 'SPY %',
            field: 'spy_pct_change',
            maxWidth: 90,
            type: 'numericColumn',
            cellRenderer: (params: any) => {
                if (params.value == null) return '--';
                const val = params.value;
                const sign = val > 0 ? '+' : '';
                return `<span class="text-text-tertiary">${sign}${val.toFixed(1)}%</span>`;
            },
        },
    ];

    const gridOptions = {
        columnDefs,
        defaultColDef: {
            sortable: true,
            resizable: true,
        },
        rowData: [],
        animateRows: true,
        pagination: true,
        paginationPageSize: 100,
        paginationPageSizeSelector: [50, 100, 250, 500],
        suppressCellFocus: true,
        domLayout: 'normal' as const,
    };

    // @ts-ignore - agGrid is loaded via CDN
    positionsGridApi = agGrid.createGrid(gridDiv, gridOptions);
}

async function loadPositions(): Promise<void> {
    if (!positionsGridApi) return;

    const politicianFilter = (document.getElementById('politician-filter') as HTMLInputElement)?.value || '';
    const tickerFilter = (document.getElementById('ticker-filter') as HTMLInputElement)?.value || '';

    try {
        const params = new URLSearchParams({
            period: currentPeriod,
            sort_by: 'est_pnl',
            sort_dir: 'desc',
            limit: '2000',
        });
        if (politicianFilter) params.set('politician', politicianFilter);

        const resp = await fetch(`/api/congress_trades/positions/data?${params}`);
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data = await resp.json();

        let positions: Position[] = data.positions || [];

        // Client-side ticker filter
        if (tickerFilter) {
            const tf = tickerFilter.toUpperCase();
            positions = positions.filter(p => p.ticker.toUpperCase().includes(tf));
        }

        positionsGridApi.setGridOption('rowData', positions);

        const countEl = document.getElementById('position-count');
        if (countEl) {
            countEl.textContent = `(${positions.length} positions)`;
        }

    } catch (err) {
        console.error('Failed to load positions:', err);
    }
}

// ── Init ─────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
    // Period buttons
    document.querySelectorAll('#period-buttons button').forEach(btn => {
        btn.addEventListener('click', () => {
            currentPeriod = btn.getAttribute('data-period') || 'last_12m';

            // Update button styles
            document.querySelectorAll('#period-buttons button').forEach(b => {
                b.className = 'px-3 py-1.5 text-sm rounded-lg border border-border text-text-secondary hover:bg-dashboard-surface-alt transition-colors';
            });
            btn.className = 'px-3 py-1.5 text-sm rounded-lg border border-blue-500 bg-blue-500/10 text-blue-400 font-medium';

            loadLeaderboard();
            loadPositions();
        });
    });

    // Min positions select
    const minPosSelect = document.getElementById('min-positions-select') as HTMLSelectElement;
    if (minPosSelect) {
        minPosSelect.addEventListener('change', () => {
            currentMinPositions = parseInt(minPosSelect.value, 10);
            loadLeaderboard();
        });
    }

    // Leaderboard sort
    const sortSelect = document.getElementById('leaderboard-sort') as HTMLSelectElement;
    if (sortSelect) {
        sortSelect.addEventListener('change', () => {
            currentSort = sortSelect.value;
            loadLeaderboard();
        });
    }

    // Filter inputs with debounce
    let filterTimeout: number | null = null;
    const politicianInput = document.getElementById('politician-filter') as HTMLInputElement;
    const tickerInput = document.getElementById('ticker-filter') as HTMLInputElement;

    const debouncedLoad = () => {
        if (filterTimeout) clearTimeout(filterTimeout);
        filterTimeout = window.setTimeout(() => loadPositions(), 300);
    };

    if (politicianInput) politicianInput.addEventListener('input', debouncedLoad);
    if (tickerInput) tickerInput.addEventListener('input', debouncedLoad);

    // Init
    initPositionsGrid();
    loadLeaderboard();
    loadPositions();
});
