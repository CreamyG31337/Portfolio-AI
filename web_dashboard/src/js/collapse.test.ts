/**
 * @vitest-environment jsdom
 */

import { beforeEach, describe, expect, it } from "vitest";
import { initCollapsesIn, setCollapsed } from "./collapse";

function buildCollapse(id: string): HTMLElement {
    const wrapper = document.createElement("div");
    wrapper.innerHTML = `
        <button type="button" data-collapse-toggle="${id}" aria-expanded="false" aria-controls="${id}">
            Toggle
            <svg data-accordion-icon class="w-3 h-3"></svg>
        </button>
        <div id="${id}" class="hidden">body</div>
    `;
    document.body.appendChild(wrapper);
    return wrapper;
}

describe("initCollapsesIn", () => {
    beforeEach(() => {
        document.body.innerHTML = "";
    });

    it("binds a subtree inserted after page load", () => {
        const wrapper = buildCollapse("panel-1");
        const trigger = wrapper.querySelector("button")!;
        const target = document.getElementById("panel-1")!;

        // Unbound: clicking does nothing (this is the bug being fixed).
        trigger.click();
        expect(target.classList.contains("hidden")).toBe(true);

        initCollapsesIn(wrapper);
        trigger.click();
        expect(target.classList.contains("hidden")).toBe(false);
        expect(trigger.getAttribute("aria-expanded")).toBe("true");
    });

    it("toggles closed again and syncs the accordion icon", () => {
        const wrapper = buildCollapse("panel-2");
        initCollapsesIn(wrapper);
        const trigger = wrapper.querySelector("button")!;
        const target = document.getElementById("panel-2")!;
        const icon = wrapper.querySelector("[data-accordion-icon]")!;

        trigger.click();
        expect(icon.classList.contains("rotate-180")).toBe(true);

        trigger.click();
        expect(target.classList.contains("hidden")).toBe(true);
        expect(trigger.getAttribute("aria-expanded")).toBe("false");
        expect(icon.classList.contains("rotate-180")).toBe(false);
    });

    it("does not double-bind when run twice over the same subtree", () => {
        const wrapper = buildCollapse("panel-3");
        initCollapsesIn(wrapper);
        initCollapsesIn(wrapper);

        const trigger = wrapper.querySelector("button")!;
        const target = document.getElementById("panel-3")!;

        // A second listener would toggle twice and leave it closed.
        trigger.click();
        expect(target.classList.contains("hidden")).toBe(false);
    });

    it("leaves collapses outside the given subtree alone", () => {
        const mine = buildCollapse("panel-mine");
        buildCollapse("panel-other");

        initCollapsesIn(mine);

        const otherTrigger = document.querySelector<HTMLElement>(
            '[data-collapse-toggle="panel-other"]'
        )!;
        otherTrigger.click();
        expect(document.getElementById("panel-other")!.classList.contains("hidden")).toBe(true);
    });

    it("ignores clicks originating on a link inside the trigger", () => {
        const wrapper = buildCollapse("panel-4");
        const trigger = wrapper.querySelector("button")!;
        const link = document.createElement("a");
        link.href = "https://example.com";
        trigger.appendChild(link);

        initCollapsesIn(wrapper);
        link.click();

        expect(document.getElementById("panel-4")!.classList.contains("hidden")).toBe(true);
    });

    it("setCollapsed syncs every trigger pointing at the target", () => {
        const wrapper = buildCollapse("panel-5");
        const extra = document.createElement("button");
        extra.setAttribute("data-collapse-toggle", "panel-5");
        extra.setAttribute("aria-expanded", "false");
        document.body.appendChild(extra);

        initCollapsesIn(wrapper);
        setCollapsed("panel-5", false);

        expect(document.getElementById("panel-5")!.classList.contains("hidden")).toBe(false);
        expect(wrapper.querySelector("button")!.getAttribute("aria-expanded")).toBe("true");
        expect(extra.getAttribute("aria-expanded")).toBe("true");
    });
});
