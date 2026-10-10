/** How often an open dashboard asks whether portfolio data changed. */
export const DASHBOARD_FRESHNESS_POLL_MS = 5 * 60 * 1000;
/** Full reload at least this often, even when the freshness token is unchanged. */
export const DASHBOARD_MAX_STALE_MS = 60 * 60 * 1000;
/**
 * Decide whether the open dashboard should reload.
 * A changed token means new portfolio data. The hourly path covers cards
 * (market brief, AI summaries) that can update without a new position row.
 * Hidden tabs and an in-flight reload wait.
 */
export function dashboardRefreshReason(input) {
    if (input.hidden || input.refreshInFlight) {
        return null;
    }
    const previous = input.previousToken;
    const next = input.nextToken;
    if (previous && next && previous !== next) {
        return "data";
    }
    if (input.nowMs - input.lastRefreshAtMs >= DASHBOARD_MAX_STALE_MS) {
        return "hourly";
    }
    return null;
}
/**
 * Token for "did portfolio data change?".
 * Position `date` is the 4pm ET snapshot and stays put during the trading day.
 * `updated_at` moves when the price job rewrites today's rows.
 */
export function portfolioFreshnessToken(payload) {
    if (!payload) {
        return null;
    }
    const updated = (payload.updated_at || "").trim();
    if (updated) {
        return updated;
    }
    const stamp = (payload.timestamp || "").trim();
    return stamp || null;
}
//# sourceMappingURL=dashboard_refresh.js.map