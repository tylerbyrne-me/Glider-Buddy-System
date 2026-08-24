/**
 * @file ciops_ice_map_layer.js
 * @description MSC GeoMet CIOPS-East sea-ice concentration WMS overlay.
 *
 * Parent toggle + hourly forecast time slider. Tiles via /api/map/ciops-ice/export
 * (feature toggle ciops_ice_map_layer).
 */

import { showToast, fetchWithAuth } from '/static/js/api.js';

const META_URL = '/api/map/ciops-ice/meta';
const EXPORT_URL = '/api/map/ciops-ice/export';
const LEGEND_URL = '/api/map/ciops-ice/legend';
const PANE = 'ciopsIcePane';
const PANE_Z = 345;
const DEFAULT_OPACITY = 0.65;
const TILE_SIZE = 256;

/** @type {import('leaflet').Map | null} */
let missionMapRef = null;

/** @type {object | null} */
let metaCache = null;

/** @type {import('leaflet').GridLayer | null} */
let iceLayer = null;

/** @type {string} */
let activeTime = '';

/** @type {string} */
let activeStyle = 'SEA_ICECONC-CIS';

/** @type {boolean} */
let isEnabled = false;

/** @type {string | null} */
let legendObjectUrl = null;

/**
 * @param {import('leaflet').Map} map
 */
export function bindCiopsIceOverlayContext(map) {
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

/**
 * @param {string} iso
 * @returns {string}
 */
function formatValidLabel(iso) {
    if (!iso) {
        return '';
    }
    const match = String(iso).match(
        /^(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2})(?::\d{2})?Z$/,
    );
    if (!match) {
        return iso;
    }
    return `Valid ${match[1]} ${match[2]}:${match[3]} UTC`;
}

function updateStatusLine() {
    const status = document.getElementById('ciopsIceStatusLine');
    if (!status) {
        return;
    }
    const ref = metaCache?.reference_time
        ? ` · run ${formatValidLabel(metaCache.reference_time).replace(/^Valid /, '')}`
        : '';
    status.textContent = `${formatValidLabel(activeTime)}${ref}`;
    status.classList.remove('text-danger');
}

function setControlsVisible(enabled) {
    const controls = document.getElementById('ciopsIceControls');
    if (controls) {
        controls.classList.toggle('d-none', !enabled);
    }
    const slider = document.getElementById('ciopsIceTimeSlider');
    if (slider) {
        slider.disabled = !enabled;
    }
}

/**
 * @param {import('leaflet').LatLngBounds} bounds
 * @param {string} timeIso
 * @param {string} style
 */
function buildExportUrlFromBounds(bounds, timeIso, style) {
    if (!bounds || !bounds.isValid() || !timeIso) {
        return null;
    }
    const west = bounds.getWest();
    const south = bounds.getSouth();
    const east = bounds.getEast();
    const north = bounds.getNorth();
    const params = new URLSearchParams({
        bbox: `${west},${south},${east},${north}`,
        size: `${TILE_SIZE},${TILE_SIZE}`,
        time: timeIso,
        style,
    });
    return `${EXPORT_URL}?${params.toString()}`;
}

