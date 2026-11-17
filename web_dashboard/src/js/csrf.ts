/**
 * CSRF Token Utility
 * Provides functions to retrieve, refresh, and use CSRF tokens from the page meta tag.
 * Flask-WTF tokens expire (default 1 hour); pages left open need a refresh + retry.
 */

/**
 * Get the CSRF token from the page meta tag
 * @returns The CSRF token string, or null if not available
 */
export function getCsrfToken(): string | null {
    const meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.getAttribute('content') : null;
}

/**
 * Get headers object with CSRF token for fetch requests
 * @returns Object with X-CSRFToken header if token is available, empty object otherwise
 */
export function getCsrfHeaders(): Record<string, string> {
    const token = getCsrfToken();
    return token ? { 'X-CSRFToken': token } : {};
}

/**
 * Fetch a fresh CSRF token from the server and update the page meta tag.
 * @returns true if the meta tag was updated with a new token
 */
export async function refreshCsrfToken(): Promise<boolean> {
    try {
        const resp = await fetch('/api/auth/csrf-token', { credentials: 'include' });
        if (!resp.ok) {
            return false;
        }
        const data = (await resp.json()) as { csrf_token?: string };
        const meta = document.querySelector('meta[name="csrf-token"]');
        if (meta && data.csrf_token) {
            meta.setAttribute('content', data.csrf_token);
            return true;
        }
    } catch (e) {
        console.error('Failed to refresh CSRF token:', e);
    }
    return false;
}

function mergeHeaders(existing: HeadersInit | undefined, csrf: Record<string, string>): HeadersInit {
    if (!existing) {
        return { ...csrf };
    }
    if (existing instanceof Headers) {
        const merged = new Headers(existing);
        for (const [key, value] of Object.entries(csrf)) {
            merged.set(key, value);
        }
        return merged;
    }
    if (Array.isArray(existing)) {
        return [...existing, ...Object.entries(csrf)];
    }
    return { ...existing, ...csrf };
}

/**
 * fetch() wrapper that attaches the CSRF header and retries once on 419 (csrf_expired).
 * Use for POST/PUT/PATCH/DELETE so long-lived pages keep working after token expiry.
 */
export async function csrfFetch(input: RequestInfo | URL, init: RequestInit = {}): Promise<Response> {
    const buildInit = (): RequestInit => ({
        credentials: init.credentials ?? 'include',
        ...init,
        headers: mergeHeaders(init.headers, getCsrfHeaders()),
    });

    let response = await fetch(input, buildInit());

    // 419 = CSRF token expired — refresh meta tag and retry once
    if (response.status === 419) {
        const refreshed = await refreshCsrfToken();
        if (refreshed) {
            response = await fetch(input, buildInit());
        }
    }

    return response;
}
