/**
 * Logo Switcher
 * Updates logo based on current theme.
 */

// Function to update all logo instances
function updateLogos(theme: string): void {
    const validThemes = ['light', 'dark', 'midnight-tokyo', 'abyss'];

    // Resolve 'system' to actual theme
    let effectiveTheme = theme;
    if (theme === 'system') {
        effectiveTheme = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    }

    // Determine which logo file to use
    let logoFile = 'logo.svg'; // Default (dark)

    if (effectiveTheme === 'light') {
        logoFile = 'logo-light.svg';
    } else if (effectiveTheme === 'midnight-tokyo') {
        logoFile = 'logo-tokyo.svg';
    } else if (effectiveTheme === 'abyss') {
        logoFile = 'logo-abyss.svg';
    }

    // Update all theme-aware logos
    const logos = document.querySelectorAll('.theme-aware-logo') as NodeListOf<HTMLImageElement>;
    logos.forEach(img => {
        // preserve base path if present, just replace filename
        const currentSrc = img.src;
        const basePath = currentSrc.substring(0, currentSrc.lastIndexOf('/') + 1);
        img.src = basePath + logoFile;
    });
}

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    // Check if themeManager exists using type casting to avoid conflicts
    const tm = (window as any).themeManager;
    if (tm) {
        // Initial update
        updateLogos(tm.getTheme());

        // Listen for changes
        tm.addListener((newTheme: string) => {
            updateLogos(newTheme);
        });
    } else {
        console.warn('ThemeManager not found, logo switching disabled');
    }

    // Listen for system preference changes if in system mode
    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', e => {
        const tm = (window as any).themeManager;
        if (tm && tm.getTheme() === 'system') {
            updateLogos('system');
        }
    });
});
