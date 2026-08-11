import { Modal } from "flowbite";
import { getCsrfHeaders } from "./csrf.js";
import { showToast } from "./toast.js";

type TabName = "youtube" | "rss";

interface YoutubeSource {
  id: number;
  label: string;
  kind: string;
  handle?: string | null;
  channel_id?: string | null;
  query_text?: string | null;
  alpha_mechanism?: string | null;
  expected_tickers?: string[];
  confidence_weight?: number;
  enabled: boolean;
  captions_ok?: boolean | null;
  last_seen_at?: string | null;
  last_error_reason?: string | null;
  notes?: string | null;
}

interface RssFeed {
  id: number;
  name: string;
  url: string;
  category?: string | null;
  enabled: boolean;
  last_fetched_at?: string | null;
  last_error?: string | null;
}

interface BulkRow {
  status: "new" | "duplicate" | "invalid";
  label: string;
  handle?: string | null;
  warnings: string[];
  errors: string[];
}

const page = document.getElementById("sources-page");
const canModify = page?.dataset.canModify === "true";

function esc(text: string | null | undefined): string {
  const d = document.createElement("div");
  d.textContent = text ?? "";
  return d.innerHTML;
}

async function api<T>(url: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...getCsrfHeaders(),
    ...(init?.headers as Record<string, string> | undefined),
  };
  const res = await fetch(url, { ...init, headers, credentials: "same-origin" });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error((data as { error?: string }).error || `HTTP ${res.status}`);
  }
  return data as T;
}

function setTab(tab: TabName): void {
  document.querySelectorAll<HTMLButtonElement>(".sources-tab").forEach((btn) => {
    const active = btn.dataset.tab === tab;
    btn.classList.toggle("border-accent", active);
    btn.classList.toggle("text-accent", active);
    btn.classList.toggle("border-transparent", !active);
    btn.classList.toggle("text-text-secondary", !active);
  });
  document.getElementById("panel-youtube")?.classList.toggle("hidden", tab !== "youtube");
  document.getElementById("panel-rss")?.classList.toggle("hidden", tab !== "rss");
}

function captionsBadge(ok: boolean | null | undefined): string {
  if (ok === true) return '<span class="text-theme-success-text">✓</span>';
  if (ok === false) return '<span class="text-theme-error-text">✗</span>';
  return '<span class="text-text-tertiary">—</span>';
}

function fmtWhen(value?: string | null): string {
  if (!value) return "—";
  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
}

async function loadYoutube(): Promise<void> {
  const body = document.getElementById("yt-table-body");
  if (!body) return;
  try {
    const data = await api<{ sources: YoutubeSource[] }>("/api/admin/sources/youtube");
    const rows = data.sources || [];
    if (!rows.length) {
      body.innerHTML =
        '<tr><td colspan="10" class="px-4 py-4 text-center text-text-secondary">No YouTube sources yet. Use Bulk import.</td></tr>';
      return;
    }
    body.innerHTML = rows
      .map((s) => {
        const tickers = (s.expected_tickers || []).join(", ") || "—";
        return `<tr class="border-b border-border" data-id="${s.id}">
          <td class="px-4 py-3 text-text-primary">${esc(s.label)}
            <div class="text-xs text-text-tertiary">${esc(s.handle || s.channel_id || s.query_text || "")}</div>
          </td>
          <td class="px-4 py-3">${esc(s.kind)}</td>
          <td class="px-4 py-3">${esc(s.alpha_mechanism || "—")}</td>
          <td class="px-4 py-3">${esc(tickers)}</td>
          <td class="px-4 py-3">${s.confidence_weight ?? 1}</td>
          <td class="px-4 py-3">
            <input type="checkbox" class="yt-enabled" data-id="${s.id}" ${s.enabled ? "checked" : ""} ${canModify ? "" : "disabled"}>
          </td>
          <td class="px-4 py-3">${captionsBadge(s.captions_ok)}</td>
          <td class="px-4 py-3 whitespace-nowrap">${esc(fmtWhen(s.last_seen_at))}</td>
          <td class="px-4 py-3">${esc(s.last_error_reason || "—")}</td>
          <td class="px-4 py-3 text-right whitespace-nowrap">
            <button type="button" class="yt-test btn-outline-sm" data-id="${s.id}" ${canModify ? "" : "disabled"}>Test</button>
            <button type="button" class="yt-edit btn-outline-sm" data-id="${s.id}" ${canModify ? "" : "disabled"}>Edit</button>
            <button type="button" class="yt-delete btn-outline-danger text-xs px-2 py-1" data-id="${s.id}" ${canModify ? "" : "disabled"}>Delete</button>
          </td>
        </tr>`;
      })
      .join("");
  } catch (err) {
    body.innerHTML = `<tr><td colspan="10" class="px-4 py-4 text-theme-error-text">${esc(String(err))}</td></tr>`;
  }
}

