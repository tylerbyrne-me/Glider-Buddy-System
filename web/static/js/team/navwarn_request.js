import { apiRequest, getAuthHeaders, showToast } from '/static/js/api.js';
import { areaAnchor, createAreaMap, describeArea, previewPosition } from '/static/js/team/navwarn_area.js';
import {
    addDays,
    convertStamp,
    formatWall,
    nowStamp,
    parseStamp,
    pickerValueToWall,
    stampFromIso,
    wallFromDate,
    wallToPickerValue,
} from '/static/js/team/navwarn_time.js';

const TRACK_HOURS_BACK = 72;
const EMPTY_AREA = { mode: 'hold', points: [], radius_km: null };

const DESK_EMAILS = {
    sydney: 'NAVWARN.MCTSSydney@innav.gc.ca',
    port_aux_basques: 'navwarn.mctsportauxbasques@innav.gc.ca',
};

const NATURE_TOPICS = {
    marine_works: [
        ['breakwater', 'Breakwater construction'],
        ['cable_laying', 'Cable laying operations'],
        ['dredging', 'Dredging operations'],
        ['floating_dock', 'Floating dock'],
        ['hydrographic', 'Hydrographic survey'],
        ['seismic', 'Seismic survey'],
        ['wharf', 'Wharf construction'],
        ['other', 'Marine works (other)'],
    ],
    obstruction: [
        ['acoustic_recorder', 'Acoustic recorder'],
        ['aquaculture', 'Aquaculture site'],
        ['diving', 'Diving operations'],
        ['ice_boom', 'Ice boom'],
        ['mussel_farm', 'Mussel farm'],
        ['repair', 'Repair work'],
        ['scientific_buoy', 'Scientific buoy and apparatus'],
        ['scientific_moorings', 'Scientific moorings'],
        ['submerged_object', 'Submerged object'],
        ['subsurface_moorings', 'Subsurface moorings'],
        ['subsurface_pipelines', 'Subsurface pipelines'],
        ['tide_gauges', 'Tide gauges'],
        ['uncharted_cables', 'Uncharted submarine cables'],
        ['underwater_installation', 'Underwater installation'],
        ['wreck', 'Wreck'],
        ['other', 'Obstruction (other)'],
    ],
    offshore: [
        ['drill_on_location', 'Drill rig on location'],
        ['drill_under_tow', 'Drill rig under tow'],
        ['drilling_site', 'Drilling site operations'],
        ['other', 'Offshore works (other)'],
    ],
    recreational: [
        ['fireworks', 'Fireworks'],
        ['race', 'Race'],
        ['regattas', 'Regattas'],
        ['swimmers', 'Swimmers'],
        ['other', 'Recreational event (other)'],
    ],
};

let draftId = null;
let missions = [];
let requesterDefault = '';
let emailDefault = '';
let telephoneDefault = '';
let areaMap = null;
let lastGeneratedExtra = '';
let currentTimezone = 'utc';
let missionTrack = { missionId: null, points: [] };

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

function numberOrNull(value) {
    const text = String(value ?? '').trim();
    if (!text) return null;
    const number = Number(text);
    return Number.isFinite(number) ? number : null;
}

function updateDeskEmail() {
    const desk = $('nwDesk').value || 'sydney';
    $('nwDeskEmail').textContent = DESK_EMAILS[desk] || DESK_EMAILS.sydney;
}

function refreshNatureTopics(selected) {
    const category = $('nwNatureCategory').value || 'obstruction';
    const options = NATURE_TOPICS[category] || [];
    const select = $('nwNatureTopic');
    const current = selected || select.value;
    select.innerHTML = '';
    options.forEach(([value, label]) => {
        const option = document.createElement('option');
        option.value = value;
        option.textContent = label;
        select.appendChild(option);
    });
    if (current && options.some(([value]) => value === current)) {
        select.value = current;
    } else if (options.some(([value]) => value === 'other')) {
        select.value = 'other';
    }
}

