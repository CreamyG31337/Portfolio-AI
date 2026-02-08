interface AuditEntry {
    timestamp?: string;
    function?: string;
    model?: string;
    provider?: string;
    duration_ms?: number | string | null;
    success?: boolean | string | null;
    tickers_extracted?: string[] | string | null;
    sentiment?: string | null;
    article_title?: string | null;
    article_url?: string | null;
    output_summary?: string | null;
    error?: string | null;
    [key: string]: unknown;
}

interface DatesResponse {
    dates: string[];
}

interface EntriesResponse {
    date: string;
    entries: AuditEntry[];
    total: number;
}

const dateSelect = document.getElementById("ai-audit-date") as HTMLSelectElement | null;
const functionSelect = document.getElementById("ai-audit-function") as HTMLSelectElement | null;
const modelSelect = document.getElementById("ai-audit-model") as HTMLSelectElement | null;
const providerSelect = document.getElementById("ai-audit-provider") as HTMLSelectElement | null;
const successSelect = document.getElementById("ai-audit-success") as HTMLSelectElement | null;
const applyButton = document.getElementById("ai-audit-apply") as HTMLButtonElement | null;
const tableBody = document.getElementById("ai-audit-table-body") as HTMLElement | null;
const emptyState = document.getElementById("ai-audit-empty-state") as HTMLElement | null;
const detailOpenButton = document.getElementById("ai-audit-detail-open") as HTMLButtonElement | null;
const detailSubtitle = document.getElementById("ai-audit-detail-subtitle") as HTMLElement | null;
const detailFields = document.getElementById("ai-audit-detail-fields") as HTMLElement | null;
const detailSummary = document.getElementById("ai-audit-detail-summary") as HTMLElement | null;
const detailErrorWrap = document.getElementById("ai-audit-detail-error-wrap") as HTMLElement | null;
const detailError = document.getElementById("ai-audit-detail-error") as HTMLElement | null;

const statTotalCalls = document.getElementById("stat-total-calls");
const statSuccessRate = document.getElementById("stat-success-rate");
const statAvgDuration = document.getElementById("stat-avg-duration");
const statModelsUsed = document.getElementById("stat-models-used");

let currentEntries: AuditEntry[] = [];

function escapeHtml(value: unknown): string {
    if (value === null || value === undefined) return "";
    const div = document.createElement("div");
    div.textContent = String(value);
    return div.innerHTML;
}

function asText(value: unknown): string {
    if (value === null || value === undefined) return "";
    if (typeof value === "string") return value;
    if (Array.isArray(value)) return value.join(", ");
    if (typeof value === "object") return JSON.stringify(value);
    return String(value);
}

function parseDurationMs(value: unknown): number {
    if (typeof value === "number" && Number.isFinite(value)) return value;
    if (typeof value === "string") {
        const parsed = Number(value);
        if (Number.isFinite(parsed)) return parsed;
    }
    return 0;
}

function formatDuration(value: unknown): string {
    const durationMs = parseDurationMs(value);
    if (durationMs >= 1000) {
        return `${(durationMs / 1000).toFixed(1)}s`;
    }
    return `${Math.round(durationMs)}ms`;
}

function formatTimestamp(value: unknown): string {
    if (!value || typeof value !== "string") return "-";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return escapeHtml(value);
    return date.toLocaleTimeString("en-US", { hour12: false });
}

function normalizeSuccess(value: unknown): boolean {
    if (typeof value === "boolean") return value;
    if (typeof value === "string") return value.trim().toLowerCase() === "true";
    return Boolean(value);
}