async function loadRss(): Promise<void> {
  const body = document.getElementById("rss-table-body");
  if (!body) return;
  try {
    const data = await api<{ feeds: RssFeed[] }>("/api/admin/sources/rss");
    const rows = data.feeds || [];
    if (!rows.length) {
      body.innerHTML =
        '<tr><td colspan="7" class="px-4 py-4 text-center text-text-secondary">No RSS feeds.</td></tr>';
      return;
    }
    body.innerHTML = rows
      .map(
        (f) => `<tr class="border-b border-border">
          <td class="px-4 py-3 text-text-primary">${esc(f.name)}</td>
          <td class="px-4 py-3 max-w-xs truncate" title="${esc(f.url)}">${esc(f.url)}</td>
          <td class="px-4 py-3">${esc(f.category || "—")}</td>
          <td class="px-4 py-3">
            <input type="checkbox" class="rss-enabled" data-id="${f.id}" ${f.enabled ? "checked" : ""} ${canModify ? "" : "disabled"}>
          </td>
          <td class="px-4 py-3 whitespace-nowrap">${esc(fmtWhen(f.last_fetched_at))}</td>
          <td class="px-4 py-3">${esc(f.last_error || "—")}</td>
          <td class="px-4 py-3 text-right">
            <button type="button" class="rss-delete btn-outline-danger text-xs px-2 py-1" data-id="${f.id}" ${canModify ? "" : "disabled"}>Delete</button>
          </td>
        </tr>`
      )
      .join("");
  } catch (err) {
    body.innerHTML = `<tr><td colspan="7" class="px-4 py-4 text-theme-error-text">${esc(String(err))}</td></tr>`;
  }
}

const modals = new Map<string, Modal>();

function showModal(id: string, show: boolean): void {
  const el = document.getElementById(id);
  if (!el) return;

  let modal = modals.get(id);
  if (!modal) {
    modal = new Modal(el);
    modals.set(id, modal);
  }

  if (show) {
    modal.show();
  } else {
    modal.hide();
  }
}

function confirmDelete(message: string): Promise<boolean> {
  const show = (window as unknown as {
    showConfirmModal?: (opts: {
      title?: string;
      message: string;
      confirmLabel?: string;
      cancelLabel?: string;
      danger?: boolean;
      onConfirm?: () => void | Promise<void>;
    }) => void;
  }).showConfirmModal;
  if (!show) {
    return Promise.resolve(window.confirm(message));
  }
  return new Promise((resolve) => {
    show({
      title: "Confirm delete",
      message,
      confirmLabel: "Delete",
      danger: true,
      onConfirm: () => resolve(true),
    });
  });
}

function wireTabs(): void {
  document.querySelectorAll<HTMLButtonElement>(".sources-tab").forEach((btn) => {
    btn.addEventListener("click", () => setTab((btn.dataset.tab as TabName) || "youtube"));
  });
}

function wireRss(): void {
  document.getElementById("rss-add-btn")?.addEventListener("click", async () => {
    const name = (document.getElementById("rss-add-name") as HTMLInputElement)?.value.trim();
    const url = (document.getElementById("rss-add-url") as HTMLInputElement)?.value.trim();
    const category = (document.getElementById("rss-add-category") as HTMLInputElement)?.value.trim();
    if (!name || !url) {
      showToast("Name and URL required", "error");
      return;
    }
    try {
      await api("/api/admin/sources/rss", {
        method: "POST",
        body: JSON.stringify({ name, url, category, enabled: true }),
      });
      showToast("Feed added", "success");
      (document.getElementById("rss-add-name") as HTMLInputElement).value = "";
      (document.getElementById("rss-add-url") as HTMLInputElement).value = "";
      await loadRss();
    } catch (err) {
      showToast(String(err), "error");
    }
  });

  document.getElementById("rss-table-body")?.addEventListener("change", async (ev) => {
    const t = ev.target as HTMLInputElement;
    if (!t.classList.contains("rss-enabled")) return;
    try {
      await api(`/api/admin/sources/rss/${t.dataset.id}`, {
        method: "PATCH",
        body: JSON.stringify({ enabled: t.checked }),
      });
      showToast(t.checked ? "Feed enabled" : "Feed disabled", "success");
    } catch (err) {
      showToast(String(err), "error");
      t.checked = !t.checked;
    }
  });

  document.getElementById("rss-table-body")?.addEventListener("click", async (ev) => {
    const btn = (ev.target as HTMLElement).closest(".rss-delete") as HTMLButtonElement | null;
    if (!btn) return;
    const ok = await confirmDelete("Delete this RSS feed?");
    if (!ok) return;
    try {
      await api(`/api/admin/sources/rss/${btn.dataset.id}`, { method: "DELETE" });
      showToast("Feed deleted", "success");
      await loadRss();
    } catch (err) {
      showToast(String(err), "error");
    }
  });
}

