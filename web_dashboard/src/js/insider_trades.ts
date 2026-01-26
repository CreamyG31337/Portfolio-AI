/**
 * Insider Trades TypeScript
 * Handles AgGrid initialization, stats, and charts
 */

export {};

interface AgGridParams {
    value: string | number | null;
    data?: InsiderTrade;
}

interface AgGridApi {
    sizeColumnsToFit(): void;
    addEventListener(event: string, callback: () => void): void;
    setGridOption(key: string, value: any): void;
    exportDataAsCsv?(params?: { fileName?: string }): void;
    showLoadingOverlay(): void;
    hideOverlay(): void;
}

interface AgGridColumnApi {
    getAllDisplayedColumns(): any[];
    autoSizeColumns(colIds: string[], skipHeader?: boolean): void;
}

interface AgGridOptions {
    columnDefs: AgGridColumnDef[];
    rowData: InsiderTrade[];
    defaultColDef?: Partial<AgGridColumnDef>;
    rowClassRules?: Record<string, (params: AgGridParams) => boolean>;
    domLayout?: string;
    pagination?: boolean;
    paginationPageSize?: number;
    paginationPageSizeSelector?: number[];
    animateRows?: boolean;
    overlayLoadingTemplate?: string;
}

interface AgGridColumnDef {
    field?: string;
    headerName?: string;
    width?: number;
    minWidth?: number;
    flex?: number;
    cellRenderer?: any;
    sortable?: boolean;
    filter?: boolean;
    resizable?: boolean;
    valueFormatter?: (params: AgGridParams) => string;
    tooltipValueGetter?: (params: AgGridParams) => string;
    cellStyle?: Record<string, string>;
}

interface InsiderTrade {
    ticker?: string;
    company_name?: string | null;
    insider_name?: string | null;
    insider_title?: string | null;
    transaction_date?: string | null;
    disclosure_date?: string | null;
    type?: string | null;
    shares?: number | null;
    price_per_share?: number | null;
    value?: number | null;
    _logo_url?: string | null;
}

interface InsiderTradeApiResponse {
    trades: InsiderTrade[];
    has_more: boolean;
    total?: number;
    error?: string;
}

let gridApi: AgGridApi | null = null;
let gridColumnApi: AgGridColumnApi | null = null;
let insiderTradesConfig: Record<string, any> = {};
let latestTrades: InsiderTrade[] = [];

const failedLogoCache = new Set<string>();
const darkThemes = new Set(["dark", "midnight-tokyo", "abyss"]);

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
    return darkThemes.has(theme);
}

function applyAgGridTheme(container: HTMLElement): void {
    const theme = getCurrentTheme();
    const useDark = isDarkTheme(theme);
    container.classList.toggle("ag-theme-alpine-dark", useDark);
    container.classList.toggle("ag-theme-alpine", !useDark);
}

function getPlotlyThemeLayout(): Record<string, any> {
    const theme = getCurrentTheme();
    const utils = (window as any).chartThemeUtils;
    if (utils?.getPlotlyLayout) {
        return utils.getPlotlyLayout(theme);
    }
    return {};
}

class TickerCellRenderer {
    private eGui!: HTMLElement;

