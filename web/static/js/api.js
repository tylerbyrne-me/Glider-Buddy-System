/**
 * @file api.js
 * @description A shared module for API requests and UI utilities.
 * This module centralizes API communication, providing a consistent
 * way to handle authenticated requests and display user feedback.
 */

const LOGIN_PATH = '/login.html';

const isLoginPath = (pathWithQuery) => {
    const qIdx = pathWithQuery.indexOf('?');
    const pathname = qIdx >= 0 ? pathWithQuery.slice(0, qIdx) : pathWithQuery;
    return pathname === LOGIN_PATH || pathname.endsWith('/login.html');
};

/**
 * Safe post-login return path. Rejects external URLs and unwraps nested login redirect chains.
 * @param {string|null|undefined} rawNext
 * @returns {string|null}
 */
export const sanitizeLoginNextPath = (rawNext) => {
    if (rawNext == null || typeof rawNext !== 'string') return null;
    let candidate = rawNext.trim();
    for (let depth = 0; depth < 20; depth += 1) {
        if (!candidate.startsWith('/') || candidate.startsWith('//')) return null;
        if (!isLoginPath(candidate)) return candidate;
        const qIdx = candidate.indexOf('?');
        if (qIdx < 0) return null;
        const inner = new URLSearchParams(candidate.slice(qIdx + 1)).get('next');
        if (!inner) return null;
        try {
            candidate = decodeURIComponent(inner);
        } catch {
            return null;
        }
    }
    return null;
};