function createIceGridLayer(timeIso, style, opacity) {
    const GridLayerClass = L.GridLayer.extend({
        createTile(coords, done) {
            const tile = document.createElement('img');
            tile.alt = '';
            tile.setAttribute('role', 'presentation');
            tile.style.width = `${TILE_SIZE}px`;
            tile.style.height = `${TILE_SIZE}px`;

            const bounds = this._tileCoordsToBounds(coords);
            const url = buildExportUrlFromBounds(
                bounds,
                this.options.ciopsTime,
                this.options.ciopsStyle,
            );
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
        ciopsTime: timeIso,
        ciopsStyle: style,
        updateWhenIdle: true,
        keepBuffer: 1,
        maxZoom: 12,
        minZoom: 3,
    });
}

function removeIceLayer() {
    if (!missionMapRef || !iceLayer) {
        return;
    }
    try {
        missionMapRef.removeLayer(iceLayer);
    } catch (_) {
        /* already removed */
    }
    iceLayer = null;
}

function enableIceLayer() {
    if (!missionMapRef || typeof L === 'undefined') {
        throw new Error('Map is not ready');
    }
    if (!activeTime) {
        throw new Error('No forecast time selected');
    }
    ensurePane();
    const opacity = Number(metaCache?.opacity_default) || DEFAULT_OPACITY;
    removeIceLayer();
    iceLayer = createIceGridLayer(activeTime, activeStyle, opacity);
    iceLayer.addTo(missionMapRef);
    updateStatusLine();
}

async function loadLegend(style) {
    const img = document.getElementById('ciopsIceLegendImg');
    if (!img) {
        return;
    }
    const params = new URLSearchParams({ style });
    const response = await fetchWithAuth(`${LEGEND_URL}?${params.toString()}`);
    if (!response.ok) {
        const detail = await response.text().catch(() => '');
        throw new Error(detail || `Legend HTTP ${response.status}`);
    }
    const blob = await response.blob();
    if (legendObjectUrl) {
        URL.revokeObjectURL(legendObjectUrl);
        legendObjectUrl = null;
    }
    legendObjectUrl = URL.createObjectURL(blob);
    img.src = legendObjectUrl;
    img.classList.remove('d-none');
}

/**
 * @param {object} meta
 */
function applyDefaultTime(meta) {
    const times = Array.isArray(meta?.times) ? meta.times : [];
    const defaultTime = meta?.default_time || times[0] || '';
    activeTime = defaultTime;
    activeStyle = meta?.style || 'SEA_ICECONC-CIS';

    const slider = document.getElementById('ciopsIceTimeSlider');
    if (slider && times.length) {
        slider.min = '0';
        slider.max = String(Math.max(0, times.length - 1));
        slider.step = '1';
        const idx = Math.max(0, times.indexOf(defaultTime));
        slider.value = String(idx >= 0 ? idx : 0);
    }
    updateStatusLine();
}

/**
 * @param {object} meta
 */
function wireControls(meta) {
    const parent = document.getElementById('ciopsIceToggle');
    if (!parent) {
        return;
    }

    applyDefaultTime(meta);
    setControlsVisible(false);

    parent.addEventListener('change', async () => {
        if (!parent.checked) {
            isEnabled = false;
            setControlsVisible(false);
            removeIceLayer();
            return;
        }
        try {
            isEnabled = true;
            setControlsVisible(true);
            await loadLegend(activeStyle);
            enableIceLayer();
        } catch (error) {
            const message = error?.message || 'Unknown error';
            showToast(`CIOPS ice error: ${message}`, 'danger');
            parent.checked = false;
            isEnabled = false;
            setControlsVisible(false);
            removeIceLayer();
        }
    });

    const slider = document.getElementById('ciopsIceTimeSlider');
    if (slider) {
        slider.addEventListener('input', () => {
            const times = Array.isArray(metaCache?.times) ? metaCache.times : [];
            const idx = Number(slider.value);
            if (!Number.isFinite(idx) || idx < 0 || idx >= times.length) {
                return;
            }
            activeTime = times[idx];
            updateStatusLine();
            if (!isEnabled || !parent.checked) {
                return;
            }
            try {
                enableIceLayer();
            } catch (error) {
                const message = error?.message || 'Unknown error';
                showToast(`CIOPS ice error: ${message}`, 'danger');
            }
        });
    }
}

/**
 * Wire UI when the feature-gated section is present.
 */
export function initCiopsIceOverlay() {
    const section = document.getElementById('ciopsIceSection');
    if (!section) {
        return;
    }

    loadMeta()
        .then((meta) => {
            const link = document.getElementById('ciopsIceOpenDataLink');
            if (link && meta.open_data_url) {
                link.href = meta.open_data_url;
            }
            wireControls(meta);
        })
        .catch((error) => {
            const message = error?.message || 'Unknown error';
            showToast(`Unable to load CIOPS ice meta: ${message}`, 'danger');
            const status = document.getElementById('ciopsIceStatusLine');
            if (status) {
                status.textContent = 'Failed to load ice forecast catalog.';
                status.classList.add('text-danger');
            }
        });
}
