/**
 * @file vector_map_layer.js
 * @description Static GeoJSON reference-zone overlays for home-page Leaflet maps.
 *
 * Builds toggles from GET /api/map/layers (feature toggle map_vector_layers).
 */

import { showToast, fetchWithAuth } from '/static/js/api.js';
import { isDarkTheme } from '/static/js/map_tiles.js';

const CATALOG_URL = '/api/map/layers';
const REFERENCE_ZONES_PANE = 'referenceZonesPane';
const REFERENCE_ZONES_PANE_Z = 350;

/** Prefer a stable display order when present in the catalog. */
const LAYER_ORDER = [
    'gosl_dsz',
    'gosl_safe_zones',
    'dfo_lobster_lfa_2022',
    'dfo_fma_crab',
    'dfo_fma_snow_crab',
    'dfo_fma_scallop',
    'dfo_fma_capelin',
    'dfo_fma_mackerel',
    'dfo_fma_herring',
    'dfo_fma_squid',
    'dfo_fma_salmon',
    'dfo_fma_northern_shrimp',
    'noaa_shipping_lanes_nw_atlantic',
];

/** @type {import('leaflet').Map | null} */
let missionMapRef = null;

/** @type {Array<{id: string, name: string, description?: string, style?: object, bounds?: number[]}> | null} */
let catalogCache = null;

/** @type {Map<string, object>} layerId -> GeoJSON FeatureCollection */
const geojsonCache = new Map();

/** @type {Map<string, import('leaflet').GeoJSON>} layerId -> Leaflet layer */
const activeLayers = new Map();

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

function sortCatalog(layers) {
    const orderIndex = new Map(LAYER_ORDER.map((id, i) => [id, i]));
    return [...layers].sort((a, b) => {
        const ai = orderIndex.has(a.id) ? orderIndex.get(a.id) : 1000;
        const bi = orderIndex.has(b.id) ? orderIndex.get(b.id) : 1000;
        if (ai !== bi) return ai - bi;
        return String(a.name || a.id).localeCompare(String(b.name || b.id));
    });
}

function shortLabel(entry) {
    const name = String(entry?.name || entry?.id || 'Layer');
    return name
        .replace(/^DFO FMA\s+/i, '')
        .replace(/^DFO Lobster\s+/i, 'Lobster ')
        .replace(/^NOAA Shipping Lanes.*/i, 'NOAA Shipping')
        .replace(/^GOSL\s+/i, 'GOSL ');
}

function toggleIdForLayer(layerId) {
    return `vectorLayerToggle_${String(layerId).replace(/[^A-Za-z0-9_-]/g, '_')}`;
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
    const props = feature?.properties || {};
    const name =
        props.name
        || props.Name
        || props.area_fma
        || props.OBJNAM
        || (props.LFA != null ? `LFA ${props.LFA}` : null)
        || props.THEMELAYER
        || 'Zone';
    const theme = props.THEMELAYER && String(props.THEMELAYER) !== String(name)
        ? `<br><small>${escapeHtml(String(props.THEMELAYER))}</small>`
        : '';
    const species = props.species && String(props.species).trim()
        ? `<br><small>Species: ${escapeHtml(String(props.species))}</small>`
        : '';
    const mls = props.MLS != null && String(props.MLS).trim()
        ? `<br><small>MLS: ${escapeHtml(String(props.MLS))}</small>`
        : '';
    layer.bindPopup(`<strong>${escapeHtml(String(name))}</strong>${theme}${species}${mls}`);
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

function wireToggle(toggle, layerId) {
    toggle.addEventListener('change', async () => {
        if (!toggle.checked) {
            removeLayer(layerId);
            return;
        }
        try {
            await enableLayer(layerId);
        } catch (error) {
            const message = error?.message || 'Unknown error';
            showToast(`Map layer error (${layerId}): ${message}`, 'danger');
            toggle.checked = false;
            removeLayer(layerId);
        }
    });
}

function renderCatalogToggles(layers) {
    const group = document.getElementById('vectorLayerToggleGroup');
    if (!group) {
        return;
    }
    group.replaceChildren();
    const sorted = sortCatalog(layers.filter((entry) => entry && entry.id));
    if (!sorted.length) {
        const empty = document.createElement('small');
        empty.className = 'text-muted';
        empty.textContent = 'No reference layers in catalog.';
        group.appendChild(empty);
        return;
    }
    for (const entry of sorted) {
        const toggleId = toggleIdForLayer(entry.id);
        const input = document.createElement('input');
        input.type = 'checkbox';
        input.className = 'btn-check';
        input.id = toggleId;
        input.autocomplete = 'off';
        input.dataset.layerId = entry.id;

        const label = document.createElement('label');
        label.className = 'btn btn-outline-primary';
        label.htmlFor = toggleId;
        label.title = entry.description || entry.name || entry.id;
        label.textContent = shortLabel(entry);

        group.appendChild(input);
        group.appendChild(label);
        wireToggle(input, entry.id);
    }
}

/**
 * Build catalog toggles when the feature-gated section is present.
 */
export function initVectorOverlay() {
    const section = document.getElementById('vectorOverlaySection');
    if (!section) {
        return;
    }

    loadCatalog()
        .then((layers) => {
            renderCatalogToggles(layers);
        })
        .catch((error) => {
            const message = error?.message || 'Unknown error';
            showToast(`Unable to load map layer catalog: ${message}`, 'danger');
            const group = document.getElementById('vectorLayerToggleGroup');
            if (group) {
                group.innerHTML = '<small class="text-danger">Failed to load layer catalog.</small>';
            }
        });
}
