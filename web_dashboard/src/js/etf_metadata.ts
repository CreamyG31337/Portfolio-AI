export { }; // Ensure file is treated as a module

type SecurityMode = "etf" | "stock";

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
    count?: number;
}

const DEFAULT_LIMIT = 200;

// DOM Elements
const loadingState = document.getElementById("loading-state");
const errorState = document.getElementById("error-state");
const errorMessage = document.getElementById("error-message");
const securityList = document.getElementById("security-list");
const searchInput = document.getElementById("search-input") as HTMLInputElement | null;
const searchButton = document.getElementById("search-button") as HTMLButtonElement | null;
const clearButton = document.getElementById("clear-button") as HTMLButtonElement | null;
const modeHelpText = document.getElementById("mode-help-text");
const resultsCount = document.getElementById("results-count");
const modeToggleButtons = Array.from(document.querySelectorAll<HTMLButtonElement>("[data-mode-toggle]"));

let currentMode: SecurityMode = "etf";
let currentQuery = "";
let searchTimer: ReturnType<typeof setTimeout> | null = null;
const dirtyTickers = new Set<string>();

// Load securities on page load
document.addEventListener("DOMContentLoaded", async () => {
    modeToggleButtons.forEach(button => {
        button.addEventListener("click", () => {
            const mode = (button.dataset.modeToggle || "etf") as SecurityMode;
            setMode(mode);
            void loadSecurities();
        });
    });

    searchInput?.addEventListener("input", () => {
        queueSearch();
    });

    searchButton?.addEventListener("click", () => {
        currentQuery = (searchInput?.value || "").trim();
        void loadSecurities();
    });

    clearButton?.addEventListener("click", () => {
        if (searchInput) {
            searchInput.value = "";
        }
        currentQuery = "";
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
        button.classList.toggle("shadow-sm", isActive);
        button.classList.toggle("text-text-secondary", !isActive);
    });

    if (modeHelpText) {
        modeHelpText.textContent = mode === "etf"
            ? "Showing ETF securities from the holdings log. Search updates live as you type."
            : "Showing stocks that are not in the ETF holdings log. Search updates live as you type.";
    }
}

function queueSearch(): void {
    if (searchTimer) {
        clearTimeout(searchTimer);
    }
    searchTimer = setTimeout(() => {
        currentQuery = (searchInput?.value || "").trim();
        void loadSecurities();
    }, 300);
}

async function loadSecurities(): Promise<void> {
    if (loadingState) loadingState.classList.remove("hidden");
    if (errorState) errorState.classList.add("hidden");
    if (securityList) securityList.classList.add("hidden");

    try {
        const params = new URLSearchParams({
            mode: currentMode,
            limit: DEFAULT_LIMIT.toString()
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
            renderSecurities(result.securities, currentMode, currentQuery);
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

function renderSecurities(securities: SecurityMetadata[], mode: SecurityMode, query: string): void {
    if (!securityList) return;

    if (resultsCount) {
        const countText = `Showing ${securities.length} result${securities.length === 1 ? "" : "s"}`;
        const hintText = query ? ` for "${query}"` : "";
        const limitText = !query && securities.length >= DEFAULT_LIMIT
            ? ` (limit ${DEFAULT_LIMIT})`
            : "";
        resultsCount.textContent = `${countText}${hintText}${limitText}`;
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

    const labelText = mode === "etf" ? "Fund Description" : "Company Description";
    const helperText = mode === "etf"
        ? "Include fund objective, strategy, themes, and sectors. Line breaks are preserved."
        : "Include a short company overview or business focus. Line breaks are preserved.";
    const placeholderText = mode === "etf"
        ? "Fund Objective:\nIWC is an ETF that seeks...\n\nFund Description:\nFocuses on micro-cap..."
        : "Company Description:\nDescribe the business, products, or strategy...";

    securityList.innerHTML = securities.map(security => {
        const ticker = escapeHtml(security.ticker);
        const companyName = escapeHtml(security.company_name || "");
        const description = escapeForTextarea(security.description || "");

        return `
            <div class="bg-dashboard-surface rounded-lg shadow-sm p-6 border border-border">
                <div class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between mb-4">
                    <div>
                        <h3 class="text-lg font-bold text-text-primary">${ticker}</h3>
                        ${companyName ? `<p class="text-sm text-text-secondary">${companyName}</p>` : ""}
                    </div>
                    <button data-save-button="${ticker}" onclick="saveSecurityMetadata('${ticker}')"
                        class="inline-flex items-center justify-center text-accent bg-transparent border border-accent hover:bg-accent/10 focus:ring-4 focus:ring-accent/30 font-medium rounded-lg text-sm px-5 py-2.5 transition-colors duration-200">
                        <i class="fas fa-floppy-disk mr-2"></i>Save
                    </button>
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
    button.classList.toggle("ring-2", isDirty);
    button.classList.toggle("ring-accent/40", isDirty);
}

function escapeForTextarea(text: string): string {
    return text
        .replace(/\\/g, "\\\\")
        .replace(/`/g, "\\`")
        .replace(/\${/g, "\\${");
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
                "Content-Type": "application/json"
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

// Make saveSecurityMetadata available globally
(window as any).saveSecurityMetadata = saveSecurityMetadata;
