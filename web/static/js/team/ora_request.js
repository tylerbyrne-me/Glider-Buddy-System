import { apiRequest, getAuthHeaders, showToast } from '/static/js/api.js';
import { createThemedTileLayer, observeThemeChange, swapMapTileLayer } from '/static/js/map_tiles.js';
import { bindVectorOverlayContext, initVectorOverlay } from '/static/js/vector_map_layer.js';
import { bindNavwarnOverlayContext, initNavwarnOverlay } from '/static/js/navwarn_map_layer.js';
import { bindVesselDensityOverlayContext, initVesselDensityOverlay } from '/static/js/vessel_density_map_layer.js';
import { bindCiopsIceOverlayContext, initCiopsIceOverlay } from '/static/js/ciops_ice_map_layer.js';

const OPS_EMAIL = 'opscenter@liquid-robotics.com';

let draftId = null;
let devices = [];
let coordinates = [];
let boxClicks = [];
let missions = [];
let map = null;
let tileHolder = { current: null };
let drawLayer = null;
let trackLayer = null;
let requesterDefault = '';

const $ = (id) => document.getElementById(id);

function radioValue(name) {
    const checked = document.querySelector(`input[name="${name}"]:checked`);
    return checked ? checked.value : null;
}

function setRadio(name, value) {
    document.querySelectorAll(`input[name="${name}"]`).forEach((input) => {
        input.checked = value != null && input.value === String(value);
    });
}

function selectedPurposes() {
    return [...document.querySelectorAll('input[name="oraPurpose"]:checked')].map((input) => input.value);
}

function setPurposes(values) {
    const chosen = new Set(values || []);
    document.querySelectorAll('input[name="oraPurpose"]').forEach((input) => {
        input.checked = chosen.has(input.value);
    });
}

function coordinateMode() {
    return radioValue('oraMode') || 'course';
}

function updateSubject() {
    const title = $('oraTitle').value.trim();
    const hull = $('oraHull').value.trim();
    const label = title || hull || 'ORA request';
    $('oraSubject').textContent = `ORA request — ${label}`;
}

function emptyDevice() {
    return { name: '', power_draw: '', duty_cycle: '', source: 'manual', included: true };
}

function payload() {
    return {
        title: $('oraTitle').value.trim() || null,
        catalog_mission_id: $('oraMission').value || null,
        hull_name: $('oraHull').value.trim() || null,
        requester: $('oraRequester').value.trim(),
        project_code: $('oraProjectCode').value.trim() || null,
        project_code_other: $('oraProjectOther').value.trim() || null,
        client: $('oraClient').value.trim() || null,
        dates_of_operation: $('oraDates').value.trim() || null,
        purposes: selectedPurposes(),
        priority: radioValue('oraPriority') ? Number(radioValue('oraPriority')) : null,
        coordinate_mode: coordinateMode(),
        coordinates: coordinates.map((point) => ({
            label: point.label || '',
            lat: point.lat === '' || point.lat == null ? null : Number(point.lat),
            lon: point.lon === '' || point.lon == null ? null : Number(point.lon),
            comment: point.comment || '',
        })),
        vehicle_model: radioValue('oraVehicle'),
        umbilical_m: radioValue('oraUmbilical'),
        towing: radioValue('oraTowing'),
        towed_device: $('oraTowedDevice').value.trim() || null,
        ecos_up_to_date: radioValue('oraEcos'),
        sv3_software_version: $('oraSoftware').value.trim() || null,
        apu_count: $('oraApus').value.trim() || null,
        smc_version: $('oraSmc').value.trim() || null,
        devices,
        notes: $('oraNotes').value.trim() || null,
    };
}

