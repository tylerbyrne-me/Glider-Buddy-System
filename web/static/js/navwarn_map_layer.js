/**
 * @file navwarn_map_layer.js
 * @description CCG NAVWARN overlays for home-page Leaflet maps.
 *
 * Active published warnings + optional area reference polygons from
 * /api/map/navwarn/* (feature toggle navwarn_map_layer).
 *
 * Active-warning UX: hide individual messages (overlapping polygons otherwise
 * steal clicks), restore from a list, and give POLYLINE / LineString features
 * a wide hit target so they open the same popup as polygons.
 */

import { showToast, fetchWithAuth } from '/static/js/api.js';
import { isDarkTheme } from '/static/js/map_tiles.js';

const ACTIVE_URL = '/api/map/navwarn/active';
const AREAS_URL = '/api/map/navwarn/areas';
const NAVWARN_PANE = 'navwarnPane';
const NAVWARN_PANE_Z = 360;
const AREA_LEVEL_DEFAULT = 'l2';
const HIDDEN_STORAGE_KEY = 'gbs.navwarn.hiddenMessageIds';
const LINE_HIT_WEIGHT = 18;
const MAX_OVERLAP_LINKS = 6;

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

/** @type {Set<number>} */
let hiddenMessageIds = loadHiddenIds();

/** @type {import('leaflet').LatLng | null} */
let lastActiveClickLatLng = null;

let navwarnUiBound = false;

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

function featureMessageId(feature) {
    const raw = feature?.properties?.messageId;
    const id = Number(raw);
    return Number.isFinite(id) ? id : null;
}

function featureLabel(feature) {
    const props = feature?.properties || {};
    if (props.seriesId) {
        return String(props.seriesId);
    }
    const id = featureMessageId(feature);
    return id != null ? `NAVWARN ${id}` : 'NAVWARN';
}

function geometryTypeRaw(feature) {
    return String(feature?.properties?.geometry_type || feature?.geometry?.type || '');
}

function isLineFeature(feature) {
    const geometryType = geometryTypeRaw(feature);
    return geometryType === 'POLYLINE'
        || geometryType === 'LineString'
        || geometryType === 'MultiLineString';
}

function geometryTypeLabel(feature) {
    const raw = geometryTypeRaw(feature);
    if (raw === 'POLYLINE' || raw === 'LineString' || raw === 'MultiLineString') {
        return 'Polyline';
    }
    if (raw === 'POLYGON' || raw === 'Polygon' || raw === 'MultiPolygon') {
        return 'Polygon';
    }
    if (raw === 'POINT' || raw === 'Point') {
        return 'Point';
    }
    return raw;
}

function isPolylineLayer(layer) {
    return typeof L !== 'undefined'
        && layer instanceof L.Polyline
        && !(layer instanceof L.Polygon);
}

function loadHiddenIds() {
    try {
        const raw = localStorage.getItem(HIDDEN_STORAGE_KEY);
        const parsed = raw ? JSON.parse(raw) : [];
        if (!Array.isArray(parsed)) {
            return new Set();
        }
        return new Set(parsed.map(Number).filter(Number.isFinite));
    } catch (_) {
        return new Set();
    }
}

function persistHiddenIds() {
    try {
        localStorage.setItem(HIDDEN_STORAGE_KEY, JSON.stringify([...hiddenMessageIds]));
    } catch (_) {
        /* private mode / quota — keep in-memory only */
    }
}

function pruneHiddenIds(collection) {
    const live = new Set(
        (collection?.features || [])
            .map(featureMessageId)
            .filter((id) => id != null)
    );
    let changed = false;
    for (const id of [...hiddenMessageIds]) {
        if (!live.has(id)) {
            hiddenMessageIds.delete(id);
            changed = true;
        }
    }
    if (changed) {
        persistHiddenIds();
    }
}

function isFeatureHidden(feature) {
    const id = featureMessageId(feature);
    return id != null && hiddenMessageIds.has(id);
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
    const isLine = isLineFeature(feature);
    return {
        color: '#d97706',
        weight: isLine ? 3 : 2,
        opacity: 0.95,
        fillColor: '#f59e0b',
        fillOpacity: dark ? 0.22 : 0.18,
        dashArray: isLine ? '6 4' : null,
        interactive: true,
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
        interactive: true,
        pane: NAVWARN_PANE,
    });
}

