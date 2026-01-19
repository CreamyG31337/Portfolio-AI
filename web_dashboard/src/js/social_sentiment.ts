/**
 * Social Sentiment TypeScript
 * Handles AgGrid initialization, data fetching, and interactions
 */

// AgGrid types
interface AgGridParams {
    value: string | null;
    data?: any;
    column?: {
        colId: string;
    };
    node?: AgGridNode;
}

interface AgGridNode {
    setDataValue(key: string, value: string): void;
    setSelected(selected: boolean): void;
}

interface AgGridApi {
    getSelectedRows(): any[];
    getSelectedNodes(): AgGridNode[];
    sizeColumnsToFit(): void;
    setGridOption(option: string, value: any): void;
}

interface AgGridColumnApi {
    // Column API methods if needed
}

interface AgGridGrid {
    api: AgGridApi;
    columnApi: AgGridColumnApi;
}

interface AgGridGlobal {
    Grid: new (element: HTMLElement, options: AgGridOptions) => AgGridGrid;
}

interface AgGridOptions {
    columnDefs: AgGridColumnDef[];
    rowData: any[];
    defaultColDef?: Partial<AgGridColumnDef>;
    rowSelection?: any;
    enableRangeSelection?: boolean;
    enableCellTextSelection?: boolean;
    ensureDomOrder?: boolean;
    domLayout?: string;
    pagination?: boolean;
    paginationPageSize?: number;
    paginationPageSizeSelector?: number[];
    onCellClicked?: (params: AgGridParams) => void;
    onSelectionChanged?: () => void;
    animateRows?: boolean;
    suppressCellFocus?: boolean;
}

interface AgGridColumnDef {
    field: string;
    headerName: string;
    valueGetter?: (params: AgGridParams) => any;
    width?: number;
    pinned?: string;
    cellRenderer?: any;
    sortable?: boolean;
    filter?: boolean;
    hide?: boolean;
    editable?: boolean;
    resizable?: boolean;
    tooltipValueGetter?: (params: AgGridParams) => string;
    cellStyle?: Record<string, string> | ((params: AgGridParams) => Record<string, string>);
}

interface AgGridCellRendererParams {
    value: string | null;
    data?: any;
}

interface AgGridCellRenderer {
    init(params: AgGridCellRendererParams): void;
    getGui(): HTMLElement;
}

// Data interfaces
interface WatchlistTicker {
    ticker: string;
    priority_tier: string;
    sources: string[];
    source_count: number;
    created_at?: string;
}

interface Alert {
    id: number;
    ticker: string;
    platform: string;
    sentiment_label: string;
    sentiment_score: number;
    analysis_session_id?: number;
    created_at: string;
    created_at_raw?: string;
}

interface AIAnalysis {
    id: number;
    ticker: string;
    platform: string;
    sentiment_label: string;
    sentiment_score: number;
    confidence_score: number;
    post_count: number;
    total_engagement: number;
    session_id: number;
    analyzed_at: string;
    analyzed_at_raw?: string;
}

interface SentimentRow {
    Ticker: string;
    Company: string;
    'In Watchlist': string;
    '💬 Stocktwits Sentiment': string;
    '💬 Stocktwits Volume': number | string;
    '💬 Stocktwits Score': string;
    '💬 Bull/Bear Ratio': string;
    '👽 Reddit Sentiment': string;
    '👽 Reddit Volume': number | string;
    '👽 Reddit Score': string;
    'Last Updated': string;
    '🤖 AI Status'?: string;
    '🤖 AI Sentiment'?: string;
    '🤖 AI Confidence'?: string;
}

// Global grid APIs
let watchlistGridApi: AgGridApi | null = null;
let sentimentGridApi: AgGridApi | null = null;

// Ticker cell renderer - makes ticker clickable
class TickerCellRenderer implements AgGridCellRenderer {
    private eGui!: HTMLElement;

    init(params: AgGridCellRendererParams): void {
        this.eGui = document.createElement('span');
        if (params.value && params.value !== 'N/A') {
            this.eGui.innerText = params.value;
            this.eGui.style.color = '#1f77b4';
            this.eGui.style.fontWeight = 'bold';
            this.eGui.style.textDecoration = 'underline';
            this.eGui.style.cursor = 'pointer';
            this.eGui.addEventListener('click', function (e: Event) {
                e.stopPropagation();
                const ticker = params.value;
                if (ticker && ticker !== 'N/A') {
                    window.location.href = `/ticker?ticker=${encodeURIComponent(ticker)}`;
                }
            });
        } else {
            this.eGui.innerText = params.value || 'N/A';
        }
    }