    init(params: AgGridParams): void {
        this.eGui = document.createElement("div");
        this.eGui.style.display = "flex";
        this.eGui.style.alignItems = "center";
        this.eGui.style.gap = "6px";

        const ticker = (params.value || "").toString();
        if (ticker && ticker !== "N/A") {
            const cleanTicker = ticker.replace(/\s+/g, "").replace(/\.(TO|V|CN|TSX|TSXV|NE|NEO)$/i, "");
            const cacheKey = cleanTicker.toUpperCase();
            const logoUrl = params.data?._logo_url;

            const img = document.createElement("img");
            img.style.width = "24px";
            img.style.height = "24px";
            img.style.objectFit = "contain";
            img.style.borderRadius = "4px";
            img.style.flexShrink = "0";

            if (failedLogoCache.has(cacheKey) || !logoUrl) {
                img.src = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='24' height='24'%3E%3C/svg%3E";
                img.alt = "";
            } else {
                img.src = logoUrl;
                img.alt = ticker;

                let fallbackAttempted = false;
                img.onerror = function () {
                    if (fallbackAttempted) {
                        failedLogoCache.add(cacheKey);
                        img.src = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='24' height='24'%3E%3C/svg%3E";
                        img.alt = "";
                        img.onerror = null;
                        return;
                    }

                    fallbackAttempted = true;
                    const yahooUrl = `https://s.yimg.com/cv/apiv2/default/images/logos/${cleanTicker}.png`;
                    if (img.src !== yahooUrl) {
                        img.src = yahooUrl;
                    } else {
                        failedLogoCache.add(cacheKey);
                        img.src = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='24' height='24'%3E%3C/svg%3E";
                        img.alt = "";
                        img.onerror = null;
                    }
                };
            }

            this.eGui.appendChild(img);

            const tickerSpan = document.createElement("span");
            tickerSpan.innerText = ticker;
            tickerSpan.style.color = "var(--accent-color)";
            tickerSpan.style.fontWeight = "bold";
            tickerSpan.style.textDecoration = "underline";
            tickerSpan.style.cursor = "pointer";
            tickerSpan.addEventListener("click", function (e: Event) {
                e.stopPropagation();
                window.location.href = `/ticker?ticker=${encodeURIComponent(ticker)}`;
            });
            this.eGui.appendChild(tickerSpan);
        } else {
            this.eGui.innerText = "N/A";
        }
    }

    getGui(): HTMLElement {
        return this.eGui;
    }
}

class TypeCellRenderer {
    private eGui!: HTMLElement;

    init(params: AgGridParams): void {
        this.eGui = document.createElement("span");
        const value = (params.value || "").toString();
        const lower = value.toLowerCase();

        if (lower === "purchase") {
            this.eGui.innerText = "🟢 Purchase";
            this.eGui.style.color = "var(--theme-success-text)";
            this.eGui.style.fontWeight = "600";
        } else if (lower === "sale") {
            this.eGui.innerText = "🔴 Sale";
            this.eGui.style.color = "var(--theme-error-text)";
            this.eGui.style.fontWeight = "600";
        } else {
            this.eGui.innerText = value || "N/A";
        }
    }

    getGui(): HTMLElement {
        return this.eGui;
    }
}

function formatCurrency(value: number | null, compact: boolean = false): string {
    if (value === null || value === undefined || Number.isNaN(value)) {
        return "N/A";
    }

    if (compact) {
        return new Intl.NumberFormat("en-US", {
            style: "currency",
            currency: "USD",
            notation: "compact",
            maximumFractionDigits: 1
        }).format(value);
    }

    return new Intl.NumberFormat("en-US", {
        style: "currency",
        currency: "USD",
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
    }).format(value);
}

function formatNumber(value: number | null): string {
    if (value === null || value === undefined || Number.isNaN(value)) {
        return "N/A";
    }

    return new Intl.NumberFormat("en-US", {
        maximumFractionDigits: 0
    }).format(value);
}

function formatDate(value: string | null): string {
    if (!value) return "N/A";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    return date.toLocaleDateString("en-US", {
        month: "short",
        day: "2-digit",
        year: "numeric"
    });
}

function formatDateTime(value: string | null): string {
    if (!value) return "N/A";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    return date.toLocaleString("en-US", {
        month: "short",
        day: "2-digit",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit"
    });
}

function getTradeValue(trade: InsiderTrade): number {
    if (trade.value !== null && trade.value !== undefined && !Number.isNaN(trade.value)) {
        return trade.value;
    }
    if (trade.shares !== null && trade.shares !== undefined
        && trade.price_per_share !== null && trade.price_per_share !== undefined) {
        return trade.shares * trade.price_per_share;
    }
    return 0;
}

function getTradeTicker(trade: InsiderTrade): string {
    return trade.ticker || "N/A";
}

