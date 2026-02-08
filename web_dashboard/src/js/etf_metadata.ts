export { }; // Ensure file is treated as a module
import { getCsrfHeaders } from './csrf.js';

type SecurityMode = "etf" | "stock" | "portfolio";

interface SecurityMetadata {
    ticker: string;
    company_name?: string;
    description?: string;
}

interface SecurityMetadataResponse {
    success: boolean;
    securities?: SecurityMetadata[];
    error?: string;
    mode?: string;
    query?: string;
    limit?: number;
    offset?: number;
    count?: number;
    total?: number;
    has_more?: boolean;
}

const PAGE_SIZE = 20;

// DOM Elements
const loadingState = document.getElementById("loading-state");
const errorState = document.getElementById("error-state");
const errorMessage = document.getElementById("error-message");
const securityList = document.getElementById("security-list");
const searchInput = document.getElementById("search-input") as HTMLInputElement | null;
const clearButton = document.getElementById("clear-button") as HTMLButtonElement | null;
const modeHelpText = document.getElementById("mode-help-text");
const resultsCount = document.getElementById("results-count");
const paginationContainer = document.getElementById("pagination-container");
const modeToggleButtons = Array.from(document.querySelectorAll<HTMLButtonElement>("[data-mode-toggle]"));

let currentMode: SecurityMode = "etf";
let currentQuery = "";
let currentOffset = 0;
let currentTotal = 0;
let hasMore = false;
let searchTimer: ReturnType<typeof setTimeout> | null = null;
const dirtyTickers = new Set<string>();

// Load securities on page load
document.addEventListener("DOMContentLoaded", async () => {
    modeToggleButtons.forEach(button => {
        button.addEventListener("click", () => {
            const mode = (button.dataset.modeToggle || "etf") as SecurityMode;
            setMode(mode);
            currentOffset = 0; // Reset to first page on mode change
            void loadSecurities();
        });
    });

    searchInput?.addEventListener("input", () => {
        queueSearch();
    });

    clearButton?.addEventListener("click", () => {
        if (searchInput) {
            searchInput.value = "";
        }
        currentQuery = "";
        currentOffset = 0;
        void loadSecurities();
    });

    setMode("etf");
    await loadSecurities();
});

function setMode(mode: SecurityMode): void {
    currentMode = mode;
    modeToggleButtons.forEach(button => {
        const isActive = button.dataset.modeToggle === mode;
        button.classList.toggle("bg-dashboard-surface", isActive);
        button.classList.toggle("text-text-primary", isActive);
        button.classList.toggle("shadow-xs", isActive);
        button.classList.toggle("text-text-secondary", !isActive);
    });

    if (modeHelpText) {
        modeHelpText.textContent = mode === "etf"
            ? "Showing ETF securities from the holdings log. Search updates live as you type."
            : mode === "portfolio"
            ? "Showing all securities in your portfolio positions. Search updates live as you type."
            : "Showing stocks that are not in the ETF holdings log. Search updates live as you type.";
    }
}

function queueSearch(): void {
    if (searchTimer) {
        clearTimeout(searchTimer);
    }
    searchTimer = setTimeout(() => {
        currentQuery = (searchInput?.value || "").trim();
        currentOffset = 0; // Reset to first page on search
        void loadSecurities();
    }, 300);
}

async function loadSecurities(): Promise<void> {
    if (loadingState) loadingState.classList.remove("hidden");
    if (errorState) errorState.classList.add("hidden");
    if (securityList) securityList.classList.add("hidden");
    if (paginationContainer) paginationContainer.classList.add("hidden");

    try {
        const params = new URLSearchParams({
            mode: currentMode,
            limit: PAGE_SIZE.toString(),
            offset: currentOffset.toString()
        });
        if (currentQuery) {
            params.set("q", currentQuery);
        }

        const response = await fetch(`/api/admin/security-metadata?${params.toString()}`, {
            credentials: "include"
        });

        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        const result: SecurityMetadataResponse = await response.json();

        if (result.success && result.securities) {
            currentTotal = result.total || result.securities.length;
            hasMore = result.has_more || false;
            renderSecurities(result.securities, currentMode, currentQuery);
            renderPagination();
        } else {
            throw new Error(result.error || "Failed to load securities");
        }
    } catch (error) {
        console.error("Error loading securities:", error);
        if (errorState && errorMessage) {
            errorMessage.textContent = error instanceof Error ? error.message : "Failed to load securities";
            errorState.classList.remove("hidden");
        }
    } finally {
        if (loadingState) loadingState.classList.add("hidden");
    }
}