function payload() {
    return {
        title: $('nwTitle').value.trim() || null,
        catalog_mission_id: $('nwMission').value || null,
        hull_name: $('nwHull').value.trim() || null,
        desk: $('nwDesk').value || 'sydney',
        requester_name: $('nwRequester').value.trim(),
        telephone: $('nwTelephone').value.trim() || null,
        email: $('nwEmail').value.trim() || null,
        publish_contact: radioValue('nwPublish') || 'no',
        publish_contact_custom: $('nwPublishCustom').value.trim() || null,
        is_update_or_cancel: radioValue('nwUpdate') || 'no',
        previous_navwarn_number: $('nwPrevious').value.trim() || null,
        start_datetime: $('nwStart').value.trim() || null,
        timezone: radioValue('nwTimezone') || 'utc',
        days_of_operation: radioValue('nwDays') || 'daily',
        days_other: $('nwDaysOther').value.trim() || null,
        hours_of_operation: radioValue('nwHours') || '24h',
        hours_other: $('nwHoursOther').value.trim() || null,
        completion_datetime: $('nwCompletion').value.trim() || null,
        completion_firmness: radioValue('nwFirmness') || 'estimated',
        position_format: radioValue('nwPosFormat') || 'dmm',
        latitude: numberOrNull($('nwLat').value),
        longitude: numberOrNull($('nwLon').value),
        place_name: $('nwPlace').value.trim() || null,
        extra_positions: $('nwExtraPositions').value.trim() || null,
        area: currentAreaPayload(),
        nature_category: $('nwNatureCategory').value || 'obstruction',
        nature_topic: $('nwNatureTopic').value || 'other',
        nature_other: $('nwNatureOther').value.trim() || null,
        vessels_on_scene: $('nwVessels').value.trim() || null,
        markers_description: $('nwMarkers').value.trim() || null,
        wash_berth: radioValue('nwWash') || 'none',
        other_details: $('nwOtherDetails').value.trim() || null,
    };
}

function applyDraft(draft) {
    draftId = draft.id ?? null;
    $('nwTitle').value = draft.title || '';
    $('nwMission').value = draft.catalog_mission_id || '';
    $('nwHull').value = draft.hull_name || '';
    $('nwDesk').value = draft.desk || 'sydney';
    updateDeskEmail();
    $('nwRequester').value = draft.requester_name || requesterDefault;
    $('nwTelephone').value = draft.telephone || '';
    $('nwEmail').value = draft.email || '';
    setRadio('nwPublish', draft.publish_contact || 'no');
    $('nwPublishCustom').value = draft.publish_contact_custom || '';
    setRadio('nwUpdate', draft.is_update_or_cancel || 'no');
    $('nwPrevious').value = draft.previous_navwarn_number || '';
    $('nwStart').value = draft.start_datetime || '';
    setRadio('nwTimezone', draft.timezone || 'utc');
    currentTimezone = draft.timezone || 'utc';
    setRadio('nwDays', draft.days_of_operation || 'daily');
    $('nwDaysOther').value = draft.days_other || '';
    setRadio('nwHours', draft.hours_of_operation || '24h');
    $('nwHoursOther').value = draft.hours_other || '';
    $('nwCompletion').value = draft.completion_datetime || '';
    setRadio('nwFirmness', draft.completion_firmness || 'estimated');
    setRadio('nwPosFormat', draft.position_format || 'dmm');
    $('nwLat').value = draft.latitude == null ? '' : draft.latitude;
    $('nwLon').value = draft.longitude == null ? '' : draft.longitude;
    $('nwPlace').value = draft.place_name || '';
    $('nwExtraPositions').value = draft.extra_positions || '';
    $('nwNatureCategory').value = draft.nature_category || 'obstruction';
    refreshNatureTopics(draft.nature_topic || 'other');
    $('nwNatureOther').value = draft.nature_other || '';
    $('nwVessels').value = draft.vessels_on_scene || '';
    $('nwMarkers').value = draft.markers_description || '';
    setRadio('nwWash', draft.wash_berth || 'none');
    $('nwOtherDetails').value = draft.other_details || '';
    $('nwDeleteBtn').disabled = !draftId;
    $('nwDuplicateBtn').disabled = !draftId;
    if (draftId) $('nwDraftSelect').value = String(draftId);
    applyArea(draft.area || EMPTY_AREA);
    $('nwFixStatus').textContent = '';
    loadMissionTrack().catch(() => {});
}

