/**
 * Theme Manager for Portfolio Dashboard
 * Handles theme switching, persistence, and API synchronization
 */

import { getCsrfHeaders } from './csrf.js';
import { Theme, ThemeChangeCallback } from './types';

interface ApiResponse {
    success: boolean;
    error?: string;
}

interface ThemeRequest {
    theme: Theme;
}

class ThemeManager {
    private currentTheme: Theme;
    private listeners: ThemeChangeCallback[];

    constructor() {
        this.currentTheme = this.loadTheme();
        this.listeners = [];
        this.init();
    }

    /**
     * Initialize the theme manager
     */
    init(): void {
        // Apply the saved theme on page load - do NOT sync to backend (persist=false)
        // This prevents overwriting server preference with default 'system' if localStorage is empty
        this.applyTheme(this.currentTheme, false);

        // Listen for theme changes from other tabs/windows
        window.addEventListener('storage', (e: StorageEvent) => {
            if (e.key === 'theme') {
                this.currentTheme = (e.newValue as Theme) || 'system';
                this.applyTheme(this.currentTheme, false); // Don't save again
            }
        });
    }

    /**
     * Load theme from localStorage
     * @returns The saved theme or 'system' as default
     */
    loadTheme(): Theme {
        // Check localStorage first
        const stored = localStorage.getItem('theme') as Theme;
        if (stored) return stored;

        // Fallback to server-provided theme (data-theme attribute)
        // This ensures we respect the backend's stored preference even if localStorage is empty
        const serverTheme = document.documentElement.getAttribute('data-theme') as Theme;
        if (serverTheme) return serverTheme;

        return 'system';
    }

    /**
     * Set the current theme
     * @param theme - Theme name ('system', 'light', 'dark', 'midnight-tokyo', 'abyss')
     */
    async setTheme(theme: Theme): Promise<void> {
        const validThemes: Theme[] = ['system', 'light', 'dark', 'midnight-tokyo', 'abyss'];
        if (!validThemes.includes(theme)) {
            console.error(`Invalid theme: ${theme}`);
            return;
        }

        this.currentTheme = theme;
        this.applyTheme(theme);
    }

    /**
     * Apply theme to the page
     * @param theme - Theme to apply
     * @param persist - Whether to persist to localStorage and API
     */
    applyTheme(theme: Theme, persist: boolean = true): void {
        // Update data-theme attribute on the HTML element
        document.documentElement.setAttribute('data-theme', theme);

        // Toggle 'dark' class for Tailwind dark mode support
        const darkThemes: Theme[] = ['dark', 'midnight-tokyo', 'abyss'];
        const isDark = darkThemes.includes(theme) ||
            (theme === 'system' && window.matchMedia('(prefers-color-scheme: dark)').matches);

        if (isDark) {
            document.documentElement.classList.add('dark');
        } else {
            document.documentElement.classList.remove('dark');
        }

        if (persist) {
            // Save to localStorage
            localStorage.setItem('theme', theme);

            // Sync to backend API
            this.syncToBackend(theme);
        }

        // Notify listeners (e.g., charts that need to update)
        this.notifyListeners(theme);
    }

    /**
     * Sync theme preference to backend
     * @param theme - Theme to save
     */
    async syncToBackend(theme: Theme): Promise<void> {
        try {
            const response = await fetch('/api/settings/theme', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    ...getCsrfHeaders()
                },
                credentials: 'include',
                body: JSON.stringify({ theme } as ThemeRequest)
            });

            if (!response.ok) {
                console.warn('Failed to sync theme to backend:', response.statusText);
            }
        } catch (error) {
            console.error('Error syncing theme to backend:', error);
        }
    }

    /**
     * Add a listener for theme changes
     * @param callback - Function to call when theme changes
     */
    addListener(callback: ThemeChangeCallback): void {
        this.listeners.push(callback);
    }

    /**
     * Remove a listener
     * @param callback - Function to remove
     */
    removeListener(callback: ThemeChangeCallback): void {
        this.listeners = this.listeners.filter(cb => cb !== callback);
    }

    /**
     * Notify all listeners of theme change
     * @param theme - New theme
     */
    notifyListeners(theme: Theme): void {
        this.listeners.forEach(callback => {
            try {
                callback(theme);
            } catch (error) {
                console.error('Error in theme listener:', error);
            }
        });
    }

    /**
     * Get the current theme
     * @returns Current theme
     */
    getTheme(): Theme {
        return this.currentTheme;
    }

    /**
     * Get the effective theme (resolves 'system' to actual dark/light)
     * @returns Effective theme ('light', 'dark', 'midnight-tokyo', 'abyss')
     */
    getEffectiveTheme(): Exclude<Theme, 'system'> {
        if (this.currentTheme === 'system') {
            return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
        }
        return this.currentTheme;
    }
}

// Extend Window interface to include themeManager
declare global {
    interface Window {
        themeManager: ThemeManager;
    }
}

// Create global instance (no export needed - loaded as regular script)
(window as Window & { themeManager: ThemeManager }).themeManager = new ThemeManager();