    getGui(): HTMLElement {
        return this.eGui;
    }
}

// Sentiment color cell renderer
class SentimentCellRenderer implements AgGridCellRenderer {
    private eGui!: HTMLElement;

    init(params: AgGridCellRendererParams): void {
        this.eGui = document.createElement('span');
        const value = params.value || '';
        this.eGui.innerText = value;

        // Apply color based on sentiment
        if (value.includes('EUPHORIC')) {
            this.eGui.style.color = 'green';
            this.eGui.style.fontWeight = 'bold';
        } else if (value.includes('FEARFUL')) {
            this.eGui.style.color = 'red';
            this.eGui.style.fontWeight = 'bold';
        } else if (value.includes('BULLISH')) {
            this.eGui.style.color = 'lightgreen';
        } else if (value.includes('BEARISH')) {
            this.eGui.style.color = 'lightcoral';
        }
    }

    getGui(): HTMLElement {
        return this.eGui;
    }
}

// Initialize watchlist grid
function initializeWatchlistGrid(data: WatchlistTicker[]): void {
    const gridDiv = document.querySelector('#watchlist-grid') as HTMLElement;

    // Detect theme and apply appropriate AgGrid theme
    const htmlElement = document.documentElement;
    const theme = htmlElement.getAttribute('data-theme') || 'system';
    let isDark = false;

    if (theme === 'dark' || theme === 'midnight-tokyo' || theme === 'abyss') {
        isDark = true;
    } else if (theme === 'system') {
        // Check system preference
        if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
            isDark = true;
        }
    }

    // Update grid container class based on theme
    if (isDark) {
        gridDiv.classList.remove('ag-theme-alpine');
        gridDiv.classList.add('ag-theme-alpine-dark');
    } else {
        gridDiv.classList.remove('ag-theme-alpine-dark');
        gridDiv.classList.add('ag-theme-alpine');
    }
    if (!gridDiv) {
        console.error('Watchlist grid container not found');
        return;
    }
    if (!(window as any).agGrid) {
        console.error('AgGrid not loaded');
        return;
    }

    const columnDefs: AgGridColumnDef[] = [
        {
            field: 'ticker',
            headerName: 'Ticker',
            width: 100,
            pinned: 'left',
            cellRenderer: TickerCellRenderer,
            sortable: true,
            filter: true
        },
        {
            field: 'priority_tier',
            headerName: 'Priority',
            width: 80,
            sortable: true,
            filter: true
        },
        {
            field: 'sources',
            headerName: 'Sources',
            width: 200,
            sortable: true,
            filter: true,
            valueGetter: (params: AgGridParams) => {
                return params.data?.sources?.join(', ') || '';
            }
        },
        {
            field: 'source_count',
            headerName: 'Source Count',
            width: 120,
            sortable: true,
            filter: true
        }
    ];

    const gridOptions: AgGridOptions = {
        columnDefs: columnDefs,
        rowData: data,
        defaultColDef: {
            editable: false,
            sortable: true,
            filter: true,
            resizable: true
        },
        pagination: true,
        paginationPageSize: 50,
        paginationPageSizeSelector: [25, 50, 100],
        animateRows: true
    };

    const agGrid = (window as any).agGrid as AgGridGlobal;
    const gridInstance = new agGrid.Grid(gridDiv, gridOptions);
    watchlistGridApi = gridInstance.api;

    if (watchlistGridApi) {
        watchlistGridApi.sizeColumnsToFit();
    }
}