function attachLineHitTarget(layer) {
    if (!isPolylineLayer(layer)) {
        return;
    }

    const attach = () => {
        if (layer._navwarnHit || !layer._map || typeof L === 'undefined') {
            return;
        }
        const hit = L.polyline(layer.getLatLngs(), {
            color: '#000000',
            weight: LINE_HIT_WEIGHT,
            opacity: 0,
            fill: false,
            interactive: true,
            bubblingMouseEvents: false,
            pane: NAVWARN_PANE,
            className: 'navwarn-line-hit',
        });
        hit._navwarnHitBuffer = true;
        hit.on('click', (event) => {
            L.DomEvent.stopPropagation(event);
            lastActiveClickLatLng = event?.latlng || lastActiveClickLatLng;
            layer.fire('click', event);
        });
        hit.addTo(layer._map);
        layer._navwarnHit = hit;
    };

    const detach = () => {
        if (!layer._navwarnHit) {
            return;
        }
        try {
            layer._navwarnHit.remove();
        } catch (_) {
            /* already removed */
        }
        layer._navwarnHit = null;
    };

    layer.on('add', attach);
    layer.on('remove', detach);
    if (layer._map) {
        attach();
    }
}

function layerHitsLatLng(layer, latlng) {
    if (!layer || !missionMapRef || !latlng) {
        return false;
    }
    const point = missionMapRef.latLngToLayerPoint(latlng);
    const candidates = [layer];
    if (layer._navwarnHit) {
        candidates.push(layer._navwarnHit);
    }
    return candidates.some((candidate) => (
        typeof candidate._containsPoint === 'function'
        && candidate._containsPoint(point)
    ));
}

function collectOverlappingFeatures(latlng, currentFeature) {
    const currentId = featureMessageId(currentFeature);
    const seen = new Set();
    const others = [];
    if (!activeLeafletLayer || !latlng) {
        return others;
    }
    activeLeafletLayer.eachLayer((layer) => {
        const feature = layer.feature;
        if (!feature) {
            return;
        }
        const id = featureMessageId(feature);
        if (id == null || id === currentId || seen.has(id)) {
            return;
        }
        if (!layerHitsLatLng(layer, latlng)) {
            return;
        }
        seen.add(id);
        others.push(feature);
    });
    return others;
}

function layersForMessage(messageId) {
    const layers = [];
    if (!activeLeafletLayer || messageId == null) {
        return layers;
    }
    activeLeafletLayer.eachLayer((layer) => {
        if (featureMessageId(layer.feature) === messageId) {
            layers.push(layer);
        }
    });
    return layers;
}

function buildActivePopupHtml(feature, overlapFeatures = []) {
    const props = feature?.properties || {};
    const seriesId = props.seriesId || 'NAVWARN';
    const title = props.title || '';
    const description = props.description || '';
    const date = props.date || '';
    const charts = props.charts || '';
    const sourceUrl = props.source_url || '';
    const messageId = featureMessageId(feature);
    const kind = geometryTypeLabel(feature);
    const overlap = Array.isArray(overlapFeatures) ? overlapFeatures : [];
    const shown = overlap.slice(0, MAX_OVERLAP_LINKS);
    const extraCount = overlap.length - shown.length;

    const overlapBits = shown.map((other) => {
        const otherId = featureMessageId(other);
        if (otherId == null) {
            return escapeHtml(featureLabel(other));
        }
        return (
            `<button type="button" class="btn btn-link btn-sm p-0 align-baseline navwarn-focus-btn"`
            + ` data-message-id="${otherId}">${escapeHtml(featureLabel(other))}</button>`
        );
    });

    const parts = [
        `<strong>${escapeHtml(seriesId)}</strong>`,
        kind ? `<div class="small text-muted">${escapeHtml(kind)}</div>` : '',
        title ? `<div>${escapeHtml(title)}</div>` : '',
        date ? `<div class="small text-muted">${escapeHtml(date)}</div>` : '',
        charts ? `<div class="small">Charts: ${escapeHtml(charts)}</div>` : '',
        description ? `<div class="small mt-1">${escapeHtml(description)}</div>` : '',
        sourceUrl
            ? `<div class="mt-1"><a href="${escapeHtml(sourceUrl)}" target="_blank" rel="noopener">Official NAVWARN</a></div>`
            : '',
        overlapBits.length
            ? `<div class="small mt-2">Also here: ${overlapBits.join(', ')}`
                + (extraCount > 0 ? ` <span class="text-muted">+${extraCount} more</span>` : '')
                + `</div>`
            : '',
        messageId != null
            ? `<div class="mt-2">`
                + `<button type="button" class="btn btn-outline-secondary btn-sm navwarn-hide-btn"`
                + ` data-message-id="${messageId}">Hide this warning</button>`
                + `</div>`
            : '',
    ];
    return parts.filter(Boolean).join('');
}

