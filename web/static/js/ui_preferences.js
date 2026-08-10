/**
 * @file ui_preferences.js
 * @description Per-user appearance prefs: theme_mode, accent, platform_accents,
 * density, map_style. localStorage for fast paint; server sync via PUT /api/users/me.
 */

import { apiRequest } from '/static/js/api.js';

export const UI_PREFS_STORAGE_KEY = 'ui_preferences';
export const RESOLVED_THEME_KEY = 'theme';

export const ACCENT_OPTIONS = Object.freeze([
    'default',
    'teal',
    'high-contrast',
    'slate',
    'ocean',
    'seafoam',
    'amber',
]);

export const PLATFORM_IDS = Object.freeze(['wave_glider', 'slocum']);

export const DEFAULT_UI_PREFERENCES = Object.freeze({
    theme_mode: 'system',
    accent: 'default',
    platform_accents: Object.freeze({
        wave_glider: 'inherit',
        slocum: 'inherit',
    }),
    density: 'comfortable',
    map_style: 'match-theme',
});

const THEME_MODES = new Set(['light', 'dark', 'system']);
const ACCENTS = new Set(ACCENT_OPTIONS);
const DENSITIES = new Set(['comfortable', 'compact']);
const MAP_STYLES = new Set(['match-theme', 'light', 'dark']);
const PLATFORM_SET = new Set(PLATFORM_IDS);

let systemMediaQuery = null;
let systemListener = null;
let persistTimer = null;
let themeSwitchEl = null;

function safeParseJson(raw) {
    if (!raw) return null;
    try {
        return JSON.parse(raw);
    } catch (_) {
        return null;
    }
}

function normalizePlatformAccents(raw) {
    const out = {
        wave_glider: 'inherit',
        slocum: 'inherit',
    };
    if (!raw || typeof raw !== 'object') return out;
    PLATFORM_IDS.forEach((id) => {
        const value = raw[id];
        if (value === 'inherit' || ACCENTS.has(value)) {
            out[id] = value;
        }
    });
    return out;
}

export function normalizePrefs(raw) {
    const src = raw && typeof raw === 'object' ? raw : {};
    return {
        theme_mode: THEME_MODES.has(src.theme_mode) ? src.theme_mode : DEFAULT_UI_PREFERENCES.theme_mode,
        accent: ACCENTS.has(src.accent) ? src.accent : DEFAULT_UI_PREFERENCES.accent,
        platform_accents: normalizePlatformAccents(src.platform_accents),
        density: DENSITIES.has(src.density) ? src.density : DEFAULT_UI_PREFERENCES.density,
        map_style: MAP_STYLES.has(src.map_style) ? src.map_style : DEFAULT_UI_PREFERENCES.map_style,
    };
}

/**
 * Platform for accent resolution. Only trust explicit data-platform on <html>
 * (APP_PLATFORM defaults to wave_glider even on non-platform pages).
 */
export function currentPlatform() {
    const fromDom = document.documentElement.getAttribute('data-platform');
    if (fromDom && PLATFORM_SET.has(fromDom)) return fromDom;
    return null;
}

/**
 * Resolve effective accent for a page platform (null = general only).
 */
export function resolveAccent(prefs, platformId = null) {
    const normalized = normalizePrefs(prefs);
    const general = normalized.accent;
    if (!platformId || !PLATFORM_SET.has(platformId)) return general;
    const override = normalized.platform_accents[platformId];
    if (!override || override === 'inherit') return general;
    return ACCENTS.has(override) ? override : general;
}

export function loadPrefs() {
    let stored = null;
    try {
        stored = safeParseJson(localStorage.getItem(UI_PREFS_STORAGE_KEY));
    } catch (_) {
        stored = null;
    }

    if (!stored) {
        let legacyTheme = null;
        try {
            legacyTheme = localStorage.getItem(RESOLVED_THEME_KEY);
        } catch (_) {
            legacyTheme = null;
        }
        if (legacyTheme === 'light' || legacyTheme === 'dark') {
            return normalizePrefs({ theme_mode: legacyTheme });
        }
        return normalizePrefs(null);
    }
    return normalizePrefs(stored);
}

export function savePrefsLocal(prefs) {
    const normalized = normalizePrefs(prefs);
    try {
        localStorage.setItem(UI_PREFS_STORAGE_KEY, JSON.stringify(normalized));
    } catch (_) {
        /* private mode / quota */
    }
    return normalized;
}