function currentAreaPayload() {
    if (!areaMap) return null;
    const area = areaMap.getArea();
    if (!area.points.length) return null;
    return {
        mode: area.mode,
        points: area.points,
        radius_km: area.mode === 'hold' ? area.radius_km : null,
    };
}

function applyArea(area) {
    if (!areaMap) return;
    setRadio('nwAreaMode', area.mode || 'hold');
    $('nwRadiusKm').value = area.radius_km ?? '';
    areaMap.setArea(area, { fit: true });
    lastGeneratedExtra = describeArea(area, radioValue('nwPosFormat') || 'dmm');
    updateAreaControls();
    updatePositionPreview();
}

function updateAreaControls() {
    const mode = radioValue('nwAreaMode') || 'hold';
    $('nwRadiusGroup').classList.toggle('d-none', mode !== 'hold');
    const count = areaMap ? areaMap.getArea().points.length : 0;
    $('nwAreaStatus').textContent = count
        ? `${count} point${count === 1 ? '' : 's'} on the map.`
        : 'No map points yet.';
}

function updatePositionPreview() {
    $('nwPositionPreview').textContent = previewPosition(
        numberOrNull($('nwLat').value),
        numberOrNull($('nwLon').value),
        radioValue('nwPosFormat') || 'dmm',
    );
}

/** Rewrite the area text only while it still matches what the map last generated. */
function refreshGeneratedExtra() {
    if (!areaMap) return;
    const textarea = $('nwExtraPositions');
    const current = textarea.value.trim();
    const next = describeArea(areaMap.getArea(), radioValue('nwPosFormat') || 'dmm');
    if (!current || current === lastGeneratedExtra.trim()) textarea.value = next;
    lastGeneratedExtra = next;
}

function onAreaChange(area) {
    const anchor = areaAnchor(area);
    if (anchor) {
        $('nwLat').value = Number(anchor.lat.toFixed(6));
        $('nwLon').value = Number(anchor.lon.toFixed(6));
    }
    refreshGeneratedExtra();
    updateAreaControls();
    updatePositionPreview();
}

function onLatLonInput() {
    updatePositionPreview();
    if (!areaMap || (radioValue('nwAreaMode') || 'hold') !== 'hold') return;
    const lat = numberOrNull($('nwLat').value);
    const lon = numberOrNull($('nwLon').value);
    if (lat == null || lon == null || Math.abs(lat) > 90 || Math.abs(lon) > 180) return;
    areaMap.setHoldPoint({ lat, lon });
    refreshGeneratedExtra();
    updateAreaControls();
}

function selectedMission() {
    return missions.find((row) => row.id === $('nwMission').value) || null;
}

function trackUrl(mission) {
    const id = encodeURIComponent(mission.track_id);
    return mission.track_kind === 'slocum'
        ? `/api/map/slocum/telemetry/${id}?hours_back=${TRACK_HOURS_BACK}`
        : `/api/map/telemetry/${id}?hours_back=${TRACK_HOURS_BACK}`;
}

async function fetchMissionTrack(mission, { force = false } = {}) {
    if (!force && missionTrack.missionId === mission.id && missionTrack.points.length) return missionTrack.points;
    const data = await apiRequest(trackUrl(mission), 'GET');
    const points = (data?.track_points || [])
        .map((point) => ({ lat: Number(point.lat), lon: Number(point.lon), timestamp: point.timestamp }))
        .filter((point) => Number.isFinite(point.lat) && Number.isFinite(point.lon));
    missionTrack = { missionId: mission.id, points };
    return points;
}