function initializeInsiderTradesGrid(trades: InsiderTrade[]): void {
    const gridDiv = document.getElementById("insider-trades-grid");
    if (!gridDiv) {
        console.error("Insider trades grid element not found");
        return;
    }

    applyAgGridTheme(gridDiv);

    if (gridDiv.getAttribute("data-initialized") === "true") {
        if (gridApi) {
            gridApi.setGridOption("rowData", trades);
        }
        return;
    }

    const columnDefs: AgGridColumnDef[] = [
        {
            field: "transaction_date",
            headerName: "Date",
            width: 130,
            valueFormatter: (params) => formatDate(params.value as string | null)
        },
        {
            field: "ticker",
            headerName: "Ticker",
            width: 140,
            cellRenderer: TickerCellRenderer
        },
        {
            field: "insider_name",
            headerName: "Insider Name",
            minWidth: 200,
            flex: 1
        },
        {
            field: "insider_title",
            headerName: "Title",
            minWidth: 160,
            flex: 1,
            valueFormatter: (params) => (params.value ? params.value.toString() : "-")
        },
        {
            field: "type",
            headerName: "Type",
            width: 140,
            cellRenderer: TypeCellRenderer
        },
        {
            field: "shares",
            headerName: "Shares",
            width: 130,
            valueFormatter: (params) => formatNumber(params.value as number | null)
        },
        {
            field: "price_per_share",
            headerName: "Price/Share",
            width: 140,
            valueFormatter: (params) => formatCurrency(params.value as number | null)
        },
        {
            field: "value",
            headerName: "Total Value",
            width: 150,
            valueFormatter: (params) => formatCurrency(getTradeValue(params.data || {}))
        },
        {
            field: "disclosure_date",
            headerName: "Disclosure Date",
            width: 170,
            valueFormatter: (params) => formatDateTime(params.value as string | null)
        }
    ];

    const gridOptions: AgGridOptions = {
        columnDefs,
        rowData: trades,
        defaultColDef: {
            sortable: true,
            filter: true,
            resizable: true
        },
        rowClassRules: {
            "insider-trade-purchase": (params) => params.data?.type === "Purchase",
            "insider-trade-sale": (params) => params.data?.type === "Sale",
            "insider-trade-high-value": (params) => getTradeValue(params.data || {}) >= 1_000_000
        },
        domLayout: "normal",
        pagination: true,
        paginationPageSize: 25,
        paginationPageSizeSelector: [25, 50, 100],
        animateRows: true,
        overlayLoadingTemplate: "<span class='ag-overlay-loading-center'>Loading insider trades...</span>"
    };

    const gridApiInstance = (window as any).agGrid.createGrid(gridDiv, gridOptions as any) as AgGridApi;
    gridApi = gridApiInstance;
    gridColumnApi = (gridApiInstance as any).columnApi ?? null;
    gridDiv.setAttribute("data-initialized", "true");

    if (gridApi && gridColumnApi) {
        gridApi.addEventListener("firstDataRendered", () => {
            setTimeout(() => {
                const columns = gridColumnApi?.getAllDisplayedColumns() || [];
                const columnIds = columns.map((col: any) => col.getColId()).filter(Boolean);
                if (columnIds.length > 0) {
                    gridColumnApi?.autoSizeColumns(columnIds, false);
                }
            }, 300);
        });
    }
}

function renderStats(trades: InsiderTrade[]): void {
    let purchaseVolume = 0;
    let saleVolume = 0;
    let largestTrade = 0;
    const tickerCounts = new Map<string, number>();

    for (const trade of trades) {
        const value = getTradeValue(trade);
        const type = trade.type || "";
        if (type === "Purchase") {
            purchaseVolume += value;
        } else if (type === "Sale") {
            saleVolume += value;
        }

        if (value > largestTrade) {
            largestTrade = value;
        }

        const ticker = getTradeTicker(trade);
        if (ticker !== "N/A") {
            tickerCounts.set(ticker, (tickerCounts.get(ticker) || 0) + 1);
        }
    }

    let mostActiveTicker = "-";
    let maxCount = 0;
    for (const [ticker, count] of tickerCounts.entries()) {
        if (count > maxCount) {
            maxCount = count;
            mostActiveTicker = `${ticker} (${count})`;
        }
    }

    const setText = (id: string, value: string) => {
        const el = document.getElementById(id);
        if (el) {
            el.textContent = value;
        }
    };

    setText("stat-total-trades", trades.length.toString());
    setText("stat-purchase-volume", formatCurrency(purchaseVolume, true));
    setText("stat-sale-volume", formatCurrency(saleVolume, true));
    setText("stat-most-active", mostActiveTicker);
    setText("stat-largest-trade", formatCurrency(largestTrade, true));
}

