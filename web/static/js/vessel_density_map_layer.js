/**
 * @file vessel_density_map_layer.js
 * @description DFO NW Atlantic AIS vessel-density MapServer rasters (2025 monthly).
 *
 * Parent toggle + exclusive month radios. Tiles via /api/map/vessel-density/export
 * (feature toggle vessel_density_map_layer).
 */

import { showToast, fetchWithAuth } from '/static/js/api.js';

const META_URL = '/api/map/vessel-density/meta';
const EXPORT_URL = '/api/map/vessel-density/export';
const PANE = 'vesselDensityPane';
const PANE_Z = 340;
const DEFAULT_OPACITY = 0.55;
const TILE_SIZE = 256;

/** @type {import('leaflet').Map | null} */
let missionMapRef = null;

/** @type {object | null} */
let metaCache = null;

/** @type {import('leaflet').GridLayer | null} */
let densityLayer = null;

/** @type {number} */
let activeLayerId = 7;

/** @type {boolean} */
let isEnabled = false;

/**
 * @param {import('leaflet').Map} map
 */
export function bindVesselDensityOverlayContext(map) {
    missionMapRef = map;
}

function ensurePane() {
    if (!missionMapRef || typeof L === 'undefined') {
        return;
    }
    if (!missionMapRef.getPane(PANE)) {
        missionMapRef.createPane(PANE);
        missionMapRef.getPane(PANE).style.zIndex = String(PANE_Z);
    }
}

async function loadMeta() {
    if (metaCache) {
        return metaCache;
    }
    const response = await fetchWithAuth(META_URL);
    if (!response.ok) {
        const detail = await response.text().catch(() => '');
        throw new Error(detail || `Meta HTTP ${response.status}`);
    }
    metaCache = await response.json();
    return metaCache;
}

function selectedMonthFromUi() {
    const checked = document.querySelector('input[name="vesselDensityMonth"]:checked');
    if (!checked) {
        return null;
    }
    const month = Number(checked.value);
    return Number.isFinite(month) ? month : null;
}

function layerIdForMonth(month, meta) {
    const entry = (meta?.months || []).find((m) => m.month === month);
    if (entry && Number.isFinite(entry.layer_id)) {
        return entry.layer_id;
    }
    return 6 + month;
}

function buildExportUrlFromBounds(bounds, layerId) {
    if (!bounds || !bounds.isValid()) {
        return null;
    }
    const west = bounds.getWest();
    const south = bounds.getSouth();
    const east = bounds.getEast();
    const north = bounds.getNorth();
    const params = new URLSearchParams({
        layer_id: String(layerId),
        bbox: `${west},${south},${east},${north}`,
        size: `${TILE_SIZE},${TILE_SIZE}`,
    });
    return `${EXPORT_URL}?${params.toString()}`;
}

function createDensityGridLayer(layerId, opacity) {
    const GridLayerClass = L.GridLayer.extend({
        createTile(coords, done) {
            const tile = document.createElement('img');
            tile.alt = '';
            tile.setAttribute('role', 'presentation');
            tile.style.width = `${TILE_SIZE}px`;
            tile.style.height = `${TILE_SIZE}px`;

            const bounds = this._tileCoordsToBounds(coords);
            const url = buildExportUrlFromBounds(bounds, this.options.vesselLayerId);
            if (!url) {
                done(new Error('Invalid tile bounds'), tile);
                return tile;
            }

            let objectUrl = null;
            fetchWithAuth(url)
                .then(async (response) => {
                    if (!response.ok) {
                        const detail = await response.text().catch(() => '');
                        throw new Error(detail || `Export HTTP ${response.status}`);
                    }
                    return response.blob();
                })
                .then((blob) => {
                    objectUrl = URL.createObjectURL(blob);
                    tile.onload = () => {
                        if (objectUrl) {
                            URL.revokeObjectURL(objectUrl);
                            objectUrl = null;
                        }
                        done(null, tile);
                    };
                    tile.onerror = () => {
                        if (objectUrl) {
                            URL.revokeObjectURL(objectUrl);
                            objectUrl = null;
                        }
                        done(new Error('Tile image failed to load'), tile);
                    };
                    tile.src = objectUrl;
                })
                .catch((error) => {
                    if (objectUrl) {
                        URL.revokeObjectURL(objectUrl);
                    }
                    done(error, tile);
                });

            return tile;
        },
    });

    return new GridLayerClass({
        pane: PANE,
        opacity,
        tileSize: TILE_SIZE,
        vesselLayerId: layerId,
        updateWhenIdle: true,
        keepBuffer: 1,
        maxZoom: 12,
        minZoom: 3,
    });
}

