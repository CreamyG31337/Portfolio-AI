/**
 * @vitest-environment jsdom
 */

import { beforeEach, describe, expect, it } from "vitest";
import { renderGrokChatterSection } from "./today";

function render(briefs: Parameters<typeof renderGrokChatterSection>[0]): HTMLElement {
    const host = document.createElement("div");
    host.innerHTML = renderGrokChatterSection(briefs);
    return host;
}

describe("renderGrokChatterSection", () => {
    beforeEach(() => {
        document.body.innerHTML = "";
    });

    it("renders nothing but a quiet empty state when there are no briefs", () => {
        const host = render([]);
        expect(host.textContent).toContain("No notable X chatter yet today");
        expect(host.querySelector("a[href='/grok/admin']")).not.toBeNull();
    });

    it("shows ticker, fund, sweep date, theme chips, post count and summary", () => {
        const host = render([
            {
                ticker: "CMI",
                fund: "Project Chimera",
                sweep_date: "2026-09-12",
                notable: true,
                summary: "X chatter over ~48h mixes thesis with activist criticism.",
                themes: ["Power Systems / gensets", "AI power backup"],
                post_count: 6,
                posts: [],
                status: "ingested",
                created_at: "2026-09-12T04:26:20+00:00",
            },
        ]);
        const item = host.querySelector("div") as HTMLElement;
        expect(item.textContent).toContain("CMI");
        expect(item.textContent).toContain("Project Chimera");
        expect(item.textContent).toContain("2026-09-12");
        expect(item.textContent).toContain("6 posts");
        expect(item.textContent).toContain("Power Systems / gensets");
        expect(item.textContent).toContain("X chatter over ~48h");
        expect(host.querySelector("a[href='/ticker?ticker=CMI']")).not.toBeNull();
    });

    it("renders post urls as new-tab links with noopener noreferrer", () => {
        const host = render([
            {
                ticker: "AAA",
                posts: [{ url: "https://x.com/user/status/123", summary: "Cites Power Systems Q2" }],
            },
        ]);
        const link = host.querySelector("a[target='_blank']") as HTMLAnchorElement;
        expect(link).not.toBeNull();
        expect(link.getAttribute("href")).toBe("https://x.com/user/status/123");
        expect(link.getAttribute("rel")).toBe("noopener noreferrer");
        expect(host.textContent).toContain("Cites Power Systems Q2");
    });

    it("never turns a non-http url into an href", () => {
        const host = render([
            { ticker: "AAA", posts: [{ url: "javascript:alert(1)" }] },
        ]);
        expect(host.querySelector("a[href^='javascript:']")).toBeNull();
        expect(host.querySelectorAll("a[target='_blank']").length).toBe(0);
        // Still visible as inert text, not swallowed.
        expect(host.textContent).toContain("javascript:alert(1)");
    });

    it("escapes every untrusted field — no live elements from X text", () => {
        const hostile = `<img src=x onerror=alert(1)><script>alert(2)</script>"'&`;
        const host = render([
            {
                ticker: `<b>AAA</b>`,
                fund: hostile,
                summary: hostile,
                themes: [hostile],
                posts: [{ url: "https://x.com/ok", summary: hostile }],
            },
        ]);
        expect(host.querySelector("img")).toBeNull();
        expect(host.querySelector("script")).toBeNull();
        expect(host.querySelector("b")).toBeNull();
        // The payload survives as text, not markup.
        expect(host.textContent).toContain("<img src=x onerror=alert(1)>");
        expect(host.textContent).toContain("<script>alert(2)</script>");
    });
});

// A stopped bot and a quiet market both arrive as zero briefs. Only the health
// payload can tell them apart, so these guard that it is actually surfaced.
describe("sweep staleness", () => {
  it("warns when the sweep has not run for several weekdays", () => {
    const host = document.createElement("div");
    host.innerHTML = renderGrokChatterSection([], {
      last_sweep: "2026-09-01",
      weekdays_stale: 9,
      stale: true,
      never_swept: false,
    });
    const text = host.textContent || "";
    expect(text).toContain("looks stopped");
    expect(text).toContain("2026-09-01");
    expect(text).toContain("9 weekdays");
    expect(text).toContain("credits");
  });

  it("says so when the bot has never filed anything", () => {
    const host = document.createElement("div");
    host.innerHTML = renderGrokChatterSection([], {
      last_sweep: null,
      weekdays_stale: 0,
      stale: false,
      never_swept: true,
    });
    expect(host.textContent || "").toContain("never filed");
  });

  it("stays silent on a normal quiet day, but still dates the section", () => {
    const host = document.createElement("div");
    host.innerHTML = renderGrokChatterSection([], {
      last_sweep: "2026-09-11",
      weekdays_stale: 1,
      stale: false,
      never_swept: false,
    });
    const text = host.textContent || "";
    expect(text).not.toContain("looks stopped");
    // The provenance date must come from the whole table, not the empty list.
    expect(text).toContain("updated 2026-09-11");
  });

  it("renders without a health payload at all", () => {
    expect(() => renderGrokChatterSection([])).not.toThrow();
  });
});
