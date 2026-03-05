/**
 * @vitest-environment jsdom
 */

import { beforeEach, describe, expect, it } from "vitest";
import { initPasswordToggles } from "./ui";

describe("initPasswordToggles", () => {
    beforeEach(() => {
        document.body.innerHTML = `
            <div class="relative">
                <input id="login-password" type="password" />
                <button type="button" data-toggle-password="login-password" aria-label="Show password">
                    <i class="fas fa-eye"></i>
                </button>
            </div>
        `;
    });

    it("toggles input type and icon classes", () => {
        initPasswordToggles();

        const input = document.getElementById("login-password") as HTMLInputElement;
        const button = document.querySelector("[data-toggle-password='login-password']") as HTMLElement;
        const icon = button.querySelector("i") as HTMLElement;

        button.click();
        expect(input.type).toBe("text");
        expect(button.getAttribute("aria-label")).toBe("Hide password");
        expect(icon.classList.contains("fa-eye-slash")).toBe(true);
        expect(icon.classList.contains("fa-eye")).toBe(false);

        button.click();
        expect(input.type).toBe("password");
        expect(button.getAttribute("aria-label")).toBe("Show password");
        expect(icon.classList.contains("fa-eye")).toBe(true);
        expect(icon.classList.contains("fa-eye-slash")).toBe(false);
    });

    it("does not attach duplicate click listeners when initialized twice", () => {
        initPasswordToggles();
        initPasswordToggles();

        const input = document.getElementById("login-password") as HTMLInputElement;
        const button = document.querySelector("[data-toggle-password='login-password']") as HTMLElement;

        button.click();
        expect(input.type).toBe("text");
    });
});