// Initialize sentiment grid
function initializeSentimentGrid(data: SentimentRow[]): void {
    const gridDiv = document.querySelector('#sentiment-grid') as HTMLElement;
    if (!gridDiv) {
        console.error('Sentiment grid container not found');
        return;
    }
    if (!(window as any).agGrid) {
        console.error('AgGrid not loaded');
        return;
    }

    // Detect theme and apply appropriate AgGrid theme
    const htmlElement = document.documentElement;
    const theme = htmlElement.getAttribute('data-theme') || 'system';
    let isDark = false;

    if (theme === 'dark' || theme === 'midnight-tokyo' || theme === 'abyss') {
        isDark = true;
    } else if (theme === 'system') {
        // Check system preference
        if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
            isDark = true;
        }
    }

    // Update grid container class based on theme
    if (isDark) {
        gridDiv.classList.remove('ag-theme-alpine');
        gridDiv.classList.add('ag-theme-alpine-dark');
    } else {
        gridDiv.classList.remove('ag-theme-alpine-dark');
        gridDiv.classList.add('ag-theme-alpine');
    }

    const columnDefs: AgGridColumnDef[] = [
        {
            field: 'Ticker',
            headerName: 'Ticker',
            width: 100,
            pinned: 'left',
            cellRenderer: TickerCellRenderer,
            sortable: true,
            filter: true
        },
        {
            field: 'Company',
            headerName: 'Company',
            width: 200,
            sortable: true,
            filter: true
        },
        {
            field: 'In Watchlist',
            headerName: 'In Watchlist',
            width: 120,
            sortable: true,
            filter: true
        },
        {
            field: '🤖 AI Status',
            headerName: 'AI Status',
            width: 120,
            sortable: true,
            filter: true
        },
        {
            field: '🤖 AI Sentiment',
            headerName: 'AI Sentiment',
            width: 120,
            sortable: true,
            filter: true,
            cellRenderer: SentimentCellRenderer
        },
        {
            field: '🤖 AI Confidence',
            headerName: 'AI Confidence',
            width: 120,
            sortable: true,
            filter: true
        },
        {
            field: '💬 Stocktwits Sentiment',
            headerName: 'Stocktwits Sentiment',
            width: 180,
            sortable: true,
            filter: true,
            cellRenderer: SentimentCellRenderer
        },
        {
            field: '💬 Stocktwits Volume',
            headerName: 'Stocktwits Volume',
            width: 150,
            sortable: true,
            filter: true
        },
        {
            field: '💬 Stocktwits Score',
            headerName: 'Stocktwits Score',
            width: 130,
            sortable: true,
            filter: true
        },
        {
            field: '💬 Bull/Bear Ratio',
            headerName: 'Bull/Bear Ratio',
            width: 130,
            sortable: true,
            filter: true
        },
        {
            field: '👽 Reddit Sentiment',
            headerName: 'Reddit Sentiment',
            width: 150,
            sortable: true,
            filter: true,
            cellRenderer: SentimentCellRenderer
        },
        {
            field: '👽 Reddit Volume',
            headerName: 'Reddit Volume',
            width: 130,
            sortable: true,
            filter: true
        },
        {
            field: '👽 Reddit Score',
            headerName: 'Reddit Score',
            width: 120,
            sortable: true,
            filter: true
        },
        {
            field: 'Last Updated',
            headerName: 'Last Updated',
            width: 180,
            sortable: true,
            filter: true
        }
    ];

    const gridOptions: AgGridOptions = {
        columnDefs: columnDefs,
        rowData: data,
        defaultColDef: {
            editable: false,
            sortable: true,
            filter: true,
            resizable: true
        },
        pagination: true,
        paginationPageSize: 100,
        paginationPageSizeSelector: [50, 100, 250, 500],
        animateRows: true
    };

    const agGrid = (window as any).agGrid as AgGridGlobal;
    const gridInstance = new agGrid.Grid(gridDiv, gridOptions);
    sentimentGridApi = gridInstance.api;

    if (sentimentGridApi) {
        sentimentGridApi.sizeColumnsToFit();
    }
}

// Load watchlist data
async function loadWatchlistData(refreshKey: number): Promise<void> {
    try {
        const response = await fetch(`/api/social_sentiment/watchlist?refresh_key=${refreshKey}`);
        if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);

        const result = await response.json();
        if (result.success && result.data) {
            const data = result.data as WatchlistTicker[];

            // Update summary metrics
            document.getElementById('watchlist-total')!.textContent = data.length.toString();
            document.getElementById('watchlist-tier-a')!.textContent =
                data.filter(t => t.priority_tier === 'A').length.toString();
            document.getElementById('watchlist-tier-b')!.textContent =
                data.filter(t => t.priority_tier === 'B').length.toString();
            document.getElementById('watchlist-tier-c')!.textContent =
                data.filter(t => t.priority_tier === 'C').length.toString();

            // Initialize grid
            if (data.length > 0) {
                document.getElementById('watchlist-loading')!.classList.add('hidden');
                document.getElementById('watchlist-empty')!.classList.add('hidden');
                document.getElementById('watchlist-content')!.classList.remove('hidden');
                initializeWatchlistGrid(data);
            } else {
                document.getElementById('watchlist-loading')!.classList.add('hidden');
                document.getElementById('watchlist-content')!.classList.add('hidden');
                document.getElementById('watchlist-empty')!.classList.remove('hidden');
            }
        }
    } catch (error) {
        console.error('Error loading watchlist:', error);
        document.getElementById('watchlist-loading')!.classList.add('hidden');
        document.getElementById('watchlist-content')!.classList.add('hidden');
        document.getElementById('watchlist-empty')!.classList.remove('hidden');
    }
}