function renderPagination(): void {
    if (!paginationContainer) return;

    const currentPage = Math.floor(currentOffset / PAGE_SIZE) + 1;
    const totalPages = Math.ceil(currentTotal / PAGE_SIZE);
    const hasPrev = currentOffset > 0;
    const hasNext = hasMore || (currentOffset + PAGE_SIZE < currentTotal);

    if (totalPages <= 1) {
        paginationContainer.classList.add("hidden");
        return;
    }

    const prevDisabled = !hasPrev ? "opacity-50 cursor-not-allowed" : "hover:bg-accent/10";
    const nextDisabled = !hasNext ? "opacity-50 cursor-not-allowed" : "hover:bg-accent/10";

    paginationContainer.innerHTML = `
        <div class="flex items-center justify-between">
            <button id="prev-page" ${!hasPrev ? "disabled" : ""}
                class="inline-flex items-center justify-center text-accent bg-transparent border border-accent focus:ring-4 focus:ring-accent/30 font-medium rounded-lg text-sm px-4 py-2 transition-colors duration-200 ${prevDisabled}">
                <i class="fas fa-chevron-left mr-2"></i>Previous
            </button>
            <span class="text-sm text-text-secondary">
                Page ${currentPage} of ${totalPages} (${currentTotal} total)
            </span>
            <button id="next-page" ${!hasNext ? "disabled" : ""}
                class="inline-flex items-center justify-center text-accent bg-transparent border border-accent focus:ring-4 focus:ring-accent/30 font-medium rounded-lg text-sm px-4 py-2 transition-colors duration-200 ${nextDisabled}">
                Next<i class="fas fa-chevron-right ml-2"></i>
            </button>
        </div>
    `;

    const prevButton = document.getElementById("prev-page");
    const nextButton = document.getElementById("next-page");

    prevButton?.addEventListener("click", () => {
        if (hasPrev) {
            currentOffset = Math.max(0, currentOffset - PAGE_SIZE);
            void loadSecurities();
        }
    });

    nextButton?.addEventListener("click", () => {
        if (hasNext) {
            currentOffset += PAGE_SIZE;
            void loadSecurities();
        }
    });

    paginationContainer.classList.remove("hidden");
}

function renderSecurities(securities: SecurityMetadata[], mode: SecurityMode, query: string): void {
    if (!securityList) return;

    if (resultsCount) {
        const startNum = currentOffset + 1;
        const endNum = currentOffset + securities.length;
        const countText = currentTotal > 0
            ? `Showing ${startNum}-${endNum} of ${currentTotal}`
            : `Showing ${securities.length} result${securities.length === 1 ? "" : "s"}`;
        const hintText = query ? ` for "${query}"` : "";
        resultsCount.textContent = `${countText}${hintText}`;
    }

    if (securities.length === 0) {
        securityList.innerHTML = `
            <div class="rounded-lg border border-border bg-dashboard-surface p-6 text-sm text-text-secondary">
                No matches found. Try another search.
            </div>
        `;
        securityList.classList.remove("hidden");
        return;
    }

    const labelText = mode === "etf" ? "Fund Description"
        : mode === "portfolio" ? "Security Description"
        : "Company Description";
    const helperText = mode === "etf"
        ? "Include fund objective, strategy, themes, and sectors. Line breaks are preserved."
        : mode === "portfolio"
        ? "Include a description for this security in your portfolio. Line breaks are preserved."
        : "Include a short company overview or business focus. Line breaks are preserved.";
    const placeholderText = mode === "etf"
        ? "Fund Objective:\nIWC is an ETF that seeks...\n\nFund Description:\nFocuses on micro-cap..."
        : mode === "portfolio"
        ? "Description:\nProvide context about this security..."
        : "Company Description:\nDescribe the business, products, or strategy...";

    securityList.innerHTML = securities.map(security => {
        const ticker = escapeHtml(security.ticker);
        const companyName = escapeHtml(security.company_name || "");
        const description = escapeForTextarea(security.description || "");
        const hasDescription = Boolean(security.description && security.description.trim());

        return `
            <div class="bg-dashboard-surface rounded-lg shadow-xs p-6 border border-border">
                <div class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between mb-4">
                    <div>
                        <h3 class="text-lg font-bold text-text-primary">${ticker}</h3>
                        ${companyName ? `<p class="text-sm text-text-secondary">${companyName}</p>` : ""}
                    </div>
                    <div class="flex gap-2">
                        <button data-fetch-button="${ticker}" onclick="fetchFromYfinance('${ticker}')"
                            class="inline-flex items-center justify-center ${hasDescription ? "text-text-secondary border-border" : "text-blue-400 border-blue-400"} bg-transparent border hover:bg-blue-400/10 focus:ring-4 focus:ring-blue-400/30 font-medium rounded-lg text-sm px-4 py-2.5 transition-colors duration-200"
                            title="Fetch description from yfinance">
                            <i class="fas fa-download mr-2"></i>Fetch
                        </button>
                        <button data-save-button="${ticker}" onclick="saveSecurityMetadata('${ticker}')"
                            class="inline-flex items-center justify-center text-accent bg-transparent border border-accent hover:bg-accent/10 focus:ring-4 focus:ring-accent/30 font-medium rounded-lg text-sm px-5 py-2.5 transition-colors duration-200 ring-offset-2 ring-offset-dashboard-surface">
                            <i class="fas fa-floppy-disk mr-2"></i>Save
                        </button>
                    </div>
                </div>

                <div>
                    <label for="description-${ticker}" class="block mb-2 text-sm font-medium text-text-primary">
                        ${labelText}
                    </label>
                    <p class="text-xs text-text-secondary mb-2">
                        ${helperText}
                    </p>
                    <textarea id="description-${ticker}" data-description-input="${ticker}"
                        rows="8"
                        class="w-full px-3 py-2 bg-dashboard-background border border-border rounded-lg text-text-primary font-mono text-sm whitespace-pre-wrap"
                        placeholder="${placeholderText}">${description}</textarea>
                </div>
            </div>
        `;
    }).join("");

    wireDirtyTracking();
    securityList.classList.remove("hidden");
}

