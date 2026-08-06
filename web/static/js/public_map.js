/**
 * @file public_map.js
 * @description Unauthenticated login-page Leaflet map (public allowlist only).
 *
 * Uses plain fetch — not apiRequest — so 401s never redirect away from login.
 */

const TRACK_COLORS = [
    '#3388ff', '#dc143c', '#008b8b', '#ff8c00',
    '#9370db', '#2e8b57', '#ff69b4', '#00ced1',
];

const AUTO_REFRESH_MS = 15 * 60 * 1000;

let publicMap = null;
let trackLayers = [];
let autoRefreshTimer = null;
let isLoading = false;

function mapMarkerThemeColors() {
    const isDark = document.documentElement.getAttribute('data-theme') === 'dark'
        || document.documentElement.getAttribute('data-bs-theme') === 'dark';
    return {
        positionRing: isDark ? '#f8f9fa' : '#ffffff',
        waypointFill: isDark ? '#ced4da' : '#f8f9fa',
        waypointBorder: isDark ? '#f8f9fa' : '#1a1a1a',
    };
}

function setStatus(message, isError = false) {
    const el = document.getElementById('publicMapStatus');
    if (!el) return;
    el.textContent = message || '';
    el.classList.toggle('text-danger', Boolean(isError));
    el.classList.toggle('text-muted', !isError);
}

function setToolbarBusy(busy) {
    const refreshBtn = document.getElementById('publicMapRefreshBtn');
    const kmlBtn = document.getElementById('publicMapDownloadKmlBtn');
    if (refreshBtn) {
        refreshBtn.disabled = busy;
        const icon = refreshBtn.querySelector('i');
        if (icon) {
            icon.classList.toggle('fa-spin', busy);
        }
    }
    if (kmlBtn) {
        kmlBtn.classList.toggle('disabled', busy);
        kmlBtn.setAttribute('aria-disabled', busy ? 'true' : 'false');
        if (busy) kmlBtn.setAttribute('tabindex', '-1');
        else kmlBtn.removeAttribute('tabindex');
    }
}

const PLATFORM_LABELS = {
    wave_glider: 'Wave Glider',
    slocum: 'Slocum',
};

function platformTypeLabel(platform) {
    if (PLATFORM_LABELS[platform]) return PLATFORM_LABELS[platform];
    return String(platform || 'Platform').replace(/_/g, ' ');
}

function clearTracks() {
    if (!publicMap) return;
    for (const track of trackLayers) {
        if (track.polyline) publicMap.removeLayer(track.polyline);
        if (track.position) publicMap.removeLayer(track.position);
        if (track.waypoint) publicMap.removeLayer(track.waypoint);
    }
    trackLayers = [];
}