async function loadMissionTrack() {
    if (!areaMap) return;
    const mission = selectedMission();
    if (!mission?.track_id || !$('nwShowTrack').checked) {
        areaMap.clearTrack();
        return;
    }
    const points = await fetchMissionTrack(mission);
    areaMap.setTrack(points, { fit: true });
}

function fixAgeText(timestamp) {
    const when = new Date(timestamp || '');
    if (Number.isNaN(when.getTime())) return timestamp || 'unknown time';
    const minutes = Math.max(0, Math.round((Date.now() - when.getTime()) / 60000));
    const age = minutes < 90 ? `${minutes} min ago` : `${Math.round(minutes / 60)} h ago`;
    return `${formatWall(wallFromDate(when, 'utc'), 'utc')} (${age})`;
}

async function useLastFix() {
    const mission = selectedMission();
    if (!mission) throw new Error('Choose a catalog mission first.');
    if (!mission.track_id) throw new Error(`No telemetry source is linked to ${mission.label}.`);
    const points = await fetchMissionTrack(mission, { force: true });
    const fix = points[points.length - 1];
    if (!fix) throw new Error(`No telemetry in the last ${TRACK_HOURS_BACK} h for ${mission.label}.`);
    $('nwLat').value = Number(fix.lat.toFixed(6));
    $('nwLon').value = Number(fix.lon.toFixed(6));
    onLatLonInput();
    $('nwFixStatus').textContent = `Last fix ${fixAgeText(fix.timestamp)}.`;
    if ($('nwShowTrack').checked) areaMap?.setTrack(points);
}

function pickerFor(fieldId) {
    return $(`${fieldId}Picker`);
}

function openDatePicker(fieldId) {
    const picker = pickerFor(fieldId);
    const timezone = radioValue('nwTimezone') || 'utc';
    const parsed = parseStamp($(fieldId).value);
    picker.value = wallToPickerValue(parsed || wallFromDate(new Date(), timezone));
    if (typeof picker.showPicker === 'function') {
        try {
            picker.showPicker();
            return;
        } catch (_err) {
            /* fall through to a visible input */
        }
    }
    picker.classList.remove('nw-dt-picker');
    picker.classList.add('form-control', 'form-control-sm', 'mt-1');
    picker.removeAttribute('aria-hidden');
    picker.focus();
}

function applyPickerValue(fieldId) {
    const wall = pickerValueToWall(pickerFor(fieldId).value);
    if (!wall) return;
    $(fieldId).value = formatWall(wall, radioValue('nwTimezone') || 'utc');
}

function completionFromStart(days) {
    const start = parseStamp($('nwStart').value);
    if (!start) throw new Error('Set a start date and time first (e.g. 15:00 UTC 2026-04-21).');
    $('nwCompletion').value = formatWall(addDays(start, days), radioValue('nwTimezone') || 'utc');
}

function useMissionDates({ overwrite = true } = {}) {
    const mission = selectedMission();
    if (!mission) {
        if (overwrite) showToast('Choose a catalog mission first.', 'warning');
        return;
    }
    const timezone = radioValue('nwTimezone') || 'utc';
    const start = stampFromIso(mission.start_time, timezone);
    const end = stampFromIso(mission.end_time, timezone);
    if (start && (overwrite || !$('nwStart').value.trim())) $('nwStart').value = start;
    if (end && (overwrite || !$('nwCompletion').value.trim())) $('nwCompletion').value = end;
    if (overwrite && !start && !end) showToast(`${mission.label} has no catalog start/end time.`, 'warning');
}

function onTimezoneChange() {
    const next = radioValue('nwTimezone') || 'utc';
    ['nwStart', 'nwCompletion'].forEach((fieldId) => {
        $(fieldId).value = convertStamp($(fieldId).value, currentTimezone, next);
    });
    currentTimezone = next;
}

