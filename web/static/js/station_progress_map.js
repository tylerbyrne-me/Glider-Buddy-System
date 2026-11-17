/**
 * @file station_progress_map.js
 * @description Dedicated full-page station progress map: active WG tracks + offload status layer.
 */

import { checkAuth } from '/static/js/auth.js';
import { apiRequest, showToast } from '/static/js/api.js';
import {
    createThemedTileLayer,
    observeThemeChange,
    swapMapTileLayer,
} from '/static/js/map_tiles.js';
import {
    bindStationOffloadOverlayContext,
    enableStationOffloadLayer,
    setStationOffloadPrefixFilter,
    getStationOffloadArrayPrefixes,
} from '/static/js/station_offload_map_layer.js';

const TRACK_COLORS = ['#3388ff', '#dc143c', '#32cd32', '#ff8c00', '#9370db', '#ff69b4', '#00ced1', '#ffa500'];
const PREFIX_STORAGE_KEY = 'gbs:stationProgressMapPrefixes';
const MISSION_STORAGE_KEY = 'gbs:stationProgressMapMissions';

/** @type {import('leaflet').Map | null} */
let map = null;
const tileHolder = { current: null };

/** @type {Map<string, { layer: import('leaflet').Polyline, positionLayer: import('leaflet').CircleMarker|null, color: string }>} */
const trackByMission = new Map();

/** @type {string[]} */
let activeMissions = [];

/** @type {Set<string>} */
let enabledMissions = new Set();

