export {};

interface IdeaRow {
  id: string;
  title: string;
  article_type?: string;
  source?: string;
  relevance_score?: number;
  tickers?: string[];
  summary?: string;
}

async function triage(articleId: string, status: "accepted" | "dismissed" | "snoozed", tickers: string[]): Promise<boolean> {
  const fund = (window as unknown as { ui?: { getSelectedFund?: () => string } }).ui?.getSelectedFund?.() || "TEST";
  const resp = await fetch("/api/ideas/triage", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ article_id: articleId, status, fund, tickers }),
  });
  if (!resp.ok) {
    const body = await resp.json().catch(() => ({})) as { error?: string };
    alert(`Triage failed: ${body.error || `HTTP ${resp.status}`}`);
    return false;
  }
  const body = await resp.json() as { failed_tickers?: string[] };
  if (body.failed_tickers?.length) {
    alert(`Saved, but these tickers could not be added to the watchlist: ${body.failed_tickers.join(", ")}`);
  }
  return true;
}

function renderIdeas(rows: IdeaRow[]): void {
  const list = document.getElementById("ideas-list");
  const loading = document.getElementById("ideas-loading");
  if (loading) loading.classList.add("hidden");
  if (!list) return;
  if (!rows.length) {
    list.innerHTML = `<p class="text-sm text-text-secondary">Inbox empty — check back after the next alpha run.</p>`;
    return;
  }
  list.innerHTML = rows.map((row) => {
    const tickers = (row.tickers || []).join(", ");
    return `<article class="bg-dashboard-surface border border-border rounded-lg p-4">
      <h3 class="font-medium text-text-primary">${row.title}</h3>
      <p class="text-xs text-text-secondary mt-1">${row.article_type || ""} · ${row.source || ""} · score ${row.relevance_score ?? "—"}</p>
      ${tickers ? `<p class="text-xs mt-1">Tickers: ${tickers}</p>` : ""}
      ${row.summary ? `<p class="text-sm mt-2 text-text-secondary line-clamp-3">${row.summary}</p>` : ""}
      <div class="flex gap-2 mt-3">
        <button type="button" data-action="accepted" data-id="${row.id}" data-tickers='${JSON.stringify(row.tickers || [])}'
          class="px-3 py-1 text-xs font-medium text-white bg-accent rounded">Accept</button>
        <button type="button" data-action="dismissed" data-id="${row.id}"
          class="px-3 py-1 text-xs border border-border rounded">Dismiss</button>
        <button type="button" data-action="snoozed" data-id="${row.id}"
          class="px-3 py-1 text-xs border border-border rounded">Snooze</button>
      </div>
    </article>`;
  }).join("");

  list.querySelectorAll("button[data-action]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const b = btn as HTMLButtonElement;
      const id = b.dataset.id || "";
      const action = b.dataset.action as "accepted" | "dismissed" | "snoozed";
      const tickers = JSON.parse(b.dataset.tickers || "[]") as string[];
      if (await triage(id, action, tickers)) {
        b.closest("article")?.remove();
      }
    });
  });
}

async function loadIdeas(): Promise<void> {
  try {
    const resp = await fetch("/api/ideas/inbox");
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const body = await resp.json() as { data: IdeaRow[] };
    renderIdeas(body.data || []);
  } catch (e) {
    const err = document.getElementById("ideas-error");
    if (err) {
      err.textContent = e instanceof Error ? e.message : String(e);
      err.classList.remove("hidden");
    }
  }
}

document.addEventListener("DOMContentLoaded", () => void loadIdeas());
