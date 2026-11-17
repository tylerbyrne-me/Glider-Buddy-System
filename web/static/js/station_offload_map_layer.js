/**
 * @file station_offload_map_layer.js
 * @description Station offload progress overlay for Leaflet maps (WG home + dedicated page).
 *
 * Fetches GeoJSON from /api/map/stations/offload-status (feature toggle station_offloads).
 * Map-only colors: green / yellow / red / white (flagged→yellow, hardware-swapped→white).
 */

import { showToast, fetchWithAuth } from '/static/js/api.js';
import { isDarkTheme } from '/static/js/map_tiles.js';

const STATUS_URL = '/api/map/stations/offload-status';
const STATION_PANE = 'stationOffloadPane';
const STATION_PANE_Z = 370;
const OFFLOAD_SHEET_URL = '/wave-glider/view_station_status.html';

const MAP_STATUS_FILL = {
    green: '#198754',
    yellow: '#ffc107',
    orange: '#ffc107',
    red: '#dc3545',
    grey: '#ffffff',
    purple: '#ffffff',
};

/** @type {import('leaflet').Map | null} */
let missionMapRef = null;

/** @type {object | null} */
let geoJsonCache = null;

/** @type {import('leaflet').LayerGroup | null} */
let markerLayerGroup = null;

/** @type {Set<string>|null} null = all prefixes */
let enabledPrefixes = null;

let isLayerEnabled = false;
let uiBound = false;

/**
 * @param {import('leaflet').Map} map
 */
export function bindStationOffloadOverlayContext(map) {
    missionMapRef = map;
}

function ensureStationPane() {
    if (!missionMapRef || typeof L === 'undefined') return;
    if (!missionMapRef.getPane(STATION_PANE)) {
        missionMapRef.createPane(STATION_PANE);
        missionMapRef.getPane(STATION_PANE).style.zIndex = String(STATION_PANE_Z);
    }
}