function applyDraft(draft) {
    draftId = draft.id ?? null;
    $('oraTitle').value = draft.title || '';
    $('oraMission').value = draft.catalog_mission_id || '';
    $('oraHull').value = draft.hull_name || '';
    $('oraRequester').value = draft.requester || requesterDefault;
    $('oraProjectCode').value = draft.project_code || '';
    $('oraProjectOther').value = draft.project_code_other || '';
    $('oraClient').value = draft.client || '';
    $('oraDates').value = draft.dates_of_operation || '';
    setPurposes(draft.purposes || []);
    setRadio('oraPriority', draft.priority);
    setRadio('oraMode', draft.coordinate_mode || 'course');
    setRadio('oraVehicle', draft.vehicle_model);
    setRadio('oraUmbilical', draft.umbilical_m);
    setRadio('oraTowing', draft.towing);
    $('oraTowedDevice').value = draft.towed_device || '';
    setRadio('oraEcos', draft.ecos_up_to_date);
    $('oraSoftware').value = draft.sv3_software_version || '';
    $('oraApus').value = draft.apu_count || '';
    $('oraSmc').value = draft.smc_version || '';
    $('oraNotes').value = draft.notes || '';
    devices = (draft.devices || []).map((row) => ({ ...emptyDevice(), ...row }));
    coordinates = (draft.coordinates || []).map((point, index) => ({
        label: point.label || `Coordinate ${index + 1}`,
        lat: point.lat,
        lon: point.lon,
        comment: point.comment || '',
    }));
    boxClicks = [];
    $('oraDeleteBtn').disabled = !draftId;
    renderDevices();
    renderCoordinates();
    redrawArea({ fit: true });
    updateSubject();
}

function applyHullProfile(profile, vehicleModel) {
    if (profile) {
        setRadio('oraVehicle', profile.vehicle_model || vehicleModel);
        setRadio('oraUmbilical', profile.umbilical_m);
        setRadio('oraTowing', profile.towing);
        $('oraTowedDevice').value = profile.towed_device || '';
        setRadio('oraEcos', profile.ecos_up_to_date);
        $('oraSoftware').value = profile.sv3_software_version || '';
        $('oraApus').value = profile.apu_count || '';
        $('oraSmc').value = profile.smc_version || '';
        return;
    }
    setRadio('oraVehicle', vehicleModel);
}

function renderDevices() {
    const body = $('oraDeviceBody');
    body.innerHTML = '';
    devices.forEach((device, index) => {
        const row = document.createElement('tr');
        row.innerHTML = `
            <td><input type="checkbox" class="form-check-input" data-field="included" ${device.included ? 'checked' : ''}></td>
            <td><input class="form-control form-control-sm" data-field="name" value=""></td>
            <td><input class="form-control form-control-sm" data-field="power_draw" value=""></td>
            <td><input class="form-control form-control-sm" data-field="duty_cycle" value=""></td>
            <td><button type="button" class="btn btn-sm btn-outline-danger" data-remove="1">Remove</button></td>`;
        row.querySelector('[data-field="name"]').value = device.name || '';
        row.querySelector('[data-field="power_draw"]').value = device.power_draw || '';
        row.querySelector('[data-field="duty_cycle"]').value = device.duty_cycle || '';
        row.querySelectorAll('input').forEach((input) => {
            input.addEventListener('input', () => {
                const field = input.dataset.field;
                if (field === 'included') {
                    devices[index].included = input.checked;
                } else {
                    devices[index][field] = input.value;
                    if (field === 'name') devices[index].source = 'manual';
                }
            });
            if (input.type === 'checkbox') {
                input.addEventListener('change', () => {
                    devices[index].included = input.checked;
                });
            }
        });
        row.querySelector('[data-remove]').addEventListener('click', () => {
            devices.splice(index, 1);
            renderDevices();
        });
        body.appendChild(row);
    });
}

function finitePair(point) {
    const lat = Number(point.lat);
    const lon = Number(point.lon);
    return Number.isFinite(lat) && Number.isFinite(lon) ? [lat, lon] : null;
}

function redrawArea({ fit = false } = {}) {
    if (!drawLayer) return;
    drawLayer.clearLayers();
    const latlngs = [];
    coordinates.forEach((point, index) => {
        const pair = finitePair(point);
        if (!pair) return;
        latlngs.push(pair);
        const marker = L.marker(pair, { draggable: true, title: point.label || `Coordinate ${index + 1}` }).addTo(drawLayer);
        marker.bindTooltip(point.label || `Coordinate ${index + 1}`);
        marker.on('click', (event) => {
            if (event.originalEvent) L.DomEvent.stopPropagation(event.originalEvent);
        });
        marker.on('dragend', (event) => {
            const latlng = event.target.getLatLng();
            coordinates[index].lat = Number(latlng.lat.toFixed(6));
            coordinates[index].lon = Number(latlng.lng.toFixed(6));
            renderCoordinates();
            redrawArea();
        });
    });
    if (latlngs.length >= 2) {
        const shape = coordinateMode() === 'box' && latlngs.length >= 3
            ? L.polygon(latlngs, { color: '#0b3a5b', weight: 2, fillOpacity: 0.08 })
            : L.polyline(latlngs, { color: '#0b3a5b', weight: 2 });
        shape.addTo(drawLayer);
    }
    if (fit && latlngs.length) {
        map.fitBounds(L.latLngBounds(latlngs).pad(0.3));
    }
}

