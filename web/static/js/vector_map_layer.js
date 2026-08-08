/**
 * @file vector_map_layer.js
 * @description Static GeoJSON reference-zone overlays for home-page Leaflet maps.
 *
 * Catalog + geometry from /api/map/layers (feature toggle map_vector_layers).
 * GOSL DSZ and safe-zone toggles share one catalog fetch and per-layer cache.
 */

import { showToast, fetchWithAuth } from '/static/js/api.js';
import { isDarkTheme } from '/static/js/map_tiles.js';

const CATALOG_URL = '/api/map/layers';
const REFERENCE_ZONES_PANE = 'referenceZonesPane';
const REFERENCE_ZONES_PANE_Z = 350;

/** @type {import('leaflet').Map | null} */
let missionMapRef = null;

/** @type {Array<{id: string, name: string, description?: string, style?: object, bounds?: number[]}> | null} */
let catalogCache = null;

/** @type {Map<string, object>} layerId -> GeoJSON FeatureCollection */
const geojsonCache = new Map();

/** @type {Map<string, import('leaflet').GeoJSON>} layerId -> Leaflet layer */
const activeLayers = new Map();

const TOGGLE_BINDINGS = [
    { toggleId: 'goslDszToggle', layerId: 'gosl_dsz' },
    { toggleId: 'goslSafeZonesToggle', layerId: 'gosl_safe_zones' },
];

/**
 * @param {import('leaflet').Map} map
 */
export function bindVectorOverlayContext(map) {
    missionMapRef = map;
}

function ensureReferenceZonesPane() {
    if (!missionMapRef || typeof L === 'undefined') {
        return;
    }
    if (!missionMapRef.getPane(REFERENCE_ZONES_PANE)) {
        missionMapRef.createPane(REFERENCE_ZONES_PANE);
        missionMapRef.getPane(REFERENCE_ZONES_PANE).style.zIndex = String(REFERENCE_ZONES_PANE_Z);
    }
}

async function loadCatalog() {
    if (catalogCache) {
        return catalogCache;
    }
    const response = await fetchWithAuth(CATALOG_URL);
    if (!response.ok) {
        const detail = await response.text().catch(() => '');
        throw new Error(detail || `Catalog HTTP ${response.status}`);
    }
    const payload = await response.json();
    catalogCache = Array.isArray(payload?.layers) ? payload.layers : [];
    return catalogCache;
}

function findCatalogEntry(layerId) {
    if (!catalogCache) {
        return null;
    }
    return catalogCache.find((entry) => entry && entry.id === layerId) || null;
}

async function loadGeoJson(layerId) {
    if (geojsonCache.has(layerId)) {
        return geojsonCache.get(layerId);
    }
    const response = await fetchWithAuth(`${CATALOG_URL}/${encodeURIComponent(layerId)}`);
    if (!response.ok) {
        const detail = await response.text().catch(() => '');
        throw new Error(detail || `Layer HTTP ${response.status}`);
    }
    const geojson = await response.json();
    geojsonCache.set(layerId, geojson);
    return geojson;
}

function resolveStyle(catalogEntry) {
    const base = catalogEntry?.style || {};
    const dark = isDarkTheme();
    const color = base.color || '#3388ff';
    const fillColor = base.fillColor || color;
    return {
        color,
        weight: Number.isFinite(base.weight) ? base.weight : 2,
        opacity: Number.isFinite(base.opacity) ? base.opacity : 0.9,
        fillColor,
        fillOpacity: Number.isFinite(base.fillOpacity)
            ? base.fillOpacity
            : (dark ? 0.18 : 0.12),
        pane: REFERENCE_ZONES_PANE,
    };
}

function bindFeaturePopup(feature, layer) {
    const name = feature?.properties?.name || feature?.properties?.Name || 'Zone';
    layer.bindPopup(`<strong>${escapeHtml(String(name))}</strong>`);
}

function escapeHtml(value) {
    return String(value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

function removeLayer(layerId) {
    if (!missionMapRef) {
        return;
    }
    const existing = activeLayers.get(layerId);
    if (existing) {
        try {
            missionMapRef.removeLayer(existing);
        } catch (_) {
            /* already removed */
        }
        activeLayers.delete(layerId);
    }
}

async function enableLayer(layerId) {
    if (!missionMapRef || typeof L === 'undefined') {
        throw new Error('Map is not ready');
    }
    ensureReferenceZonesPane();
    await loadCatalog();
    const catalogEntry = findCatalogEntry(layerId);
    if (!catalogEntry) {
        throw new Error(`Unknown layer: ${layerId}`);
    }
    const geojson = await loadGeoJson(layerId);
    removeLayer(layerId);
    const leafletLayer = L.geoJSON(geojson, {
        style: () => resolveStyle(catalogEntry),
        onEachFeature: bindFeaturePopup,
        pane: REFERENCE_ZONES_PANE,
    });
    leafletLayer.addTo(missionMapRef);
    activeLayers.set(layerId, leafletLayer);
}

/**
 * Wire GOSL DSZ / safe-zone toggles when the feature-gated section is present.
 */
export function initVectorOverlay() {
    const section = document.getElementById('vectorOverlaySection');
    if (!section) {
        return;
    }

    for (const binding of TOGGLE_BINDINGS) {
        const toggle = document.getElementById(binding.toggleId);
        if (!toggle) {
            continue;
        }
        toggle.addEventListener('change', async () => {
            if (!toggle.checked) {
                removeLayer(binding.layerId);
                return;
            }
            try {
                await enableLayer(binding.layerId);
            } catch (error) {
                const message = error?.message || 'Unknown error';
                showToast(`Map layer error (${binding.layerId}): ${message}`, 'danger');
                toggle.checked = false;
                removeLayer(binding.layerId);
            }
        });
    }
}
