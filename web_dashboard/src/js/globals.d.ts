/**
 * Global type declarations for browser globals
 * These are shared across all TypeScript files
 * 
 * ⚠️ IMPORTANT: This is a TypeScript declaration file.
 * - Edit this file: web_dashboard/src/js/globals.d.ts
 * - This file is automatically included by TypeScript
 * - DO NOT edit compiled .js files - they will be overwritten
 * 
 * NOTE: TypeScript compiles ALL files together, even though only one page
 * loads at runtime. This is why we centralize global declarations here.
 */

// Global browser APIs loaded from CDNs
declare global {
    interface Window {
        INITIAL_FUND?: string;
        marked?: {
            parse: (text: string) => string;
        };
        // agGrid is NOT declared here - each file that uses it declares its own type
        // This avoids conflicts since different files use different AgGrid type definitions
        // Flowbite Modal instances (used by funds.ts)
        editModal?: any;
        createModal?: any;
        // Funds page global functions
        toggleProduction?: (fundName: string, isProduction: boolean) => Promise<void>;
        openEditModal?: (fundName: string) => void;
        createFund?: (event: Event) => Promise<void>;
        updateFund?: (event: Event) => Promise<void>;
        showDeleteConfirm?: () => void;
        confirmDeleteFund?: () => Promise<void>;
        refreshTickerMetadata?: () => Promise<void>;
        rebuildPortfolio?: () => Promise<void>;
    }
    
    // ApexCharts removed - all charts now use Plotly
}

// Export empty object to make this a module (required for declare global)
export {};