// Load alerts data
async function loadAlertsData(refreshKey: number): Promise<void> {
    try {
        const response = await fetch(`/api/social_sentiment/alerts?refresh_key=${refreshKey}`);
        if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);

        const result = await response.json();
        if (result.success && result.data) {
            const alerts = result.data as Alert[];
            const alertsList = document.getElementById('alerts-list')!;
            alertsList.innerHTML = '';

            if (alerts.length > 0) {
                document.getElementById('alerts-loading')!.classList.add('hidden');
                document.getElementById('alerts-empty')!.classList.add('hidden');
                document.getElementById('alerts-content')!.classList.remove('hidden');

                alerts.forEach((alert, idx) => {
                    const alertDiv = document.createElement('div');
                    alertDiv.className = 'mb-4 p-4 rounded-lg border';
                    alertDiv.classList.add(
                        alert.sentiment_label === 'EUPHORIC'
                            ? 'bg-green-50 dark:bg-green-900/30 border-green-200 dark:border-green-700'
                            : 'bg-red-50 dark:bg-red-900/30 border-red-200 dark:border-red-700'
                    );

                    alertDiv.innerHTML = `
                        <div class="flex items-center justify-between mb-2">
                            <div>
                                <span class="font-bold text-lg text-gray-900 dark:text-gray-100">${alert.ticker}</span>
                                <span class="ml-2 text-sm text-gray-600 dark:text-gray-400">(${alert.platform.toUpperCase()})</span>
                                <span class="ml-2 font-semibold text-gray-900 dark:text-gray-100">${alert.sentiment_label}</span>
                                <span class="ml-2 text-sm text-gray-700 dark:text-gray-300">Score: ${alert.sentiment_score.toFixed(1)}</span>
                            </div>
                            <div class="text-sm text-gray-600 dark:text-gray-400">${alert.created_at}</div>
                        </div>
                        <div class="flex gap-2 mt-2">
                            <button onclick="loadAlertPosts(${alert.id}, ${alert.analysis_session_id || 'null'}, ${idx})" 
                                    class="text-sm px-3 py-1 bg-blue-600 text-white rounded hover:bg-blue-700">
                                View Source Posts
                            </button>
                            <button onclick="window.location.href='/ticker?ticker=${encodeURIComponent(alert.ticker)}'" 
                                    class="text-sm px-3 py-1 bg-gray-600 text-white rounded hover:bg-gray-700">
                                View Ticker Details
                            </button>
                        </div>
                        <div id="alert-posts-${idx}" class="hidden mt-4"></div>
                    `;
                    alertsList.appendChild(alertDiv);
                });
            } else {
                document.getElementById('alerts-loading')!.classList.add('hidden');
                document.getElementById('alerts-content')!.classList.add('hidden');
                document.getElementById('alerts-empty')!.classList.remove('hidden');
            }
        }
    } catch (error) {
        console.error('Error loading alerts:', error);
        document.getElementById('alerts-loading')!.classList.add('hidden');
        document.getElementById('alerts-content')!.classList.add('hidden');
        document.getElementById('alerts-empty')!.classList.remove('hidden');
    }
}

