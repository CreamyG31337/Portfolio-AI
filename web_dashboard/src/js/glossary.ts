/**
 * Client-side half of the glossary. Terms are defined once in
 * web_dashboard/glossary.py and embedded into every page by base.html as
 * <script id="glossary-data" type="application/json">, so TypeScript-rendered
 * badges explain themselves exactly like the server-rendered ones.
 *
 *   import { helpTip } from './glossary';
 *   html += `Tension ${helpTip('TENSION')}`;
 *
 * Flowbite initialises tooltips by scanning the DOM, so call initTooltips()
 * after injecting markup that contains help tips.
 */

interface GlossaryEntry {
    label: string;
    short: string;
    source?: string;
}

type Glossary = Record<string, GlossaryEntry>;

let cached: Glossary | null = null;
let tipSeq = 0;

export function getGlossary(): Glossary {
    if (cached) return cached;
    try {
        const node = document.getElementById("glossary-data");
        cached = node?.textContent ? (JSON.parse(node.textContent) as Glossary) : {};
    } catch {
        cached = {};
    }
    return cached;
}

const HTML_ESCAPES: Record<string, string> = {
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
};

function esc(value: unknown): string {
    return String(value ?? "").replace(/[&<>"']/g, (ch) => HTML_ESCAPES[ch]);
}

/**
 * Markup for a "?" that explains `term`. Returns "" for an unknown key, so a
 * typo shows nothing rather than an empty bubble.
 */
export function helpTip(term: string, extraClass = ""): string {
    const entry = getGlossary()[term];
    if (!entry) return "";
    const id = `tip-js-${term.replace(/[^A-Za-z0-9_-]/g, "")}-${++tipSeq}`;
    const source = entry.source
        ? `<span class="block mt-1 opacity-75">Where this comes from: ${esc(entry.source)}</span>`
        : "";
    // trigger=click, not hover: phones have no hover, and a definition nobody
    // can reach on mobile is not a definition.
    // stopPropagation: tips sit inside <summary> and clickable rows, where a
    // click would otherwise also toggle or navigate.
    return `<button type="button" data-tooltip-target="${id}" data-tooltip-trigger="click"
        onclick="event.stopPropagation()"
        class="inline-flex items-center justify-center text-text-secondary hover:text-accent focus:outline-hidden focus:ring-2 focus:ring-accent rounded-full align-middle ${esc(extraClass)}"
        aria-label="What does ${esc(entry.label)} mean?"><i class="fas fa-circle-question text-xs" aria-hidden="true"></i></button>
    <div id="${id}" role="tooltip"
        class="absolute z-10 invisible inline-block px-3 py-2 text-xs font-medium text-white bg-gray-900 rounded-lg shadow-xs opacity-0 tooltip dark:bg-gray-700 max-w-xs">
        <span class="block font-semibold">${esc(entry.label)}</span>
        <span class="block mt-0.5">${esc(entry.short)}</span>
        ${source}
        <div class="tooltip-arrow" data-popper-arrow></div>
    </div>`;
}

/** Plain text for a term, for title attributes and aria-labels. */
export function termText(term: string): string {
    const entry = getGlossary()[term];
    if (!entry) return "";
    return entry.source ? `${entry.short} (${entry.source})` : entry.short;
}

/** Re-scan the DOM so Flowbite wires up tips added after page load. */
export function initTooltips(): void {
    const flowbite = (window as unknown as { initTooltips?: () => void; initFlowbite?: () => void });
    if (typeof flowbite.initTooltips === "function") {
        flowbite.initTooltips();
    } else if (typeof flowbite.initFlowbite === "function") {
        flowbite.initFlowbite();
    }
}
