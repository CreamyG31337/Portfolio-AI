/**
 * Chimera holder glance. Source file — compiled to static/js/chimera_holders.js.
 */

import { FormatterCache } from "./formatters.js";

export interface HolderRow {
    name: string;
    net_contribution: number;
    current_value: number;
    gain_loss: number;
    gain_loss_pct: number | null;
    ownership_pct: number;
    day_change: number;
    day_change_pct: number | null;
    /** Set on the one summed row that stands in for everyone not picked. */
    others_count?: number;
}

export interface HolderGlance {
    fund: string;
    display_currency: string;
    fund_value: number;
    unit_price: number | null;
    day_change: number;
    day_change_pct: number | null;
    holders: HolderRow[];
}

type SortKey = "current_value" | "gain_loss_pct" | "net_contribution" | "name";

const SHOWN_STORAGE_KEY = "chimeraHolders.shown";

let glance: HolderGlance | null = null;
let shown = new Set<string>();

function loadShown(): Set<string> {
    try {
        const raw = window.localStorage.getItem(SHOWN_STORAGE_KEY);
        const parsed: unknown = raw ? JSON.parse(raw) : [];
        if (Array.isArray(parsed)) {
            return new Set(parsed.filter((name): name is string => typeof name === "string"));
        }
    } catch {
        // Private window or blocked storage: start with nobody picked.
    }
    return new Set();
}

function saveShown(): void {
    try {
        window.localStorage.setItem(SHOWN_STORAGE_KEY, JSON.stringify([...shown]));
    } catch {
        // The pick just won't stick across visits.
    }
}

/**
 * Picked holders keep their own rows. Everyone else is summed into one
 * nameless "Others" row. With nobody picked, every holder is shown by name.
 */
export function groupHolders(holders: HolderRow[], picked: Set<string>): { named: HolderRow[]; others: HolderRow | null } {
    if (picked.size === 0) {
        return { named: [...holders], others: null };
    }
    const named = holders.filter((holder) => picked.has(holder.name));
    const rest = holders.filter((holder) => !picked.has(holder.name));
    if (rest.length === 0) {
        return { named, others: null };
    }
    const sum = (key: "net_contribution" | "current_value" | "gain_loss" | "ownership_pct" | "day_change"): number =>
        rest.reduce((total, holder) => total + (holder[key] || 0), 0);
    const net = sum("net_contribution");
    const gain = sum("gain_loss");
    return {
        named,
        others: {
            name: rest.length === 1 ? "Other holder" : `Others (${rest.length} people)`,
            net_contribution: net,
            current_value: sum("current_value"),
            gain_loss: gain,
            gain_loss_pct: net > 0 ? (gain / net) * 100 : null,
            ownership_pct: sum("ownership_pct"),
            day_change: sum("day_change"),
            day_change_pct: rest[0].day_change_pct,
            others_count: rest.length,
        },
    };
}

export function money(value: number, currency: string): string {
    return FormatterCache.get("en-CA", {
        style: "currency",
        currency: currency || "CAD",
        currencyDisplay: "narrowSymbol",
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
    }).format(value);
}

export function signedMoney(value: number, currency: string): string {
    const formatted = money(Math.abs(value), currency);
    if (value > 0) {
        return `+${formatted}`;
    }
    if (value < 0) {
        return `-${formatted}`;
    }
    return formatted;
}

export function signedPct(value: number): string {
    const body = `${Math.abs(value).toFixed(1)}%`;
    if (value > 0) {
        return `+${body}`;
    }
    if (value < 0) {
        return `-${body}`;
    }
    return body;
}

export function formatHolderLine(holder: HolderRow, currency: string): string {
    const pct = holder.gain_loss_pct == null ? "" : `, ${signedPct(holder.gain_loss_pct)}`;
    return `${holder.name} — put in ${money(holder.net_contribution, currency)}, now worth ${money(holder.current_value, currency)} (${signedMoney(holder.gain_loss, currency)}${pct})`;
}

export function formatHolderReport(holders: HolderRow[], currency: string, fundLabel: string): string {
    const lines = holders.map((holder) => formatHolderLine(holder, currency));
    return [`${fundLabel}`, ...lines].join("\n");
}

function escapeHtml(value: string): string {
    return value
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
}

function toneClass(value: number): string {
    if (value > 0) {
        return "text-theme-success-text";
    }
    if (value < 0) {
        return "text-theme-error-text";
    }
    return "text-text-primary";
}

