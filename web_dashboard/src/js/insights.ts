export {};

interface ThesisRow {
  id: string;
  ticker: string;
  title: string;
  disposition: string;
  intent: string;
  status: string;
  created_by: string;
  created_at?: string;
  updated_at?: string;
  entry_count?: number;
  evidence_count?: number;
  review_status?: string;
  is_weak?: boolean;
  age_days?: number | null;
}

interface ThesisEntry {
  id: string;
  entry_kind: string;
  author_kind: string;
  author_id?: string;
  body: string;
  created_at?: string;
  metadata?: Record<string, unknown>;
}

interface ThesisEvidence {
  id: string;
  evidence_kind: string;
  url?: string;
  title?: string;
  relation: string;
  article_title?: string;
  article_url?: string;
}

interface ThesisDetail extends ThesisRow {
  entries?: ThesisEntry[];
  evidence?: ThesisEvidence[];
}

function badgeClass(disposition: string): string {
  switch (disposition) {
    case "bullish":
      return "bg-green-500/10 text-green-500 border-green-500/30";
    case "bearish":
      return "bg-red-500/10 text-red-500 border-red-500/30";
    default:
      return "bg-amber-500/10 text-amber-600 border-amber-500/30";
  }
}

function intentLabel(intent: string): string {
  switch (intent) {
    case "seek_entry":
      return "Seek entry";
    case "seek_exit":
      return "Seek exit";
    default:
      return "Monitor";
  }
}

function formatDate(iso?: string): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

function reviewBadge(row: ThesisRow): string {
  const bits: string[] = [];
  if (row.is_weak) {
    bits.push(
      `<span class="px-2 py-0.5 text-xs rounded border border-amber-600/40 text-amber-700 dark:text-amber-400">weak</span>`
    );
  }
  if (row.review_status === "stale") {
    bits.push(
      `<span class="px-2 py-0.5 text-xs rounded border border-red-500/40 text-red-600">stale${
        row.age_days != null ? ` ${row.age_days}d` : ""
      }</span>`
    );
  } else if (row.review_status === "due_for_review") {
    bits.push(
      `<span class="px-2 py-0.5 text-xs rounded border border-amber-500/40 text-amber-600">due${
        row.age_days != null ? ` ${row.age_days}d` : ""
      }</span>`
    );
  }
  return bits.join("");
}

async function loadTheses(): Promise<void> {
  const loading = document.getElementById("insights-loading");
  const errEl = document.getElementById("insights-error");
  const list = document.getElementById("insights-list");
  const dueHint = document.getElementById("insights-due-hint");
  if (!list) return;

  const archived = (document.getElementById("insights-show-archived") as HTMLInputElement)?.checked;
  const dueOnly = (document.getElementById("insights-due-only") as HTMLInputElement)?.checked;
  const intent = (document.getElementById("insights-filter-intent") as HTMLSelectElement)?.value || "";
  const disposition = (document.getElementById("insights-filter-disposition") as HTMLSelectElement)?.value || "";
  const ticker = (document.getElementById("insights-filter-ticker") as HTMLInputElement)?.value.trim().toUpperCase();

  if (dueHint) {
    if (dueOnly) dueHint.classList.remove("hidden");
    else dueHint.classList.add("hidden");
  }

  if (loading) loading.classList.remove("hidden");
  if (errEl) errEl.classList.add("hidden");

  try {
    let rows: ThesisRow[] = [];
    if (dueOnly) {
      const resp = await fetch("/api/insights/due?limit=100", { credentials: "include" });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const body = (await resp.json()) as { data: ThesisRow[] };
      rows = body.data || [];
      if (ticker) rows = rows.filter((r) => r.ticker === ticker);
      if (intent) rows = rows.filter((r) => r.intent === intent);
      if (disposition) rows = rows.filter((r) => r.disposition === disposition);
    } else {
      const params = new URLSearchParams();
      if (archived) params.set("include_archived", "1");
      if (intent) params.set("intent", intent);
      if (disposition) params.set("disposition", disposition);
      if (ticker) params.set("ticker", ticker);
      const resp = await fetch(`/api/insights?${params.toString()}`, { credentials: "include" });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const body = (await resp.json()) as { data: ThesisRow[] };
      rows = body.data || [];
    }
    if (loading) loading.classList.add("hidden");

    if (!rows.length) {
      list.innerHTML = dueOnly
        ? `<p class="text-sm text-text-secondary">Nothing due for review.</p>`
        : `<p class="text-sm text-text-secondary">No theses yet. Create one to capture your view on a ticker.</p>`;
      return;
    }

    list.innerHTML = rows
      .map((row) => {
        const archivedBadge =
          row.status === "archived"
            ? `<span class="ml-2 px-2 py-0.5 text-xs rounded border border-border text-text-secondary">archived</span>`
            : "";
        return `<article class="bg-dashboard-surface border border-border rounded-lg p-4 cursor-pointer hover:border-accent/50 insights-row" data-id="${row.id}">
          <div class="flex flex-wrap items-center gap-2 mb-1">
            <a href="/ticker?ticker=${encodeURIComponent(row.ticker)}" class="font-bold text-accent underline" onclick="event.stopPropagation()">${row.ticker}</a>
            <span class="px-2 py-0.5 text-xs font-semibold rounded border ${badgeClass(row.disposition)}">${row.disposition}</span>
            <span class="px-2 py-0.5 text-xs rounded border border-border text-text-secondary">${intentLabel(row.intent)}</span>
            ${reviewBadge(row)}
            ${archivedBadge}
          </div>
          <h3 class="font-medium text-text-primary">${row.title}</h3>
          <p class="text-xs text-text-secondary mt-1">${row.created_by} · ${formatDate(row.updated_at || row.created_at)} · ${row.entry_count ?? 0} posts · ${row.evidence_count ?? 0} evidence</p>
        </article>`;
      })
      .join("");

    list.querySelectorAll(".insights-row").forEach((el) => {
      el.addEventListener("click", () => {
        const id = (el as HTMLElement).dataset.id;
        if (id) void openDetail(id);
      });
    });
  } catch (e) {
    if (loading) loading.classList.add("hidden");
    if (errEl) {
      errEl.textContent = e instanceof Error ? e.message : String(e);
      errEl.classList.remove("hidden");
    }
  }
}

