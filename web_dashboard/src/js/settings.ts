// Settings page AJAX handlers
console.log('Settings.js loaded successfully');

// API Response interface
interface ApiResponse {
    success?: boolean;
    error?: string;
}

// Settings API request interfaces
interface TimezoneRequest {
    timezone: string;
}

interface CurrencyRequest {
    currency: string;
}

interface ThemeRequest {
    theme: string;
}

/**
 * Show success message for a given element ID
 * @param elementId - The ID of the element to show
 */
function showSuccess(elementId: string): void {
    const element = document.getElementById(elementId);
    if (element) {
        element.style.display = 'block';
        setTimeout(() => {
            element.style.display = 'none';
        }, 3000);
    }
}

/**
 * Show error message for a given element ID
 * @param elementId - The ID of the element to show
 * @param errorMessage - Optional error message to display
 */
function showSettingsError(elementId: string, errorMessage?: string): void {
    const element = document.getElementById(elementId);
    if (element) {
        // Update error message if provided
        if (errorMessage) {
            element.textContent = '❌ ' + errorMessage;
        }
        element.style.display = 'block';
        setTimeout(() => {
            element.style.display = 'none';
        }, 5000);
    }
}

// Initialize event handlers when DOM is ready
document.addEventListener('DOMContentLoaded', function (): void {
    // 1. Auto-initialize from DOM config if present
    const configElement = document.getElementById('settings-config');
    if (configElement) {
        try {
            const config = JSON.parse(configElement.textContent || '{}');

            // Set current timezone
            const timezoneSelect = document.getElementById('timezone-select') as HTMLSelectElement | null;
            if (config.currentTimezone && timezoneSelect) {
                timezoneSelect.value = config.currentTimezone;
                timezoneSelect.dataset.original = config.currentTimezone; // Store original for revert
                updateTimezonePreview();
            }

            // Set current currency
            const currencySelect = document.getElementById('currency-select') as HTMLSelectElement | null;
            if (config.currentCurrency && currencySelect) {
                currencySelect.value = config.currentCurrency;
                currencySelect.dataset.original = config.currentCurrency; // Store original for revert
            }

            // Set current theme
            const themeSelect = document.getElementById('theme-select') as HTMLSelectElement | null;
            if (config.currentTheme && themeSelect) {
                themeSelect.value = config.currentTheme;
                themeSelect.dataset.original = config.currentTheme; // Store original for revert
                updateThemePreview();
            }
        } catch (err) {
            console.error('[Settings] Failed to auto-init:', err);
        }
    }

    // 2. V2 Beta Toggle Handler
    const v2Toggle = document.getElementById('v2-toggle') as HTMLInputElement | null;
    if (v2Toggle) {
        v2Toggle.addEventListener('change', async function (this: HTMLInputElement) {
            const enabled = this.checked;
            const toggleElement = this;
            try {
                const response = await fetch('/api/settings/v2_enabled', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({ enabled: enabled })
                });

                if (!response.ok) {
                    const data = await response.json().catch(() => ({}));
                    throw new Error(data.error || `HTTP ${response.status}`);
                }

                const data: ApiResponse = await response.json();
                if (!data.success) {
                    throw new Error(data.error || 'Failed to update');
                }

                // If V2 was disabled, redirect to Streamlit settings page
                // Otherwise, reload to update navigation menu
                if (!enabled) {
                    window.location.href = '/settings';
                } else {
                    window.location.reload();
                }
            } catch (error) {
                console.error('Error updating v2_enabled:', error);
                toggleElement.checked = !enabled; // Revert
                const errorMsg = error instanceof Error ? error.message : 'Unknown error';
                alert('Failed to update preference: ' + errorMsg);
            }
        });
    }

    // Timezone auto-save handler
    const timezoneSelect = document.getElementById('timezone-select') as HTMLSelectElement | null;
    if (timezoneSelect) {
        // Store original value in dataset for revert
        if (!timezoneSelect.dataset.original) {
            timezoneSelect.dataset.original = timezoneSelect.value;
        }

        timezoneSelect.addEventListener('change', function (this: HTMLSelectElement): void {
            updateTimezonePreview();
            const timezone = this.value;
            const selectElement = this;
            const originalValue = selectElement.dataset.original || selectElement.value;

            fetch('/api/settings/timezone', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ timezone: timezone } as TimezoneRequest)
            })
                .then((response: Response) => {
                    if (!response.ok) {
                        return response.json().then((data: ApiResponse) => {
                            throw new Error(data.error || `HTTP ${response.status}`);
                        });
                    }
                    return response.json();
                })
                .then((data: ApiResponse) => {
                    if (data.success) {
                        showSuccess('timezone-success');
                        selectElement.dataset.original = timezone;
                    } else {
                        const errorMsg = data.error || 'Failed to save timezone. Please try again.';
                        console.error('Timezone save failed:', errorMsg);
                        selectElement.value = originalValue; // Revert
                        updateTimezonePreview();
                        showSettingsError('timezone-error', errorMsg);
                    }
                })
                .catch((error: Error) => {
                    const errorMsg = error.message || 'Error saving timezone. Please try again.';
                    console.error('Error saving timezone:', error);
                    selectElement.value = originalValue; // Revert
                    updateTimezonePreview();
                    showSettingsError('timezone-error', errorMsg);
                });
        });
    }

    // Currency auto-save handler
    const currencySelect = document.getElementById('currency-select') as HTMLSelectElement | null;
    if (currencySelect) {
        // Store original value in dataset for revert
        if (!currencySelect.dataset.original) {
            currencySelect.dataset.original = currencySelect.value;
        }

        currencySelect.addEventListener('change', function (this: HTMLSelectElement): void {
            const currency = this.value;
            const selectElement = this;
            const originalValue = selectElement.dataset.original || selectElement.value;

            fetch('/api/settings/currency', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ currency: currency } as CurrencyRequest)
            })
                .then((response: Response) => {
                    if (!response.ok) {
                        return response.json().then((data: ApiResponse) => {
                            throw new Error(data.error || `HTTP ${response.status}`);
                        });
                    }
                    return response.json();
                })
                .then((data: ApiResponse) => {
                    if (data.success) {
                        showSuccess('currency-success');
                        selectElement.dataset.original = currency;
                    } else {
                        const errorMsg = data.error || 'Failed to save currency. Please try again.';
                        console.error('Currency save failed:', errorMsg);
                        selectElement.value = originalValue; // Revert
                        showSettingsError('currency-error', errorMsg);
                    }
                })
                .catch((error: Error) => {
                    const errorMsg = error.message || 'Error saving currency. Please try again.';
                    console.error('Error saving currency:', error);
                    selectElement.value = originalValue; // Revert
                    showSettingsError('currency-error', errorMsg);
                });
        });
    }

    // Theme auto-save handler
    const themeSelect = document.getElementById('theme-select') as HTMLSelectElement | null;
    if (themeSelect) {
        // Store original value in dataset for revert
        if (!themeSelect.dataset.original) {
            themeSelect.dataset.original = themeSelect.value;
        }

        themeSelect.addEventListener('change', function (this: HTMLSelectElement): void {
            updateThemePreview();
            const theme: string = this.value;
            const selectElement: HTMLSelectElement = this; // Capture 'this' for use in callbacks
            const originalValue = selectElement.dataset.original || selectElement.value;

            // Apply theme immediately (optimistic update)
            document.documentElement.setAttribute('data-theme', theme);

            // Save to server
            fetch('/api/settings/theme', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ theme: theme } as ThemeRequest)
            })
                .then((response: Response) => {
                    if (!response.ok) {
                        return response.json().then((data: ApiResponse) => {
                            throw new Error(data.error || `HTTP ${response.status}`);
                        });
                    }
                    return response.json();
                })
                .then((data: ApiResponse) => {
                    if (data.success) {
                        showSuccess('theme-success');
                        selectElement.dataset.original = theme;
                        // Update localStorage so theme.ts reads correct value on reload
                        localStorage.setItem('theme', theme);
                        // Theme changes usually require a reload to apply globally
                        setTimeout(() => window.location.reload(), 500);
                    } else {
                        const errorMsg = data.error || 'Failed to save theme. Please try again.';
                        console.error('Theme save failed:', errorMsg);
                        // Revert on error
                        document.documentElement.setAttribute('data-theme', originalValue);
                        selectElement.value = originalValue;
                        updateThemePreview();
                        showSettingsError('theme-error', errorMsg);
                    }
                })
                .catch((error: Error) => {
                    const errorMsg = error.message || 'Error saving theme. Please try again.';
                    console.error('Error saving theme:', error);
                    // Revert on error
                    document.documentElement.setAttribute('data-theme', originalValue);
                    selectElement.value = originalValue;
                    updateThemePreview();
                    showSettingsError('theme-error', errorMsg);
                });
        });
    }

    // Password Change Handler
    const changePasswordForm = document.getElementById('change-password-form');
    if (changePasswordForm) {
        changePasswordForm.addEventListener('submit', async function (e) {
            e.preventDefault();
            const newPasswordInput = document.getElementById('new-password') as HTMLInputElement;
            const confirmPasswordInput = document.getElementById('confirm-password') as HTMLInputElement;
            const submitBtn = document.getElementById('change-password-btn') as HTMLButtonElement;

            const newPassword = newPasswordInput.value;
            const confirmPassword = confirmPasswordInput.value;

            if (newPassword !== confirmPassword) {
                showSettingsError('password-error', 'Passwords do not match');
                return;
            }

            if (newPassword.length < 6) {
                showSettingsError('password-error', 'Password must be at least 6 characters');
                return;
            }

            const originalText = submitBtn.textContent || 'Update Password';
            submitBtn.disabled = true;
            submitBtn.textContent = 'Updating...';

            try {
                const response = await fetch('/api/auth/change-password', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({ password: newPassword }),
                });

                const data = await response.json();

                if (response.ok) {
                    showSuccess('password-success');
                    newPasswordInput.value = '';
                    confirmPasswordInput.value = '';
                } else {
                    showSettingsError('password-error', data.error || 'Failed to update password');
                }
            } catch (error) {
                console.error('Password update error:', error);
                showSettingsError('password-error', 'An unexpected error occurred');
            } finally {
                submitBtn.disabled = false;
                submitBtn.textContent = originalText;
            }
        });
    }

    // Password Toggle Handler
    const toggleButtons = document.querySelectorAll('[data-toggle-password]');
    toggleButtons.forEach(button => {
        button.addEventListener('click', function (this: HTMLElement) {
            const targetId = this.getAttribute('data-toggle-password');
            if (targetId) {
                const input = document.getElementById(targetId) as HTMLInputElement | null;
                const icon = this.querySelector('i');
                if (input && icon) {
                    if (input.type === 'password') {
                        input.type = 'text';
                        icon.classList.remove('fa-eye');
                        icon.classList.add('fa-eye-slash');
                        this.classList.add('text-accent');
                    } else {
                        input.type = 'password';
                        icon.classList.remove('fa-eye-slash');
                        icon.classList.add('fa-eye');
                        this.classList.remove('text-accent');
                    }
                }
            }
        });
    });
});

function updateTimezonePreview(): void {
    const tzSelect = document.getElementById('timezone-select') as HTMLSelectElement | null;
    const preview = document.getElementById('timezone-preview');
    if (tzSelect && preview) {
        preview.textContent = `Selected: ${tzSelect.value}`;
    }
}

function updateThemePreview(): void {
    const themeSelect = document.getElementById('theme-select') as HTMLSelectElement | null;
    const preview = document.getElementById('theme-preview');
    if (themeSelect && preview) {
        const theme = themeSelect.value;
        if (theme === 'system') {
            preview.textContent = 'ℹ️ Theme will follow your browser/OS dark mode setting';
        } else if (theme === 'dark') {
            preview.textContent = '🌙 Dark mode will be forced on';
        } else if (theme === 'light') {
            preview.textContent = '☀️ Light mode will be forced on';
        } else if (theme === 'midnight-tokyo') {
            preview.textContent = '🌃 Cyberpunk neon theme';
        } else if (theme === 'abyss') {
            preview.textContent = '🌊 Deep ocean void theme';
        }
    }
}
