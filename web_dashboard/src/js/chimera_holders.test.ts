/**
 * @vitest-environment jsdom
 */

import { describe, expect, it } from "vitest";
import { formatHolderLine, formatHolderReport, groupHolders, type HolderRow } from "./chimera_holders";

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

const sam: HolderRow = { ...alex, name: "Sam", net_contribution: 1000, current_value: 900, gain_loss: -100, gain_loss_pct: -10, ownership_pct: 2, day_change: 3 };
const kim: HolderRow = { ...alex, name: "Kim", net_contribution: 3000, current_value: 3300, gain_loss: 300, gain_loss_pct: 10, ownership_pct: 6, day_change: 7 };

describe("groupHolders", () => {
    it("shows everyone by name when nobody is picked", () => {
        const { named, others } = groupHolders([alex, sam, kim], new Set());
        expect(named.map((h) => h.name)).toEqual(["Alex", "Sam", "Kim"]);
        expect(others).toBeNull();
    });

    it("sums everyone not picked into one nameless row", () => {
        const { named, others } = groupHolders([alex, sam, kim], new Set(["Alex"]));
        expect(named.map((h) => h.name)).toEqual(["Alex"]);
        expect(others?.name).toBe("Others (2 people)");
        expect(others?.name).not.toContain("Sam");
        expect(others?.net_contribution).toBe(4000);
        expect(others?.current_value).toBe(4200);
        expect(others?.gain_loss).toBe(200);
        expect(others?.gain_loss_pct).toBeCloseTo(5);
        expect(others?.ownership_pct).toBe(8);
        expect(others?.day_change).toBe(10);
        expect(others?.others_count).toBe(2);
    });

    it("has no Others row when everyone is picked", () => {
        const { others } = groupHolders([alex, sam], new Set(["Alex", "Sam"]));
        expect(others).toBeNull();
    });

    it("puts the Others line in the copied text without names", () => {
        const { named, others } = groupHolders([alex, sam, kim], new Set(["Alex"]));
        const report = formatHolderReport([...named, others!], "CAD", "Project Chimera");
        expect(report).toContain("Others (2 people) — put in");
        expect(report).not.toContain("Kim");
    });
});

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
