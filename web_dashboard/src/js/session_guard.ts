/**
 * Global fetch guard: redirect to /auth when an /api/* call returns 401.
 *
 * Loaded on every authenticated page via _scripts_content.html.
 * Named session_guard (not auth.js) to reduce false positives from ad blockers
 * that block script URLs containing "auth".
 */

const nativeFetch = window.fetch.bind(window);

window.fetch = async function sessionGuardFetch(
    input: RequestInfo | URL,
    init?: RequestInit,
): Promise<Response> {
    const response = await nativeFetch(input, init);
    if (response.status !== 401) {
        return response;
    }

    let url = "";
    if (typeof input === "string") {
        url = input;
    } else if (input instanceof URL) {
        url = input.href;
    } else {
        url = input.url;
    }

    const path = window.location.pathname || "";
    if (url.includes("/api/") && !path.startsWith("/auth")) {
        const next = encodeURIComponent(path + window.location.search);
        window.location.assign(`/auth?next=${next}`);
    }

    return response;
};