function bindActivePopup(feature, layer) {
    layer.on('mousedown', (event) => {
        lastActiveClickLatLng = event?.latlng || lastActiveClickLatLng;
    });
    layer.bindPopup(() => (
        buildActivePopupHtml(feature, collectOverlappingFeatures(lastActiveClickLatLng, feature))
    ));
    layer.on('click', () => {
        if (typeof layer.bringToFront === 'function') {
            layer.bringToFront();
        }
        if (layer._navwarnHit && typeof layer._navwarnHit.bringToFront === 'function') {
            layer._navwarnHit.bringToFront();
        }
    });
}

function bindActiveFeature(feature, layer) {
    bindActivePopup(feature, layer);
    attachLineHitTarget(layer);
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
    const hiddenCount = hiddenMessageIds.size;
    const visibleCount = kind === 'areas'
        ? features.length
        : features.filter((feature) => !isFeatureHidden(feature)).length;
    const countLabel = kind === 'areas'
        ? `${visibleCount} area polygons`
        : `${visibleCount} active warning features`;
    const bits = [countLabel];
    if (kind !== 'areas' && hiddenCount) {
        bits.push(`${hiddenCount} hidden`);
    }
    if (fetchedAt) {
        bits.push(`updated ${fetchedAt}`);
    }
    if (meta.truncated) {
        bits.push('list may be truncated');
    }
    el.textContent = bits.join(' · ');
}

function ensureHiddenPanel() {
    const section = document.getElementById('navwarnOverlaySection');
    if (!section || document.getElementById('navwarnHiddenPanel')) {
        return;
    }
    const panel = document.createElement('div');
    panel.id = 'navwarnHiddenPanel';
    panel.className = 'navwarn-hidden-panel mt-2 d-none';
    panel.innerHTML = [
        '<div class="d-flex justify-content-between align-items-center">',
        '<span class="small text-muted">Hidden warnings</span>',
        '<button type="button" class="btn btn-link btn-sm py-0 navwarn-show-all-btn">Show all</button>',
        '</div>',
        '<ul id="navwarnHiddenItems" class="navwarn-hidden-items list-unstyled small mb-0"></ul>',
    ].join('');
    section.appendChild(panel);
}

function lookupFeatureByMessageId(messageId) {
    const features = activeGeoJsonCache?.features || [];
    return features.find((feature) => featureMessageId(feature) === messageId) || null;
}