export function systemPrefersDark() {
    return Boolean(window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches);
}

export function resolveTheme(themeMode) {
    const mode = THEME_MODES.has(themeMode) ? themeMode : DEFAULT_UI_PREFERENCES.theme_mode;
    if (mode === 'system') {
        return systemPrefersDark() ? 'dark' : 'light';
    }
    return mode;
}

export function applyPrefsToDom(prefs, options = {}) {
    const normalized = normalizePrefs(prefs);
    const root = document.documentElement;
    const resolved = resolveTheme(normalized.theme_mode);
    const accent = resolveAccent(normalized, currentPlatform());

    root.setAttribute('data-theme', resolved);
    root.setAttribute('data-bs-theme', resolved);
    root.setAttribute('data-accent', accent);
    root.setAttribute('data-density', normalized.density);
    root.setAttribute('data-map-style', normalized.map_style);

    try {
        localStorage.setItem(RESOLVED_THEME_KEY, resolved);
    } catch (_) {
        /* ignore */
    }

    const switchEl = options.themeSwitch !== undefined ? options.themeSwitch : themeSwitchEl;
    if (switchEl) {
        switchEl.checked = resolved === 'dark';
    }

    syncSystemListener(normalized.theme_mode);
    return { prefs: normalized, resolvedTheme: resolved, resolvedAccent: accent };
}

function syncSystemListener(themeMode) {
    if (!window.matchMedia) return;

    if (!systemMediaQuery) {
        systemMediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
    }

    if (systemListener) {
        if (typeof systemMediaQuery.removeEventListener === 'function') {
            systemMediaQuery.removeEventListener('change', systemListener);
        } else if (typeof systemMediaQuery.removeListener === 'function') {
            systemMediaQuery.removeListener(systemListener);
        }
        systemListener = null;
    }

    if (themeMode !== 'system') return;

    systemListener = () => {
        const prefs = loadPrefs();
        if (prefs.theme_mode !== 'system') return;
        applyPrefsToDom(prefs);
    };

    if (typeof systemMediaQuery.addEventListener === 'function') {
        systemMediaQuery.addEventListener('change', systemListener);
    } else if (typeof systemMediaQuery.addListener === 'function') {
        systemMediaQuery.addListener(systemListener);
    }
}

export function hasAuthToken() {
    try {
        return Boolean(localStorage.getItem('accessToken'));
    } catch (_) {
        return false;
    }
}

export async function persistPrefsToServer(prefs) {
    if (!hasAuthToken()) return null;
    const normalized = normalizePrefs(prefs);
    try {
        return await apiRequest('/api/users/me', 'PUT', { ui_preferences: normalized });
    } catch (err) {
        console.warn('Failed to persist UI preferences:', err);
        return null;
    }
}

function schedulePersist(prefs) {
    if (!hasAuthToken()) return;
    if (persistTimer) clearTimeout(persistTimer);
    persistTimer = setTimeout(() => {
        persistTimer = null;
        persistPrefsToServer(prefs);
    }, 400);
}

export function commitPrefs(prefs, options = {}) {
    const { persistLocal = true, persistServer = true, themeSwitch } = options;
    const normalized = persistLocal ? savePrefsLocal(prefs) : normalizePrefs(prefs);
    applyPrefsToDom(normalized, { themeSwitch });
    if (persistServer) schedulePersist(normalized);
    return normalized;
}

export function setThemeModeFromToggle(isDark, options = {}) {
    const prefs = { ...loadPrefs(), theme_mode: isDark ? 'dark' : 'light' };
    return commitPrefs(prefs, options);
}

export function applyServerPreferences(serverPrefs, options = {}) {
    if (!serverPrefs) return loadPrefs();
    const normalized = normalizePrefs(serverPrefs);
    return commitPrefs(normalized, {
        persistLocal: true,
        persistServer: false,
        themeSwitch: options.themeSwitch,
    });
}

export function initThemeControls(themeSwitch) {
    themeSwitchEl = themeSwitch || document.getElementById('themeSwitch');
    const prefs = loadPrefs();
    applyPrefsToDom(prefs, { themeSwitch: themeSwitchEl });

    if (themeSwitchEl && !themeSwitchEl.dataset.uiPrefsBound) {
        themeSwitchEl.dataset.uiPrefsBound = '1';
        themeSwitchEl.addEventListener('change', () => {
            setThemeModeFromToggle(themeSwitchEl.checked, { themeSwitch: themeSwitchEl });
        });
    }
    return prefs;
}