function sortHolders(rows: HolderRow[]): HolderRow[] {
    const sort = ((document.getElementById("holder-sort") as HTMLSelectElement | null)?.value ?? "current_value") as SortKey;
    return [...rows].sort((a, b) => {
        if (sort === "name") {
            return a.name.localeCompare(b.name);
        }
        const left = sort === "gain_loss_pct" ? (a.gain_loss_pct ?? Number.NEGATIVE_INFINITY) : a[sort];
        const right = sort === "gain_loss_pct" ? (b.gain_loss_pct ?? Number.NEGATIVE_INFINITY) : b[sort];
        if (left === right) {
            return a.name.localeCompare(b.name);
        }
        return right - left;
    });
}

/** Rows in display order: picked people sorted, then the Others row last. */
function visibleHolders(): HolderRow[] {
    if (!glance) {
        return [];
    }
    const { named, others } = groupHolders(glance.holders, shown);
    const rows = sortHolders(named);
    if (others) {
        rows.push(others);
    }
    return rows;
}

function renderPicker(): void {
    const picker = document.getElementById("holder-picker");
    if (!picker || !glance) {
        return;
    }
    const search = (document.getElementById("holder-search") as HTMLInputElement | null)?.value.trim().toLowerCase() ?? "";
    const names = glance.holders
        .map((holder) => holder.name)
        .filter((name) => name.toLowerCase().includes(search))
        .sort((a, b) => a.localeCompare(b));
    picker.innerHTML = names.map((name) => {
        const on = shown.has(name);
        const look = on
            ? "border-accent text-accent bg-dashboard-surface-alt font-medium"
            : "border-border text-text-secondary bg-dashboard-surface hover:text-text-primary";
        const icon = on ? "fa-check" : "fa-plus";
        return `<button type="button" data-holder="${escapeHtml(name)}" aria-pressed="${on}"
            class="inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-sm ${look}">
            <i class="fas ${icon} text-xs" aria-hidden="true"></i>${escapeHtml(name)}
        </button>`;
    }).join("") || `<p class="text-sm text-text-secondary">No names match that search.</p>`;

    const summary = document.getElementById("holder-picker-summary");
    if (summary) {
        const rest = glance.holders.length - shown.size;
        summary.textContent = shown.size === 0
            ? "Nobody picked, so everyone is shown by name."
            : `${shown.size} named${rest > 0 ? `, ${rest} grouped as Others` : ""}.`;
    }
    const clear = document.getElementById("holder-picker-clear") as HTMLButtonElement | null;
    if (clear) {
        clear.disabled = shown.size === 0;
    }
}

function toggleHolder(name: string): void {
    if (shown.has(name)) {
        shown.delete(name);
    } else {
        shown.add(name);
    }
    saveShown();
    renderPicker();
    render();
}

function render(): void {
    if (!glance) {
        return;
    }
    const currency = glance.display_currency || "CAD";
    const rows = visibleHolders();
    const cards = document.getElementById("holder-cards");
    const tbody = document.getElementById("holder-rows");
    if (!cards || !tbody) {
        return;
    }

    cards.innerHTML = rows.map((holder) => {
        const pct = holder.gain_loss_pct == null ? "—" : signedPct(holder.gain_loss_pct);
        const isOthers = holder.others_count != null;
        const surface = isOthers ? "bg-dashboard-surface-alt" : "bg-dashboard-surface";
        const title = isOthers ? "text-text-secondary italic" : "text-text-primary";
        return `<article class="rounded-lg border border-border ${surface} p-4">
            <h3 class="text-base font-semibold ${title} mb-2">${escapeHtml(holder.name)}</h3>
            <dl class="grid grid-cols-2 gap-x-3 gap-y-1 text-sm">
                <dt class="text-text-tertiary">Put in</dt>
                <dd class="text-right text-text-primary">${money(holder.net_contribution, currency)}</dd>
                <dt class="text-text-tertiary">Worth now</dt>
                <dd class="text-right font-medium text-text-primary">${money(holder.current_value, currency)}</dd>
                <dt class="text-text-tertiary">Gain / loss</dt>
                <dd class="text-right ${toneClass(holder.gain_loss)}">${signedMoney(holder.gain_loss, currency)} (${pct})</dd>
                <dt class="text-text-tertiary">Share</dt>
                <dd class="text-right text-text-primary">${holder.ownership_pct.toFixed(1)}%</dd>
                <dt class="text-text-tertiary">Today</dt>
                <dd class="text-right ${toneClass(holder.day_change)}">${signedMoney(holder.day_change, currency)}</dd>
            </dl>
        </article>`;
    }).join("");

    tbody.innerHTML = rows.map((holder) => {
        const pct = holder.gain_loss_pct == null ? "—" : signedPct(holder.gain_loss_pct);
        const isOthers = holder.others_count != null;
        const rowLook = isOthers ? "border-t-2 bg-dashboard-surface-alt" : "border-t";
        const nameLook = isOthers ? "text-text-secondary italic" : "text-text-primary";
        return `<tr class="${rowLook} border-border">
            <td class="px-4 py-3 font-medium ${nameLook}">${escapeHtml(holder.name)}</td>
            <td class="px-4 py-3 text-right text-text-primary">${money(holder.net_contribution, currency)}</td>
            <td class="px-4 py-3 text-right font-medium text-text-primary">${money(holder.current_value, currency)}</td>
            <td class="px-4 py-3 text-right ${toneClass(holder.gain_loss)}">${signedMoney(holder.gain_loss, currency)}</td>
            <td class="px-4 py-3 text-right ${toneClass(holder.gain_loss)}">${pct}</td>
            <td class="px-4 py-3 text-right text-text-primary">${holder.ownership_pct.toFixed(1)}%</td>
            <td class="px-4 py-3 text-right ${toneClass(holder.day_change)}">${signedMoney(holder.day_change, currency)}</td>
        </tr>`;
    }).join("");
}