// Load alert posts
async function loadAlertPosts(metricId: number, sessionId: number | null, alertIdx: number): Promise<void> {
    const postsDiv = document.getElementById(`alert-posts-${alertIdx}`)!;
    if (!postsDiv.classList.contains('hidden')) {
        postsDiv.classList.add('hidden');
        return;
    }

    try {
        let response;
        if (sessionId) {
            response = await fetch(`/api/social_sentiment/posts/session/${sessionId}`);
        } else {
            response = await fetch(`/api/social_sentiment/posts/${metricId}`);
        }

        if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);

        const result = await response.json();
        if (result.success && result.data) {
            const posts = result.data;
            postsDiv.innerHTML = '<h4 class="font-semibold mb-2 text-gray-900 dark:text-gray-100">Source Posts:</h4>';

            if (posts.length > 0) {
                posts.forEach((post: any) => {
                    const postDiv = document.createElement('div');
                    postDiv.className = 'mb-3 p-3 bg-white dark:bg-gray-800 rounded border border-gray-200 dark:border-gray-700';
                    postDiv.innerHTML = `
                        <div class="flex justify-between mb-1">
                            <span class="font-semibold text-gray-900 dark:text-gray-100">${post.author || 'Unknown'}</span>
                            <span class="text-sm text-gray-600 dark:text-gray-400">${post.posted_at}</span>
                        </div>
                        <p class="text-sm mb-2 text-gray-700 dark:text-gray-300">${post.content || ''}</p>
                        <div class="flex justify-between text-xs text-gray-600 dark:text-gray-400">
                            <span>👍 ${post.engagement_score || 0} engagement</span>
                            ${post.url ? `<a href="${post.url}" target="_blank" class="text-blue-600 dark:text-blue-400 hover:underline">View Original Post</a>` : ''}
                        </div>
                    `;
                    postsDiv.appendChild(postDiv);
                });
            } else {
                postsDiv.innerHTML += '<p class="text-sm text-gray-600 dark:text-gray-400">No posts found for this alert.</p>';
            }

            postsDiv.classList.remove('hidden');
        }
    } catch (error) {
        console.error('Error loading alert posts:', error);
        postsDiv.innerHTML = '<p class="text-sm text-red-600 dark:text-red-400">Error loading posts.</p>';
        postsDiv.classList.remove('hidden');
    }
}

// Load AI analyses data
async function loadAIAnalysesData(refreshKey: number): Promise<void> {
    try {
        const response = await fetch(`/api/social_sentiment/ai_analyses?refresh_key=${refreshKey}`);
        if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);

        const result = await response.json();
        if (result.success && result.data) {
            const analyses = result.data as AIAnalysis[];
            const analysesList = document.getElementById('ai-analyses-list')!;
            analysesList.innerHTML = '';

            // Update summary metrics
            document.getElementById('ai-total')!.textContent = analyses.length.toString();
            const avgConfidence = analyses.length > 0
                ? (analyses.reduce((sum, a) => sum + a.confidence_score, 0) / analyses.length * 100).toFixed(1)
                : '0';
            document.getElementById('ai-avg-confidence')!.textContent = `${avgConfidence}%`;
            document.getElementById('ai-euphoric')!.textContent =
                analyses.filter(a => a.sentiment_label === 'EUPHORIC').length.toString();
            document.getElementById('ai-fearful')!.textContent =
                analyses.filter(a => a.sentiment_label === 'FEARFUL').length.toString();

            if (analyses.length > 0) {
                document.getElementById('ai-loading')!.classList.add('hidden');
                document.getElementById('ai-empty')!.classList.add('hidden');
                document.getElementById('ai-content')!.classList.remove('hidden');

                analyses.forEach((analysis) => {
                    const analysisDiv = document.createElement('div');
                    analysisDiv.className = 'mb-4 p-4 bg-gray-50 dark:bg-gray-700 rounded-lg border border-gray-200 dark:border-gray-600';
                    analysisDiv.innerHTML = `
                        <div class="flex items-center justify-between mb-2">
                            <div>
                                <span class="font-bold text-gray-900 dark:text-gray-100">${analysis.ticker}</span>
                                <span class="ml-2 text-sm text-gray-600 dark:text-gray-400">${analysis.platform.toUpperCase()}</span>
                                <span class="ml-2 font-semibold ${analysis.sentiment_label === 'EUPHORIC' ? 'text-green-600 dark:text-green-400' : analysis.sentiment_label === 'FEARFUL' ? 'text-red-600 dark:text-red-400' : ''}">
                                    ${analysis.sentiment_label}
                                </span>
                            </div>
                            <div class="text-sm text-gray-600 dark:text-gray-400">${analysis.analyzed_at}</div>
                        </div>
                        <div class="grid grid-cols-4 gap-4 text-sm mb-2 text-gray-700 dark:text-gray-300">
                            <div>Score: ${analysis.sentiment_score.toFixed(1)}</div>
                            <div>Confidence: ${(analysis.confidence_score * 100).toFixed(1)}%</div>
                            <div>Posts: ${analysis.post_count}</div>
                            <div>Engagement: ${analysis.total_engagement}</div>
                        </div>
                        <button onclick="loadAIDetails(${analysis.id}, ${analysis.session_id})" 
                                class="text-sm px-3 py-1 bg-blue-600 text-white rounded hover:bg-blue-700">
                            View Details
                        </button>
                        <div id="ai-details-${analysis.id}" class="hidden mt-4"></div>
                    `;
                    analysesList.appendChild(analysisDiv);
                });
            } else {
                document.getElementById('ai-loading')!.classList.add('hidden');
                document.getElementById('ai-content')!.classList.add('hidden');
                document.getElementById('ai-empty')!.classList.remove('hidden');
            }
        }
    } catch (error) {
        console.error('Error loading AI analyses:', error);
        document.getElementById('ai-loading')!.classList.add('hidden');
        document.getElementById('ai-content')!.classList.add('hidden');
        document.getElementById('ai-empty')!.classList.remove('hidden');
    }
}