function wireDirtyTracking(): void {
    if (!securityList) return;

    const inputs = Array.from(
        securityList.querySelectorAll<HTMLTextAreaElement>("[data-description-input]")
    );
    inputs.forEach(input => {
        const ticker = input.dataset.descriptionInput;
        if (!ticker) return;
        input.addEventListener("input", () => {
            dirtyTickers.add(ticker);
            updateSaveButtonState(ticker, true);
        });
    });
}

function updateSaveButtonState(ticker: string, isDirty: boolean): void {
    const button = document.querySelector<HTMLButtonElement>(`[data-save-button="${ticker}"]`);
    if (!button) return;
    button.classList.toggle("animate-pulse", isDirty);
    button.classList.toggle("ring-4", isDirty);
    button.classList.toggle("ring-amber-400/80", isDirty);
    button.classList.toggle("bg-amber-400/15", isDirty);
    button.classList.toggle("text-amber-200", isDirty);
    button.classList.toggle("border-amber-400/70", isDirty);
}

function escapeForTextarea(text: string): string {
    return text
        .replace(/\\/g, "\\\\")
        .replace(/`/g, "\\`")
        .replace(/\${/g, "\\${");
}

async function fetchFromYfinance(ticker: string): Promise<void> {
    const fetchButton = document.querySelector<HTMLButtonElement>(`[data-fetch-button="${ticker}"]`);
    const descriptionEl = document.getElementById(`description-${ticker}`) as HTMLTextAreaElement | null;

    if (!descriptionEl) {
        showToast("Error: Could not find form field", "error");
        return;
    }

    // Show loading state on button
    if (fetchButton) {
        fetchButton.disabled = true;
        fetchButton.innerHTML = `<i class="fas fa-spinner fa-spin mr-2"></i>Fetching...`;
    }

    try {
        const response = await fetch(`/api/admin/security-metadata/${encodeURIComponent(ticker)}/fetch`, {
            method: "POST",
            headers: { ...getCsrfHeaders() },
            credentials: "include"
        });

        const result = await response.json();

        if (response.ok && result.success) {
            if (result.description) {
                descriptionEl.value = result.description;
                dirtyTickers.add(ticker);
                updateSaveButtonState(ticker, true);
                showToast(`Fetched description for ${ticker}`, "success");
            } else {
                showToast(`No description available from yfinance for ${ticker}`, "info");
            }
        } else {
            showToast(result.error || "Failed to fetch from yfinance", "error");
        }
    } catch (error) {
        console.error("Error fetching from yfinance:", error);
        showToast("Failed to fetch from yfinance", "error");
    } finally {
        // Restore button state
        if (fetchButton) {
            fetchButton.disabled = false;
            fetchButton.innerHTML = `<i class="fas fa-download mr-2"></i>Fetch`;
        }
    }
}

async function saveSecurityMetadata(ticker: string): Promise<void> {
    const descriptionEl = document.getElementById(`description-${ticker}`) as HTMLTextAreaElement | null;

    if (!descriptionEl) {
        showToast("Error: Could not find form field", "error");
        return;
    }

    const description = descriptionEl.value;

    try {
        const response = await fetch(`/api/admin/security-metadata/${encodeURIComponent(ticker)}`, {
            method: "PUT",
            headers: {
                "Content-Type": "application/json",
                ...getCsrfHeaders()
            },
            credentials: "include",
            body: JSON.stringify({
                description
            })
        });

        if (response.ok) {
            dirtyTickers.delete(ticker);
            updateSaveButtonState(ticker, false);
            showToast(`Saved metadata for ${ticker}`, "success");
        } else {
            const result = await response.json();
            showToast(result.error || "Failed to save", "error");
        }
    } catch (error) {
        console.error("Error saving metadata:", error);
        showToast("Failed to save metadata", "error");
    }
}

function escapeHtml(text: string): string {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
}

function showToast(message: string, type: "success" | "error" | "info" = "info"): void {
    const toast = document.createElement("div");
    toast.className = `fixed top-4 right-4 px-4 py-2 rounded shadow-lg z-50 ${
        type === "success" ? "bg-green-500 text-white" :
        type === "error" ? "bg-red-500 text-white" :
        "bg-blue-500 text-white"
    }`;
    toast.textContent = message;
    document.body.appendChild(toast);
    setTimeout(() => {
        toast.remove();
    }, 5000);
}

// Make functions available globally
(window as any).saveSecurityMetadata = saveSecurityMetadata;
(window as any).fetchFromYfinance = fetchFromYfinance;