function sentimentBadge(sentiment: unknown): string {
    const value = asText(sentiment).toLowerCase();
    if (!value) {
        return '<span class="inline-flex px-2 py-1 rounded-full text-xs font-medium bg-dashboard-background text-text-secondary">N/A</span>';
    }
    if (value.includes("pos")) {
        return `<span class="inline-flex px-2 py-1 rounded-full text-xs font-medium bg-theme-success-bg text-theme-success-text">${escapeHtml(asText(sentiment))}</span>`;
    }
    if (value.includes("neg")) {
        return `<span class="inline-flex px-2 py-1 rounded-full text-xs font-medium bg-theme-error-bg text-theme-error-text">${escapeHtml(asText(sentiment))}</span>`;
    }
    return `<span class="inline-flex px-2 py-1 rounded-full text-xs font-medium bg-theme-info-bg text-theme-info-text">${escapeHtml(asText(sentiment))}</span>`;
}

function providerBadge(provider: unknown): string {
    const value = asText(provider).toLowerCase() || "unknown";
    const styles: Record<string, string> = {
        ollama: "bg-theme-info-bg text-theme-info-text",
        glm: "bg-theme-warning-bg text-theme-warning-text",
        webai: "bg-theme-success-bg text-theme-success-text"
    };
    const style = styles[value] || "bg-dashboard-background text-text-secondary";
    return `<span class="inline-flex px-2 py-1 rounded-full text-xs font-medium ${style}">${escapeHtml(value)}</span>`;
}

function tickersText(value: unknown): string {
    if (Array.isArray(value)) {
        return value.length ? value.join(", ") : "-";
    }
    if (typeof value === "string") {
        return value || "-";
    }
    return "-";
}

function populateSelectOptions(selectEl: HTMLSelectElement, values: string[], preserveValue: string): void {
    const uniqueSorted = [...new Set(values.filter(Boolean))].sort((a, b) => a.localeCompare(b));
    const options = ['<option value="">All</option>'];
    for (const value of uniqueSorted) {
        options.push(`<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`);
    }
    selectEl.innerHTML = options.join("");
    if (preserveValue && uniqueSorted.includes(preserveValue)) {
        selectEl.value = preserveValue;
    }
}

function updateDynamicFilters(entries: AuditEntry[]): void {
    if (!functionSelect || !modelSelect) return;
    const selectedFunction = functionSelect.value;
    const selectedModel = modelSelect.value;
    const functions = entries.map((entry) => asText(entry.function).trim()).filter(Boolean);
    const models = entries.map((entry) => asText(entry.model).trim()).filter(Boolean);
    populateSelectOptions(functionSelect, functions, selectedFunction);
    populateSelectOptions(modelSelect, models, selectedModel);
}

function updateStats(entries: AuditEntry[]): void {
    if (!statTotalCalls || !statSuccessRate || !statAvgDuration || !statModelsUsed) return;
    const total = entries.length;
    const successes = entries.filter((entry) => normalizeSuccess(entry.success)).length;
    const rate = total > 0 ? (successes / total) * 100 : 0;
    const durationValues = entries.map((entry) => parseDurationMs(entry.duration_ms)).filter((n) => n > 0);
    const avgDuration = durationValues.length
        ? durationValues.reduce((a, b) => a + b, 0) / durationValues.length
        : 0;
    const uniqueModels = new Set(entries.map((entry) => asText(entry.model).trim()).filter(Boolean)).size;

    statTotalCalls.textContent = String(total);
    statSuccessRate.textContent = `${rate.toFixed(1)}%`;
    statSuccessRate.className = "mt-2 text-2xl font-semibold " + (
        rate >= 80 ? "text-theme-success-text" : rate >= 50 ? "text-theme-warning-text" : "text-theme-error-text"
    );
    statAvgDuration.textContent = formatDuration(avgDuration);
    statModelsUsed.textContent = String(uniqueModels);
}