// Load AI analysis details
async function loadAIDetails(analysisId: number, sessionId: number): Promise<void> {
    const detailsDiv = document.getElementById(`ai-details-${analysisId}`)!;
    if (!detailsDiv.classList.contains('hidden')) {
        detailsDiv.classList.add('hidden');
        return;
    }

    try {
        const response = await fetch(`/api/social_sentiment/ai_details/${analysisId}`);
        if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);

        const result = await response.json();
        if (result.success && result.data) {
            const data = result.data;
            const analysis = data.analysis;
            const extractedTickers = data.extracted_tickers || [];
            const posts = data.posts || [];

            detailsDiv.innerHTML = `
                <div class="bg-white dark:bg-gray-800 p-4 rounded border border-gray-300 dark:border-gray-600">
                    <h4 class="font-semibold mb-2 text-gray-900 dark:text-gray-100">Analysis Summary</h4>
                    <p class="text-sm mb-4 text-gray-700 dark:text-gray-300">${analysis.summary || 'No summary available'}</p>
                    
                    <h4 class="font-semibold mb-2 text-gray-900 dark:text-gray-100">Key Themes</h4>
                    <ul class="list-disc list-inside text-sm mb-4 text-gray-700 dark:text-gray-300">
                        ${analysis.key_themes && analysis.key_themes.length > 0
                    ? analysis.key_themes.map((theme: string) => `<li>${theme}</li>`).join('')
                    : '<li>No themes identified</li>'}
                    </ul>
                    
                    <h4 class="font-semibold mb-2 text-gray-900 dark:text-gray-100">Detailed Reasoning</h4>
                    <p class="text-sm mb-4 text-gray-700 dark:text-gray-300">${analysis.reasoning || 'No reasoning provided'}</p>
                    
                    ${extractedTickers.length > 0 ? `
                        <h4 class="font-semibold mb-2 text-gray-900 dark:text-gray-100">Extracted Tickers</h4>
                        <div class="text-sm mb-4 text-gray-700 dark:text-gray-300">
                            ${extractedTickers.map((t: any) => `
                                <div class="mb-1">
                                    <strong>${t.ticker}</strong> (${(t.confidence * 100).toFixed(1)}%) - ${t.company_name || 'Unknown'}
                                    ${t.is_primary ? ' <span class="text-green-600 dark:text-green-400">Primary</span>' : ''}
                                </div>
                            `).join('')}
                        </div>
                    ` : ''}
                    
                    ${posts.length > 0 ? `
                        <h4 class="font-semibold mb-2 text-gray-900 dark:text-gray-100">Sample Posts</h4>
                        ${posts.map((post: any) => `
                            <div class="mb-3 p-2 bg-gray-50 dark:bg-gray-700 rounded border border-gray-200 dark:border-gray-600">
                                <div class="flex justify-between mb-1">
                                    <span class="font-semibold text-sm text-gray-900 dark:text-gray-100">${post.author || 'Unknown'}</span>
                                    <span class="text-xs text-gray-600 dark:text-gray-400">${post.posted_at}</span>
                                </div>
                                <p class="text-sm text-gray-700 dark:text-gray-300">${post.content ? (post.content.length > 300 ? post.content.substring(0, 300) + '...' : post.content) : ''}</p>
                                <div class="flex justify-between text-xs text-gray-600 dark:text-gray-400 mt-1">
                                    <span>👍 ${post.engagement_score || 0} engagement</span>
                                    ${post.url ? `<a href="${post.url}" target="_blank" class="text-blue-600 dark:text-blue-400 hover:underline">View Original</a>` : ''}
                                </div>
                            </div>
                        `).join('')}
                    ` : ''}
                </div>
            `;

            detailsDiv.classList.remove('hidden');
        }
    } catch (error) {
        console.error('Error loading AI details:', error);
        detailsDiv.innerHTML = '<p class="text-sm text-red-600 dark:text-red-400">Error loading details.</p>';
        detailsDiv.classList.remove('hidden');
    }
}

