/**
 * Chart Theme Utilities for Plotly
 * Handles theme-specific chart styling and dynamic relayout
 */

import { Theme, EffectiveTheme } from './types';

interface PlotlyLayout {
    paper_bgcolor: string;
    plot_bgcolor: string;
    font: { color: string };
    xaxis: {
        gridcolor: string;
        zerolinecolor: string;
    };
    yaxis: {
        gridcolor: string;
        zerolinecolor: string;
    };
}

interface ThemeConfig {
    paper_bgcolor: string;
    plot_bgcolor: string;
    font: { color: string };
    gridcolor: string;
    zerolinecolor: string;
}

interface PlotlyElement extends HTMLElement {
    _fullLayout?: unknown;
}

/**
 * Get Plotly layout configuration for a given theme
 * @param themeName - Theme name ('system', 'light', 'dark', 'midnight-tokyo', 'abyss')
 * @returns Plotly layout object with theme-specific styles
 */
export function getPlotlyLayout(themeName: Theme): PlotlyLayout {
    // Resolve 'system' to actual theme
    let effectiveTheme: EffectiveTheme = themeName === 'system'
        ? (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')
        : themeName;

    const themeConfigs: Record<EffectiveTheme, ThemeConfig> = {
        light: {
            paper_bgcolor: 'white',
            plot_bgcolor: 'white',
            font: { color: 'rgb(31, 41, 55)' },
            gridcolor: 'rgb(229, 231, 235)',
            zerolinecolor: 'rgb(229, 231, 235)'
        },
        dark: {
            paper_bgcolor: 'rgb(31, 41, 55)',
            plot_bgcolor: 'rgb(31, 41, 55)',
            font: { color: 'rgb(209, 213, 219)' },
            gridcolor: 'rgb(55, 65, 81)',
            zerolinecolor: 'rgb(55, 65, 81)'
        },
        'midnight-tokyo': {
            paper_bgcolor: '#24283b',
            plot_bgcolor: '#24283b',
            font: { color: '#c0caf5' },
            gridcolor: '#3b4261',
            zerolinecolor: '#3b4261'
        },
        abyss: {
            paper_bgcolor: '#000c18',
            plot_bgcolor: '#000c18',
            font: { color: '#a9b1d6' },
            gridcolor: '#1a2b42',
            zerolinecolor: '#1a2b42'
        }
    };

    const config = themeConfigs[effectiveTheme] || themeConfigs.light;

    return {
        paper_bgcolor: config.paper_bgcolor,
        plot_bgcolor: config.plot_bgcolor,
        font: config.font,
        xaxis: {
            gridcolor: config.gridcolor,
            zerolinecolor: config.zerolinecolor
        },
        yaxis: {
            gridcolor: config.gridcolor,
            zerolinecolor: config.zerolinecolor
        }
    };
}

/**
 * Apply theme to an existing Plotly chart
 * @param chartElement - Chart DOM element or ID
 * @param themeName - Theme to apply
 */
export function applyThemeToChart(chartElement: HTMLElement | string, themeName: Theme): void {
    // Get the element
    const element: PlotlyElement | null = typeof chartElement === 'string'
        ? (document.getElementById(chartElement) as PlotlyElement | null)
        : (chartElement as PlotlyElement);

    if (!element) {
        console.warn('Chart element not found:', chartElement);
        return;
    }

    // Check if it's a Plotly chart
    if (!element._fullLayout) {
        console.warn('Element is not a Plotly chart:', element);
        return;
    }

    try {
        const layout = getPlotlyLayout(themeName);
        // Plotly is loaded globally, so we need to access it via window
        (window as any).Plotly.relayout(element, layout);
    } catch (error) {
        console.error('Error applying theme to chart:', error);
    }
}

/**
 * Apply theme to all Plotly charts on the page
 * @param themeName - Theme to apply
 */
export function applyThemeToAllCharts(themeName: Theme): void {
    // Find all Plotly charts
    const charts = document.querySelectorAll<PlotlyElement>('.js-plotly-plot');

    charts.forEach(chart => {
        applyThemeToChart(chart, themeName);
    });
}

/**
 * Initialize chart theme synchronization
 * Automatically updates charts when theme changes
 */
export function initChartThemeSync(): void {
    const themeManager = (window as Window & { themeManager?: { addListener: (callback: (theme: Theme) => void) => void } }).themeManager;
    if (themeManager) {
        themeManager.addListener((theme: Theme) => {
            applyThemeToAllCharts(theme);
        });
    } else {
        console.warn('ThemeManager not found. Chart theme synchronization disabled.');
    }
}

// Auto-initialize when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initChartThemeSync);
} else {
    initChartThemeSync();
}

// Export functions for use in other modules
if (typeof window !== 'undefined') {
    (window as any).chartThemeUtils = {
        getPlotlyLayout,
        applyThemeToChart,
        applyThemeToAllCharts,
        initChartThemeSync
    };
}
