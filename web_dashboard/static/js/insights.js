import { sentimentToneClasses } from "./sentiment_badges.js";
import { helpTip, initTooltips } from "./glossary.js";
const holdingsByTicker = new Map();
let holdingsFundName = null;
let openThesisId = null;
function getSelectedFund() {
    const fromUi = window.ui?.getSelectedFund?.();
    if (fromUi)
        return fromUi;
    const sel = document.getElementById("global-fund-select");
    const v = (sel?.value || "").trim();
    if (!v || v.toLowerCase() === "all")
        return null;
    return v;
}
function formatCompactDollars(value) {
    const abs = Math.abs(value);
    if (abs >= 10000) {
        const k = value / 1000;
        const rounded = Math.abs(k) >= 100 ? k.toFixed(0) : k.toFixed(1);
        return `$${rounded}k`;
    }
    return ("$" +
        Math.round(value).toLocaleString("en-US", {
            maximumFractionDigits: 0,
        }));
}
async function loadHoldings() {
    const fund = getSelectedFund();
    holdingsFundName = fund;
    holdingsByTicker.clear();
    try {
        const params = new URLSearchParams();
        if (fund)
            params.append("fund", fund);
        const resp = await fetch(`/api/dashboard/holdings?${params.toString()}`, {
            credentials: "include",
        });
        if (!resp.ok)
            return;
        const body = (await resp.json());
        for (const row of body.data || []) {
            const ticker = String(row.ticker || "")
                .trim()
                .toUpperCase();
            if (!ticker)
                continue;
            const shares = Number(row.shares) || 0;
            const value = Number(row.value) || 0;
            if (shares <= 0 && value <= 0)
                continue;
            holdingsByTicker.set(ticker, { shares, value });
        }
    }
    catch {
        // Holdings are optional enrichment — don't block Insights.
    }
}
function holdingChip(ticker) {
    const pos = holdingsByTicker.get(ticker.trim().toUpperCase());
    if (!pos || (pos.shares <= 0 && pos.value <= 0))
        return "";
    const fund = holdingsFundName || "Selected fund";
    const sharesLabel = pos.shares === 1 ? "1 share" : `${pos.shares.toLocaleString("en-US")} shares`;
    const title = escapeHtml(`${fund} · ${sharesLabel}`);
    const amount = escapeHtml(formatCompactDollars(pos.value));
    return `<span class="inline-flex items-center gap-1 px-2 py-0.5 text-xs rounded border border-border text-text-secondary" title="${title}"><i class="fas fa-briefcase text-[10px] opacity-80" aria-hidden="true"></i><span>${amount}</span></span>`;
}
function badgeClass(disposition) {
    return sentimentToneClasses(disposition);
}
// Ticker + company name where the payload provides one; bare ticker otherwise
// (coverage is partial — ETFs and some .TO names have none).
function tickerLabel(ticker, companyName) {
    const t = escapeHtml(ticker || "");
    const name = String(companyName ?? "").trim();
    if (!name)
        return t;
    return `${t} <span class="text-xs font-normal text-text-secondary">${escapeHtml(name)}</span>`;
}
function intentLabel(intent) {
    switch (intent) {
        case "seek_entry":
            return "Seek entry";
        case "seek_exit":
            return "Seek exit";
        default:
            return "Monitor";
    }
}
function formatDate(iso) {
    if (!iso)
        return "—";
    try {
        return new Date(iso).toLocaleString();
    }
    catch {
        return iso;
    }
}
function linkHostname(href) {
    try {
        return new URL(href).hostname.replace(/^www\./, "");
    }
    catch {
        return "";
    }
}
function renderEvidenceItem(ev, thesisTitle) {
    const href = (ev.url || ev.article_url || "").trim();
    const host = href ? linkHostname(href) : "";
    const kind = ev.evidence_kind || "evidence";
    // user_url rows from moat probe wrongly used the thesis title as caption while
    // pointing at quote pages (e.g. Yahoo). Prefer a real article title, else host.
    let label = (ev.article_title || "").trim();
    if (!label) {
        const title = (ev.title || "").trim();
        const titleLooksLikeThesis = !!title &&
            (title === thesisTitle || title.startsWith("[LLM draft]"));
        if (kind === "user_url" && titleLooksLikeThesis && host) {
            label = host;
        }
        else if (title) {
            label = title;
        }
        else {
            label = host || href || kind;
        }
    }
    const destHint = href && host && label !== host
        ? ` <span class="text-xs text-text-secondary">(${escapeHtml(host)})</span>`
        : "";
    const link = href
        ? `<a href="${escapeHtml(href)}" target="_blank" rel="noopener" class="text-accent underline">${escapeHtml(label)}</a>${destHint}`
        : escapeHtml(label);
    return `<li class="text-sm"><span class="text-xs text-text-secondary">${escapeHtml(ev.relation)} · ${escapeHtml(kind)}</span> — ${link}</li>`;
}
// Review chips explain themselves: "stale" and "due" are the app's own
// vocabulary, and a first-time viewer cannot guess what review_status means.
function reviewBadge(row) {
    const bits = [];
    if (row.is_weak) {
        bits.push(`<span class="px-2 py-0.5 text-xs rounded border border-amber-600/40 text-amber-700 dark:text-amber-400">weak</span>`);
    }
    if (row.review_status === "stale") {
        bits.push(`<span class="px-2 py-0.5 text-xs rounded border border-red-500/40 text-red-600">stale${row.age_days != null ? ` ${row.age_days}d` : ""}</span>${helpTip("STALE_THESIS", "p-1")}`);
    }
    else if (row.review_status === "due_for_review") {
        bits.push(`<span class="px-2 py-0.5 text-xs rounded border border-amber-500/40 text-amber-600">due${row.age_days != null ? ` ${row.age_days}d` : ""}</span>${helpTip("thesis_due", "p-1")}`);
    }
    return bits.join("");
}
async function loadTheses() {
    const loading = document.getElementById("insights-loading");
    const errEl = document.getElementById("insights-error");
    const list = document.getElementById("insights-list");
    const dueHint = document.getElementById("insights-due-hint");
    if (!list)
        return;
    const archived = document.getElementById("insights-show-archived")?.checked;
    const dueOnly = document.getElementById("insights-due-only")?.checked;
    const intent = document.getElementById("insights-filter-intent")?.value || "";
    const disposition = document.getElementById("insights-filter-disposition")?.value || "";
    const ticker = document.getElementById("insights-filter-ticker")?.value.trim().toUpperCase();
    if (dueHint) {
        if (dueOnly)
            dueHint.classList.remove("hidden");
        else
            dueHint.classList.add("hidden");
    }
    if (loading)
        loading.classList.remove("hidden");
    if (errEl)
        errEl.classList.add("hidden");
    try {
        let rows = [];
        if (dueOnly) {
            const resp = await fetch("/api/insights/due?limit=100", { credentials: "include" });
            if (!resp.ok)
                throw new Error(`HTTP ${resp.status}`);
            const body = (await resp.json());
            rows = body.data || [];
            if (ticker)
                rows = rows.filter((r) => r.ticker === ticker);
            if (intent)
                rows = rows.filter((r) => r.intent === intent);
            if (disposition)
                rows = rows.filter((r) => r.disposition === disposition);
        }
        else {
            const params = new URLSearchParams();
            if (archived)
                params.set("include_archived", "1");
            if (intent)
                params.set("intent", intent);
            if (disposition)
                params.set("disposition", disposition);
            if (ticker)
                params.set("ticker", ticker);
            const resp = await fetch(`/api/insights?${params.toString()}`, { credentials: "include" });
            if (!resp.ok)
                throw new Error(`HTTP ${resp.status}`);
            const body = (await resp.json());
            rows = body.data || [];
        }
        if (loading)
            loading.classList.add("hidden");
        if (!rows.length) {
            list.innerHTML = dueOnly
                ? `<p class="text-sm text-text-secondary">Nothing due for review.</p>`
                : `<p class="text-sm text-text-secondary">No theses yet. Create one to capture your view on a ticker.</p>`;
            return;
        }
        list.innerHTML = rows
            .map((row) => {
            const archivedBadge = row.status === "archived"
                ? `<span class="ml-2 px-2 py-0.5 text-xs rounded border border-border text-text-secondary">archived</span>`
                : "";
            return `<article class="bg-dashboard-surface border border-border rounded-lg p-4 cursor-pointer hover:border-accent/50 insights-row" data-id="${escapeHtml(row.id)}">
          <div class="flex flex-wrap items-center gap-2 mb-1">
            <a href="/ticker?ticker=${encodeURIComponent(row.ticker)}" class="font-bold text-accent underline" onclick="event.stopPropagation()">${tickerLabel(row.ticker, row.company_name)}</a>
            ${holdingChip(row.ticker)}
            <span class="px-2 py-0.5 text-xs font-semibold rounded border ${badgeClass(row.disposition)}">${escapeHtml(row.disposition)}</span>${helpTip("disposition", "p-1")}
            <span class="px-2 py-0.5 text-xs rounded border border-border text-text-secondary">${intentLabel(row.intent)}</span>${helpTip("intent", "p-1")}
            ${reviewBadge(row)}
            ${archivedBadge}
          </div>
          <h3 class="font-medium text-text-primary">${escapeHtml(row.title)}</h3>
          <p class="text-xs text-text-secondary mt-1">${escapeHtml(row.created_by)} · ${formatDate(row.updated_at || row.created_at)} · ${row.entry_count ?? 0} notes · ${row.evidence_count ?? 0} evidence</p>
        </article>`;
        })
            .join("");
        // Rows above injected help tips; Flowbite needs a re-scan to wire them.
        initTooltips();
        list.querySelectorAll(".insights-row").forEach((el) => {
            el.addEventListener("click", () => {
                const id = el.dataset.id;
                if (id)
                    void openDetail(id);
            });
        });
    }
    catch (e) {
        if (loading)
            loading.classList.add("hidden");
        if (errEl) {
            errEl.textContent = e instanceof Error ? e.message : String(e);
            errEl.classList.remove("hidden");
        }
    }
}
async function openDetail(thesisId) {
    const panel = document.getElementById("insights-detail");
    const body = document.getElementById("insights-detail-body");
    if (!panel || !body)
        return;
    openThesisId = thesisId;
    panel.classList.remove("hidden");
    body.innerHTML = `<p class="text-sm text-text-secondary">Loading…</p>`;
    try {
        const resp = await fetch(`/api/insights/${encodeURIComponent(thesisId)}`, { credentials: "include" });
        if (!resp.ok)
            throw new Error(`HTTP ${resp.status}`);
        const payload = (await resp.json());
        const t = payload.data;
        const entries = (t.entries || [])
            .map((e) => {
            const border = e.entry_kind === "llm_reply"
                ? "border-sky-500/50"
                : e.entry_kind === "review"
                    ? "border-amber-500/50"
                    : "border-border";
            // AI verdicts are the app's least guessable vocabulary (TENSION means
            // "the AI disagreed with your own reasoning"). Show the verdict as a
            // badge that explains itself, plus one line up front that these
            // evaluations are advisory only. Unknown verdicts get no tip (helpTip
            // returns "") but still show as an escaped badge.
            const verdict = e.entry_kind === "llm_reply" && e.metadata && typeof e.metadata.verdict === "string"
                ? ` · <span class="px-1.5 py-0.5 text-xs rounded border border-sky-500/40 text-sky-700 dark:text-sky-400">${escapeHtml(e.metadata.verdict)}</span>${helpTip(String(e.metadata.verdict).toUpperCase(), "p-1")}`
                : "";
            return `<div class="border-l-2 ${border} pl-3 py-2 mb-2">
          <p class="text-xs text-text-secondary">${escapeHtml(e.entry_kind)}${verdict} · ${escapeHtml(e.author_id || e.author_kind)} · ${formatDate(e.created_at)}</p>
          <p class="text-sm text-text-primary whitespace-pre-wrap">${escapeHtml(e.body)}</p>
        </div>`;
        })
            .join("");
        const evidence = (t.evidence || []).map((ev) => renderEvidenceItem(ev, t.title)).join("");
        const dispOpts = ["bullish", "bearish", "neutral"]
            .map((d) => `<option value="${d}"${d === t.disposition ? " selected" : ""}>${d}</option>`)
            .join("");
        const intentOpts = [
            ["seek_entry", "Seek entry"],
            ["seek_exit", "Seek exit"],
            ["monitor", "Monitor"],
        ]
            .map(([v, label]) => `<option value="${v}"${v === t.intent ? " selected" : ""}>${label}</option>`)
            .join("");
        body.innerHTML = `
      <div class="mb-4">
        <div class="flex flex-wrap gap-2 mb-2 items-center">
          <span class="font-bold text-accent">${tickerLabel(t.ticker, t.company_name)}</span>
          ${holdingChip(t.ticker)}
          <span class="px-2 py-0.5 text-xs font-semibold rounded border ${badgeClass(t.disposition)}">${escapeHtml(t.disposition)}</span>${helpTip("disposition", "p-1")}
          <span class="px-2 py-0.5 text-xs rounded border border-border">${intentLabel(t.intent)}</span>${helpTip("intent", "p-1")}
          <span class="text-xs text-text-secondary">${escapeHtml(t.status)}</span>
        </div>
        <h2 class="text-xl font-bold text-text-primary">${escapeHtml(t.title)}</h2>
        <p class="text-xs text-text-secondary mt-1">${escapeHtml(t.created_by)}</p>
      </div>
      <section class="mb-6">
        <h3 class="text-sm font-semibold text-text-primary mb-2">Thread</h3>
        <p class="text-xs text-text-secondary mb-2"><i class="fas fa-robot mr-1 opacity-60" aria-hidden="true"></i>Entries marked "llm_reply" are AI evaluations of your reasoning. They are advisory only — they never change your stance, notes, or review status.</p>
        ${entries || "<p class='text-sm text-text-secondary'>No entries.</p>"}
        <textarea id="detail-comment" rows="3" placeholder="Write a note…"
          class="w-full mt-2 bg-dashboard-background border border-border rounded-lg px-3 py-2 text-sm text-text-primary"></textarea>
        <div class="mt-2 space-y-1 text-xs text-text-secondary">
          <p><span class="font-medium text-text-primary">Comment</span> — discussion note only. Does not change stance or clear due/stale.</p>
          <p><span class="font-medium text-text-primary">Review</span> — human check-in that bumps last reviewed and can update disposition/intent. AI eval also refreshes due/stale (≥14d / ≥30d since last check-in) without changing stance.</p>
        </div>
        <div class="grid grid-cols-2 gap-2 mt-3">
          <div>
            <label class="text-xs text-text-secondary" for="detail-disposition">Disposition (review) ${helpTip("disposition", "p-1")}</label>
            <select id="detail-disposition"
              class="w-full mt-1 text-sm bg-dashboard-background border border-border rounded-lg px-2 py-1.5 text-text-primary">${dispOpts}</select>
          </div>
          <div>
            <label class="text-xs text-text-secondary" for="detail-intent">Intent (review) ${helpTip("intent", "p-1")}</label>
            <select id="detail-intent"
              class="w-full mt-1 text-sm bg-dashboard-background border border-border rounded-lg px-2 py-1.5 text-text-primary">${intentOpts}</select>
          </div>
        </div>
        <div class="flex flex-wrap gap-2 mt-2">
          <button type="button" data-action="comment" class="btn-outline-sm" title="Add a discussion note without refreshing the review clock">Add comment</button>
          <button type="button" data-action="review" class="btn-outline-sm" title="Mark as reviewed and optionally update stance">Add review</button>
          <button type="button" data-action="archive" class="px-3 py-1 text-xs border border-border rounded-lg text-text-secondary hover:bg-dashboard-surface-alt">Archive</button>
        </div>
      </section>
      <section>
        <h3 class="text-sm font-semibold text-text-primary mb-2">Evidence</h3>
        <p class="text-xs text-text-secondary mb-2">Linked sources for this thesis (articles, filings, notes). Host shown in parentheses so you can see where the link goes.</p>
        <ul class="list-disc list-inside space-y-1 mb-2">${evidence || "<li class='text-sm text-text-secondary'>None linked.</li>"}</ul>
        <input id="detail-evidence-url" type="url" placeholder="Paste URL to attach"
          class="w-full text-sm bg-dashboard-background border border-border rounded-lg px-3 py-1 text-text-primary">
        <button type="button" data-action="evidence" class="mt-2 btn-outline-sm">Attach URL</button>
      </section>`;
        body.querySelectorAll("button[data-action]").forEach((btn) => {
            btn.addEventListener("click", () => {
                const action = btn.dataset.action;
                if (action === "comment" || action === "review")
                    void postEntry(thesisId, action);
                else if (action === "archive")
                    void archiveThesis(thesisId);
                else if (action === "evidence")
                    void attachUrl(thesisId);
            });
        });
        // The drawer injected tips (disposition, intent, AI verdicts) — wire them.
        initTooltips();
    }
    catch (e) {
        body.innerHTML = `<p class="text-sm text-theme-error-text">${e instanceof Error ? e.message : String(e)}</p>`;
    }
}
function escapeHtml(text) {
    return text
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
}
async function postEntry(thesisId, kind) {
    const ta = document.getElementById("detail-comment");
    const body = ta?.value.trim();
    if (!body)
        return;
    const payload = { entry_kind: kind, body };
    if (kind === "review") {
        const disposition = document.getElementById("detail-disposition")
            ?.value;
        const intent = document.getElementById("detail-intent")?.value;
        if (disposition)
            payload.disposition = disposition;
        if (intent)
            payload.intent = intent;
    }
    const resp = await fetch(`/api/insights/${encodeURIComponent(thesisId)}/entries`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
    });
    if (!resp.ok) {
        alert(`Failed: HTTP ${resp.status}`);
        return;
    }
    if (ta)
        ta.value = "";
    await openDetail(thesisId);
    await loadTheses();
}
async function archiveThesis(thesisId) {
    if (!confirm("Archive this thesis? You can restore it from the archived list."))
        return;
    const resp = await fetch(`/api/insights/${encodeURIComponent(thesisId)}/archive`, {
        method: "POST",
        credentials: "include",
    });
    if (!resp.ok) {
        alert(`Archive failed: HTTP ${resp.status}`);
        return;
    }
    document.getElementById("insights-detail")?.classList.add("hidden");
    openThesisId = null;
    await loadTheses();
}
async function attachUrl(thesisId) {
    const input = document.getElementById("detail-evidence-url");
    const url = input?.value.trim();
    if (!url)
        return;
    const resp = await fetch(`/api/insights/${encodeURIComponent(thesisId)}/evidence`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ evidence_kind: "user_url", url, relation: "context" }),
    });
    if (!resp.ok) {
        alert(`Attach failed: HTTP ${resp.status}`);
        return;
    }
    if (input)
        input.value = "";
    await openDetail(thesisId);
}
function closeInsightsModal() {
    // tsc does not bundle bare "flowbite" imports for the browser; use the same
    // data-modal-hide click pattern as funds.ts / trade_entry.ts.
    document.querySelector('[data-modal-hide="insights-modal"]')?.click();
}
function wireModal() {
    const form = document.getElementById("insights-form");
    // Flowbite handles modal open/close via data attributes (data-modal-target, data-modal-hide)
    document.getElementById("insights-detail-close")?.addEventListener("click", () => {
        openThesisId = null;
        document.getElementById("insights-detail")?.classList.add("hidden");
    });
    form?.addEventListener("submit", async (ev) => {
        ev.preventDefault();
        const ticker = document.getElementById("ins-ticker").value.trim().toUpperCase();
        const title = document.getElementById("ins-title").value.trim();
        const disposition = document.getElementById("ins-disposition").value;
        const intent = document.getElementById("ins-intent").value;
        const body = document.getElementById("ins-body").value.trim();
        const source_url = document.getElementById("ins-source-url").value.trim();
        const resp = await fetch("/api/insights", {
            method: "POST",
            credentials: "include",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ ticker, title, disposition, intent, body, source_url: source_url || undefined }),
        });
        if (!resp.ok) {
            const err = (await resp.json().catch(() => ({})));
            alert(err.error || `HTTP ${resp.status}`);
            return;
        }
        closeInsightsModal();
        form.reset();
        await loadTheses();
    });
}
document.addEventListener("DOMContentLoaded", () => {
    wireModal();
    document.getElementById("insights-refresh-btn")?.addEventListener("click", () => {
        void (async () => {
            await loadHoldings();
            await loadTheses();
        })();
    });
    document.getElementById("insights-show-archived")?.addEventListener("change", () => void loadTheses());
    document.getElementById("insights-due-only")?.addEventListener("change", () => void loadTheses());
    document.getElementById("insights-filter-intent")?.addEventListener("change", () => void loadTheses());
    document.getElementById("insights-filter-disposition")?.addEventListener("change", () => void loadTheses());
    document.getElementById("insights-filter-ticker")?.addEventListener("change", () => void loadTheses());
    window.addEventListener("fundChanged", () => {
        void (async () => {
            await loadHoldings();
            await loadTheses();
            if (openThesisId && !document.getElementById("insights-detail")?.classList.contains("hidden")) {
                await openDetail(openThesisId);
            }
        })();
    });
    const params = new URLSearchParams(window.location.search);
    const deepThesis = (params.get("thesis") || window.location.hash.replace(/^#/, "") || "").trim();
    const deepTicker = (params.get("ticker") || "").trim().toUpperCase();
    if (deepTicker) {
        const input = document.getElementById("insights-filter-ticker");
        if (input)
            input.value = deepTicker;
    }
    void (async () => {
        await loadHoldings();
        await loadTheses();
        if (deepThesis) {
            await openDetail(deepThesis);
        }
    })();
});
//# sourceMappingURL=insights.js.map