/**
 * @file navwarn_map_layer.js
 * @description CCG NAVWARN overlays for home-page Leaflet maps.
 *
 * Active published warnings + optional area reference polygons from
 * /api/map/navwarn/* (feature toggle navwarn_map_layer).
 */

import { showToast, fetchWithAuth } from '/static/js/api.js';
import { isDarkTheme } from '/static/js/map_tiles.js';

const ACTIVE_URL = '/api/map/navwarn/active';
const AREAS_URL = '/api/map/navwarn/areas';
const NAVWARN_PANE = 'navwarnPane';
const NAVWARN_PANE_Z = 360;
const AREA_LEVEL_DEFAULT = 'l2';

/** @type {import('leaflet').Map | null} */
let missionMapRef = null;

/** @type {object | null} */
let activeGeoJsonCache = null;

/** @type {object | null} */
let areasGeoJsonCache = null;

/** @type {import('leaflet').GeoJSON | null} */
let activeLeafletLayer = null;

/** @type {import('leaflet').GeoJSON | null} */
let areasLeafletLayer = null;

/**
 * @param {import('leaflet').Map} map
 */
export function bindNavwarnOverlayContext(map) {
    missionMapRef = map;
}

function ensureNavwarnPane() {
    if (!missionMapRef || typeof L === 'undefined') {
        return;
    }
    if (!missionMapRef.getPane(NAVWARN_PANE)) {
        missionMapRef.createPane(NAVWARN_PANE);
        missionMapRef.getPane(NAVWARN_PANE).style.zIndex = String(NAVWARN_PANE_Z);
    }
}