function removeDensityLayer() {
    if (!missionMapRef || !densityLayer) {
        return;
    }
    try {
        missionMapRef.removeLayer(densityLayer);
    } catch (_) {
        /* already removed */
    }
    densityLayer = null;
}

function enableDensityLayer() {
    if (!missionMapRef || typeof L === 'undefined') {
        throw new Error('Map is not ready');
    }
    ensurePane();
    const opacity = Number(metaCache?.opacity_default) || DEFAULT_OPACITY;
    removeDensityLayer();
    densityLayer = createDensityGridLayer(activeLayerId, opacity);
    densityLayer.addTo(missionMapRef);
}

function setMonthRadiosEnabled(enabled) {
    const group = document.getElementById('vesselDensityMonthGroup');
    if (group) {
        group.classList.toggle('d-none', !enabled);
    }
    document.querySelectorAll('input[name="vesselDensityMonth"]').forEach((input) => {
        input.disabled = !enabled;
    });
}

function applyDefaultMonth(meta) {
    const defaultMonth = Number(meta?.default_month) || new Date().getUTCMonth() + 1;
    const radio = document.querySelector(
        `input[name="vesselDensityMonth"][value="${defaultMonth}"]`,
    );
    if (radio) {
        radio.checked = true;
    }
    activeLayerId = layerIdForMonth(defaultMonth, meta);
}

function wireControls(meta) {
    const parent = document.getElementById('vesselDensityToggle');
    if (!parent) {
        return;
    }

    applyDefaultMonth(meta);
    setMonthRadiosEnabled(false);

    parent.addEventListener('change', async () => {
        if (!parent.checked) {
            isEnabled = false;
            setMonthRadiosEnabled(false);
            removeDensityLayer();
            return;
        }
        try {
            const month = selectedMonthFromUi() || meta.default_month;
            activeLayerId = layerIdForMonth(month, meta);
            isEnabled = true;
            setMonthRadiosEnabled(true);
            enableDensityLayer();
        } catch (error) {
            const message = error?.message || 'Unknown error';
            showToast(`Vessel density error: ${message}`, 'danger');
            parent.checked = false;
            isEnabled = false;
            setMonthRadiosEnabled(false);
            removeDensityLayer();
        }
    });

    document.querySelectorAll('input[name="vesselDensityMonth"]').forEach((input) => {
        input.addEventListener('change', () => {
            if (!isEnabled || !parent.checked) {
                return;
            }
            const month = Number(input.value);
            activeLayerId = layerIdForMonth(month, metaCache || meta);
            try {
                enableDensityLayer();
            } catch (error) {
                const message = error?.message || 'Unknown error';
                showToast(`Vessel density error: ${message}`, 'danger');
            }
        });
    });
}

/**
 * Wire UI when the feature-gated section is present.
 */
export function initVesselDensityOverlay() {
    const section = document.getElementById('vesselDensitySection');
    if (!section) {
        return;
    }

    loadMeta()
        .then((meta) => {
            const link = document.getElementById('vesselDensityOpenDataLink');
            if (link && meta.open_data_url) {
                link.href = meta.open_data_url;
            }
            wireControls(meta);
        })
        .catch((error) => {
            const message = error?.message || 'Unknown error';
            showToast(`Unable to load vessel density meta: ${message}`, 'danger');
            const status = document.getElementById('vesselDensityStatusLine');
            if (status) {
                status.textContent = 'Failed to load vessel density catalog.';
                status.classList.add('text-danger');
            }
        });
}