function renderCharts(trades: InsiderTrade[]): void {
    renderVolumeChart(trades);
    renderTopInsidersChart(trades);
    renderTypeDistributionChart(trades);
}

function renderVolumeChart(trades: InsiderTrade[]): void {
    const chartEl = document.getElementById("insider-volume-chart");
    const plotly = (window as any).Plotly;
    if (!chartEl || !plotly) return;

    const dailyMap = new Map<string, { purchase: number; sale: number }>();
    for (const trade of trades) {
        if (!trade.transaction_date) continue;
        const dateKey = trade.transaction_date.split("T")[0];
        const value = getTradeValue(trade);
        const type = trade.type || "";
        const current = dailyMap.get(dateKey) || { purchase: 0, sale: 0 };
        if (type === "Purchase") current.purchase += value;
        if (type === "Sale") current.sale += value;
        dailyMap.set(dateKey, current);
    }

    const dates = Array.from(dailyMap.keys()).sort();
    const purchases = dates.map((date) => dailyMap.get(date)?.purchase || 0);
    const sales = dates.map((date) => dailyMap.get(date)?.sale || 0);

    if (dates.length === 0) {
        renderEmptyChart(chartEl, "No data to chart");
        return;
    }

    const data = [
        {
            x: dates,
            y: purchases,
            type: "bar",
            name: "Purchases",
            marker: { color: "#00C853" }
        },
        {
            x: dates,
            y: sales,
            type: "bar",
            name: "Sales",
            marker: { color: "#FF5252" }
        }
    ];

    const themeLayout = getPlotlyThemeLayout();
    const layout = {
        ...themeLayout,
        barmode: "group",
        margin: { l: 40, r: 10, t: 10, b: 40 },
        xaxis: { ...(themeLayout.xaxis || {}), tickangle: -30 },
        yaxis: { ...(themeLayout.yaxis || {}), tickprefix: "$" },
        legend: { orientation: "h", y: -0.2 }
    };

    plotly.newPlot(chartEl, data, layout, { displayModeBar: false });
}

function renderTopInsidersChart(trades: InsiderTrade[]): void {
    const chartEl = document.getElementById("insider-top-insiders-chart");
    const plotly = (window as any).Plotly;
    if (!chartEl || !plotly) return;

    const counts = new Map<string, number>();
    for (const trade of trades) {
        const name = trade.insider_name || "Unknown";
        counts.set(name, (counts.get(name) || 0) + 1);
    }

    const top = Array.from(counts.entries())
        .sort((a, b) => b[1] - a[1])
        .slice(0, 10)
        .reverse();

    if (top.length === 0) {
        renderEmptyChart(chartEl, "No data to chart");
        return;
    }

    const labels = top.map(([name]) => name);
    const values = top.map(([, count]) => count);

    const data = [
        {
            x: values,
            y: labels,
            type: "bar",
            orientation: "h",
            marker: { color: "#64B5F6" }
        }
    ];

    const themeLayout = getPlotlyThemeLayout();
    const layout = {
        ...themeLayout,
        margin: { l: 140, r: 10, t: 10, b: 30 },
        xaxis: { ...(themeLayout.xaxis || {}), dtick: 1 },
        yaxis: { ...(themeLayout.yaxis || {}) }
    };

    plotly.newPlot(chartEl, data, layout, { displayModeBar: false });
}

function renderTypeDistributionChart(trades: InsiderTrade[]): void {
    const chartEl = document.getElementById("insider-type-distribution-chart");
    const plotly = (window as any).Plotly;
    if (!chartEl || !plotly) return;

    let purchaseCount = 0;
    let saleCount = 0;
    for (const trade of trades) {
        if (trade.type === "Purchase") purchaseCount += 1;
        if (trade.type === "Sale") saleCount += 1;
    }

    if (purchaseCount + saleCount === 0) {
        renderEmptyChart(chartEl, "No data to chart");
        return;
    }

    const data = [
        {
            labels: ["Purchase", "Sale"],
            values: [purchaseCount, saleCount],
            type: "pie",
            marker: { colors: ["#00C853", "#FF5252"] },
            textinfo: "percent"
        }
    ];

    const themeLayout = getPlotlyThemeLayout();
    const layout = {
        ...themeLayout,
        margin: { l: 10, r: 10, t: 10, b: 10 },
        showlegend: true
    };

    plotly.newPlot(chartEl, data, layout, { displayModeBar: false });
}