let ytCache: YoutubeSource[] = [];

async function refreshYtCache(): Promise<void> {
  const data = await api<{ sources: YoutubeSource[] }>("/api/admin/sources/youtube");
  ytCache = data.sources || [];
}

function openYtEdit(source?: YoutubeSource): void {
  (document.getElementById("yt-edit-title") as HTMLElement).textContent = source
    ? "Edit YouTube source"
    : "Add YouTube source";
  (document.getElementById("yt-edit-id") as HTMLInputElement).value = source ? String(source.id) : "";
  (document.getElementById("yt-edit-label") as HTMLInputElement).value = source?.label || "";
  (document.getElementById("yt-edit-handle") as HTMLInputElement).value = source?.handle || "";
  (document.getElementById("yt-edit-kind") as HTMLSelectElement).value = source?.kind || "channel";
  (document.getElementById("yt-edit-query") as HTMLInputElement).value = source?.query_text || "";
  (document.getElementById("yt-edit-mechanism") as HTMLSelectElement).value =
    source?.alpha_mechanism || "";
  (document.getElementById("yt-edit-tickers") as HTMLInputElement).value = (
    source?.expected_tickers || []
  ).join(", ");
  (document.getElementById("yt-edit-notes") as HTMLTextAreaElement).value = source?.notes || "";
  showModal("yt-edit-modal", true);
}

function wireYoutube(): void {
  document.getElementById("yt-add-btn")?.addEventListener("click", () => openYtEdit());
  document.getElementById("yt-edit-cancel")?.addEventListener("click", () =>
    showModal("yt-edit-modal", false)
  );
  document.getElementById("yt-edit-save")?.addEventListener("click", async () => {
    const id = (document.getElementById("yt-edit-id") as HTMLInputElement).value;
    const body = {
      label: (document.getElementById("yt-edit-label") as HTMLInputElement).value.trim(),
      handle: (document.getElementById("yt-edit-handle") as HTMLInputElement).value.trim(),
      kind: (document.getElementById("yt-edit-kind") as HTMLSelectElement).value,
      query_text: (document.getElementById("yt-edit-query") as HTMLInputElement).value.trim(),
      alpha_mechanism: (document.getElementById("yt-edit-mechanism") as HTMLSelectElement).value,
      expected_tickers: (document.getElementById("yt-edit-tickers") as HTMLInputElement).value,
      notes: (document.getElementById("yt-edit-notes") as HTMLTextAreaElement).value.trim(),
    };
    try {
      if (id) {
        await api(`/api/admin/sources/youtube/${id}`, { method: "PATCH", body: JSON.stringify(body) });
      } else {
        await api("/api/admin/sources/youtube", { method: "POST", body: JSON.stringify(body) });
      }
      showModal("yt-edit-modal", false);
      showToast("Saved", "success");
      await loadYoutube();
      await refreshYtCache();
    } catch (err) {
      showToast(String(err), "error");
    }
  });

  document.getElementById("yt-table-body")?.addEventListener("change", async (ev) => {
    const t = ev.target as HTMLInputElement;
    if (!t.classList.contains("yt-enabled")) return;
    try {
      await api(`/api/admin/sources/youtube/${t.dataset.id}`, {
        method: "PATCH",
        body: JSON.stringify({ enabled: t.checked }),
      });
      showToast(t.checked ? "Enabled" : "Disabled", "success");
    } catch (err) {
      showToast(String(err), "error");
      t.checked = !t.checked;
    }
  });

  document.getElementById("yt-table-body")?.addEventListener("click", async (ev) => {
    const target = ev.target as HTMLElement;
    const testBtn = target.closest(".yt-test") as HTMLButtonElement | null;
    const editBtn = target.closest(".yt-edit") as HTMLButtonElement | null;
    const delBtn = target.closest(".yt-delete") as HTMLButtonElement | null;

    if (editBtn) {
      const src = ytCache.find((s) => String(s.id) === editBtn.dataset.id);
      openYtEdit(src);
      return;
    }
    if (delBtn) {
      const ok = await confirmDelete("Delete this YouTube source?");
      if (!ok) return;
      try {
        await api(`/api/admin/sources/youtube/${delBtn.dataset.id}`, { method: "DELETE" });
        showToast("Deleted", "success");
        await loadYoutube();
        await refreshYtCache();
      } catch (err) {
        showToast(String(err), "error");
      }
      return;
    }
    if (testBtn) {
      (document.getElementById("yt-test-source-id") as HTMLInputElement).value =
        testBtn.dataset.id || "";
      (document.getElementById("yt-test-url") as HTMLInputElement).value = "";
      showModal("yt-test-modal", true);
    }
  });

  document.getElementById("yt-test-cancel")?.addEventListener("click", () =>
    showModal("yt-test-modal", false)
  );
  document.getElementById("yt-test-run")?.addEventListener("click", async () => {
    const id = (document.getElementById("yt-test-source-id") as HTMLInputElement).value;
    const url_or_id = (document.getElementById("yt-test-url") as HTMLInputElement).value.trim();
    if (!url_or_id) {
      showToast("Video URL or id required", "error");
      return;
    }
    try {
      const result = await api<{
        ok: boolean;
        reason?: string;
        message?: string;
        char_count?: number;
        language?: string;
        caption_kind?: string;
      }>("/api/admin/sources/youtube/test", {
        method: "POST",
        body: JSON.stringify({ id: Number(id), url_or_id }),
      });
      showModal("yt-test-modal", false);
      if (result.ok) {
        showToast(
          `Captions OK (${result.language}, ${result.caption_kind}, ${result.char_count} chars)`,
          "success"
        );
      } else {
        showToast(`${result.reason}: ${result.message || "failed"}`, "error");
      }
      await loadYoutube();
      await refreshYtCache();
    } catch (err) {
      showToast(String(err), "error");
    }
  });
}

