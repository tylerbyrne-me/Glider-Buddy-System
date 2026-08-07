/**
 * @file map_tiles.js
 * @description Theme-aware Leaflet base tile layers (OSM light / CARTO Dark Matter).
 */

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

export function getTileLayerConfig(forceDark = null) {
    const useDark = forceDark === null ? isDarkTheme() : Boolean(forceDark);
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
    let lastDark = isDarkTheme();
    const observer = new MutationObserver((mutations) => {
        const themeChanged = mutations.some(
            (m) =>
                m.type === 'attributes'
                && (m.attributeName === 'data-theme' || m.attributeName === 'data-bs-theme')
        );
        if (!themeChanged) return;
        const nextDark = isDarkTheme();
        if (nextDark === lastDark) return;
        lastDark = nextDark;
        // Allow CSS variables to settle (same pattern as chart theme observers).
        window.setTimeout(() => onChange(nextDark), 50);
    });
    observer.observe(document.documentElement, {
        attributes: true,
        attributeFilter: ['data-theme', 'data-bs-theme'],
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
    // Keep tiles under overlays / tracks.
    if (typeof next.setZIndex === 'function') {
        next.setZIndex(0);
    }
    layerHolder.current = next;
    return next;
}