function renderEmptyChart(target: HTMLElement, message: string): void {
    const plotly = (window as any).Plotly;
    if (!plotly) return;
    const themeLayout = getPlotlyThemeLayout();
    const data: any[] = [];
    const layout = {
        ...themeLayout,
        annotations: [{
            text: message,
            showarrow: false,
            font: { size: 12 }
        }],
        xaxis: { ...(themeLayout.xaxis || {}), visible: false },
        yaxis: { ...(themeLayout.yaxis || {}), visible: false },
        margin: { l: 10, r: 10, t: 10, b: 10 }
    };
    plotly.newPlot(target, data, layout, { displayModeBar: false });
}

function renderNotableTrades(
    trades: InsiderTrade[],
    containerId: string,
    type: string,
    emptyMessage: string
): void {
    const container = document.getElementById(containerId);
    if (!container) return;

    container.innerHTML = "";

    const filtered = trades
        .filter((trade) => trade.type === type)
        .sort((a, b) => getTradeValue(b) - getTradeValue(a))
        .slice(0, 5);

    if (filtered.length === 0) {
        const empty = document.createElement("div");
        empty.className = "text-sm text-text-secondary";
        empty.textContent = emptyMessage;
        container.appendChild(empty);
        return;
    }

    for (const trade of filtered) {
        const card = document.createElement("div");
        card.className = "bg-dashboard-surface-alt border border-border rounded-lg p-3";

        const title = document.createElement("div");
        title.className = "text-sm font-semibold text-text-primary";
        title.textContent = `${getTradeTicker(trade)} • ${trade.insider_name || "Unknown"}`;

        const details = document.createElement("div");
        details.className = "text-xs text-text-secondary mt-1";
        const sharesText = trade.shares !== null && trade.shares !== undefined
            ? `${formatNumber(trade.shares)} shares`
            : "Shares N/A";
        const valueText = formatCurrency(getTradeValue(trade));
        const dateText = formatDate(trade.transaction_date || null);
        details.textContent = `${sharesText} • ${valueText} • ${dateText}`;

        card.appendChild(title);
        card.appendChild(details);
        container.appendChild(card);
    }
}

function getSelectedFund(): string | null {
    const selector = document.getElementById("global-fund-select") as HTMLSelectElement | null;
    const urlFund = new URLSearchParams(window.location.search).get("fund");
    const selected = (selector?.value || urlFund || "").trim();
    return selected || null;
}

function updateFundFilterState(): void {
    const checkbox = document.getElementById("fund-only-filter") as HTMLInputElement | null;
    const hint = document.getElementById("fund-only-filter-hint");
    const label = document.getElementById("fund-only-filter-label");
    const hiddenInput = document.getElementById("fund-filter") as HTMLInputElement | null;

    const fund = getSelectedFund();
    const enabled = Boolean(fund && fund.toLowerCase() !== "all");

    if (hiddenInput) {
        hiddenInput.value = fund || "";
    }

    if (!checkbox || !hint || !label) {
        return;
    }

    checkbox.disabled = !enabled;
    if (!enabled) {
        checkbox.checked = false;
        hint.classList.remove("hidden");
        label.classList.add("opacity-60", "cursor-not-allowed");
    } else {
        hint.classList.add("hidden");
        label.classList.remove("opacity-60", "cursor-not-allowed");
    }
}

function filterRecentTrades(trades: InsiderTrade[]): InsiderTrade[] {
    const cutoff = new Date();
    cutoff.setDate(cutoff.getDate() - 7);
    cutoff.setHours(0, 0, 0, 0);

    return trades.filter((trade) => {
        if (!trade.transaction_date) return false;
        const parsed = new Date(trade.transaction_date);
        if (Number.isNaN(parsed.getTime())) return false;
        return parsed >= cutoff;
    });
}

async function renderNotableSection(): Promise<void> {
    const notableTrades = filterRecentTrades(latestTrades);
    renderNotableTrades(
        notableTrades,
        "notable-purchases",
        "Purchase",
        "No notable purchases in the last 7 days."
    );
    renderNotableTrades(
        notableTrades,
        "notable-sales",
        "Sale",
        "No notable sales in the last 7 days."
    );
}