function escapeHtml(value) {
    return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

function hoursBack() {
    const el = document.getElementById('stationProgressHoursBack');
    const n = parseInt(el?.value || '24', 10);
    return Number.isFinite(n) && n > 0 ? String(n) : '24';
}

function loadStoredSet(key) {
    try {
        const raw = sessionStorage.getItem(key);
        if (!raw) return null;
        const parsed = JSON.parse(raw);
        if (!Array.isArray(parsed)) return null;
        return new Set(parsed.map((v) => String(v).trim()).filter(Boolean));
    } catch (_) {
        return null;
    }
}

function persistSet(key, set) {
    try {
        sessionStorage.setItem(key, JSON.stringify(Array.from(set).sort()));
    } catch (_) { /* ignore */ }
}

function setTrackStatus(text) {
    const el = document.getElementById('stationProgressTrackStatus');
    if (el) el.textContent = text || '';
}

function clearTrack(missionId) {
    const entry = trackByMission.get(missionId);
    if (!entry || !map) return;
    try {
        if (entry.layer) map.removeLayer(entry.layer);
        if (entry.positionLayer) map.removeLayer(entry.positionLayer);
    } catch (_) { /* ignore */ }
    trackByMission.delete(missionId);
}

function clearAllTracks() {
    Array.from(trackByMission.keys()).forEach(clearTrack);
}

function createTipMarker(points, color, missionId) {
    if (!points?.length || typeof L === 'undefined') return null;
    const last = points[points.length - 1];
    return L.circleMarker([last.lat, last.lon], {
        radius: 6,
        color: '#ffffff',
        weight: 2,
        fillColor: color,
        fillOpacity: 1,
    }).bindTooltip(`Mission ${escapeHtml(missionId)}`, { direction: 'top' });
}

async function loadTrack(missionId, colorIndex) {
    clearTrack(missionId);
    if (!map) return;
    const data = await apiRequest(
        `/api/map/telemetry/${encodeURIComponent(missionId)}?hours_back=${encodeURIComponent(hoursBack())}`,
        'GET',
    );
    const points = Array.isArray(data?.track_points) ? data.track_points : [];
    if (!points.length) return;
    const color = TRACK_COLORS[colorIndex % TRACK_COLORS.length];
    const layer = L.polyline(
        points.map((p) => [p.lat, p.lon]),
        { color, weight: 3, opacity: 0.85 },
    ).addTo(map);
    const positionLayer = createTipMarker(points, color, missionId);
    if (positionLayer) positionLayer.addTo(map);
    trackByMission.set(missionId, { layer, positionLayer, color });
}

async function refreshEnabledTracks() {
    if (!map) return;
    setTrackStatus('Loading tracks…');
    clearAllTracks();
    const enabled = activeMissions.filter((id) => enabledMissions.has(id));
    try {
        await Promise.all(
            enabled.map((missionId, index) => loadTrack(missionId, index).catch((err) => {
                console.warn(`Track load failed for ${missionId}:`, err);
            })),
        );
        setTrackStatus(`${trackByMission.size} track(s) shown`);
        fitMap();
    } catch (error) {
        setTrackStatus('Track load error');
        showToast(`Track load error: ${error.message}`, 'danger');
    }
}

function fitMap() {
    if (!map) return;
    const bounds = [];
    trackByMission.forEach((entry) => {
        try {
            const b = entry.layer?.getBounds?.();
            if (b?.isValid?.()) bounds.push(b);
        } catch (_) { /* ignore */ }
    });
    if (!bounds.length) {
        map.invalidateSize();
        return;
    }
    let combined = bounds[0];
    for (let i = 1; i < bounds.length; i += 1) {
        combined = combined.extend(bounds[i]);
    }
    try {
        map.invalidateSize();
        map.fitBounds(combined, { padding: [28, 28], maxZoom: 11 });
    } catch (_) { /* ignore */ }
}

function renderMissionToggles() {
    const host = document.getElementById('stationProgressMissionToggles');
    if (!host) return;
    host.innerHTML = activeMissions.map((missionId) => {
        const id = `spmMission_${missionId}`;
        const checked = enabledMissions.has(missionId) ? 'checked' : '';
        return `
            <input type="checkbox" class="btn-check" id="${escapeHtml(id)}" data-mission-id="${escapeHtml(missionId)}" autocomplete="off" ${checked}>
            <label class="btn btn-outline-primary" for="${escapeHtml(id)}">${escapeHtml(missionId)}</label>
        `;
    }).join('') || '<span class="small text-muted">No active WG missions</span>';
}

function renderPrefixToggles(prefixes) {
    const host = document.getElementById('stationProgressPrefixToggles');
    if (!host) return;
    const stored = loadStoredSet(PREFIX_STORAGE_KEY);
    const enabled = stored !== null
        ? new Set(prefixes.filter((p) => stored.has(p)))
        : new Set(prefixes);
    setStationOffloadPrefixFilter(enabled);
    host.innerHTML = prefixes.map((code) => {
        const id = `spmPrefix_${code}`;
        const checked = enabled.has(code) ? 'checked' : '';
        return `
            <input type="checkbox" class="btn-check" id="${escapeHtml(id)}" data-map-prefix="${escapeHtml(code)}" autocomplete="off" ${checked}>
            <label class="btn btn-outline-secondary" for="${escapeHtml(id)}">${escapeHtml(code)}</label>
        `;
    }).join('') || '<span class="small text-muted">No station prefixes</span>';
}

function syncPrefixesFromDom() {
    const host = document.getElementById('stationProgressPrefixToggles');
    const next = new Set();
    host?.querySelectorAll('input[data-map-prefix]').forEach((input) => {
        if (input.checked) next.add(String(input.dataset.mapPrefix || '').toUpperCase());
    });
    persistSet(PREFIX_STORAGE_KEY, next);
    setStationOffloadPrefixFilter(next);
}

function syncMissionsFromDom() {
    const host = document.getElementById('stationProgressMissionToggles');
    const next = new Set();
    host?.querySelectorAll('input[data-mission-id]').forEach((input) => {
        if (input.checked) next.add(String(input.dataset.missionId || ''));
    });
    enabledMissions = next;
    persistSet(MISSION_STORAGE_KEY, enabledMissions);
}

function initMap() {
    const el = document.getElementById('stationProgressFullMap');
    if (!el || typeof L === 'undefined') {
        throw new Error('Leaflet map container unavailable');
    }
    map = L.map(el, {
        center: [45.0, -63.0],
        zoom: 6,
        worldCopyJump: true,
    });
    tileHolder.current = createThemedTileLayer();
    tileHolder.current.addTo(map);
    observeThemeChange(() => {
        swapMapTileLayer(map, tileHolder);
    });
    bindStationOffloadOverlayContext(map);
}

async function bootstrap() {
    const authed = await checkAuth();
    if (!authed) return;

    initMap();

    try {
        const missions = await apiRequest('/api/available_missions', 'GET');
        activeMissions = Array.isArray(missions)
            ? missions.filter((m) => typeof m === 'string' && m.trim())
            : [];
    } catch (error) {
        activeMissions = [];
        showToast(`Unable to load active missions: ${error.message}`, 'warning');
    }

    const storedMissions = loadStoredSet(MISSION_STORAGE_KEY);
    if (storedMissions !== null) {
        enabledMissions = new Set(activeMissions.filter((id) => storedMissions.has(id)));
    } else {
        enabledMissions = new Set(activeMissions);
    }
    renderMissionToggles();

    await enableStationOffloadLayer({ fitBounds: false, forceRefresh: true });
    renderPrefixToggles(getStationOffloadArrayPrefixes());
    await refreshEnabledTracks();

    document.getElementById('stationProgressMissionToggles')?.addEventListener('change', async (event) => {
        if (!(event.target instanceof HTMLInputElement) || !event.target.dataset.missionId) return;
        syncMissionsFromDom();
        await refreshEnabledTracks();
    });
    document.getElementById('stationProgressMissionsAllBtn')?.addEventListener('click', async () => {
        enabledMissions = new Set(activeMissions);
        persistSet(MISSION_STORAGE_KEY, enabledMissions);
        renderMissionToggles();
        await refreshEnabledTracks();
    });
    document.getElementById('stationProgressMissionsNoneBtn')?.addEventListener('click', async () => {
        enabledMissions = new Set();
        persistSet(MISSION_STORAGE_KEY, enabledMissions);
        renderMissionToggles();
        await refreshEnabledTracks();
    });
    document.getElementById('stationProgressHoursBack')?.addEventListener('change', async () => {
        await refreshEnabledTracks();
    });

    document.getElementById('stationProgressPrefixToggles')?.addEventListener('change', (event) => {
        if (!(event.target instanceof HTMLInputElement) || !event.target.dataset.mapPrefix) return;
        syncPrefixesFromDom();
    });
    document.getElementById('stationProgressPrefixAllBtn')?.addEventListener('click', () => {
        const prefixes = getStationOffloadArrayPrefixes();
        persistSet(PREFIX_STORAGE_KEY, new Set(prefixes));
        renderPrefixToggles(prefixes);
    });
    document.getElementById('stationProgressPrefixNoneBtn')?.addEventListener('click', () => {
        persistSet(PREFIX_STORAGE_KEY, new Set());
        renderPrefixToggles(getStationOffloadArrayPrefixes());
    });
}

document.addEventListener('DOMContentLoaded', () => {
    bootstrap().catch((error) => {
        console.error(error);
        showToast(`Station progress map failed: ${error.message}`, 'danger');
    });
});