// Load sentiment data
export async function loadSentimentData(refreshKey: number, showOnlyWatchlist: boolean = true): Promise<void> {
    try {
        const response = await fetch(
            `/api/social_sentiment/latest_sentiment?refresh_key=${refreshKey}&show_only_watchlist=${showOnlyWatchlist}`
        );
        if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);

        const result = await response.json();
        if (result.success && result.data) {
            const data = result.data as SentimentRow[];

            // Calculate summary statistics
            const uniqueTickers = new Set(data.map(row => row.Ticker));
            const sentimentColumns = ['💬 Stocktwits Sentiment', '👽 Reddit Sentiment'];
            let euphoricCount = 0;
            let fearfulCount = 0;

            data.forEach(row => {
                sentimentColumns.forEach(col => {
                    const value = row[col as keyof SentimentRow] as string;
                    if (value && value.includes('EUPHORIC')) euphoricCount++;
                    if (value && value.includes('FEARFUL')) fearfulCount++;
                });
            });

            document.getElementById('stats-unique-tickers')!.textContent = uniqueTickers.size.toString();
            document.getElementById('stats-total-metrics')!.textContent = data.length.toString();
            document.getElementById('stats-euphoric')!.textContent = euphoricCount.toString();
            document.getElementById('stats-fearful')!.textContent = fearfulCount.toString();

            if (data.length > 0) {
                document.getElementById('sentiment-loading')!.classList.add('hidden');
                document.getElementById('sentiment-empty')!.classList.add('hidden');
                document.getElementById('sentiment-content')!.classList.remove('hidden');

                // Destroy existing grid if it exists
                if (sentimentGridApi) {
                    sentimentGridApi.setGridOption('rowData', []);
                }

                initializeSentimentGrid(data);
            } else {
                document.getElementById('sentiment-loading')!.classList.add('hidden');
                document.getElementById('sentiment-content')!.classList.add('hidden');
                document.getElementById('sentiment-empty')!.classList.remove('hidden');
            }
        }
    } catch (error) {
        console.error('Error loading sentiment data:', error);
        document.getElementById('sentiment-loading')!.classList.add('hidden');
        document.getElementById('sentiment-content')!.classList.add('hidden');
        document.getElementById('sentiment-empty')!.classList.remove('hidden');
    }
}

// Initialize page
export function initializeSocialSentimentPage(refreshKey: number): void {
    loadWatchlistData(refreshKey);
    loadAlertsData(refreshKey);
    loadAIAnalysesData(refreshKey);
    loadSentimentData(refreshKey, true);
}

// Make functions available globally
(window as any).loadAlertPosts = loadAlertPosts;
(window as any).loadAIDetails = loadAIDetails;
(window as any).loadSentimentData = loadSentimentData;
(window as any).initializeSocialSentimentPage = initializeSocialSentimentPage;
(window as any).refreshData = function () {
    const currentUrl = new URL(window.location.href);
    const currentRefreshKey = parseInt(currentUrl.searchParams.get('refresh_key') || '0');
    currentUrl.searchParams.set('refresh_key', (currentRefreshKey + 1).toString());
    window.location.href = currentUrl.toString();
};

// Auto-initialize if config is present
document.addEventListener('DOMContentLoaded', () => {
    const configElement = document.getElementById('social-sentiment-config');
    if (configElement) {
        try {
            const config = JSON.parse(configElement.textContent || '{}');
            const refreshKey = config.refreshKey || 0;
            initializeSocialSentimentPage(refreshKey);

            // Handle watchlist filter checkbox if it exists
            const watchlistFilter = document.getElementById('show-only-watchlist') as HTMLInputElement | null;
            if (watchlistFilter) {
                watchlistFilter.addEventListener('change', function () {
                    loadSentimentData(refreshKey, this.checked);
                });
            }
        } catch (err) {
            console.error('[SocialSentiment] Failed to auto-init:', err);
        }
    }
});
