/**
 * @vitest-environment jsdom
 */

import { describe, expect, it } from "vitest";
import { formatHolderLine, formatHolderReport, type HolderRow } from "./chimera_holders";

const alex: HolderRow = {
    name: "Alex",
    net_contribution: 5000,
    current_value: 6240,
    gain_loss: 1240,
    gain_loss_pct: 24.8,
    ownership_pct: 12.4,
    day_change: 18,
    day_change_pct: 0.4,
};

describe("formatHolderLine", () => {
    it("states what they put in, what it is worth, and the gain", () => {
        const line = formatHolderLine(alex, "CAD");
        expect(line).toContain("Alex");
        expect(line).toContain("put in");
        expect(line).toContain("now worth");
        expect(line).toContain("+24.8%");
    });

    it("builds a multi-person note for a text", () => {
        const report = formatHolderReport([alex], "CAD", "Project Chimera");
        expect(report.startsWith("Project Chimera")).toBe(true);
        expect(report).toContain("Alex —");
    });
});