function renderRows(entries: AuditEntry[]): void {
    if (!tableBody || !emptyState) return;

    if (!entries.length) {
        tableBody.innerHTML = "";
        emptyState.classList.remove("hidden");
        return;
    }

    emptyState.classList.add("hidden");
    tableBody.innerHTML = entries.map((entry, index) => {
        const isSuccess = normalizeSuccess(entry.success);
        const successHtml = isSuccess
            ? '<span class="inline-flex items-center text-theme-success-text"><i class="fas fa-check-circle mr-1"></i>Yes</span>'
            : '<span class="inline-flex items-center text-theme-error-text"><i class="fas fa-times-circle mr-1"></i>No</span>';

        const articleTitle = asText(entry.article_title) || "-";
        const articleUrl = asText(entry.article_url);
        const articleCell = articleUrl
            ? `<a class="text-accent hover:underline" href="${escapeHtml(articleUrl)}" target="_blank" rel="noopener" onclick="event.stopPropagation()">${escapeHtml(articleTitle)}</a>`
            : escapeHtml(articleTitle);

        return `
            <tr data-entry-index="${index}" class="hover:bg-dashboard-background cursor-pointer">
                <td class="px-4 py-3 text-sm text-text-primary">${formatTimestamp(entry.timestamp)}</td>
                <td class="px-4 py-3 text-sm text-text-primary">${escapeHtml(asText(entry.function) || "-")}</td>
                <td class="px-4 py-3 text-sm text-text-primary">${escapeHtml(asText(entry.model) || "-")}</td>
                <td class="px-4 py-3 text-sm">${providerBadge(entry.provider)}</td>
                <td class="px-4 py-3 text-sm text-text-primary">${formatDuration(entry.duration_ms)}</td>
                <td class="px-4 py-3 text-sm">${successHtml}</td>
                <td class="px-4 py-3 text-sm text-text-primary max-w-48 truncate" title="${escapeHtml(tickersText(entry.tickers_extracted))}">${escapeHtml(tickersText(entry.tickers_extracted))}</td>
                <td class="px-4 py-3 text-sm">${sentimentBadge(entry.sentiment)}</td>
                <td class="px-4 py-3 text-sm text-text-primary max-w-64 truncate" title="${escapeHtml(articleTitle)}">${articleCell}</td>
            </tr>
        `;
    }).join("");

    tableBody.querySelectorAll("tr[data-entry-index]").forEach((row) => {
        row.addEventListener("click", () => {
            const indexValue = row.getAttribute("data-entry-index");
            if (!indexValue) return;
            const index = Number(indexValue);
            if (Number.isNaN(index) || !currentEntries[index]) return;
            openDetailModal(currentEntries[index]);
        });
    });
}

function openDetailModal(entry: AuditEntry): void {
    if (!detailFields || !detailOpenButton || !detailSummary || !detailErrorWrap || !detailError || !detailSubtitle) {
        return;
    }

    const subtitle = `${formatTimestamp(entry.timestamp)} • ${asText(entry.function) || "Unknown Function"}`;
    detailSubtitle.textContent = subtitle;

    const preferredKeys = [
        "timestamp", "function", "model", "provider", "duration_ms", "success",
        "tickers_extracted", "sentiment", "caller", "input_chars", "input_hash",
        "article_title", "article_url"
    ];
    const seen = new Set<string>(preferredKeys);
    const allKeys = [...preferredKeys, ...Object.keys(entry).filter((key) => !seen.has(key))];

    detailFields.innerHTML = allKeys
        .filter((key) => key !== "output_summary" && key !== "error")
        .map((key) => {
            let value = entry[key];
            if (key === "article_url" && value) {
                return `
                    <div class="border border-border rounded-lg p-3 bg-dashboard-background">
                        <dt class="text-xs uppercase tracking-wide text-text-secondary">${escapeHtml(key)}</dt>
                        <dd class="mt-1 text-sm text-accent break-all">
                            <a href="${escapeHtml(asText(value))}" target="_blank" rel="noopener" class="hover:underline">${escapeHtml(asText(value))}</a>
                        </dd>
                    </div>
                `;
            }
            if (typeof value === "boolean") value = value ? "true" : "false";
            const valueText = asText(value) || "-";
            return `
                <div class="border border-border rounded-lg p-3 bg-dashboard-background">
                    <dt class="text-xs uppercase tracking-wide text-text-secondary">${escapeHtml(key)}</dt>
                    <dd class="mt-1 text-sm text-text-primary break-words">${escapeHtml(valueText)}</dd>
                </div>
            `;
        })
        .join("");

    detailSummary.textContent = asText(entry.output_summary) || "(No output summary)";

    const errorText = asText(entry.error).trim();
    if (errorText) {
        detailErrorWrap.classList.remove("hidden");
        detailError.textContent = errorText;
    } else {
        detailErrorWrap.classList.add("hidden");
        detailError.textContent = "";
    }

    detailOpenButton.click();
}

