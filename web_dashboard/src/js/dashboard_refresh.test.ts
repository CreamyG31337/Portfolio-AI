import { describe, expect, it } from "vitest";
import {
    DASHBOARD_MAX_STALE_MS,
    dashboardRefreshReason,
    portfolioFreshnessToken,
} from "./dashboard_refresh";

const base = {
    hidden: false,
    refreshInFlight: false,
    nowMs: 1_000_000,
    lastRefreshAtMs: 1_000_000,
    previousToken: "2026-10-09T14:00:00+00:00",
    nextToken: "2026-10-09T14:00:00+00:00",
};

describe("dashboardRefreshReason", () => {
    it("stays quiet when the data token is unchanged and the page is fresh", () => {
        expect(dashboardRefreshReason(base)).toBeNull();
    });

    it("reloads when portfolio data has a new token", () => {
        expect(
            dashboardRefreshReason({
                ...base,
                nextToken: "2026-10-09T14:15:00+00:00",
            })
        ).toBe("data");
    });

    it("reloads at least once an hour even when the token is unchanged", () => {
        expect(
            dashboardRefreshReason({
                ...base,
                nowMs: base.lastRefreshAtMs + DASHBOARD_MAX_STALE_MS,
            })
        ).toBe("hourly");
    });

    it("does not treat the first token observation as new data", () => {
        expect(
            dashboardRefreshReason({
                ...base,
                previousToken: null,
                nextToken: "2026-10-09T14:15:00+00:00",
            })
        ).toBeNull();
    });

    it("skips hidden tabs and overlapping reloads", () => {
        expect(dashboardRefreshReason({ ...base, hidden: true, nextToken: "new" })).toBeNull();
        expect(
            dashboardRefreshReason({ ...base, refreshInFlight: true, nextToken: "new" })
        ).toBeNull();
    });

    it("still honors the hourly reload when the freshness check has no token", () => {
        expect(
            dashboardRefreshReason({
                ...base,
                nextToken: null,
                nowMs: base.lastRefreshAtMs + DASHBOARD_MAX_STALE_MS,
            })
        ).toBe("hourly");
    });
});

describe("portfolioFreshnessToken", () => {
    it("prefers updated_at over the snapshot date", () => {
        expect(
            portfolioFreshnessToken({
                timestamp: "2026-10-09T20:00:00+00:00",
                updated_at: "2026-10-09T18:15:02+00:00",
            })
        ).toBe("2026-10-09T18:15:02+00:00");
    });

    it("falls back to the snapshot timestamp", () => {
        expect(
            portfolioFreshnessToken({
                timestamp: "2026-10-09T20:00:00+00:00",
                updated_at: "  ",
            })
        ).toBe("2026-10-09T20:00:00+00:00");
        expect(portfolioFreshnessToken(null)).toBeNull();
    });
});