function blankDraft() {
    applyDraft({
        id: null,
        desk: 'sydney',
        requester_name: requesterDefault,
        telephone: telephoneDefault || null,
        email: emailDefault || null,
        publish_contact: 'no',
        is_update_or_cancel: 'no',
        timezone: 'utc',
        days_of_operation: 'daily',
        hours_of_operation: '24h',
        completion_firmness: 'estimated',
        position_format: 'dmm',
        nature_category: 'obstruction',
        nature_topic: 'other',
        nature_other: 'Acoustic/Oceanographic Survey',
        wash_berth: 'none',
    });
    $('nwDraftSelect').value = '';
}

function applyAccountContactDefaults({ overwrite = false } = {}) {
    if (emailDefault && (overwrite || !$('nwEmail').value.trim())) {
        $('nwEmail').value = emailDefault;
    }
    if (telephoneDefault && (overwrite || !$('nwTelephone').value.trim())) {
        $('nwTelephone').value = telephoneDefault;
    }
    if (requesterDefault && (overwrite || !$('nwRequester').value.trim())) {
        $('nwRequester').value = requesterDefault;
    }
}

async function refreshDraftList(selectId) {
    const drafts = await apiRequest('/api/team/navwarn/drafts', 'GET');
    const select = $('nwDraftSelect');
    const current = selectId ?? select.value;
    select.innerHTML = '<option value="">New request</option>';
    (drafts || []).forEach((draft) => {
        const option = document.createElement('option');
        option.value = String(draft.id);
        const when = (draft.updated_at_utc || '').slice(0, 16).replace('T', ' ');
        option.textContent = `${draft.title || draft.hull_name || 'Untitled'} — ${draft.desk || 'desk'} ${when}`;
        select.appendChild(option);
    });
    if (current) select.value = String(current);
}