function showGlance(data: HolderGlance): void {
    glance = data;
    const currency = data.display_currency || "CAD";
    document.getElementById("holder-loading")?.classList.add("hidden");
    if (!data.holders.length) {
        document.getElementById("holder-empty")?.classList.remove("hidden");
        return;
    }
    document.getElementById("holder-body")?.classList.remove("hidden");
    const copyButton = document.getElementById("copy-holder-report") as HTMLButtonElement | null;
    if (copyButton) {
        copyButton.disabled = false;
    }
    const fundValue = document.getElementById("holder-fund-value");
    if (fundValue) {
        fundValue.textContent = money(data.fund_value, currency);
    }
    const count = document.getElementById("holder-count");
    if (count) {
        count.textContent = String(data.holders.length);
    }
    const day = document.getElementById("holder-fund-day");
    if (day) {
        const pct = data.day_change_pct == null ? "" : ` (${signedPct(data.day_change_pct)})`;
        day.textContent = `${signedMoney(data.day_change, currency)}${pct}`;
        day.className = `text-2xl font-bold ${toneClass(data.day_change)}`;
    }
    // Forget picks for people who no longer hold units.
    const present = new Set(data.holders.map((holder) => holder.name));
    shown = new Set([...shown].filter((name) => present.has(name)));
    renderPicker();
    render();
}

async function copyReport(): Promise<void> {
    if (!glance) {
        return;
    }
    const rows = visibleHolders();
    if (!rows.length) {
        return;
    }
    const status = document.getElementById("copy-holder-status");
    const text = formatHolderReport(rows, glance.display_currency || "CAD", glance.fund);
    try {
        await navigator.clipboard.writeText(text);
        if (status) {
            status.textContent = "Copied. Paste it into the text.";
            status.classList.remove("hidden");
        }
    } catch {
        if (status) {
            status.textContent = "Could not copy. Select the table and copy it yourself.";
            status.classList.remove("hidden", "text-theme-success-text");
            status.classList.add("text-theme-error-text");
        }
    }
}

async function load(): Promise<void> {
    const errorEl = document.getElementById("holder-error");
    try {
        const response = await fetch("/api/admin/chimera-holders", { credentials: "include" });
        if (!response.ok) {
            throw new Error(`Request failed (${response.status})`);
        }
        const data = (await response.json()) as HolderGlance;
        showGlance(data);
    } catch (error) {
        document.getElementById("holder-loading")?.classList.add("hidden");
        if (errorEl) {
            errorEl.textContent = error instanceof Error ? error.message : "Could not load holder balances.";
            errorEl.classList.remove("hidden");
        }
    }
}

function init(): void {
    shown = loadShown();
    document.getElementById("holder-search")?.addEventListener("input", renderPicker);
    document.getElementById("holder-picker")?.addEventListener("click", (event) => {
        const button = (event.target as HTMLElement).closest<HTMLButtonElement>("button[data-holder]");
        if (button?.dataset.holder) {
            toggleHolder(button.dataset.holder);
        }
    });
    document.getElementById("holder-picker-clear")?.addEventListener("click", () => {
        shown.clear();
        saveShown();
        renderPicker();
        render();
    });
    document.getElementById("holder-sort")?.addEventListener("change", render);
    document.getElementById("copy-holder-report")?.addEventListener("click", () => {
        void copyReport();
    });
    void load();
}

if (document.getElementById("holder-cards")) {
    init();
}
