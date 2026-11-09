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

let glance: HolderGlance | null = null;

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

function visibleHolders(): HolderRow[] {
    if (!glance) {
        return [];
    }
    const search = (document.getElementById("holder-search") as HTMLInputElement | null)?.value.trim().toLowerCase() ?? "";
    const sort = ((document.getElementById("holder-sort") as HTMLSelectElement | null)?.value ?? "current_value") as SortKey;
    const rows = glance.holders.filter((holder) => holder.name.toLowerCase().includes(search));
    rows.sort((a, b) => {
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
    return rows;
}

function render(): void {
    if (!glance) {
        return;
    }
    const currency = glance.display_currency || "CAD";
    const rows = visibleHolders();
    const cards = document.getElementById("holder-cards");
    const tbody = document.getElementById("holder-rows");
    const filterEmpty = document.getElementById("holder-filter-empty");
    if (!cards || !tbody || !filterEmpty) {
        return;
    }

    if (rows.length === 0) {
        cards.innerHTML = "";
        tbody.innerHTML = "";
        filterEmpty.classList.remove("hidden");
        return;
    }
    filterEmpty.classList.add("hidden");

    cards.innerHTML = rows.map((holder) => {
        const pct = holder.gain_loss_pct == null ? "—" : signedPct(holder.gain_loss_pct);
        return `<article class="rounded-lg border border-border bg-dashboard-surface p-4">
            <h3 class="text-base font-semibold text-text-primary mb-2">${escapeHtml(holder.name)}</h3>
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
        return `<tr class="border-t border-border">
            <td class="px-4 py-3 font-medium text-text-primary">${escapeHtml(holder.name)}</td>
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
    document.getElementById("holder-search")?.addEventListener("input", render);
    document.getElementById("holder-sort")?.addEventListener("change", render);
    document.getElementById("copy-holder-report")?.addEventListener("click", () => {
        void copyReport();
    });
    void load();
}

if (document.getElementById("holder-cards")) {
    init();
}