async function loadMissions() {
    missions = await apiRequest('/api/team/navwarn/missions', 'GET');
    const select = $('nwMission');
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

async function saveDraft() {
    const body = payload();
    const saved = draftId
        ? await apiRequest(`/api/team/navwarn/drafts/${draftId}`, 'PUT', body)
        : await apiRequest('/api/team/navwarn/drafts', 'POST', body);
    applyDraft(saved);
    await refreshDraftList(saved.id);
    $('nwStatus').textContent = `Saved draft ${saved.id}.`;
    showToast('NAVWARN draft saved');
}

async function downloadFile(path, fallbackName) {
    const body = payload();
    const response = await fetch(path, {
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
    const filename = match ? match[1] : fallbackName;
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    link.click();
    URL.revokeObjectURL(url);
    const email = $('nwDeskEmail').textContent;
    $('nwStatus').textContent = `Downloaded ${filename}. Email it to ${email}.`;
    showToast(`Downloaded ${filename}`);
}

async function fillDefaults({ quiet = false } = {}) {
    const hull = $('nwHull').value.trim();
    const defaults = await apiRequest(
        `/api/team/navwarn/defaults?hull_name=${encodeURIComponent(hull || '')}`,
        'GET',
    );
    if (!$('nwVessels').value.trim()) $('nwVessels').value = defaults.vessels_on_scene || '';
    if (!$('nwMarkers').value.trim()) $('nwMarkers').value = defaults.markers_description || '';
    if (!$('nwOtherDetails').value.trim()) $('nwOtherDetails').value = defaults.other_details || '';
    if (!$('nwNatureOther').value.trim()) $('nwNatureOther').value = defaults.nature_other || '';
    if (!quiet) showToast('Filled Wave Glider defaults');
}

async function duplicateAsUpdate() {
    if (!draftId) return;
    const previous = window.prompt(
        'Previous NAVWARN number (leave blank to keep the draft value):',
        $('nwPrevious').value.trim(),
    );
    if (previous === null) return;
    const saved = await apiRequest(`/api/team/navwarn/drafts/${draftId}/duplicate`, 'POST', {
        previous_navwarn_number: previous.trim() || null,
    });
    applyDraft(saved);
    await refreshDraftList(saved.id);
    $('nwStatus').textContent = `Duplicated as update draft ${saved.id}.`;
    showToast('Duplicated as update');
}

async function initRequester() {
    requesterDefault = document.body.dataset.username || '';
    emailDefault = '';
    telephoneDefault = '';
    try {
        const me = await apiRequest('/api/users/me', 'GET');
        if (me?.full_name && String(me.full_name).trim()) {
            requesterDefault = String(me.full_name).trim();
        } else if (me?.username) {
            requesterDefault = me.username;
        }
        if (me?.email && String(me.email).trim()) {
            emailDefault = String(me.email).trim();
        }
        if (me?.telephone && String(me.telephone).trim()) {
            telephoneDefault = String(me.telephone).trim();
        }
    } catch (_err) {
        /* optional */
    }
    applyAccountContactDefaults({ overwrite: false });
}

function bind() {
    $('nwDesk').addEventListener('change', updateDeskEmail);
    $('nwNatureCategory').addEventListener('change', () => refreshNatureTopics());
    $('nwCopyEmailBtn').addEventListener('click', async () => {
        const email = $('nwDeskEmail').textContent;
        try {
            await navigator.clipboard.writeText(email);
            showToast('Desk email copied');
        } catch (_err) {
            showToast('Could not copy email', 'danger');
        }
    });
    $('nwNewBtn').addEventListener('click', () => blankDraft());
    $('nwSaveBtn').addEventListener('click', () => {
        saveDraft().catch((error) => showToast(error.message || 'Save failed', 'danger'));
    });
    $('nwDeleteBtn').addEventListener('click', async () => {
        if (!draftId) return;
        if (!window.confirm('Delete this NAVWARN draft?')) return;
        try {
            await apiRequest(`/api/team/navwarn/drafts/${draftId}`, 'DELETE');
            blankDraft();
            await refreshDraftList('');
            $('nwStatus').textContent = 'Draft deleted.';
            showToast('Draft deleted');
        } catch (error) {
            showToast(error.message || 'Delete failed', 'danger');
        }
    });
    $('nwDuplicateBtn').addEventListener('click', () => {
        duplicateAsUpdate().catch((error) => showToast(error.message || 'Duplicate failed', 'danger'));
    });
    $('nwDocxBtn').addEventListener('click', () => {
        downloadFile('/api/team/navwarn/docx', 'NAVWARN Request.docx').catch((error) => {
            showToast(error.message || 'Download failed', 'danger');
        });
    });
    $('nwPdfBtn').addEventListener('click', () => {
        downloadFile('/api/team/navwarn/pdf', 'NAVWARN Request.pdf').catch((error) => {
            showToast(error.message || 'Download failed', 'danger');
        });
    });
    $('nwFillDefaultsBtn').addEventListener('click', () => {
        fillDefaults().catch((error) => showToast(error.message || 'Defaults failed', 'danger'));
    });
    $('nwDraftSelect').addEventListener('change', async () => {
        const value = $('nwDraftSelect').value;
        if (!value) {
            blankDraft();
            return;
        }
        try {
            const draft = await apiRequest(`/api/team/navwarn/drafts/${value}`, 'GET');
            applyDraft(draft);
            $('nwStatus').textContent = `Loaded draft ${draft.id}.`;
        } catch (error) {
            showToast(error.message || 'Could not load draft', 'danger');
        }
    });
    $('nwMission').addEventListener('change', () => {
        onMissionChange().catch((error) => {
            showToast(error.message || 'Could not load Float SV3 hull ID', 'danger');
        });
    });

    document.querySelectorAll('[data-dt-now]').forEach((button) => {
        button.addEventListener('click', () => {
            $(button.dataset.dtNow).value = nowStamp(radioValue('nwTimezone') || 'utc');
        });
    });
    document.querySelectorAll('[data-dt-pick]').forEach((button) => {
        const fieldId = button.dataset.dtPick;
        button.addEventListener('click', () => openDatePicker(fieldId));
        pickerFor(fieldId).addEventListener('change', () => applyPickerValue(fieldId));
    });
    document.querySelectorAll('[data-dt-offset-days]').forEach((button) => {
        button.addEventListener('click', () => {
            try {
                completionFromStart(Number(button.dataset.dtOffsetDays));
            } catch (error) {
                showToast(error.message, 'warning');
            }
        });
    });
    $('nwMissionDatesBtn').addEventListener('click', () => useMissionDates({ overwrite: true }));
    document.querySelectorAll('input[name="nwTimezone"]').forEach((input) => {
        input.addEventListener('change', onTimezoneChange);
    });

    $('nwLat').addEventListener('input', onLatLonInput);
    $('nwLon').addEventListener('input', onLatLonInput);
    document.querySelectorAll('input[name="nwPosFormat"]').forEach((input) => {
        input.addEventListener('change', () => {
            refreshGeneratedExtra();
            updatePositionPreview();
        });
    });
    $('nwLastFixBtn').addEventListener('click', () => {
        useLastFix().catch((error) => {
            $('nwFixStatus').textContent = '';
            showToast(error.message || 'Could not load telemetry', 'warning');
        });
    });

    document.querySelectorAll('input[name="nwAreaMode"]').forEach((input) => {
        input.addEventListener('change', () => {
            areaMap?.setMode(radioValue('nwAreaMode') || 'hold');
        });
    });
    $('nwRadiusKm').addEventListener('input', () => {
        const radius = numberOrNull($('nwRadiusKm').value);
        areaMap?.setRadius(radius != null && radius > 0 ? radius : null);
    });
    $('nwUndoPointBtn').addEventListener('click', () => areaMap?.undo());
    $('nwClearPointsBtn').addEventListener('click', () => areaMap?.clear());
    $('nwShowTrack').addEventListener('change', () => {
        loadMissionTrack().catch((error) => showToast(error.message || 'Could not load track', 'warning'));
    });
}

async function resolveFloatHull(platformName, { overwrite = false } = {}) {
    const name = (platformName || '').trim();
    if (!name) return null;
    const result = await apiRequest(
        `/api/team/navwarn/float-hull?platform_name=${encodeURIComponent(name)}`,
        'GET',
    );
    if (result.hull_id && (overwrite || !$('nwHull').value.trim())) {
        $('nwHull').value = result.hull_id;
    }
    if (result.warning) {
        $('nwStatus').textContent = result.warning;
    } else if (result.hull_id) {
        $('nwStatus').textContent = `Hull ID ${result.hull_id} from ${result.component_name || 'Float SV3 component'} on ${name}.`;
    }
    return result;
}

async function onMissionChange() {
    const mission = selectedMission();
    missionTrack = { missionId: null, points: [] };
    $('nwFixStatus').textContent = '';
    loadMissionTrack().catch(() => {});
    if (!mission) return;
    if (!$('nwTitle').value.trim()) {
        $('nwTitle').value = mission.label || '';
    }
    if (!$('nwRequester').value.trim() && requesterDefault) {
        $('nwRequester').value = requesterDefault;
    }
    useMissionDates({ overwrite: false });
    if (mission.platform_name) {
        const result = await resolveFloatHull(mission.platform_name, { overwrite: false });
        if (result?.hull_id) await fillDefaults({ quiet: true });
    }
}

async function boot() {
    areaMap = createAreaMap({ elementId: 'nwMap', onChange: onAreaChange });
    bind();
    refreshNatureTopics('other');
    updateDeskEmail();
    await initRequester();
    blankDraft();
    await Promise.all([refreshDraftList(''), loadMissions()]);
}

boot().catch((error) => {
    console.error(error);
    showToast(error.message || 'NAVWARN page failed to load', 'danger');
});