function buildPopupHtml(mission) {
    const platformName = mission.platform_name || mission.display_name || mission.mission_id || 'Glider';
    const missionTitle = mission.mission_title || mission.mission_id || '';
    const platform = platformTypeLabel(mission.platform);
    const pos = mission.current_position;
    const posLine = pos
        ? `<br><small>${Number(pos.lat).toFixed(4)}, ${Number(pos.lon).toFixed(4)}</small>`
        : '';
    let reportLine = '';
    if (mission.weekly_report_url) {
        const href = String(mission.weekly_report_url).replace(/"/g, '&quot;');
        reportLine = `<br><a href="${href}" target="_blank" rel="noopener noreferrer" class="btn btn-link btn-sm p-0">View weekly report</a>`;
    }
    return `<strong>${escapeHtml(platformName)}</strong><br>`
        + `<small class="text-muted">${escapeHtml(platform)}</small><br>`
        + `Mission Title: ${escapeHtml(missionTitle)}${posLine}${reportLine}`;
}

function escapeHtml(value) {
    return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

function plotMission(mission, colorIndex) {
    const points = Array.isArray(mission.track_points) ? mission.track_points : [];
    if (!publicMap || points.length === 0) return;

    const color = TRACK_COLORS[colorIndex % TRACK_COLORS.length];
    const latlngs = points
        .filter((p) => Number.isFinite(p.lat) && Number.isFinite(p.lon))
        .map((p) => [p.lat, p.lon]);
    if (!latlngs.length) return;

    const polyline = L.polyline(latlngs, {
        color,
        weight: 3,
        opacity: 0.85,
    }).addTo(publicMap);
    polyline.bindPopup(buildPopupHtml(mission));

    const theme = mapMarkerThemeColors();
    const last = latlngs[latlngs.length - 1];
    const position = L.circleMarker(last, {
        radius: 8,
        color: theme.positionRing,
        weight: 3,
        fillColor: color,
        fillOpacity: 1,
        opacity: 1,
    }).addTo(publicMap);
    position.bindPopup(buildPopupHtml(mission));

    let waypoint = null;
    const wpt = mission.current_waypoint;
    if (wpt && Number.isFinite(wpt.lat) && Number.isFinite(wpt.lon)) {
        waypoint = L.circleMarker([wpt.lat, wpt.lon], {
            radius: 7,
            color: theme.waypointBorder,
            weight: 2,
            fillColor: theme.waypointFill,
            fillOpacity: 0.95,
            opacity: 1,
            dashArray: '2 2',
        }).addTo(publicMap);
        const label = wpt.label ? escapeHtml(wpt.label) : 'Waypoint';
        waypoint.bindPopup(
            `<strong>Current waypoint</strong><br>${escapeHtml(mission.platform_name || mission.display_name || mission.mission_id)}`
            + `<br>${label}<br><small>${Number(wpt.lat).toFixed(4)}, ${Number(wpt.lon).toFixed(4)}</small>`
        );
    }

    trackLayers.push({ polyline, position, waypoint });
}

function fitToTracks() {
    if (!publicMap || !trackLayers.length) return;
    const group = L.featureGroup(trackLayers.map((t) => t.polyline).filter(Boolean));
    if (!group.getLayers().length) return;
    publicMap.fitBounds(group.getBounds().pad(0.12));
}

async function loadPublicMapBundle({ forceRefresh = false } = {}) {
    if (isLoading) return;
    isLoading = true;
    setToolbarBusy(true);
    setStatus(forceRefresh ? 'Refreshing tracks…' : 'Loading map…');

    try {
        const url = forceRefresh
            ? '/api/public/map/bundle?refresh=1'
            : '/api/public/map/bundle';
        const response = await fetch(url, {
            method: 'GET',
            credentials: 'same-origin',
            headers: { Accept: 'application/json' },
        });
        if (response.status === 404) {
            setStatus('Public map is currently unavailable.', true);
            return;
        }
        if (response.status === 429) {
            setStatus('Too many refresh requests. Please wait and try again.', true);
            return;
        }
        if (!response.ok) {
            throw new Error(`Map request failed (${response.status})`);
        }
        const bundle = await response.json();
        clearTracks();
        const missions = Array.isArray(bundle.missions) ? bundle.missions : [];
        let plotted = 0;
        missions.forEach((mission, idx) => {
            const before = trackLayers.length;
            plotMission(mission, idx);
            if (trackLayers.length > before) plotted += 1;
        });
        if (plotted > 0) {
            fitToTracks();
            const generated = bundle.generated_at || 'unknown';
            const hours = bundle.window_hours != null ? bundle.window_hours : 168;
            setStatus(`Last updated ${generated} · last ${hours}h · ${plotted} track(s)`);
        } else {
            setStatus('No public glider tracks are currently available.');
        }
    } catch (err) {
        console.error('public_map load failed', err);
        setStatus(err.message || 'Failed to load public map.', true);
    } finally {
        isLoading = false;
        setToolbarBusy(false);
    }
}

async function downloadPublicKml() {
    const btn = document.getElementById('publicMapDownloadKmlBtn');
    if (btn) {
        btn.classList.add('disabled');
        btn.setAttribute('aria-disabled', 'true');
    }
    try {
        const response = await fetch('/api/public/map/kml', {
            method: 'GET',
            credentials: 'same-origin',
        });
        if (response.status === 429) {
            setStatus('Too many KML downloads. Please wait and try again.', true);
            return;
        }
        if (!response.ok) {
            throw new Error(`KML download failed (${response.status})`);
        }
        const blob = await response.blob();
        const disposition = response.headers.get('Content-Disposition') || '';
        const match = /filename="?([^"]+)"?/i.exec(disposition);
        const filename = match ? match[1] : 'public_gliders.kml';
        const objectUrl = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = objectUrl;
        link.download = filename;
        document.body.appendChild(link);
        link.click();
        link.remove();
        URL.revokeObjectURL(objectUrl);
    } catch (err) {
        console.error('public_map kml failed', err);
        setStatus(err.message || 'KML download failed.', true);
    } finally {
        if (btn) {
            btn.classList.remove('disabled');
            btn.setAttribute('aria-disabled', 'false');
        }
    }
}

function syncPublicLoginBannerOffset() {
    const nav = document.querySelector('body.page-public-login .gbs-navbar');
    if (!nav) return;
    const height = Math.ceil(nav.getBoundingClientRect().height);
    if (height > 0) {
        document.body.style.setProperty('--public-login-banner-height', `${height}px`);
    }
    if (publicMap) publicMap.invalidateSize();
}

function initializePublicMap() {
    const container = document.getElementById('publicMapContainer');
    if (!container || typeof L === 'undefined') return;

    syncPublicLoginBannerOffset();

    publicMap = L.map('publicMapContainer', {
        zoomControl: false,
        worldCopyJump: true,
    }).setView([44.6, -63.5], 6);
    L.control.zoom({ position: 'bottomright' }).addTo(publicMap);

    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 18,
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    }).addTo(publicMap);

    const refreshBtn = document.getElementById('publicMapRefreshBtn');
    if (refreshBtn) {
        refreshBtn.addEventListener('click', () => {
            loadPublicMapBundle({ forceRefresh: true });
        });
    }
    const kmlBtn = document.getElementById('publicMapDownloadKmlBtn');
    if (kmlBtn) {
        kmlBtn.addEventListener('click', (event) => {
            event.preventDefault();
            if (kmlBtn.classList.contains('disabled')) return;
            downloadPublicKml();
        });
    }

    loadPublicMapBundle({ forceRefresh: false });
    autoRefreshTimer = window.setInterval(() => {
        loadPublicMapBundle({ forceRefresh: false });
    }, AUTO_REFRESH_MS);

    // Leaflet needs a resize after the centered layout settles.
    window.setTimeout(() => {
        syncPublicLoginBannerOffset();
    }, 50);
    window.setTimeout(() => {
        syncPublicLoginBannerOffset();
    }, 250);
}

document.addEventListener('DOMContentLoaded', () => {
    const shell = document.querySelector('.public-login-shell[data-public-map-enabled="true"]');
    if (!shell) return;
    syncPublicLoginBannerOffset();
    initializePublicMap();
});

window.addEventListener('resize', () => {
    syncPublicLoginBannerOffset();
});

window.addEventListener('beforeunload', () => {
    if (autoRefreshTimer) {
        window.clearInterval(autoRefreshTimer);
        autoRefreshTimer = null;
    }
});
