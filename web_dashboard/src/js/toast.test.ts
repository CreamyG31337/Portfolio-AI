/**
 * @vitest-environment jsdom
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { showToast } from "./toast";

describe("showToast", () => {
    beforeEach(() => {
        vi.useFakeTimers();
        document.body.innerHTML = "";
    });

    afterEach(() => {
        vi.useRealTimers();
    });

    it("creates a single shared container and appends a toast", () => {
        showToast("Saved", "success");
        showToast("Oops", "error");

        const containers = document.querySelectorAll("#toast-container");
        expect(containers.length).toBe(1);
        expect(containers[0].childElementCount).toBe(2);
    });

    it("escapes HTML in the message", () => {
        showToast("<img src=x onerror=alert(1)>");

        const container = document.getElementById("toast-container") as HTMLElement;
        // The payload must be rendered as text, not as a live <img> element.
        expect(container.querySelector("img")).toBeNull();
        expect(container.textContent).toContain("<img src=x onerror=alert(1)>");
    });

    it("applies the type-specific border and role", () => {
        showToast("Heads up", "warning");
        const toast = document.querySelector("#toast-container > div") as HTMLElement;
        expect(toast.className).toContain("border-theme-warning-text");
        expect(toast.getAttribute("role")).toBe("status");

        document.body.innerHTML = "";
        showToast("Broke", "error");
        const errToast = document.querySelector("#toast-container > div") as HTMLElement;
        expect(errToast.getAttribute("role")).toBe("alert");
    });

    it("removes the toast (and empty container) after auto-dismiss", () => {
        showToast("Bye");
        expect(document.getElementById("toast-container")).not.toBeNull();

        // Auto-dismiss (4s) then fade-out removal (300ms).
        vi.advanceTimersByTime(4000 + 300);
        expect(document.getElementById("toast-container")).toBeNull();
    });
});
