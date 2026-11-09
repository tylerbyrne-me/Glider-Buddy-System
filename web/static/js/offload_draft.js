/**
 * @file offload_draft.js
 * @description Debounced localStorage drafts for in-progress station offload forms.
 * Survives tab discard, page reload, and re-login when the same username + station are used.
 */

const DRAFT_PREFIX = 'gbs:offloadDraft:';
const DRAFT_TTL_MS = 48 * 60 * 60 * 1000;

/**
 * @param {string} username
 * @param {string} stationId
 * @returns {string}
 */
export function draftKey(username, stationId) {
    const user = String(username || 'anonymous').trim() || 'anonymous';
    const station = String(stationId || '').trim();
    return `${DRAFT_PREFIX}${user}:${station}`;
}

/**
 * @param {string} username
 * @param {string} stationId
 * @param {Record<string, unknown>} fields
 */
export function saveDraft(username, stationId, fields) {
    const station = String(stationId || '').trim();
    if (!station || !fields || typeof fields !== 'object') return;
    const payload = {
        savedAtUtc: new Date().toISOString(),
        fields,
    };
    try {
        localStorage.setItem(draftKey(username, station), JSON.stringify(payload));
    } catch (err) {
        console.warn('offload draft save failed:', err);
    }
}

/**
 * @param {string} username
 * @param {string} stationId
 * @returns {{savedAtUtc: string, fields: Record<string, unknown>}|null}
 */
export function loadDraft(username, stationId) {
    const station = String(stationId || '').trim();
    if (!station) return null;
    try {
        const raw = localStorage.getItem(draftKey(username, station));
        if (!raw) return null;
        const parsed = JSON.parse(raw);
        if (!parsed || typeof parsed !== 'object' || !parsed.fields) {
            clearDraft(username, station);
            return null;
        }
        const savedMs = Date.parse(parsed.savedAtUtc || '');
        if (!Number.isFinite(savedMs) || Date.now() - savedMs > DRAFT_TTL_MS) {
            clearDraft(username, station);
            return null;
        }
        return parsed;
    } catch (err) {
        console.warn('offload draft load failed:', err);
        return null;
    }
}

/**
 * @param {string} username
 * @param {string} stationId
 */
export function clearDraft(username, stationId) {
    const station = String(stationId || '').trim();
    if (!station) return;
    try {
        localStorage.removeItem(draftKey(username, station));
    } catch (err) {
        console.warn('offload draft clear failed:', err);
    }
}

/**
 * Debounce helper for draft saves.
 * @param {(fields: Record<string, unknown>) => void} fn
 * @param {number} [waitMs=500]
 * @returns {(fields: Record<string, unknown>) => void}
 */
export function debounceDraftSave(fn, waitMs = 500) {
    let timer = null;
    return (fields) => {
        if (timer) clearTimeout(timer);
        timer = setTimeout(() => {
            timer = null;
            fn(fields);
        }, waitMs);
    };
}

/**
 * @returns {string}
 */
export function newClientSubmissionId() {
    if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
        return crypto.randomUUID();
    }
    return `offload-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}