function renderHiddenList() {
    ensureHiddenPanel();
    const panel = document.getElementById('navwarnHiddenPanel');
    const list = document.getElementById('navwarnHiddenItems');
    if (!panel || !list) {
        return;
    }
    const activeOn = Boolean(document.getElementById('navwarnActiveToggle')?.checked);
    const ids = [...hiddenMessageIds].sort((a, b) => a - b);
    if (!activeOn || !ids.length) {
        panel.classList.add('d-none');
        list.innerHTML = '';
        return;
    }
    panel.classList.remove('d-none');
    list.innerHTML = ids.map((id) => {
        const feature = lookupFeatureByMessageId(id);
        const label = feature ? featureLabel(feature) : `NAVWARN ${id}`;
        return (
            `<li class="d-flex justify-content-between align-items-center gap-2">`
            + `<span>${escapeHtml(label)}</span>`
            + `<button type="button" class="btn btn-link btn-sm py-0 navwarn-show-btn"`
            + ` data-message-id="${id}">Show</button>`
            + `</li>`
        );
    }).join('');
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
    pruneHiddenIds(activeGeoJsonCache);
    removeActiveLayer();
    activeLeafletLayer = L.geoJSON(activeGeoJsonCache, {
        style: activeStyle,
        pointToLayer,
        filter: (feature) => !isFeatureHidden(feature),
        onEachFeature: bindActiveFeature,
        pane: NAVWARN_PANE,
    });
    activeLeafletLayer.addTo(missionMapRef);
    updateStatusLine(activeGeoJsonCache, 'active');
    renderHiddenList();
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

function closeActivePopup() {
    if (missionMapRef && typeof missionMapRef.closePopup === 'function') {
        missionMapRef.closePopup();
    }
}

async function hideActiveMessage(messageId) {
    if (!Number.isFinite(messageId)) {
        return;
    }
    hiddenMessageIds.add(messageId);
    persistHiddenIds();
    closeActivePopup();
    if (activeLeafletLayer) {
        await enableActiveLayer();
    } else {
        renderHiddenList();
    }
}

async function showActiveMessage(messageId) {
    if (!Number.isFinite(messageId)) {
        return;
    }
    hiddenMessageIds.delete(messageId);
    persistHiddenIds();
    if (activeLeafletLayer) {
        await enableActiveLayer();
    } else {
        renderHiddenList();
    }
}

async function showAllHiddenMessages() {
    hiddenMessageIds.clear();
    persistHiddenIds();
    if (activeLeafletLayer) {
        await enableActiveLayer();
    } else {
        renderHiddenList();
    }
}

function focusActiveMessage(messageId) {
    if (!Number.isFinite(messageId)) {
        return;
    }
    const layers = layersForMessage(messageId);
    if (!layers.length) {
        return;
    }
    const preferred = lastActiveClickLatLng
        ? layers.find((layer) => layerHitsLatLng(layer, lastActiveClickLatLng)) || layers[0]
        : layers[0];
    layers.forEach((layer) => {
        if (typeof layer.bringToFront === 'function') {
            layer.bringToFront();
        }
        if (layer._navwarnHit && typeof layer._navwarnHit.bringToFront === 'function') {
            layer._navwarnHit.bringToFront();
        }
    });
    const overlap = collectOverlappingFeatures(lastActiveClickLatLng, preferred.feature);
    preferred.setPopupContent(buildActivePopupHtml(preferred.feature, overlap));
    if (lastActiveClickLatLng && typeof preferred.openPopup === 'function') {
        preferred.openPopup(lastActiveClickLatLng);
    } else if (typeof preferred.openPopup === 'function') {
        preferred.openPopup();
    }
}

function onNavwarnDocumentClick(event) {
    const hideBtn = event.target.closest('.navwarn-hide-btn');
    if (hideBtn) {
        event.preventDefault();
        hideActiveMessage(Number(hideBtn.dataset.messageId));
        return;
    }
    const showBtn = event.target.closest('.navwarn-show-btn');
    if (showBtn) {
        event.preventDefault();
        showActiveMessage(Number(showBtn.dataset.messageId));
        return;
    }
    const showAllBtn = event.target.closest('.navwarn-show-all-btn');
    if (showAllBtn) {
        event.preventDefault();
        showAllHiddenMessages();
        return;
    }
    const focusBtn = event.target.closest('.navwarn-focus-btn');
    if (focusBtn) {
        event.preventDefault();
        focusActiveMessage(Number(focusBtn.dataset.messageId));
    }
}

/**
 * Wire NAVWARN toggles when the feature-gated section is present.
 */
export function initNavwarnOverlay() {
    const section = document.getElementById('navwarnOverlaySection');
    if (!section) {
        return;
    }

    ensureHiddenPanel();
    if (!navwarnUiBound) {
        document.addEventListener('click', onNavwarnDocumentClick);
        navwarnUiBound = true;
    }

    const activeToggle = document.getElementById('navwarnActiveToggle');
    if (activeToggle) {
        activeToggle.addEventListener('change', async () => {
            if (!activeToggle.checked) {
                removeActiveLayer();
                renderHiddenList();
                return;
            }
            try {
                await enableActiveLayer();
            } catch (error) {
                const message = error?.message || 'Unknown error';
                showToast(`NAVWARN active layer error: ${message}`, 'danger');
                activeToggle.checked = false;
                removeActiveLayer();
                renderHiddenList();
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
