/**
 * @file public_map.js
 * @description Unauthenticated login-page Leaflet map (public allowlist only).
 *
 * Uses plain fetch — not apiRequest — so 401s never redirect away from login.
 */

import {
    createThemedTileLayer,
    observeThemeChange,
    swapMapTileLayer,
    isDarkTheme,
} from '/static/js/map_tiles.js';

const TRACK_COLORS = [
    '#3388ff', '#dc143c', '#008b8b', '#ff8c00',
    '#9370db', '#2e8b57', '#ff69b4', '#00ced1',
];

const AUTO_REFRESH_MS = 15 * 60 * 1000;

let publicMap = null;
let trackLayers = [];
let autoRefreshTimer = null;
let isLoading = false;
let openMissionId = null;
const publicMapTileHolder = { current: null };

function mapMarkerThemeColors() {
    const isDark = isDarkTheme();
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
    }
    const icon = refreshBtn ? refreshBtn.querySelector('i') : null;
    if (icon) {
        icon.classList.toggle('fa-spin', busy);
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

function escapeHtml(value) {
    return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

function missionDetailFields(mission) {
    const platformName = mission.platform_name || mission.display_name || mission.mission_id || 'Glider';
    const missionTitle = mission.mission_title || mission.mission_id || '';
    const platform = platformTypeLabel(mission.platform);
    const pos = mission.current_position;
    const hasPos = pos && Number.isFinite(Number(pos.lat)) && Number.isFinite(Number(pos.lon));
    const posText = hasPos
        ? `${Number(pos.lat).toFixed(4)}, ${Number(pos.lon).toFixed(4)}`
        : '';
    return {
        platformName,
        missionTitle,
        platform,
        posText,
        weeklyReportUrl: mission.weekly_report_url || '',
    };
}

function buildPopupHtml(mission) {
    const fields = missionDetailFields(mission);
    const posLine = fields.posText
        ? `<br><small>${escapeHtml(fields.posText)}</small>`
        : '';
    let reportLine = '';
    if (fields.weeklyReportUrl) {
        const href = String(fields.weeklyReportUrl).replace(/"/g, '&quot;');
        reportLine = `<br><a href="${href}" target="_blank" rel="noopener noreferrer" class="btn btn-link btn-sm p-0">View weekly report</a>`;
    }
    return `<strong>${escapeHtml(fields.platformName)}</strong><br>`
        + `<small class="text-muted">${escapeHtml(fields.platform)}</small><br>`
        + `Mission Title: ${escapeHtml(fields.missionTitle)}${posLine}${reportLine}`;
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

function captureOpenMissionId() {
    const openEl = document.querySelector('#publicDeploymentList .collapse.show');
    if (!openEl) {
        openMissionId = null;
        return;
    }
    openMissionId = openEl.getAttribute('data-mission-id') || null;
}

function expandDeploymentItem(index, { scroll = true } = {}) {
    const collapseEl = document.getElementById(`publicDeployment-${index}`);
    if (!collapseEl) return;

    const list = document.getElementById('publicDeploymentList');
    if (list) {
        list.querySelectorAll('.collapse.show').forEach((el) => {
            if (el === collapseEl) return;
            if (typeof bootstrap !== 'undefined' && bootstrap.Collapse) {
                bootstrap.Collapse.getOrCreateInstance(el, { toggle: false }).hide();
            } else {
                el.classList.remove('show');
            }
        });
    }

    if (typeof bootstrap !== 'undefined' && bootstrap.Collapse) {
        bootstrap.Collapse.getOrCreateInstance(collapseEl, { toggle: false }).show();
    } else {
        collapseEl.classList.add('show');
    }

    openMissionId = collapseEl.getAttribute('data-mission-id') || openMissionId;

    if (scroll) {
        const item = collapseEl.closest('.public-deployment-item');
        if (item && typeof item.scrollIntoView === 'function') {
            item.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
        }
    }
}

function focusMission(index) {
    const track = trackLayers[index];
    if (!publicMap || !track) return;

    expandDeploymentItem(index, { scroll: true });

    if (track.polyline) {
        const bounds = track.polyline.getBounds();
        if (bounds && bounds.isValid()) {
            const sw = bounds.getSouthWest();
            const ne = bounds.getNorthEast();
            const isPoint = sw.lat === ne.lat && sw.lng === ne.lng;
            if (!isPoint) {
                publicMap.fitBounds(bounds.pad(0.2), { maxZoom: 10 });
            } else if (track.position) {
                publicMap.setView(track.position.getLatLng(), Math.min(publicMap.getZoom(), 10) || 8);
            }
        }
    } else if (track.position) {
        publicMap.setView(track.position.getLatLng(), 8);
    }

    if (track.position) {
        track.position.openPopup();
    }
}

function bindTrackToSidebar(layer, index) {
    if (!layer) return;
    layer.on('click', () => {
        expandDeploymentItem(index, { scroll: true });
    });
}

function renderDeploymentList(missions) {
    const listEl = document.getElementById('publicDeploymentList');
    const countEl = document.getElementById('publicDeploymentCount');
    if (!listEl) return;

    captureOpenMissionId();
    listEl.innerHTML = '';

    // Caller passes only successfully plotted missions (1:1 with trackLayers).
    const plotted = Array.isArray(missions) ? missions : [];

    if (countEl) countEl.textContent = String(plotted.length);

    if (!plotted.length) {
        listEl.innerHTML = '<p class="public-deployments-empty text-muted mb-0">No active deployments</p>';
        openMissionId = null;
        return;
    }

    const fragment = document.createDocumentFragment();
    let restoreIndex = -1;

    plotted.forEach((mission, index) => {
        const fields = missionDetailFields(mission);
        const track = trackLayers[index];
        const color = (track && track.color) || TRACK_COLORS[index % TRACK_COLORS.length];
        const missionId = String(mission.mission_id || (track && track.missionId) || `mission-${index}`);
        const collapseId = `publicDeployment-${index}`;
        const headingId = `publicDeploymentHeading-${index}`;

        if (openMissionId && missionId === openMissionId) {
            restoreIndex = index;
        }

        const item = document.createElement('div');
        item.className = 'public-deployment-item';
        item.dataset.missionId = missionId;
        item.dataset.trackIndex = String(index);

        let reportHtml = '';
        if (fields.weeklyReportUrl) {
            const href = String(fields.weeklyReportUrl).replace(/"/g, '&quot;');
            reportHtml = `
                <div class="public-deployment-field">
                    <span class="public-deployment-label">Weekly report</span>
                    <a href="${href}" target="_blank" rel="noopener noreferrer">View weekly report</a>
                </div>`;
        }

        const locationHtml = fields.posText
            ? `<div class="public-deployment-field">
                    <span class="public-deployment-label">Location</span>
                    <span>${escapeHtml(fields.posText)}</span>
               </div>`
            : '';

        item.innerHTML = `
            <button class="public-deployment-toggle collapsed"
                    type="button"
                    data-bs-toggle="collapse"
                    data-bs-target="#${collapseId}"
                    aria-expanded="false"
                    aria-controls="${collapseId}"
                    id="${headingId}">
                <span class="public-deployment-swatch" style="background-color: ${escapeHtml(color)}" aria-hidden="true"></span>
                <span class="public-deployment-name">${escapeHtml(fields.platformName)}</span>
                <i class="fas fa-chevron-down public-deployment-chevron" aria-hidden="true"></i>
            </button>
            <div id="${collapseId}"
                 class="collapse public-deployment-body"
                 data-mission-id="${escapeHtml(missionId)}"
                 aria-labelledby="${headingId}">
                <div class="public-deployment-actions">
                    <button type="button" class="btn btn-primary btn-sm public-deployment-focus"
                            data-track-index="${index}">
                        Focus
                    </button>
                </div>
                <div class="public-deployment-fields">
                    <div class="public-deployment-field">
                        <span class="public-deployment-label">Platform</span>
                        <span>${escapeHtml(fields.platform)}</span>
                    </div>
                    <div class="public-deployment-field">
                        <span class="public-deployment-label">Mission Title</span>
                        <span>${escapeHtml(fields.missionTitle)}</span>
                    </div>
                    ${locationHtml}
                    ${reportHtml}
                </div>
            </div>
        `;

        fragment.appendChild(item);
    });

    listEl.appendChild(fragment);

    listEl.querySelectorAll('.public-deployment-focus').forEach((btn) => {
        btn.addEventListener('click', (event) => {
            event.preventDefault();
            event.stopPropagation();
            const index = Number(btn.getAttribute('data-track-index'));
            if (Number.isFinite(index)) focusMission(index);
        });
    });

    listEl.querySelectorAll('.public-deployment-body').forEach((collapseEl) => {
        collapseEl.addEventListener('show.bs.collapse', () => {
            openMissionId = collapseEl.getAttribute('data-mission-id') || null;
            listEl.querySelectorAll('.collapse.show').forEach((el) => {
                if (el === collapseEl) return;
                if (typeof bootstrap !== 'undefined' && bootstrap.Collapse) {
                    bootstrap.Collapse.getOrCreateInstance(el, { toggle: false }).hide();
                }
            });
        });
        collapseEl.addEventListener('hide.bs.collapse', () => {
            if (openMissionId === collapseEl.getAttribute('data-mission-id')) {
                openMissionId = null;
            }
        });
    });

    if (restoreIndex >= 0) {
        expandDeploymentItem(restoreIndex, { scroll: false });
    }
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

    const trackIndex = trackLayers.length;
    bindTrackToSidebar(polyline, trackIndex);
    bindTrackToSidebar(position, trackIndex);
    if (waypoint) bindTrackToSidebar(waypoint, trackIndex);

    trackLayers.push({
        polyline,
        position,
        waypoint,
        missionId: String(mission.mission_id || `mission-${colorIndex}`),
        color,
    });
}

function restyleTrackMarkersForTheme() {
    const theme = mapMarkerThemeColors();
    for (const track of trackLayers) {
        if (track.position) {
            track.position.setStyle({ color: theme.positionRing });
        }
        if (track.waypoint) {
            track.waypoint.setStyle({
                color: theme.waypointBorder,
                fillColor: theme.waypointFill,
            });
        }
    }
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
            renderDeploymentList([]);
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
        const plottedMissions = [];
        missions.forEach((mission) => {
            const before = trackLayers.length;
            plotMission(mission, before);
            if (trackLayers.length > before) plottedMissions.push(mission);
        });
        renderDeploymentList(plottedMissions);
        if (plottedMissions.length > 0) {
            fitToTracks();
            const generated = bundle.generated_at || 'unknown';
            const hours = bundle.window_hours != null ? bundle.window_hours : 168;
            setStatus(`Last updated ${generated} · last ${hours}h · ${plottedMissions.length} track(s)`);
        } else {
            setStatus('No public glider tracks are currently available.');
        }
    } catch (err) {
        console.error('public_map load failed', err);
        setStatus(err.message || 'Failed to load public map.', true);
        renderDeploymentList([]);
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

    publicMapTileHolder.current = createThemedTileLayer();
    publicMapTileHolder.current.addTo(publicMap);
    observeThemeChange(() => {
        swapMapTileLayer(publicMap, publicMapTileHolder);
        restyleTrackMarkersForTheme();
    });

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

    // Leaflet needs a resize after the sidebar + map layout settles.
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