function buildSearchParams(): URLSearchParams {
    const searchParams = new URLSearchParams(window.location.search);

    // Override with current fund selection from DOM if available
    const fundInput = document.getElementById("fund-filter") as HTMLInputElement | null;
    if (fundInput) {
        if (fundInput.value) {
            searchParams.set("fund", fundInput.value);
        } else {
            searchParams.delete("fund");
        }
    }

    // Override with current fund_only selection from DOM if available
    const fundOnlyCheckbox = document.getElementById("fund-only-filter") as HTMLInputElement | null;
    if (fundOnlyCheckbox) {
        if (fundOnlyCheckbox.checked) {
            searchParams.set("fund_only", "true");
        } else {
            searchParams.delete("fund_only");
        }
    }

    if (!searchParams.has("use_date_filter") && insiderTradesConfig.defaultUseDateFilter) {
        searchParams.set("use_date_filter", "true");
        if (insiderTradesConfig.defaultStartDate && !searchParams.has("start_date")) {
            searchParams.set("start_date", insiderTradesConfig.defaultStartDate);
        }
        if (insiderTradesConfig.defaultEndDate && !searchParams.has("end_date")) {
            searchParams.set("end_date", insiderTradesConfig.defaultEndDate);
        }
    }

    return searchParams;
}

async function fetchTradeData(): Promise<void> {
    const searchParams = buildSearchParams();
    const emptyState = document.getElementById("insider-empty");

    try {
        const response = await fetch(`/api/insider_trades/data?${searchParams.toString()}`);
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        const data: InsiderTradeApiResponse = await response.json();
        if (data.error) {
            throw new Error(data.error);
        }

        const trades = data.trades || [];
        latestTrades = trades;

        initializeInsiderTradesGrid(trades);
        renderStats(trades);
        renderCharts(trades);
        await renderNotableSection();

        if (emptyState) {
            if (trades.length === 0) {
                emptyState.classList.remove("hidden");
            } else {
                emptyState.classList.add("hidden");
            }
        }
    } catch (error) {
        console.error("Failed to fetch insider trades data:", error);
        if (gridApi) {
            gridApi.hideOverlay();
        }
    }
}

(window as any).refreshData = function () {
    const currentUrl = new URL(window.location.href);
    const currentRefreshKey = parseInt(currentUrl.searchParams.get("refresh_key") || "0");
    currentUrl.searchParams.set("refresh_key", (currentRefreshKey + 1).toString());
    window.location.href = currentUrl.toString();
};

(window as any).downloadCsv = function () {
    if (!gridApi || !gridApi.exportDataAsCsv) {
        alert("Grid not initialized.");
        return;
    }

    gridApi.exportDataAsCsv({ fileName: "insider_trades.csv" });
};

document.addEventListener("DOMContentLoaded", () => {
    const gridDiv = document.getElementById("insider-trades-grid");
    const themeManager = (window as any).themeManager;
    if (gridDiv && themeManager?.addListener) {
        themeManager.addListener(() => {
            applyAgGridTheme(gridDiv);
        });
    }

    const useDateFilter = document.getElementById("use-date-filter") as HTMLInputElement | null;
    const dateRangeInputs = document.getElementById("date-range-inputs");
    if (useDateFilter && dateRangeInputs) {
        useDateFilter.addEventListener("change", function () {
            if (this.checked) {
                dateRangeInputs.classList.remove("hidden");
            } else {
                dateRangeInputs.classList.add("hidden");
            }
        });
    }

    const configElement = document.getElementById("insider-trades-config");
    if (configElement) {
        try {
            insiderTradesConfig = JSON.parse(configElement.textContent || "{}");
            if (insiderTradesConfig.lazyLoad) {
                fetchTradeData();
            }
        } catch (err) {
            console.error("[InsiderTrades] Failed to auto-init:", err);
        }
    }

    updateFundFilterState();

    window.addEventListener("fundChanged", () => {
        const fundOnly = document.getElementById("fund-only-filter") as HTMLInputElement | null;
        const wasChecked = fundOnly?.checked;

        updateFundFilterState();

        if (fundOnly?.checked || wasChecked) {
            fetchTradeData();
        }
    });
});