async function openDetail(thesisId: string): Promise<void> {
  const panel = document.getElementById("insights-detail");
  const body = document.getElementById("insights-detail-body");
  if (!panel || !body) return;
  panel.classList.remove("hidden");
  body.innerHTML = `<p class="text-sm text-text-secondary">Loading…</p>`;

  try {
    const resp = await fetch(`/api/insights/${encodeURIComponent(thesisId)}`, { credentials: "include" });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const payload = (await resp.json()) as { data: ThesisDetail };
    const t = payload.data;
    const entries = (t.entries || [])
      .map((e) => {
        const border =
          e.entry_kind === "llm_reply"
            ? "border-sky-500/50"
            : e.entry_kind === "review"
              ? "border-amber-500/50"
              : "border-border";
        const verdict =
          e.entry_kind === "llm_reply" && e.metadata && typeof e.metadata.verdict === "string"
            ? ` · ${escapeHtml(e.metadata.verdict)}`
            : "";
        return `<div class="border-l-2 ${border} pl-3 py-2 mb-2">
          <p class="text-xs text-text-secondary">${e.entry_kind}${verdict} · ${e.author_id || e.author_kind} · ${formatDate(e.created_at)}</p>
          <p class="text-sm text-text-primary whitespace-pre-wrap">${escapeHtml(e.body)}</p>
        </div>`;
      })
      .join("");
    const evidence = (t.evidence || [])
      .map((ev) => {
        const label = ev.title || ev.article_title || ev.url || ev.evidence_kind;
        const href = ev.url || ev.article_url;
        const link = href ? `<a href="${escapeHtml(href)}" target="_blank" rel="noopener" class="text-accent underline">${escapeHtml(label || "")}</a>` : escapeHtml(label || "");
        return `<li class="text-sm"><span class="text-xs text-text-secondary">${ev.relation}</span> — ${link}</li>`;
      })
      .join("");

    body.innerHTML = `
      <div class="mb-4">
        <div class="flex flex-wrap gap-2 mb-2">
          <span class="px-2 py-0.5 text-xs font-semibold rounded border ${badgeClass(t.disposition)}">${t.disposition}</span>
          <span class="px-2 py-0.5 text-xs rounded border border-border">${intentLabel(t.intent)}</span>
          <span class="text-xs text-text-secondary">${t.status}</span>
        </div>
        <h2 class="text-xl font-bold text-text-primary">${escapeHtml(t.title)}</h2>
        <p class="text-xs text-text-secondary mt-1">${t.ticker} · ${t.created_by}</p>
      </div>
      <section class="mb-6">
        <h3 class="text-sm font-semibold text-text-primary mb-2">Thread</h3>
        ${entries || "<p class='text-sm text-text-secondary'>No entries.</p>"}
        <textarea id="detail-comment" rows="3" placeholder="Add comment or review…"
          class="w-full mt-2 bg-dashboard-background border border-border rounded-lg px-3 py-2 text-sm text-text-primary"></textarea>
        <div class="flex flex-wrap gap-2 mt-2">
          <button type="button" data-action="comment" class="px-3 py-1 text-xs border border-border rounded-lg text-text-primary">Add comment</button>
          <button type="button" data-action="review" class="px-3 py-1 text-xs border border-amber-500/50 text-amber-600 rounded-lg">Add review</button>
          <button type="button" data-action="archive" class="px-3 py-1 text-xs border border-border rounded-lg text-text-secondary">Archive</button>
        </div>
      </section>
      <section>
        <h3 class="text-sm font-semibold text-text-primary mb-2">Evidence</h3>
        <ul class="list-disc list-inside space-y-1 mb-2">${evidence || "<li class='text-sm text-text-secondary'>None linked.</li>"}</ul>
        <input id="detail-evidence-url" type="url" placeholder="Paste URL to attach"
          class="w-full text-sm bg-dashboard-background border border-border rounded-lg px-3 py-1 text-text-primary">
        <button type="button" data-action="evidence" class="mt-2 px-3 py-1 text-xs border border-border rounded-lg text-text-primary">Attach URL</button>
      </section>`;

    body.querySelectorAll("button[data-action]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const action = (btn as HTMLButtonElement).dataset.action;
        if (action === "comment" || action === "review") void postEntry(thesisId, action);
        else if (action === "archive") void archiveThesis(thesisId);
        else if (action === "evidence") void attachUrl(thesisId);
      });
    });
  } catch (e) {
    body.innerHTML = `<p class="text-sm text-theme-error-text">${e instanceof Error ? e.message : String(e)}</p>`;
  }
}