/** Redirects to login with session_expired and next params. Used by apiRequest and fetchWithAuth. */
const redirectToLoginOn401 = () => {
    localStorage.removeItem('accessToken');
    const onLoginPage = isLoginPath(window.location.pathname);
    if (onLoginPage) {
        // #region agent log
        fetch('http://127.0.0.1:7650/ingest/4c770a18-5d45-4257-8f2a-77da070675ea',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Session-Id':'a1bfbb'},body:JSON.stringify({sessionId:'a1bfbb',hypothesisId:'H-login-loop',location:'api.js:redirectToLoginOn401',message:'401 on login page — skip redirect',data:{pathname:window.location.pathname},timestamp:Date.now(),runId:'login-loop'})}).catch(()=>{});
        // #endregion
        return;
    }
    const current = window.location.pathname + window.location.search;
    const nextPath = sanitizeLoginNextPath(current) ?? '/platform';
    // #region agent log
    fetch('http://127.0.0.1:7650/ingest/4c770a18-5d45-4257-8f2a-77da070675ea',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Session-Id':'a1bfbb'},body:JSON.stringify({sessionId:'a1bfbb',hypothesisId:'H-login-loop',location:'api.js:redirectToLoginOn401',message:'redirect to login',data:{from:current,nextPath},timestamp:Date.now(),runId:'login-loop'})}).catch(()=>{});
    // #endregion
    window.location.href = `${LOGIN_PATH}?session_expired=true&next=${encodeURIComponent(nextPath)}`;
};

/**
 * Shows a Bootstrap toast notification.
 * @param {string} message - The message to display in the toast.
 * @param {string} [type='success'] - The type of toast ('success' or 'danger').
 */
export const showToast = (message, type = 'success') => {
    const toastContainer = document.getElementById('toast-container');
    if (!toastContainer) {
        console.error('Toast container not found. Please add `<div id="toast-container" class="toast-container position-fixed top-0 end-0 p-3"></div>` to your base HTML.');
        return;
    }
    const toastId = `toast-${Date.now()}`;
    const toastHTML = `
        <div id="${toastId}" class="toast align-items-center text-white bg-${type === 'success' ? 'success' : 'danger'} border-0" role="alert" aria-live="assertive" aria-atomic="true">
            <div class="d-flex">
                <div class="toast-body">${message}</div>
                <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button>
            </div>
        </div>
    `;
    toastContainer.insertAdjacentHTML('beforeend', toastHTML);
    const toastEl = document.getElementById(toastId);
    const toast = new bootstrap.Toast(toastEl, { delay: 5000 });
    toast.show();
    toastEl.addEventListener('hidden.bs.toast', () => toastEl.remove());
};

/**
 * Current platform for Knowledge Base (wave_glider or slocum). Set by base template as window.APP_PLATFORM.
 * @returns {string}
 */
export const getPlatform = () => (typeof window !== 'undefined' && window.APP_PLATFORM) ? window.APP_PLATFORM : 'wave_glider';

/**
 * Canonical API prefix for the current platform (Slocum already uses /api/slocum).
 * Wave Glider: /api/wave_glider (aliased server-side to legacy /api/...).
 * @returns {string}
 */
export const getPlatformApiPrefix = () => {
    const platform = getPlatform();
    if (platform === 'slocum') return '/api/slocum';
    if (platform === 'wave_glider') return '/api/wave_glider';
    return '/api';
};

/**
 * Prefer platform-prefixed APIs for Wave Glider first-party calls.
 * Leaves /api/slocum, /api/wave_glider, /api/admin, /api/auth, /api/token unchanged.
 * @param {string} url
 * @returns {string}
 */
export const withPlatformApiPrefix = (url) => {
    if (typeof url !== 'string' || !url.startsWith('/api/')) return url;
    if (
        url.startsWith('/api/slocum') ||
        url.startsWith('/api/wave_glider') ||
        url.startsWith('/api/admin') ||
        url.startsWith('/api/auth') ||
        url.startsWith('/api/token') ||
        url.startsWith('/api/users')
    ) {
        return url;
    }
    if (getPlatform() !== 'wave_glider') return url;
    return `/api/wave_glider${url.slice(4)}`;
};

/**
 * Appends platform query parameter to a URL for KB API calls.
 * @param {string} url - Base URL (may already have query params).
 * @returns {string}
 */
export const appendPlatformParam = (url) => {
    const sep = url.includes('?') ? '&' : '?';
    return `${url}${sep}platform=${encodeURIComponent(getPlatform())}`;
};

/**
 * Makes an authenticated API request.
 * Handles token retrieval, headers, and standardized error handling.
 * @param {string} url - The API endpoint URL.
 * @param {string} method - The HTTP method (e.g., 'GET', 'POST', 'PUT', 'DELETE').
 * @param {Object|null} [body=null] - The request body for POST/PUT requests.
 * @returns {Promise<any>} A promise that resolves with the JSON response body.
 * @throws {Error} Throws an error if the request fails, with the message from the server.
 */
export const apiRequest = async (url, method, body = null) => {
    url = withPlatformApiPrefix(url);
    const token = localStorage.getItem('accessToken');
    const headers = {
        'Content-Type': 'application/json',
    };
    if (token) {
        headers['Authorization'] = `Bearer ${token}`;
    }

    const options = { method, headers, credentials: 'include' };
    if (body) {
        options.body = JSON.stringify(body);
    }

    const response = await fetch(url, options);

    if (response.status === 401) {
        redirectToLoginOn401();
        throw new Error('Session expired. Redirecting to login.');
    }

    if (!response.ok) {
        let errorMessage = `HTTP error! Status: ${response.status}`;
        try {
            const errorData = await response.json();
            console.error('API Error Response:', errorData);
            // Handle different error response formats
            if (typeof errorData === 'string') {
                errorMessage = errorData;
            } else if (errorData && typeof errorData === 'object') {
                // FastAPI validation errors have a specific structure
                if (Array.isArray(errorData.detail)) {
                    // Validation errors
                    const validationErrors = errorData.detail.map(err => 
                        `${err.loc?.join('.')}: ${err.msg}`
                    ).join('; ');
                    errorMessage = `Validation error: ${validationErrors}`;
                } else {
                    errorMessage = errorData.detail || errorData.message || errorData.error || JSON.stringify(errorData);
                }
            }
        } catch (e) {
            // If JSON parsing fails, try to get text
            try {
                const text = await response.text();
                errorMessage = text || errorMessage;
            } catch (textError) {
                // Use default error message
            }
        }
        throw new Error(errorMessage);
    }

    return response.status === 204 ? null : await response.json();
};

/**
 * Returns headers object with Bearer token if present. Use for one-off fetch calls that need auth.
 * Prefer apiRequest() or fetchWithAuth() so 401 handling and credentials are consistent.
 */
export const getAuthHeaders = () => {
    const token = localStorage.getItem('accessToken');
    const headers = {};
    if (token) headers['Authorization'] = `Bearer ${token}`;
    return headers;
};

/**
 * Makes a fetch request with auth (Bearer + credentials) and consistent 401 handling.
 * Use for FormData, blob, or other non-JSON requests. On 401, redirects to login with next= and throws.
 * @param {string} url - The API endpoint URL.
 * @param {Object} [options={}] - Fetch options (method, headers, body, etc.). Headers are merged with auth.
 * @returns {Promise<Response>} The fetch response promise (caller should check response.ok and handle 401 only if not redirected).
 */
export const fetchWithAuth = async (url, options = {}) => {
    url = withPlatformApiPrefix(url);
    const token = localStorage.getItem('accessToken');
    const headers = new Headers(options.headers || {});
    if (token && !headers.has('Authorization')) {
        headers.set('Authorization', `Bearer ${token}`);
    }
    const response = await fetch(url, { ...options, headers, credentials: 'include' });
    if (response.status === 401) {
        redirectToLoginOn401();
        throw new Error('Session expired. Redirecting to login.');
    }
    return response;
};

/**
 * Escapes HTML to prevent XSS attacks.
 * @param {string} str - The string to escape.
 * @returns {string} The escaped string.
 */
export const escapeHTML = (str) => {
    if (str === null || str === undefined) return '';
    return str.toString().replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#039;');
};