function escapeHtml(value) {
    return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

function mapFillForStatusColor(statusColor) {
    const key = String(statusColor || 'grey').toLowerCase();
    return MAP_STATUS_FILL[key] || MAP_STATUS_FILL.grey;
}

function mapStrokeColor() {
    return isDarkTheme() ? '#f8f9fa' : '#1a1a1a';
}

function updateStatusLine(text) {
    const el = document.getElementById('stationOffloadStatusLine');
    if (el) el.textContent = text || '';
}

function featurePassesPrefixFilter(feature) {
    if (!(enabledPrefixes instanceof Set)) return true;
    const prefix = String(feature?.properties?.array_prefix || '').toUpperCase();
    return enabledPrefixes.has(prefix);
}

function clearMarkers() {
    if (markerLayerGroup && missionMapRef) {
        try {
            missionMapRef.removeLayer(markerLayerGroup);
        } catch (_) { /* ignore */ }
    }
    markerLayerGroup = null;
}

function drawMarkers({ fitBounds = false } = {}) {
    if (!missionMapRef || typeof L === 'undefined' || !geoJsonCache) return;

    ensureStationPane();
    clearMarkers();
    markerLayerGroup = L.layerGroup([], { pane: STATION_PANE });

    const stroke = mapStrokeColor();
    const latLngs = [];
    let plotted = 0;
    const features = Array.isArray(geoJsonCache.features) ? geoJsonCache.features : [];

    features.forEach((feature) => {
        if (!featurePassesPrefixFilter(feature)) return;
        const coords = feature?.geometry?.coordinates;
        if (!Array.isArray(coords) || coords.length < 2) return;
        const lon = Number(coords[0]);
        const lat = Number(coords[1]);
        if (!Number.isFinite(lat) || !Number.isFinite(lon)) return;

        const props = feature.properties || {};
        const fill = mapFillForStatusColor(props.status_color);
        const marker = L.circleMarker([lat, lon], {
            radius: 4,
            weight: 1,
            color: stroke,
            opacity: 1,
            fillColor: fill,
            fillOpacity: 1,
            pane: STATION_PANE,
        });
        const glider = props.last_offload_by_glider
            ? `<br>Glider: ${escapeHtml(props.last_offload_by_glider)}`
            : '';
        const stationId = props.station_id || '';
        const sheetHref = `${OFFLOAD_SHEET_URL}?station=${encodeURIComponent(stationId)}`;
        marker.bindPopup(
            `<strong>${escapeHtml(stationId)}</strong><br>`
            + `${escapeHtml(props.status_text || '—')}${glider}<br>`
            + `<a href="${sheetHref}" target="_blank" rel="noopener">Open offload sheet</a>`,
        );
        markerLayerGroup.addLayer(marker);
        latLngs.push([lat, lon]);
        plotted += 1;
    });

    markerLayerGroup.addTo(missionMapRef);

    const omitted = Number(geoJsonCache?.meta?.omitted_missing_coords) || 0;
    updateStatusLine(`${plotted} plotted · ${omitted} without lat/lon`);

    if (fitBounds && latLngs.length) {
        try {
            missionMapRef.fitBounds(latLngs, { padding: [24, 24], maxZoom: 12 });
        } catch (_) { /* ignore */ }
    }
}

async function fetchGeoJson(force = false) {
    if (geoJsonCache && !force) return geoJsonCache;
    const response = await fetchWithAuth(STATUS_URL);
    if (!response.ok) {
        const detail = await response.text().catch(() => '');
        throw new Error(detail || `HTTP ${response.status}`);
    }
    geoJsonCache = await response.json();
    return geoJsonCache;
}

/**
 * Enable the station offload overlay on the bound map.
 * @param {{ fitBounds?: boolean, forceRefresh?: boolean }} [opts]
 */
export async function enableStationOffloadLayer(opts = {}) {
    const { fitBounds = false, forceRefresh = false } = opts;
    if (!missionMapRef) return;
    isLayerEnabled = true;
    updateStatusLine('Loading stations…');
    try {
        await fetchGeoJson(forceRefresh);
        drawMarkers({ fitBounds });
    } catch (error) {
        isLayerEnabled = false;
        clearMarkers();
        updateStatusLine('Failed to load stations');
        showToast(`Station offload layer: ${error.message}`, 'warning');
    }
}

export function disableStationOffloadLayer() {
    isLayerEnabled = false;
    clearMarkers();
    updateStatusLine('');
}

/**
 * Restrict visible stations by array prefix (CBS, HFX, …). null/undefined = all.
 * @param {Iterable<string>|null|undefined} prefixes
 */
export function setStationOffloadPrefixFilter(prefixes) {
    if (prefixes == null) {
        enabledPrefixes = null;
    } else {
        enabledPrefixes = new Set(
            Array.from(prefixes).map((p) => String(p).trim().toUpperCase()).filter(Boolean),
        );
    }
    if (isLayerEnabled) {
        drawMarkers({ fitBounds: false });
    }
}

export function getStationOffloadArrayPrefixes() {
    const features = Array.isArray(geoJsonCache?.features) ? geoJsonCache.features : [];
    const codes = new Set();
    features.forEach((feature) => {
        const prefix = String(feature?.properties?.array_prefix || '').toUpperCase();
        if (prefix) codes.add(prefix);
    });
    return Array.from(codes).sort((a, b) => a.localeCompare(b));
}

export async function refreshStationOffloadLayerIfActive() {
    if (!isLayerEnabled) return;
    await enableStationOffloadLayer({ fitBounds: false, forceRefresh: true });
}

/**
 * Wire home-map toggle UI when #stationOffloadOverlaySection is present.
 */
export function initStationOffloadOverlay() {
    const section = document.getElementById('stationOffloadOverlaySection');
    const toggle = document.getElementById('stationOffloadLayerToggle');
    if (!section || !toggle || uiBound) return;
    uiBound = true;

    toggle.addEventListener('change', async () => {
        if (toggle.checked) {
            await enableStationOffloadLayer({ fitBounds: false, forceRefresh: !geoJsonCache });
        } else {
            disableStationOffloadLayer();
        }
    });
}
