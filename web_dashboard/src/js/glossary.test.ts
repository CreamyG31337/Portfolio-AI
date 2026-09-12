/** @vitest-environment jsdom */
// The client glossary reads #glossary-data (embedded by base.html) and caches
// it on first use, so the script tag below must exist before any helpTip()
// call in this file. Escaping here is the security contract: term text is
// authored in glossary.py today, but anything stored must never reach the DOM
// as markup.
import { beforeAll, describe, expect, it, vi } from "vitest";
import { helpTip, initTooltips, termText } from "./glossary.js";

const GLOSSARY = {
  TENSION: {
    label: "Tension",
    short: "An AI review disagrees with <your> reasoning.",
    source: 'Advisory review "only"',
  },
  thesis_due: { label: "Due for review", short: "Scheduled for another look." },
};

beforeAll(() => {
  const script = document.createElement("script");
  script.id = "glossary-data";
  script.type = "application/json";
  script.textContent = JSON.stringify(GLOSSARY);
  document.body.appendChild(script);
});

describe("helpTip", () => {
  it("returns '' for an unknown key (a typo shows nothing)", () => {
    expect(helpTip("NOT_A_TERM")).toBe("");
  });

  it("renders a tap-friendly (click-trigger) button plus tooltip div", () => {
    const html = helpTip("thesis_due");
    expect(html).toContain('data-tooltip-trigger="click"');
    expect(html).toMatch(/data-tooltip-target="[^"]+"/);
    expect(html).toContain('role="tooltip"');
    // the button is an inline-flex circle — big enough for a thumb with p-1
    expect(helpTip("thesis_due", "p-1")).toContain("p-1");
  });

  it("escapes label, short and source text", () => {
    const html = helpTip("TENSION");
    expect(html).toContain("&lt;your&gt;");
    expect(html).toContain("&quot;only&quot;");
    expect(html).not.toContain("<your>");
    expect(html).not.toContain('"only"');
  });

  it("gives each tip a unique target id", () => {
    const a = helpTip("thesis_due");
    const b = helpTip("thesis_due");
    const idA = a.match(/data-tooltip-target="([^"]+)"/)?.[1];
    const idB = b.match(/data-tooltip-target="([^"]+)"/)?.[1];
    expect(idA).toBeTruthy();
    expect(idA).not.toBe(idB);
  });
});

describe("termText", () => {
  it("appends the source when present", () => {
    expect(termText("TENSION")).toBe(
      'An AI review disagrees with <your> reasoning. (Advisory review "only")'
    );
  });

  it("is just the short text when there is no source", () => {
    expect(termText("thesis_due")).toBe("Scheduled for another look.");
  });

  it("returns '' for an unknown key", () => {
    expect(termText("NOT_A_TERM")).toBe("");
  });
});

describe("initTooltips", () => {
  it("prefers window.initTooltips when Flowbite exposes it", () => {
    const init = vi.fn();
    (window as unknown as { initTooltips?: () => void }).initTooltips = init;
    initTooltips();
    expect(init).toHaveBeenCalledOnce();
  });

  it("falls back to initFlowbite", () => {
    const w = window as unknown as { initTooltips?: () => void; initFlowbite?: () => void };
    delete w.initTooltips;
    const initFlowbite = vi.fn();
    w.initFlowbite = initFlowbite;
    initTooltips();
    expect(initFlowbite).toHaveBeenCalledOnce();
  });

  it("does nothing when neither global exists", () => {
    const w = window as unknown as { initTooltips?: () => void; initFlowbite?: () => void };
    delete w.initTooltips;
    delete w.initFlowbite;
    expect(() => initTooltips()).not.toThrow();
  });
});