function renderCoordinates() {
    const body = $('oraCoordBody');
    body.innerHTML = '';
    coordinates.forEach((point, index) => {
        const row = document.createElement('tr');
        row.innerHTML = `
            <td><input class="form-control form-control-sm" data-field="label"></td>
            <td><input class="form-control form-control-sm" data-field="lat" inputmode="decimal"></td>
            <td><input class="form-control form-control-sm" data-field="lon" inputmode="decimal"></td>
            <td><input class="form-control form-control-sm" data-field="comment"></td>
            <td><button type="button" class="btn btn-sm btn-outline-danger" data-remove="1">Remove</button></td>`;
        row.querySelector('[data-field="label"]').value = point.label || '';
        row.querySelector('[data-field="lat"]').value = point.lat ?? '';
        row.querySelector('[data-field="lon"]').value = point.lon ?? '';
        row.querySelector('[data-field="comment"]').value = point.comment || '';
        row.querySelectorAll('input').forEach((input) => {
            input.addEventListener('input', () => {
                const field = input.dataset.field;
                if (field === 'lat' || field === 'lon') {
                    coordinates[index][field] = input.value === '' ? null : Number(input.value);
                } else {
                    coordinates[index][field] = input.value;
                }
                redrawArea();
            });
        });
        row.querySelector('[data-remove]').addEventListener('click', () => {
            coordinates.splice(index, 1);
            renderCoordinates();
            redrawArea({ fit: false });
        });
        body.appendChild(row);
    });
}

function boxCorners(first, second) {
    const north = Math.max(first.lat, second.lat);
    const south = Math.min(first.lat, second.lat);
    const east = Math.max(first.lon, second.lon);
    const west = Math.min(first.lon, second.lon);
    return [
        { label: 'Coordinate 1', lat: north, lon: west, comment: 'Box NW' },
        { label: 'Coordinate 2', lat: north, lon: east, comment: 'Box NE' },
        { label: 'Coordinate 3', lat: south, lon: east, comment: 'Box SE' },
        { label: 'Coordinate 4', lat: south, lon: west, comment: 'Box SW' },
    ];
}

function onMapClick(event) {
    const lat = Number(event.latlng.lat.toFixed(6));
    const lon = Number(event.latlng.lng.toFixed(6));
    const mode = coordinateMode();
    if (mode === 'hold_station') {
        coordinates = [{ label: 'Coordinate 1', lat, lon, comment: 'Hold station' }];
        boxClicks = [];
    } else if (mode === 'box') {
        boxClicks.push({ lat, lon });
        if (boxClicks.length < 2) {
            coordinates = [{ label: 'Coordinate 1', lat, lon, comment: 'Box corner' }];
        } else {
            coordinates = boxCorners(boxClicks[0], boxClicks[1]);
            boxClicks = [];
        }
    } else {
        const index = coordinates.length + 1;
        coordinates.push({
            label: `Coordinate ${index}`,
            lat,
            lon,
            comment: index === 1 ? 'Deployment location' : '',
        });
    }
    renderCoordinates();
    redrawArea({ fit: false });
}

async function refreshDraftList(selectId) {
    const drafts = await apiRequest('/api/team/ora/drafts', 'GET');
    const select = $('oraDraftSelect');
    const current = selectId ?? select.value;
    select.innerHTML = '<option value="">New request</option>';
    (drafts || []).forEach((draft) => {
        const option = document.createElement('option');
        option.value = String(draft.id);
        const when = (draft.updated_at_utc || '').slice(0, 16).replace('T', ' ');
        option.textContent = `${draft.title || draft.hull_name || 'Untitled'} — ${draft.requester || 'ORA'} ${when}`;
        select.appendChild(option);
    });
    if (current) select.value = String(current);
}

async function loadMissions() {
    missions = await apiRequest('/api/team/ora/missions', 'GET');
    const select = $('oraMission');
    const current = select.value;
    select.innerHTML = '<option value="">Not linked</option>';
    (missions || []).forEach((mission) => {
        const option = document.createElement('option');
        option.value = mission.id;
        option.textContent = `${mission.label} (${mission.operational_state})`;
        select.appendChild(option);
    });
    if (current) select.value = current;
}

