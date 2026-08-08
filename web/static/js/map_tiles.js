/**
 * @file map_tiles.js
 * @description Theme-aware Leaflet base tile layers (OSM light / CARTO Dark Matter).
 * Respects ui_preferences.map_style when set (match-theme | light | dark).
 */

import { loadPrefs } from '/static/js/ui_preferences.js';

const LIGHT_TILES = {
    url: 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    maxZoom: 18,
};

const DARK_TILES = {
    url: 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',
    attribution:
        '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/attributions">CARTO</a>',
    subdomains: 'abcd',
    maxZoom: 20,
};

export function isDarkTheme() {
    const root = document.documentElement;
    return (
        root.getAttribute('data-theme') === 'dark'
        || root.getAttribute('data-bs-theme') === 'dark'
    );
}

/**
 * Whether map tiles should use the dark basemap.
 * @param {boolean|null} forceDark Explicit override; null reads prefs + theme.
 */
export function shouldUseDarkTiles(forceDark = null) {
    if (forceDark !== null) return Boolean(forceDark);
    const prefs = loadPrefs();
    if (prefs.map_style === 'dark') return true;
    if (prefs.map_style === 'light') return false;
    const root = document.documentElement;
    const attr = root.getAttribute('data-map-style');
    if (attr === 'dark') return true;
    if (attr === 'light') return false;
    return isDarkTheme();
}

export function getTileLayerConfig(forceDark = null) {
    const useDark = shouldUseDarkTiles(forceDark);
    return useDark ? { ...DARK_TILES } : { ...LIGHT_TILES };
}

export function createThemedTileLayer(forceDark = null) {
    if (typeof L === 'undefined') {
        throw new Error('Leaflet (L) is not available');
    }
    const config = getTileLayerConfig(forceDark);
    const options = {
        attribution: config.attribution,
        maxZoom: config.maxZoom,
    };
    if (config.subdomains) {
        options.subdomains = config.subdomains;
    }
    return L.tileLayer(config.url, options);
}

/**
 * @param {(isDark: boolean) => void} onChange
 * @returns {MutationObserver}
 */
export function observeThemeChange(onChange) {
    let lastDark = shouldUseDarkTiles();
    const observer = new MutationObserver((mutations) => {
        const themeChanged = mutations.some(
            (m) =>
                m.type === 'attributes'
                && (
                    m.attributeName === 'data-theme'
                    || m.attributeName === 'data-bs-theme'
                    || m.attributeName === 'data-map-style'
                )
        );
        if (!themeChanged) return;
        const nextDark = shouldUseDarkTiles();
        if (nextDark === lastDark) return;
        lastDark = nextDark;
        window.setTimeout(() => onChange(nextDark), 50);
    });
    observer.observe(document.documentElement, {
        attributes: true,
        attributeFilter: ['data-theme', 'data-bs-theme', 'data-map-style'],
    });
    return observer;
}

/**
 * Replace the base tile layer on a map.
 * @param {L.Map} map
 * @param {{ current: L.TileLayer | null }} layerHolder Mutable holder for the active tile layer.
 * @returns {L.TileLayer | null}
 */
export function swapMapTileLayer(map, layerHolder) {
    if (!map || typeof L === 'undefined') return null;
    if (layerHolder.current) {
        try {
            map.removeLayer(layerHolder.current);
        } catch (_) {
            /* layer may already be gone */
        }
        layerHolder.current = null;
    }
    const next = createThemedTileLayer();
    next.addTo(map);
    if (typeof next.setZIndex === 'function') {
        next.setZIndex(0);
    }
    layerHolder.current = next;
    return next;
}
