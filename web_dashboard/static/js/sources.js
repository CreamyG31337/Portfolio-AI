import { getCsrfHeaders } from "./csrf.js";
import { showToast } from "./toast.js";
const page = document.getElementById("sources-page");
const canModify = page?.dataset.canModify === "true";
function esc(text) {
    const d = document.createElement("div");
    d.textContent = text ?? "";
    return d.innerHTML;
}
async function api(url, init) {
    const headers = {
        "Content-Type": "application/json",
        ...getCsrfHeaders(),
        ...init?.headers,
    };
    const res = await fetch(url, { ...init, headers, credentials: "same-origin" });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
        throw new Error(data.error || `HTTP ${res.status}`);
    }
    return data;
}
function setTab(tab) {
    document.querySelectorAll(".sources-tab").forEach((btn) => {
        const active = btn.dataset.tab === tab;
        btn.classList.toggle("border-accent", active);
        btn.classList.toggle("text-accent", active);
        btn.classList.toggle("border-transparent", !active);
        btn.classList.toggle("text-text-secondary", !active);
    });
    document.getElementById("panel-youtube")?.classList.toggle("hidden", tab !== "youtube");
    document.getElementById("panel-rss")?.classList.toggle("hidden", tab !== "rss");
}
function captionsBadge(ok) {
    if (ok === true)
        return '<span class="text-theme-success-text">✓</span>';
    if (ok === false)
        return '<span class="text-theme-error-text">✗</span>';
    return '<span class="text-text-tertiary">—</span>';
}
function fmtWhen(value) {
    if (!value)
        return "—";
    try {
        return new Date(value).toLocaleString();
    }
    catch {
        return value;
    }
}
async function loadYoutube() {
    const body = document.getElementById("yt-table-body");
    if (!body)
        return;
    try {
        const data = await api("/api/admin/sources/youtube");
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
    }
    catch (err) {
        body.innerHTML = `<tr><td colspan="10" class="px-4 py-4 text-theme-error-text">${esc(String(err))}</td></tr>`;
    }
}
async function loadRss() {
    const body = document.getElementById("rss-table-body");
    if (!body)
        return;
    try {
        const data = await api("/api/admin/sources/rss");
        const rows = data.feeds || [];
        if (!rows.length) {
            body.innerHTML =
                '<tr><td colspan="7" class="px-4 py-4 text-center text-text-secondary">No RSS feeds.</td></tr>';
            return;
        }
        body.innerHTML = rows
            .map((f) => `<tr class="border-b border-border">
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
        </tr>`)
            .join("");
    }
    catch (err) {
        body.innerHTML = `<tr><td colspan="7" class="px-4 py-4 text-theme-error-text">${esc(String(err))}</td></tr>`;
    }
}
// Drive the modals through Flowbite's own data-attribute triggers so they stay
// in Flowbite's registry (required for data-modal-hide). Do not
// `import { Modal } from "flowbite"` — tsc emits a bare specifier and the
// browser never runs this module.
function showModal(id, show) {
    if (show) {
        const trigger = document.getElementById(`${id}-trigger`);
        if (trigger) {
            trigger.click();
        }
        else {
            console.error(`[Sources] Modal trigger not found for ${id}`);
        }
        return;
    }
    document.querySelector(`[data-modal-hide="${id}"]`)?.click();
}
function confirmDelete(message) {
    const show = window.showConfirmModal;
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
function wireTabs() {
    document.querySelectorAll(".sources-tab").forEach((btn) => {
        btn.addEventListener("click", () => setTab(btn.dataset.tab || "youtube"));
    });
}
function wireRss() {
    document.getElementById("rss-add-btn")?.addEventListener("click", async () => {
        const name = document.getElementById("rss-add-name")?.value.trim();
        const url = document.getElementById("rss-add-url")?.value.trim();
        const category = document.getElementById("rss-add-category")?.value.trim();
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
            document.getElementById("rss-add-name").value = "";
            document.getElementById("rss-add-url").value = "";
            await loadRss();
        }
        catch (err) {
            showToast(String(err), "error");
        }
    });
    document.getElementById("rss-table-body")?.addEventListener("change", async (ev) => {
        const t = ev.target;
        if (!t.classList.contains("rss-enabled"))
            return;
        try {
            await api(`/api/admin/sources/rss/${t.dataset.id}`, {
                method: "PATCH",
                body: JSON.stringify({ enabled: t.checked }),
            });
            showToast(t.checked ? "Feed enabled" : "Feed disabled", "success");
        }
        catch (err) {
            showToast(String(err), "error");
            t.checked = !t.checked;
        }
    });
    document.getElementById("rss-table-body")?.addEventListener("click", async (ev) => {
        const btn = ev.target.closest(".rss-delete");
        if (!btn)
            return;
        const ok = await confirmDelete("Delete this RSS feed?");
        if (!ok)
            return;
        try {
            await api(`/api/admin/sources/rss/${btn.dataset.id}`, { method: "DELETE" });
            showToast("Feed deleted", "success");
            await loadRss();
        }
        catch (err) {
            showToast(String(err), "error");
        }
    });
}
let ytCache = [];
async function refreshYtCache() {
    const data = await api("/api/admin/sources/youtube");
    ytCache = data.sources || [];
}
function openYtEdit(source) {
    document.getElementById("yt-edit-title").textContent = source
        ? "Edit YouTube source"
        : "Add YouTube source";
    document.getElementById("yt-edit-id").value = source ? String(source.id) : "";
    document.getElementById("yt-edit-label").value = source?.label || "";
    document.getElementById("yt-edit-handle").value = source?.handle || "";
    document.getElementById("yt-edit-kind").value = source?.kind || "channel";
    document.getElementById("yt-edit-query").value = source?.query_text || "";
    document.getElementById("yt-edit-mechanism").value =
        source?.alpha_mechanism || "";
    document.getElementById("yt-edit-tickers").value = (source?.expected_tickers || []).join(", ");
    document.getElementById("yt-edit-notes").value = source?.notes || "";
    showModal("yt-edit-modal", true);
}
function wireYoutube() {
    document.getElementById("yt-add-btn")?.addEventListener("click", () => openYtEdit());
    // Cancel/close buttons carry data-modal-hide; Flowbite closes them natively.
    document.getElementById("yt-edit-save")?.addEventListener("click", async () => {
        const id = document.getElementById("yt-edit-id").value;
        const body = {
            label: document.getElementById("yt-edit-label").value.trim(),
            handle: document.getElementById("yt-edit-handle").value.trim(),
            kind: document.getElementById("yt-edit-kind").value,
            query_text: document.getElementById("yt-edit-query").value.trim(),
            alpha_mechanism: document.getElementById("yt-edit-mechanism").value,
            expected_tickers: document.getElementById("yt-edit-tickers").value,
            notes: document.getElementById("yt-edit-notes").value.trim(),
        };
        try {
            if (id) {
                await api(`/api/admin/sources/youtube/${id}`, { method: "PATCH", body: JSON.stringify(body) });
            }
            else {
                await api("/api/admin/sources/youtube", { method: "POST", body: JSON.stringify(body) });
            }
            showModal("yt-edit-modal", false);
            showToast("Saved", "success");
            await loadYoutube();
            await refreshYtCache();
        }
        catch (err) {
            showToast(String(err), "error");
        }
    });
    document.getElementById("yt-table-body")?.addEventListener("change", async (ev) => {
        const t = ev.target;
        if (!t.classList.contains("yt-enabled"))
            return;
        try {
            await api(`/api/admin/sources/youtube/${t.dataset.id}`, {
                method: "PATCH",
                body: JSON.stringify({ enabled: t.checked }),
            });
            showToast(t.checked ? "Enabled" : "Disabled", "success");
        }
        catch (err) {
            showToast(String(err), "error");
            t.checked = !t.checked;
        }
    });
    document.getElementById("yt-table-body")?.addEventListener("click", async (ev) => {
        const target = ev.target;
        const testBtn = target.closest(".yt-test");
        const editBtn = target.closest(".yt-edit");
        const delBtn = target.closest(".yt-delete");
        if (editBtn) {
            const src = ytCache.find((s) => String(s.id) === editBtn.dataset.id);
            openYtEdit(src);
            return;
        }
        if (delBtn) {
            const ok = await confirmDelete("Delete this YouTube source?");
            if (!ok)
                return;
            try {
                await api(`/api/admin/sources/youtube/${delBtn.dataset.id}`, { method: "DELETE" });
                showToast("Deleted", "success");
                await loadYoutube();
                await refreshYtCache();
            }
            catch (err) {
                showToast(String(err), "error");
            }
            return;
        }
        if (testBtn) {
            document.getElementById("yt-test-source-id").value =
                testBtn.dataset.id || "";
            document.getElementById("yt-test-url").value = "";
            showModal("yt-test-modal", true);
        }
    });
    document.getElementById("yt-test-run")?.addEventListener("click", async () => {
        const id = document.getElementById("yt-test-source-id").value;
        const url_or_id = document.getElementById("yt-test-url").value.trim();
        if (!url_or_id) {
            showToast("Video URL or id required", "error");
            return;
        }
        try {
            const result = await api("/api/admin/sources/youtube/test", {
                method: "POST",
                body: JSON.stringify({ id: Number(id), url_or_id }),
            });
            showModal("yt-test-modal", false);
            if (result.ok) {
                showToast(`Captions OK (${result.language}, ${result.caption_kind}, ${result.char_count} chars)`, "success");
            }
            else {
                showToast(`${result.reason}: ${result.message || "failed"}`, "error");
            }
            await loadYoutube();
            await refreshYtCache();
        }
        catch (err) {
            showToast(String(err), "error");
        }
    });
}
function wireBulk() {
    const commitBtn = document.getElementById("yt-bulk-commit-btn");
    document.getElementById("yt-bulk-btn")?.addEventListener("click", () => {
        document.getElementById("yt-bulk-payload").value = "";
        document.getElementById("yt-bulk-preview-body").innerHTML = "";
        document.getElementById("yt-bulk-summary").textContent = "";
        if (commitBtn)
            commitBtn.disabled = true;
        showModal("yt-bulk-modal", true);
    });
    document.getElementById("yt-bulk-preview-btn")?.addEventListener("click", async () => {
        const format = document.querySelector('input[name="bulk-format"]:checked')?.value ||
            "json";
        const payload = document.getElementById("yt-bulk-payload").value;
        try {
            const data = await api("/api/admin/sources/youtube/bulk-preview", {
                method: "POST",
                body: JSON.stringify({ format, payload }),
            });
            const summary = data.summary || {};
            document.getElementById("yt-bulk-summary").textContent =
                `new=${summary.new || 0} duplicate=${summary.duplicate || 0} invalid=${summary.invalid || 0}`;
            document.getElementById("yt-bulk-preview-body").innerHTML = (data.rows || [])
                .map((r) => {
                const color = r.status === "new"
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
            if (commitBtn)
                commitBtn.disabled = !(summary.new > 0);
        }
        catch (err) {
            showToast(String(err), "error");
        }
    });
    commitBtn?.addEventListener("click", async () => {
        const format = document.querySelector('input[name="bulk-format"]:checked')?.value ||
            "json";
        const payload = document.getElementById("yt-bulk-payload").value;
        try {
            const data = await api("/api/admin/sources/youtube/bulk-commit", { method: "POST", body: JSON.stringify({ format, payload }) });
            showToast(`Inserted ${data.inserted}, skipped ${data.skipped}`, "success");
            if (data.errors?.length)
                showToast(data.errors[0], "error");
            showModal("yt-bulk-modal", false);
            await loadYoutube();
            await refreshYtCache();
        }
        catch (err) {
            showToast(String(err), "error");
        }
    });
}
async function init() {
    if (!page)
        return;
    wireTabs();
    wireRss();
    wireYoutube();
    wireBulk();
    setTab("youtube");
    await Promise.all([loadYoutube(), loadRss(), refreshYtCache().catch(() => undefined)]);
}
void init();
//# sourceMappingURL=sources.js.map