function blankDraft(deviceRows) {
    applyDraft({
        id: null,
        requester: requesterDefault,
        purposes: ['mission'],
        priority: 3,
        coordinate_mode: 'course',
        devices: deviceRows,
        coordinates: [],
    });
    $('oraDraftSelect').value = '';
}

async function saveDraft() {
    const body = payload();
    const saved = draftId
        ? await apiRequest(`/api/team/ora/drafts/${draftId}`, 'PUT', body)
        : await apiRequest('/api/team/ora/drafts', 'POST', body);
    applyDraft(saved);
    await refreshDraftList(saved.id);
    $('oraStatus').textContent = `Saved draft ${saved.id}. Hull config is remembered when the hull field is set.`;
    showToast('ORA draft saved');
}

async function downloadPdf() {
    const body = payload();
    const response = await fetch('/api/team/ora/pdf', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', ...getAuthHeaders() },
        body: JSON.stringify(body),
    });
    if (!response.ok) {
        let detail = response.statusText;
        try {
            const data = await response.json();
            detail = data.detail || detail;
        } catch (_err) {
            /* keep status text */
        }
        throw new Error(typeof detail === 'string' ? detail : 'Download failed');
    }
    const blob = await response.blob();
    const disposition = response.headers.get('Content-Disposition') || '';
    const match = disposition.match(/filename="([^"]+)"/);
    const filename = match ? match[1] : 'ORA Request.pdf';
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    link.click();
    URL.revokeObjectURL(url);
    $('oraStatus').textContent = `Downloaded ${filename}. Email it to ${OPS_EMAIL}.`;
}

async function loadTracker() {
    const platformName = $('oraHull').value.trim();
    $('oraTrackerWarning').textContent = '';
    const result = await apiRequest('/api/team/ora/loadout', 'POST', {
        platform_name: platformName,
        devices,
    });
    devices = result.devices || [];
    renderDevices();
    const count = (result.instrument_names || []).length;
    $('oraTrackerWarning').textContent = result.warning || `Merged ${count} Sensor Tracker instrument name(s).`;
    showToast(`Loaded Tracker instruments for ${result.platform_name}`);
}

async function loadContextTracks() {
    if (!trackLayer) return;
    trackLayer.clearLayers();
    if (!$('oraShowTracks').checked) return;
    let targets = [];
    try {
        targets = await apiRequest('/api/team/ora/context-tracks', 'GET');
    } catch (error) {
        showToast(error.message || 'Could not list glider tracks', 'danger');
        return;
    }
    const jobs = (targets || []).filter((target) => target.track_id && target.track_kind);
    const queue = jobs.slice(0, 16);
    const workers = Array.from({ length: 4 }, async () => {
        while (queue.length) {
            const target = queue.shift();
            const url = target.track_kind === 'slocum'
                ? `/api/map/slocum/telemetry/${encodeURIComponent(target.track_id)}?hours_back=48`
                : `/api/map/telemetry/${encodeURIComponent(target.track_id)}?hours_back=48`;
            try {
                const data = await apiRequest(url, 'GET');
                const points = (data.track_points || [])
                    .map((point) => [Number(point.lat), Number(point.lon)])
                    .filter((pair) => Number.isFinite(pair[0]) && Number.isFinite(pair[1]));
                if (points.length < 2) continue;
                const color = target.platform_family === 'slocum' ? '#1a7f6e' : '#3d5a80';
                L.polyline(points, { color, weight: 2, opacity: 0.7, interactive: false }).addTo(trackLayer);
                L.circleMarker(points[points.length - 1], {
                    radius: 4,
                    color,
                    weight: 1,
                    fillOpacity: 0.9,
                }).bindTooltip(target.label).addTo(trackLayer);
            } catch (_error) {
                /* one mission missing data should not block the editor */
            }
        }
    });
    await Promise.all(workers);
}