function wireBulk(): void {
  const commitBtn = document.getElementById("yt-bulk-commit-btn") as HTMLButtonElement | null;
  document.getElementById("yt-bulk-btn")?.addEventListener("click", () => {
    (document.getElementById("yt-bulk-payload") as HTMLTextAreaElement).value = "";
    document.getElementById("yt-bulk-preview-body")!.innerHTML = "";
    document.getElementById("yt-bulk-summary")!.textContent = "";
    if (commitBtn) commitBtn.disabled = true;
    showModal("yt-bulk-modal", true);
  });
  document.getElementById("yt-bulk-close")?.addEventListener("click", () =>
    showModal("yt-bulk-modal", false)
  );

  document.getElementById("yt-bulk-preview-btn")?.addEventListener("click", async () => {
    const format =
      (document.querySelector('input[name="bulk-format"]:checked') as HTMLInputElement)?.value ||
      "json";
    const payload = (document.getElementById("yt-bulk-payload") as HTMLTextAreaElement).value;
    try {
      const data = await api<{
        rows: BulkRow[];
        summary: Record<string, number>;
      }>("/api/admin/sources/youtube/bulk-preview", {
        method: "POST",
        body: JSON.stringify({ format, payload }),
      });
      const summary = data.summary || {};
      document.getElementById("yt-bulk-summary")!.textContent =
        `new=${summary.new || 0} duplicate=${summary.duplicate || 0} invalid=${summary.invalid || 0}`;
      document.getElementById("yt-bulk-preview-body")!.innerHTML = (data.rows || [])
        .map((r) => {
          const color =
            r.status === "new"
              ? "text-theme-success-text"
              : r.status === "duplicate"
                ? "text-text-tertiary"
                : "text-theme-error-text";
          const note = [...(r.warnings || []), ...(r.errors || [])].join("; ");
          return `<tr class="border-b border-border">
            <td class="px-3 py-2 ${color}">${esc(r.status)}</td>
            <td class="px-3 py-2">${esc(r.label)}</td>
            <td class="px-3 py-2">${esc(r.handle || "")}</td>
            <td class="px-3 py-2 text-xs">${esc(note)}</td>
          </tr>`;
        })
        .join("");
      if (commitBtn) commitBtn.disabled = !(summary.new > 0);
    } catch (err) {
      showToast(String(err), "error");
    }
  });

  commitBtn?.addEventListener("click", async () => {
    const format =
      (document.querySelector('input[name="bulk-format"]:checked') as HTMLInputElement)?.value ||
      "json";
    const payload = (document.getElementById("yt-bulk-payload") as HTMLTextAreaElement).value;
    try {
      const data = await api<{ inserted: number; skipped: number; errors: string[] }>(
        "/api/admin/sources/youtube/bulk-commit",
        { method: "POST", body: JSON.stringify({ format, payload }) }
      );
      showToast(`Inserted ${data.inserted}, skipped ${data.skipped}`, "success");
      if (data.errors?.length) showToast(data.errors[0], "error");
      showModal("yt-bulk-modal", false);
      await loadYoutube();
      await refreshYtCache();
    } catch (err) {
      showToast(String(err), "error");
    }
  });
}

async function init(): Promise<void> {
  if (!page) return;
  wireTabs();
  wireRss();
  wireYoutube();
  wireBulk();
  setTab("youtube");
  await Promise.all([loadYoutube(), loadRss(), refreshYtCache().catch(() => undefined)]);
}

void init();