function escapeHtml(value) {
    return String(value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

async function loadGeoJson(url) {
    const response = await fetchWithAuth(url);
    if (!response.ok) {
        const detail = await response.text().catch(() => '');
        throw new Error(detail || `NAVWARN HTTP ${response.status}`);
    }
    return response.json();
}

function activeStyle(feature) {
    const dark = isDarkTheme();
    const geometryType = feature?.properties?.geometry_type || feature?.geometry?.type || '';
    const isLine = geometryType === 'POLYLINE' || geometryType === 'LineString';
    return {
        color: '#d97706',
        weight: isLine ? 3 : 2,
        opacity: 0.95,
        fillColor: '#f59e0b',
        fillOpacity: dark ? 0.22 : 0.18,
        dashArray: isLine ? '6 4' : null,
        pane: NAVWARN_PANE,
    };
}

function areasStyle() {
    const dark = isDarkTheme();
    return {
        color: dark ? '#94a3b8' : '#64748b',
        weight: 1.5,
        opacity: 0.85,
        fillColor: dark ? '#64748b' : '#94a3b8',
        fillOpacity: dark ? 0.08 : 0.06,
        pane: NAVWARN_PANE,
    };
}

function pointToLayer(feature, latlng) {
    return L.circleMarker(latlng, {
        radius: 6,
        color: '#d97706',
        weight: 2,
        opacity: 0.95,
        fillColor: '#fbbf24',
        fillOpacity: 0.85,
        pane: NAVWARN_PANE,
    });
}

function bindActivePopup(feature, layer) {
    const props = feature?.properties || {};
    const seriesId = props.seriesId || 'NAVWARN';
    const title = props.title || '';
    const description = props.description || '';
    const date = props.date || '';
    const charts = props.charts || '';
    const sourceUrl = props.source_url || '';
    const parts = [
        `<strong>${escapeHtml(seriesId)}</strong>`,
        title ? `<div>${escapeHtml(title)}</div>` : '',
        date ? `<div class="small text-muted">${escapeHtml(date)}</div>` : '',
        charts ? `<div class="small">Charts: ${escapeHtml(charts)}</div>` : '',
        description ? `<div class="small mt-1">${escapeHtml(description)}</div>` : '',
        sourceUrl
            ? `<div class="mt-1"><a href="${escapeHtml(sourceUrl)}" target="_blank" rel="noopener">Official NAVWARN</a></div>`
            : '',
    ];
    layer.bindPopup(parts.filter(Boolean).join(''));
}

function bindAreaPopup(feature, layer) {
    const props = feature?.properties || {};
    const name = props.name || `Area ${props.areaId || ''}`;
    layer.bindPopup(
        `<strong>${escapeHtml(name)}</strong>`
        + `<div class="small text-muted">CCG NAVWARN area (reference)</div>`
    );
}

function updateStatusLine(collection, kind) {
    const el = document.getElementById('navwarnStatusLine');
    if (!el) {
        return;
    }
    const features = Array.isArray(collection?.features) ? collection.features : [];
    const meta = collection?.metadata || {};
    const fetchedAt = meta.fetched_at ? String(meta.fetched_at) : '';
    const countLabel = kind === 'areas'
        ? `${features.length} area polygons`
        : `${features.length} active warning features`;
    const bits = [countLabel];
    if (fetchedAt) {
        bits.push(`updated ${fetchedAt}`);
    }
    if (meta.truncated) {
        bits.push('list may be truncated');
    }
    el.textContent = bits.join(' · ');
}

function removeActiveLayer() {
    if (!missionMapRef || !activeLeafletLayer) {
        return;
    }
    try {
        missionMapRef.removeLayer(activeLeafletLayer);
    } catch (_) {
        /* already removed */
    }
    activeLeafletLayer = null;
}

function removeAreasLayer() {
    if (!missionMapRef || !areasLeafletLayer) {
        return;
    }
    try {
        missionMapRef.removeLayer(areasLeafletLayer);
    } catch (_) {
        /* already removed */
    }
    areasLeafletLayer = null;
}

async function enableActiveLayer() {
    if (!missionMapRef || typeof L === 'undefined') {
        throw new Error('Map is not ready');
    }
    ensureNavwarnPane();
    if (!activeGeoJsonCache) {
        activeGeoJsonCache = await loadGeoJson(ACTIVE_URL);
    }
    removeActiveLayer();
    activeLeafletLayer = L.geoJSON(activeGeoJsonCache, {
        style: activeStyle,
        pointToLayer,
        onEachFeature: bindActivePopup,
        pane: NAVWARN_PANE,
    });
    activeLeafletLayer.addTo(missionMapRef);
    updateStatusLine(activeGeoJsonCache, 'active');
}

async function enableAreasLayer() {
    if (!missionMapRef || typeof L === 'undefined') {
        throw new Error('Map is not ready');
    }
    ensureNavwarnPane();
    if (!areasGeoJsonCache) {
        areasGeoJsonCache = await loadGeoJson(AREAS_URL);
    }
    removeAreasLayer();
    const filtered = {
        ...areasGeoJsonCache,
        features: (areasGeoJsonCache.features || []).filter((feature) => {
            const level = feature?.properties?.level || AREA_LEVEL_DEFAULT;
            return level === AREA_LEVEL_DEFAULT;
        }),
    };
    areasLeafletLayer = L.geoJSON(filtered, {
        style: areasStyle,
        onEachFeature: bindAreaPopup,
        pane: NAVWARN_PANE,
    });
    areasLeafletLayer.addTo(missionMapRef);
    updateStatusLine(filtered, 'areas');
}

/**
 * Wire NAVWARN toggles when the feature-gated section is present.
 */
export function initNavwarnOverlay() {
    const section = document.getElementById('navwarnOverlaySection');
    if (!section) {
        return;
    }

    const activeToggle = document.getElementById('navwarnActiveToggle');
    if (activeToggle) {
        activeToggle.addEventListener('change', async () => {
            if (!activeToggle.checked) {
                removeActiveLayer();
                return;
            }
            try {
                await enableActiveLayer();
            } catch (error) {
                const message = error?.message || 'Unknown error';
                showToast(`NAVWARN active layer error: ${message}`, 'danger');
                activeToggle.checked = false;
                removeActiveLayer();
            }
        });
    }

    const areasToggle = document.getElementById('navwarnAreasToggle');
    if (areasToggle) {
        areasToggle.addEventListener('change', async () => {
            if (!areasToggle.checked) {
                removeAreasLayer();
                return;
            }
            try {
                await enableAreasLayer();
            } catch (error) {
                const message = error?.message || 'Unknown error';
                showToast(`NAVWARN areas layer error: ${message}`, 'danger');
                areasToggle.checked = false;
                removeAreasLayer();
            }
        });
    }
}