function initMap() {
    map = L.map('oraMap', { scrollWheelZoom: true }).setView([44.2, -63.0], 6);
    tileHolder.current = createThemedTileLayer().addTo(map);
    observeThemeChange(() => {
        tileHolder.current = swapMapTileLayer(map, tileHolder.current);
    });
    trackLayer = L.layerGroup().addTo(map);
    drawLayer = L.layerGroup().addTo(map);
    map.on('click', onMapClick);
    bindVectorOverlayContext(map);
    bindNavwarnOverlayContext(map);
    bindVesselDensityOverlayContext(map);
    bindCiopsIceOverlayContext(map);
    initVectorOverlay();
    initNavwarnOverlay();
    initVesselDensityOverlay();
    initCiopsIceOverlay();
}

document.addEventListener('DOMContentLoaded', async () => {
    requesterDefault = document.body.dataset.username || '';
    const nameNode = document.querySelector('[data-current-username]');
    if (nameNode) requesterDefault = nameNode.dataset.currentUsername || requesterDefault;
    initMap();
    try {
        const defaults = await apiRequest('/api/team/ora/device-defaults', 'GET');
        await loadMissions();
        await refreshDraftList();
        blankDraft(defaults || []);
        if (!requesterDefault) {
            const user = await apiRequest('/api/users/me', 'GET').catch(() => null);
            if (user && user.username) {
                requesterDefault = user.username;
                if (!$('oraRequester').value) $('oraRequester').value = requesterDefault;
            }
        }
        await loadContextTracks();
    } catch (error) {
        showToast(error.message || 'Could not open the ORA page', 'danger');
    }

    $('oraTitle').addEventListener('input', updateSubject);
    $('oraHull').addEventListener('input', updateSubject);
    document.querySelectorAll('input[name="oraMode"]').forEach((input) => {
        input.addEventListener('change', () => {
            boxClicks = [];
            redrawArea();
        });
    });
    $('oraShowTracks').addEventListener('change', () => {
        loadContextTracks().catch((error) => showToast(error.message, 'danger'));
    });
    $('oraMission').addEventListener('change', () => {
        const mission = missions.find((item) => item.id === $('oraMission').value);
        if (!mission) return;
        $('oraHull').value = mission.platform_name || '';
        $('oraDates').value = mission.dates_of_operation || '';
        if (!$('oraTitle').value) $('oraTitle').value = mission.label;
        applyHullProfile(mission.hull_profile, mission.vehicle_model);
        updateSubject();
    });
    $('oraNewBtn').addEventListener('click', async () => {
        const defaults = await apiRequest('/api/team/ora/device-defaults', 'GET');
        blankDraft(defaults || []);
        $('oraStatus').textContent = 'New request.';
    });
    $('oraDraftSelect').addEventListener('change', async () => {
        const id = $('oraDraftSelect').value;
        if (!id) {
            const defaults = await apiRequest('/api/team/ora/device-defaults', 'GET');
            blankDraft(defaults || []);
            return;
        }
        const draft = await apiRequest(`/api/team/ora/drafts/${id}`, 'GET');
        applyDraft(draft);
    });
    $('oraSaveBtn').addEventListener('click', () => {
        saveDraft().catch((error) => showToast(error.message || 'Save failed', 'danger'));
    });
    $('oraDownloadBtn').addEventListener('click', () => {
        downloadPdf().catch((error) => showToast(error.message || 'Download failed', 'danger'));
    });
    $('oraDeleteBtn').addEventListener('click', async () => {
        if (!draftId) return;
        if (!window.confirm('Delete this ORA draft?')) return;
        await apiRequest(`/api/team/ora/drafts/${draftId}`, 'DELETE');
        const defaults = await apiRequest('/api/team/ora/device-defaults', 'GET');
        await refreshDraftList('');
        blankDraft(defaults || []);
        showToast('Draft deleted');
    });
    $('oraTrackerBtn').addEventListener('click', () => {
        loadTracker().catch((error) => showToast(error.message || 'Tracker load failed', 'danger'));
    });
    $('oraBusBtn').addEventListener('click', async () => {
        devices = await apiRequest('/api/team/ora/device-defaults', 'GET');
        renderDevices();
    });
    $('oraAddDeviceBtn').addEventListener('click', () => {
        devices.push(emptyDevice());
        renderDevices();
    });
    $('oraAddPointBtn').addEventListener('click', () => {
        coordinates.push({
            label: `Coordinate ${coordinates.length + 1}`,
            lat: null,
            lon: null,
            comment: '',
        });
        renderCoordinates();
    });
    $('oraClearPointsBtn').addEventListener('click', () => {
        coordinates = [];
        boxClicks = [];
        renderCoordinates();
        redrawArea();
    });
});
