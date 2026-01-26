# Code Review for Commit f44e89d

**Commit:** `f44e89d23d465584f91a5557c9e6e96e83694512`
**Author:** Lance Colton
**Date:** Mon Jan 26 02:36:05 2026 -0800
**Subject:** style: Adjust insider trades chart layout and improve y-axis settings

## Overview
The commit addresses layout issues in the insider trades dashboard, specifically focusing on the "Top 10 Active Insiders" chart and general chart margins. The changes align with the commit message, implementing fixed margins and disabling auto-margins for better control over the presentation of long insider names.

## Detailed Findings

### 1. `web_dashboard/src/js/insider_trades.ts`

#### **Dead Code: Unused `wrapLabel` function**
In the `renderTopInsidersChart` function, a helper function `wrapLabel` is defined to handle text wrapping for long labels.

```typescript
    const wrapLabel = (label: string, maxLineLength: number, maxLines: number): string => {
        // ... implementation ...
    };

    // Use full names without truncation - let automargin handle sizing
    const labels = top.map(([name]) => name);
```

**Observation:** The `wrapLabel` function is never called. The code explicitly uses `top.map(([name]) => name)` which passes the full name directly.
**Recommendation:** Remove the `wrapLabel` function to clean up the codebase, or utilize it if the intention was to wrap long names instead of relying on the large left margin.

#### **Stale Comment / Contradiction**
The comment immediately following the unused function says:
```typescript
    // Use full names without truncation - let automargin handle sizing
```
However, the layout configuration explicitly disables `automargin`:
```typescript
    yaxis: {
        ...(themeLayout.yaxis || {}),
        automargin: false,  // <--- Contradicts comment
        tickmode: "linear",
        tickfont: { size: 11 }
    }
```
**Observation:** The comment implies that Plotly's `automargin` feature is relied upon, but the code disables it in favor of a fixed left margin (`margin: { l: 280, ... }`).
**Recommendation:** Update the comment to reflect the actual strategy (e.g., "// Use full names; relying on fixed left margin of 280px").

#### **Hardcoded Margins**
The chart layout uses a fixed left margin of `280px`:
```typescript
    margin: { l: 280, r: 20, t: 10, b: 30 },
```
**Observation:** While this likely accommodates most names, extremely long names might still be cut off.
**Recommendation:** Verify if `280px` is sufficient for the longest expected data. If `wrapLabel` was intended to solve this, consider reinstating it. Otherwise, this approach is acceptable for a "style adjustment" but less robust than a dynamic solution.

### 2. `web_dashboard/templates/insider_trades.html`

**Observation:** The height of the top insiders chart container was set to `h-[300px]`.
```html
<div id="insider-top-insiders-chart" class="h-[300px]"></div>
```
**Assessment:** This looks correct and aligns with the goal of improving visibility.

## Summary
The changes successfully implement the visual style adjustments requested. However, the cleanup of unused code (`wrapLabel`) and updating of comments in `insider_trades.ts` is recommended to maintain code quality.