function escapeHtml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

async function postEntry(thesisId: string, kind: "comment" | "review"): Promise<void> {
  const ta = document.getElementById("detail-comment") as HTMLTextAreaElement | null;
  const body = ta?.value.trim();
  if (!body) return;
  const resp = await fetch(`/api/insights/${encodeURIComponent(thesisId)}/entries`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ entry_kind: kind, body }),
  });
  if (!resp.ok) {
    alert(`Failed: HTTP ${resp.status}`);
    return;
  }
  if (ta) ta.value = "";
  await openDetail(thesisId);
  await loadTheses();
}

async function archiveThesis(thesisId: string): Promise<void> {
  if (!confirm("Archive this thesis? You can restore it from the archived list.")) return;
  const resp = await fetch(`/api/insights/${encodeURIComponent(thesisId)}/archive`, {
    method: "POST",
    credentials: "include",
  });
  if (!resp.ok) {
    alert(`Archive failed: HTTP ${resp.status}`);
    return;
  }
  document.getElementById("insights-detail")?.classList.add("hidden");
  await loadTheses();
}

async function attachUrl(thesisId: string): Promise<void> {
  const input = document.getElementById("detail-evidence-url") as HTMLInputElement | null;
  const url = input?.value.trim();
  if (!url) return;
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
  if (input) input.value = "";
  await openDetail(thesisId);
}

function wireModal(): void {
  // TODO(palette): Convert #insights-modal to Flowbite Modal markup + API
  // (aria/focus/Esc) instead of manual .hidden toggles — see trade_entry.ts.
  const modal = document.getElementById("insights-modal");
  const form = document.getElementById("insights-form") as HTMLFormElement | null;
  document.getElementById("insights-new-btn")?.addEventListener("click", () => modal?.classList.remove("hidden"));
  document.getElementById("insights-modal-cancel")?.addEventListener("click", () => modal?.classList.add("hidden"));
  document.getElementById("insights-detail-close")?.addEventListener("click", () => {
    document.getElementById("insights-detail")?.classList.add("hidden");
  });
  form?.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const ticker = (document.getElementById("ins-ticker") as HTMLInputElement).value.trim().toUpperCase();
    const title = (document.getElementById("ins-title") as HTMLInputElement).value.trim();
    const disposition = (document.getElementById("ins-disposition") as HTMLSelectElement).value;
    const intent = (document.getElementById("ins-intent") as HTMLSelectElement).value;
    const body = (document.getElementById("ins-body") as HTMLTextAreaElement).value.trim();
    const source_url = (document.getElementById("ins-source-url") as HTMLInputElement).value.trim();
    const resp = await fetch("/api/insights", {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ticker, title, disposition, intent, body, source_url: source_url || undefined }),
    });
    if (!resp.ok) {
      const err = (await resp.json().catch(() => ({}))) as { error?: string };
      alert(err.error || `HTTP ${resp.status}`);
      return;
    }
    modal?.classList.add("hidden");
    form.reset();
    await loadTheses();
  });
}

document.addEventListener("DOMContentLoaded", () => {
  wireModal();
  document.getElementById("insights-refresh-btn")?.addEventListener("click", () => void loadTheses());
  document.getElementById("insights-show-archived")?.addEventListener("change", () => void loadTheses());
  document.getElementById("insights-due-only")?.addEventListener("change", () => void loadTheses());
  document.getElementById("insights-filter-intent")?.addEventListener("change", () => void loadTheses());
  document.getElementById("insights-filter-disposition")?.addEventListener("change", () => void loadTheses());
  document.getElementById("insights-filter-ticker")?.addEventListener("change", () => void loadTheses());
  void loadTheses();
});