function buildEntriesUrl(): string | null {
    if (!dateSelect || !dateSelect.value) {
        return null;
    }
    const params = new URLSearchParams();
    params.set("date", dateSelect.value);
    if (functionSelect?.value) params.set("function", functionSelect.value);
    if (modelSelect?.value) params.set("model", modelSelect.value);
    if (providerSelect?.value) params.set("provider", providerSelect.value);
    if (successSelect?.value) params.set("success", successSelect.value);
    return `/api/admin/ai-audit/entries?${params.toString()}`;
}

async function loadEntries(): Promise<void> {
    if (!tableBody) return;
    const url = buildEntriesUrl();
    if (!url) {
        tableBody.innerHTML = '<tr><td colspan="9" class="px-4 py-8 text-center text-text-secondary">Select a date to view entries.</td></tr>';
        return;
    }

    tableBody.innerHTML = '<tr><td colspan="9" class="px-4 py-8 text-center text-text-secondary">Loading audit entries...</td></tr>';

    try {
        const response = await fetch(url, { credentials: "include" });
        const payload: EntriesResponse & { error?: string } = await response.json();
        if (!response.ok) {
            throw new Error(payload.error || "Failed to load entries");
        }

        currentEntries = payload.entries || [];
        updateDynamicFilters(currentEntries);
        updateStats(currentEntries);
        renderRows(currentEntries);
    } catch (error) {
        const message = error instanceof Error ? error.message : "Unknown error";
        currentEntries = [];
        updateStats([]);
        if (tableBody) {
            tableBody.innerHTML = `<tr><td colspan="9" class="px-4 py-8 text-center text-theme-error-text">${escapeHtml(message)}</td></tr>`;
        }
        if (emptyState) emptyState.classList.add("hidden");
    }
}

async function loadDates(): Promise<void> {
    if (!dateSelect) return;
    dateSelect.innerHTML = '<option value="">Loading...</option>';
    try {
        const response = await fetch("/api/admin/ai-audit/dates", { credentials: "include" });
        const payload: DatesResponse & { error?: string } = await response.json();
        if (!response.ok) {
            throw new Error(payload.error || "Failed to load dates");
        }

        const dates = payload.dates || [];
        if (!dates.length) {
            dateSelect.innerHTML = '<option value="">No log files found</option>';
            updateStats([]);
            if (tableBody) {
                tableBody.innerHTML = '<tr><td colspan="9" class="px-4 py-8 text-center text-text-secondary">No AI audit files were found.</td></tr>';
            }
            return;
        }

        dateSelect.innerHTML = dates
            .map((date) => `<option value="${escapeHtml(date)}">${escapeHtml(date)}</option>`)
            .join("");
        dateSelect.value = dates[0];
        await loadEntries();
    } catch (error) {
        const message = error instanceof Error ? error.message : "Unknown error";
        dateSelect.innerHTML = `<option value="">${escapeHtml(message)}</option>`;
        if (tableBody) {
            tableBody.innerHTML = `<tr><td colspan="9" class="px-4 py-8 text-center text-theme-error-text">${escapeHtml(message)}</td></tr>`;
        }
    }
}

function registerEvents(): void {
    if (applyButton) {
        applyButton.addEventListener("click", () => {
            loadEntries();
        });
    }
    if (dateSelect) {
        dateSelect.addEventListener("change", () => {
            loadEntries();
        });
    }
}

document.addEventListener("DOMContentLoaded", async () => {
    registerEvents();
    await loadDates();
});

export {};
