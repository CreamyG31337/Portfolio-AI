/**
 * CSRF Token Utility
 * Provides functions to retrieve and use CSRF tokens from the page meta tag
 */
/**
 * Get the CSRF token from the page meta tag
 * @returns The CSRF token string, or null if not available
 */
export function getCsrfToken() {
    const meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.getAttribute('content') : null;
}
/**
 * Get headers object with CSRF token for fetch requests
 * @returns Object with X-CSRFToken header if token is available, empty object otherwise
 */
export function getCsrfHeaders() {
    const token = getCsrfToken();
    return token ? { 'X-CSRFToken': token } : {};
}
//# sourceMappingURL=csrf.js.map