/**
 * @file dashboard.js
 * @description Wave Glider dashboard: declarative time-series charts via
 * WG_TIME_SERIES_CARD_CONFIGS + chart_time_series_utils (rows→series adapter).
 * Spectrum / error doughnut / mini charts / forecasts stay imperative.
 * ERDDAP follow-up: configs are serializable so they can move server-side later.
 */

import { checkAuth, getUserProfile } from '/static/js/auth.js';
import { apiRequest, fetchWithAuth, showToast } from '/static/js/api.js';
import { renderPicHandoffDetails } from '/static/js/pic_handoff_details.js';
import { initializeWgVm4OffloadSection } from '/static/js/wg_vm4.js';
import { formatUtcDateTime, datetimeLocalToUtcIso, findNearestTimeIndexUtc, toUtcDate } from '/static/js/datetime_utils.js';
import { registerForceUtcTimeDisplayPlugin } from '/static/js/chart_utc_utils.js';
import { initializeMiniCharts } from '/static/js/mini_charts.js';
import { renderSensorTrackerInstrumentColumns } from '/static/js/sensor_tracker_instruments.js';
import {
    applyTimeAxisZoom,
    bindResetZoomButton,
    CHART_ZOOM_HINT,
    isChartZoomPluginAvailable,
} from '/static/js/chart_zoom_utils.js';
import {
    applyPlotStyleToDatasets,
    bindPlotStyleControls,
} from '/static/js/chart_plot_style_utils.js';
import {
    applyTimeSeriesHoverDefaults,
    ensureDatasetHitRadius,
} from '/static/js/chart_hover_defaults.js';
import { registerNearestXByDatasetInteractionMode } from '/static/js/chart_overlay_utils.js';
import {
    rowsToSeries,
    recordsToPoints,
    seriesHasPlottableData,
    drawNoDataOnCanvas,
    resolveColor,
    buildLinearScale,
    buildTimeScaleX,
    maskOutlierPointsByZScore,
    shouldSkipOutlierSuppress,
} from '/static/js/chart_time_series_utils.js';
import {
    CHART_COLORS,
    WG_TIME_SERIES_CARD_CONFIGS,
    fieldsForSource,
    findWgCategoryForCanvas,
} from '/static/js/wg_chart_config.js';

registerForceUtcTimeDisplayPlugin();
registerNearestXByDatasetInteractionMode();

document.addEventListener('DOMContentLoaded', async function() {
    registerForceUtcTimeDisplayPlugin();
    registerNearestXByDatasetInteractionMode();
    // --- Authentication Check ---
    if (!await checkAuth()) {
        return; // Stop further execution if not authenticated and redirection is handled by checkAuth
    }
    const currentUser = await getUserProfile();
    const missionId = document.body.dataset.missionId;
    const missionSelector = document.getElementById('missionSelector'); // Keep this
    const isHistorical = document.body.dataset.isHistorical === 'true';
    const isRealtimeMission = !isHistorical && document.body.dataset.isRealtime === 'true';
    const USER_ROLE = document.body.dataset.userRole || '';
    const USERNAME = document.body.dataset.username || '';
    const urlParams = new URLSearchParams(window.location.search);
    
    // Get enabled sensors from backend configuration
    const enabledSensorsStr = document.body.dataset.enabledSensors || '';
    const enabledSensors = enabledSensorsStr ? enabledSensorsStr.split(',') : [];

    const DATA_LINEAGE_TOOLTIPS = {
        navigation: {
            total_distance_traveled_mission: {
                sourceType: 'raw',
                rawHeader: 'gliderDistance',
                description: 'Calculated as incremental distance accumulated across mission telemetry points.',
            },
        },
    };

    function getDataLineageTooltipLines(tooltipKey) {
        const [category, metric] = tooltipKey.split('.');
        const tooltipMeta = DATA_LINEAGE_TOOLTIPS?.[category]?.[metric];
        if (!tooltipMeta) return [];

        const tooltipLines = [];
        if (tooltipMeta.sourceType === 'raw' && tooltipMeta.rawHeader) {
            tooltipLines.push(`Source: ${tooltipMeta.rawHeader}`);
        }
        if (tooltipMeta.sourceType === 'derived') {
            tooltipLines.push('Derived metric');
        }
        if (tooltipMeta.description) {
            tooltipLines.push(tooltipMeta.description);
        }
        if (tooltipMeta.formula) {
            tooltipLines.push(`Formula: ${tooltipMeta.formula}`);
        }
        return tooltipLines;
    }

    function applyDataLineageTooltipToElement(selector, tooltipKey) {
        const element = document.querySelector(selector);
        if (!element) return;
        const tooltipText = getDataLineageTooltipLines(tooltipKey).join(' ');
        if (!tooltipText) return;
        element.setAttribute('title', tooltipText);
        element.setAttribute('aria-label', tooltipText);
        element.setAttribute('data-bs-toggle', 'tooltip');
        element.setAttribute('data-bs-placement', 'top');
    }

    function initializeDataLineageTooltips() {
        if (!window.bootstrap?.Tooltip) return;
        document
            .querySelectorAll('[data-tooltip-key][data-bs-toggle="tooltip"]')
            .forEach((el) => window.bootstrap.Tooltip.getOrCreateInstance(el));
    }

    applyDataLineageTooltipToElement('[data-tooltip-key="navigation.total_distance_traveled_mission"]', 'navigation.total_distance_traveled_mission');
    initializeDataLineageTooltips();
    
    // Helper function to check if a sensor is enabled
    function isSensorEnabled(sensorName) {
        return enabledSensors.length === 0 || enabledSensors.includes(sensorName);
    }

    // --- Mission Media ---
    const missionMediaForm = document.getElementById('missionMediaUploadForm');
    const missionMediaFile = document.getElementById('missionMediaFile');
    const missionMediaOperation = document.getElementById('missionMediaOperation');
    const missionMediaCaption = document.getElementById('missionMediaCaption');
    const missionMediaGallery = document.getElementById('missionMediaGallery');
    const missionMediaUploadBtn = document.getElementById('missionMediaUploadBtn');
    const missionMediaUploadSpinner = document.getElementById('missionMediaUploadSpinner');
    const overviewPlanContainer = document.getElementById('overviewPlanContainer');
    const overviewPlanLink = document.getElementById('overviewPlanLink');
    const overviewPlanEmpty = document.getElementById('overviewPlanEmpty');
    const overviewWeeklyReportContainer = document.getElementById('overviewWeeklyReportContainer');
    const overviewWeeklyReportLink = document.getElementById('overviewWeeklyReportLink');
    const overviewEndReportContainer = document.getElementById('overviewEndReportContainer');
    const overviewEndReportLink = document.getElementById('overviewEndReportLink');
    const overviewNoReports = document.getElementById('overviewNoReports');
    const overviewSensorTrackerContainer = document.getElementById('overviewSensorTrackerContainer');
    const overviewSensorTrackerEmpty = document.getElementById('overviewSensorTrackerEmpty');
    const overviewStTitle = document.getElementById('overviewStTitle');
    const overviewStStart = document.getElementById('overviewStStart');
    const overviewStEnd = document.getElementById('overviewStEnd');
    const overviewStPlatform = document.getElementById('overviewStPlatform');
    const overviewStDataRepo = document.getElementById('overviewStDataRepo');
    const overviewStDescription = document.getElementById('overviewStDescription');
    const dashboardMissionNotesList = document.getElementById('dashboardMissionNotesList');
    const dashboardMissionGoalsList = document.getElementById('dashboardMissionGoalsList');
    const goalModalElement = document.getElementById('goalModal');
    const goalModal = goalModalElement ? new bootstrap.Modal(goalModalElement) : null;
    const goalModalLabel = document.getElementById('goalModalLabel');
    const goalForm = document.getElementById('goalForm');
    const goalIdInput = document.getElementById('goalIdInput');
    const goalDescriptionInput = document.getElementById('goalDescriptionInput');
    const saveGoalBtn = document.getElementById('saveGoalBtn');
    const missionNoteModalElement = document.getElementById('missionNoteModal');
    const missionNoteModal = missionNoteModalElement ? new bootstrap.Modal(missionNoteModalElement) : null;
    const missionNoteModalLabel = document.getElementById('missionNoteModalLabel');
    const missionNoteIdInput = document.getElementById('missionNoteIdInput');
    const missionNoteContentInput = document.getElementById('missionNoteContentInput');
    const missionNoteIncludeReportWrap = document.getElementById('missionNoteIncludeReportWrap');
    const missionNoteIncludeReport = document.getElementById('missionNoteIncludeReport');
    const saveMissionNoteBtn = document.getElementById('saveMissionNoteBtn');

    let lastMissionNotesForEdit = [];

    // --- PIC Handoffs (Mission-linked) ---
    const dashboardPicHandoffsSpinner = document.getElementById('dashboardPicHandoffsSpinner');
    const dashboardPicHandoffsRefreshBtn = document.getElementById('dashboardPicHandoffsRefreshBtn');
    const dashboardPicHandoffsLatest = document.getElementById('dashboardPicHandoffsLatest');
    const dashboardPicHandoffsTableBody = document.getElementById('dashboardPicHandoffsTableBody');
    const dashboardPicHandoffsEmpty = document.getElementById('dashboardPicHandoffsEmpty');

    const dashboardPicModalElement = document.getElementById('dashboardPicHandoffsFormDetailsModal');
    const dashboardPicModalTitle = document.getElementById('dashboardPicHandoffsFormDetailsModalLabel');
    const dashboardPicModalBody = document.getElementById('dashboardPicHandoffsFormDetailsContent');
    const dashboardPicDetailsModal = dashboardPicModalElement ? new bootstrap.Modal(dashboardPicModalElement) : null;

    const escapeHtml = (value) => {
        if (value === null || value === undefined) return '';
        return String(value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    };

    const formatTimestamp = (value) => {
        if (!value) return '-';
        return formatUtcDateTime(value);
    };

    const renderMediaEmpty = (message) => {
        if (!missionMediaGallery) return;
        missionMediaGallery.innerHTML = `<div class="text-muted small">${message}</div>`;
    };

    const renderMediaCard = (media, canDelete) => {
        const col = document.createElement('div');
        col.className = 'col-md-4 mission-media-item';
        col.dataset.mediaId = media.id;

        const caption = media.caption ? escapeHtml(media.caption) : '';
        const operation = media.operation_type ? escapeHtml(media.operation_type) : 'Unspecified';
        const uploadedBy = escapeHtml(media.uploaded_by_username || 'Unknown');
        const isVideo = media.media_type === 'video';
        const mediaPreview = isVideo
            ? `<video class="card-img-top" controls preload="metadata" style="height: 150px; object-fit: cover;">
                    <source src="${media.file_url}">
               </video>`
            : `<a href="${media.file_url}" target="_blank" rel="noopener noreferrer">
                    <img src="${media.file_url}" class="card-img-top" alt="${caption || 'Mission media'}" style="height: 150px; object-fit: cover;">
               </a>`;

        const approvalStatus = media.approval_status || 'approved';
        const statusBadge = approvalStatus === 'pending'
            ? '<span class="badge bg-warning text-dark">Pending</span>'
            : approvalStatus === 'rejected'
                ? '<span class="badge bg-danger">Rejected</span>'
                : '<span class="badge bg-success">Approved</span>';
        const approveButtons = USER_ROLE === 'admin' && approvalStatus === 'pending'
            ? `<button type="button" class="btn btn-sm btn-success mt-2 mission-media-approve-btn" data-media-id="${media.id}">Approve</button>
               <button type="button" class="btn btn-sm btn-outline-warning mt-2 mission-media-reject-btn" data-media-id="${media.id}">Reject</button>`
            : '';
        const deleteButton = canDelete
            ? `<button type="button" class="btn btn-sm btn-outline-danger mt-2 mission-media-delete-btn" data-media-id="${media.id}">Delete</button>`
            : '';

        col.innerHTML = `
            <div class="card h-100">
                ${mediaPreview}
                <div class="card-body p-2">
                    <div class="small text-muted mb-1">${operation.charAt(0).toUpperCase() + operation.slice(1)} • ${uploadedBy}</div>
                    <div class="mb-1">${statusBadge}</div>
                    ${caption ? `<div class="small">${caption}</div>` : ''}
                    <div class="d-flex flex-wrap gap-2">
                        ${approveButtons}
                        ${deleteButton}
                    </div>
                </div>
            </div>
        `;
        return col;
    };

    const DASHBOARD_RECENT_NOTE_LIMIT = 4;

    const renderMissionNotes = (notes) => {
        if (!dashboardMissionNotesList) return;
        const notesContainer = dashboardMissionNotesList.closest('.mission-notes-container');
        const existingHistory = notesContainer ? notesContainer.querySelector('.older-mission-notes-wrapper') : null;
        if (existingHistory) existingHistory.remove();

        if (!notes || notes.length === 0) {
            lastMissionNotesForEdit = [];
            dashboardMissionNotesList.innerHTML = '<li class="list-group-item text-muted no-mission-notes-placeholder">No mission comments have been added.</li>';
            return;
        }

        const sortedNotes = [...notes].sort((firstNote, secondNote) => {
            const firstTimestamp = Date.parse(firstNote.created_at_utc || '');
            const secondTimestamp = Date.parse(secondNote.created_at_utc || '');
            if (Number.isNaN(firstTimestamp) && Number.isNaN(secondTimestamp)) return 0;
            if (Number.isNaN(firstTimestamp)) return 1;
            if (Number.isNaN(secondTimestamp)) return -1;
            return secondTimestamp - firstTimestamp;
        });

        const recentNotes = sortedNotes.slice(0, DASHBOARD_RECENT_NOTE_LIMIT);
        const olderNotes = sortedNotes.slice(DASHBOARD_RECENT_NOTE_LIMIT);
        lastMissionNotesForEdit = sortedNotes;

        dashboardMissionNotesList.innerHTML = recentNotes.map(note => {
            const canEdit = USER_ROLE === 'admin' || (USERNAME && note.created_by_username === USERNAME);
            return `
                <li class="list-group-item d-flex justify-content-between align-items-start" data-note-id="${note.id}" data-note-created-at="${escapeHtml(note.created_at_utc || '')}">
                    <div>
                        <p class="mb-1">${escapeHtml(note.content)}</p>
                        <small class="text-muted">
                            &mdash; ${escapeHtml(note.created_by_username || 'Unknown')} on ${formatTimestamp(note.created_at_utc)}
                        </small>
                    </div>
                    ${canEdit ? `
                        <div class="d-flex flex-shrink-0 gap-1 ms-2">
                            <button type="button" class="btn btn-sm btn-outline-secondary edit-note-btn" title="Edit comment" data-note-id="${note.id}">
                                <i class="fas fa-pencil-alt"></i>
                            </button>
                            <button type="button" class="btn btn-sm btn-outline-danger delete-note-btn" title="Delete Note" data-note-id="${note.id}">
                                <i class="fas fa-trash-alt"></i>
                            </button>
                        </div>
                    ` : ''}
                </li>
            `;
        }).join('');

        if (!notesContainer || olderNotes.length === 0) return;

        const olderNotesMarkup = olderNotes.map(note => {
            const canEdit = USER_ROLE === 'admin' || (USERNAME && note.created_by_username === USERNAME);
            return `
                <li class="list-group-item d-flex justify-content-between align-items-start" data-note-id="${note.id}" data-note-created-at="${escapeHtml(note.created_at_utc || '')}">
                    <div>
                        <p class="mb-1">${escapeHtml(note.content)}</p>
                        <small class="text-muted">
                            &mdash; ${escapeHtml(note.created_by_username || 'Unknown')} on ${formatTimestamp(note.created_at_utc)}
                        </small>
                    </div>
                    ${canEdit ? `
                        <div class="d-flex flex-shrink-0 gap-1 ms-2">
                            <button type="button" class="btn btn-sm btn-outline-secondary edit-note-btn" title="Edit comment" data-note-id="${note.id}">
                                <i class="fas fa-pencil-alt"></i>
                            </button>
                            <button type="button" class="btn btn-sm btn-outline-danger delete-note-btn" title="Delete Note" data-note-id="${note.id}">
                                <i class="fas fa-trash-alt"></i>
                            </button>
                        </div>
                    ` : ''}
                </li>
            `;
        }).join('');

        const historyWrapper = document.createElement('div');
        historyWrapper.className = 'older-mission-notes-wrapper mt-2';
        historyWrapper.innerHTML = `
            <button type="button" class="btn btn-sm btn-outline-secondary toggle-older-notes-btn">
                Show older comments (${olderNotes.length})
            </button>
            <ul class="list-group older-mission-notes-list d-none mt-2">
                ${olderNotesMarkup}
            </ul>
        `;

        const toggleButton = historyWrapper.querySelector('.toggle-older-notes-btn');
        const olderList = historyWrapper.querySelector('.older-mission-notes-list');
        toggleButton.addEventListener('click', () => {
            const isHidden = olderList.classList.toggle('d-none');
            toggleButton.textContent = isHidden
                ? `Show older comments (${olderNotes.length})`
                : `Hide older comments (${olderNotes.length})`;
        });

        const noteComposerCard = notesContainer.querySelector('.card.mt-3');
        notesContainer.insertBefore(historyWrapper, noteComposerCard || null);
    };

    const renderMissionGoals = (goals) => {
        if (!dashboardMissionGoalsList) return;
        if (!goals || goals.length === 0) {
            dashboardMissionGoalsList.innerHTML = '<li class="list-group-item text-muted no-mission-goals-placeholder">No mission goals have been defined.</li>';
            return;
        }
        dashboardMissionGoalsList.innerHTML = goals.map(goal => {
            const adminControls = USER_ROLE === 'admin'
                ? `
                    <button class="btn btn-sm btn-link p-0 ms-2 edit-goal-btn" title="Edit Goal" data-goal-id="${goal.id}" data-description="${escapeHtml(goal.description)}">
                        <i class="fas fa-pencil-alt"></i>
                    </button>
                    <button class="btn btn-sm btn-link p-0 ms-2 text-danger delete-goal-btn" title="Delete Goal" data-goal-id="${goal.id}">
                        <i class="fas fa-trash-alt"></i>
                    </button>
                `
                : '';
            const completedBadge = goal.is_completed
                ? `<span class="badge bg-success rounded-pill small ms-2" title="Completed at ${formatTimestamp(goal.completed_at_utc)}">
                        By: ${escapeHtml(goal.completed_by_username || '')}
                   </span>`
                : '';
            return `
                <li class="list-group-item d-flex justify-content-between align-items-start" data-goal-id="${goal.id}">
                    <div class="form-check flex-grow-1">
                        <input class="form-check-input mission-goal-checkbox" type="checkbox" id="goal-${goal.id}" data-goal-id="${goal.id}" ${goal.is_completed ? 'checked' : ''}>
                        <label class="form-check-label ${goal.is_completed ? 'text-decoration-line-through text-muted' : ''}" for="goal-${goal.id}">
                            ${escapeHtml(goal.description)}
                        </label>
                        ${adminControls}
                    </div>
                    ${completedBadge}
                </li>
            `;
        }).join('');
    };

    const formatUtcTimestampForTable = (timestampValue) => {
        if (!timestampValue) return 'N/A';
        const formattedValue = formatUtcDateTime(String(timestampValue).endsWith('Z') ? String(timestampValue) : `${timestampValue}Z`);
        return formattedValue === '-' ? 'N/A' : formattedValue;
    };

    const displayPicFormDetailsInModal = (form, changedItemIds = []) => {
        if (!dashboardPicDetailsModal || !dashboardPicModalTitle || !dashboardPicModalBody) {
            console.error('PIC modal elements not found for displaying form details.');
            alert('Could not display form details. Modal components missing.');
            return;
        }
        dashboardPicModalTitle.textContent = `Details for: ${form.form_title} (Mission: ${form.mission_id})`;
        dashboardPicModalBody.innerHTML = renderPicHandoffDetails(form, changedItemIds || [], currentUser);
        dashboardPicDetailsModal.show();
    };

    /** @type {Array<object>} */
    let picHandoffListItems = [];
    let picHandoffListMeta = { days: 30, total: 0, has_more: false, limit: 100, offset: 0, allHistory: false };
    const dashboardPicHandoffsWindowHint = document.getElementById('dashboardPicHandoffsWindowHint');
    const dashboardPicHandoffsLoadOlderWrap = document.getElementById('dashboardPicHandoffsLoadOlderWrap');
    const dashboardPicHandoffsLoadOlderBtn = document.getElementById('dashboardPicHandoffsLoadOlderBtn');

    const updatePicHandoffsWindowUi = () => {
        if (dashboardPicHandoffsWindowHint) {
            if (picHandoffListMeta.allHistory || picHandoffListMeta.days === 0) {
                dashboardPicHandoffsWindowHint.textContent = `Showing all submissions (${picHandoffListItems.length} of ${picHandoffListMeta.total}).`;
            } else {
                dashboardPicHandoffsWindowHint.textContent = `Showing last ${picHandoffListMeta.days} days (${picHandoffListItems.length} of ${picHandoffListMeta.total}).`;
            }
            dashboardPicHandoffsWindowHint.style.display = 'block';
        }
        if (dashboardPicHandoffsLoadOlderWrap) {
            const showOlder = picHandoffListMeta.has_more || (!picHandoffListMeta.allHistory && picHandoffListMeta.days > 0);
            dashboardPicHandoffsLoadOlderWrap.style.display = showOlder ? 'block' : 'none';
        }
        if (dashboardPicHandoffsLoadOlderBtn) {
            if (picHandoffListMeta.has_more) {
                dashboardPicHandoffsLoadOlderBtn.textContent = 'Load more';
            } else if (!picHandoffListMeta.allHistory && picHandoffListMeta.days > 0) {
                dashboardPicHandoffsLoadOlderBtn.textContent = 'Load older submissions';
            }
        }
    };

    const openPicFormDetails = async (summary, { withChanges = false } = {}) => {
        try {
            if (withChanges) {
                const r = await apiRequest(`/api/forms/id/${summary.id}/with-changes`, 'GET');
                displayPicFormDetailsInModal(r.form, r.changed_item_ids || []);
                return;
            }
            const form = await apiRequest(`/api/forms/id/${summary.id}`, 'GET');
            displayPicFormDetailsInModal(form, []);
        } catch (e) {
            console.error('Failed to load PIC form details', e);
            showToast(`Failed to load form details: ${e.message}`, 'danger');
        }
    };

    const renderPicHandoffs = (forms) => {
        if (!dashboardPicHandoffsLatest || !dashboardPicHandoffsTableBody || !dashboardPicHandoffsEmpty) return;

        const hasForms = Array.isArray(forms) && forms.length > 0;

        if (!hasForms) {
            dashboardPicHandoffsLatest.innerHTML = '<div class="text-muted small">No PIC Handoff submissions exist for this mission.</div>';
            dashboardPicHandoffsTableBody.innerHTML = '<tr><td colspan="5" class="text-muted small">No PIC Handoff submissions exist for this mission.</td></tr>';
            dashboardPicHandoffsEmpty.style.display = 'block';
            updatePicHandoffsWindowUi();
            return;
        }

        dashboardPicHandoffsEmpty.style.display = 'none';

        const latest = forms[0];
        dashboardPicHandoffsLatest.innerHTML = `
            <div class="d-flex justify-content-between align-items-start flex-wrap gap-2">
                <div>
                    <div class="fw-bold">${escapeHtml(latest.form_title || 'PIC Handoff Checklist')}</div>
                    <div class="text-muted small">
                        ${escapeHtml(formatUtcTimestampForTable(latest.submission_timestamp))} • ${escapeHtml(latest.submitted_by_username || 'Unknown')}
                    </div>
                </div>
                <div>
                    <button type="button" class="btn btn-sm btn-info" id="dashboardPicHandoffsViewLatestBtn">View Details</button>
                </div>
            </div>
        `;
        const viewLatestBtn = document.getElementById('dashboardPicHandoffsViewLatestBtn');
        if (viewLatestBtn) {
            viewLatestBtn.addEventListener('click', () => openPicFormDetails(latest, { withChanges: true }));
        }

        dashboardPicHandoffsTableBody.innerHTML = '';
        forms.forEach((form, index) => {
            const row = dashboardPicHandoffsTableBody.insertRow();
            row.insertCell().textContent = form.mission_id || '';
            row.insertCell().textContent = form.form_title || '';
            row.insertCell().textContent = formatUtcTimestampForTable(form.submission_timestamp);
            row.insertCell().textContent = form.submitted_by_username || '';

            const actionsCell = row.insertCell();
            const viewButton = document.createElement('button');
            viewButton.classList.add('btn', 'btn-sm', 'btn-info');
            viewButton.textContent = 'View Details';
            viewButton.addEventListener('click', () => openPicFormDetails(form, { withChanges: index === 0 }));
            actionsCell.appendChild(viewButton);
        });
        updatePicHandoffsWindowUi();
    };

    const loadPicHandoffsForMission = async ({ days = 30, offset = 0, append = false, allHistory = false } = {}) => {
        if (!dashboardPicHandoffsSpinner || !dashboardPicHandoffsLatest || !dashboardPicHandoffsTableBody || !dashboardPicHandoffsEmpty) return;

        if (!missionId) {
            dashboardPicHandoffsLatest.innerHTML = '<div class="text-muted small">No mission selected.</div>';
            dashboardPicHandoffsTableBody.innerHTML = '<tr><td colspan="5" class="text-muted small">No mission selected.</td></tr>';
            dashboardPicHandoffsEmpty.style.display = 'none';
            return;
        }

        dashboardPicHandoffsSpinner.style.display = 'block';
        dashboardPicHandoffsEmpty.style.display = 'none';

        try {
            const params = new URLSearchParams();
            params.set('days', String(allHistory ? 0 : days));
            params.set('limit', '100');
            params.set('offset', String(offset));
            const payload = await apiRequest(
                `/api/forms/pic_handoffs/mission/${encodeURIComponent(missionId)}?${params.toString()}`,
                'GET'
            );
            const items = Array.isArray(payload) ? payload : (payload.items || []);
            const meta = Array.isArray(payload)
                ? { days: allHistory ? 0 : days, total: items.length, has_more: false, limit: 100, offset, allHistory }
                : {
                    days: payload.days ?? (allHistory ? 0 : days),
                    total: payload.total ?? items.length,
                    has_more: Boolean(payload.has_more),
                    limit: payload.limit ?? 100,
                    offset: payload.offset ?? offset,
                    allHistory,
                };
            picHandoffListMeta = meta;
            picHandoffListItems = append ? picHandoffListItems.concat(items) : items;
            renderPicHandoffs(picHandoffListItems);
        } catch (error) {
            dashboardPicHandoffsLatest.innerHTML = `<div class="text-danger small">Failed to load PIC submissions: ${escapeHtml(error.message)}</div>`;
            dashboardPicHandoffsTableBody.innerHTML = `<tr><td colspan="5" class="text-danger small">Failed to load PIC submissions: ${escapeHtml(error.message)}</td></tr>`;
            dashboardPicHandoffsEmpty.style.display = 'none';
        } finally {
            dashboardPicHandoffsSpinner.style.display = 'none';
        }
    };

    const loadMissionMedia = async () => {
        if (!missionMediaGallery) return;
        if (!missionId) {
            renderMediaEmpty('No mission selected.');
            return;
        }
        try {
            const includePending = USER_ROLE === 'admin' ? 'true' : 'false';
            const mediaItems = await apiRequest(`/api/missions/${missionId}/media?include_pending=${includePending}`, 'GET');
            if (!mediaItems || mediaItems.length === 0) {
                renderMediaEmpty('No media uploaded for this mission yet.');
                return;
            }
            missionMediaGallery.innerHTML = '';
            mediaItems.forEach((media) => {
                const canDelete = USER_ROLE === 'admin' || (USERNAME && media.uploaded_by_username === USERNAME);
                missionMediaGallery.appendChild(renderMediaCard(media, canDelete));
            });
        } catch (error) {
            renderMediaEmpty(`Failed to load media: ${error.message}`);
        }
    };

    if (missionMediaForm) {
        missionMediaForm.addEventListener('submit', async (event) => {
            event.preventDefault();
            if (!missionId) return;
            const fileToUpload = missionMediaFile ? missionMediaFile.files[0] : null;
            if (!fileToUpload) {
                showToast('Please select a media file to upload.', 'warning');
                return;
            }

            if (missionMediaUploadBtn) missionMediaUploadBtn.disabled = true;
            if (missionMediaUploadSpinner) missionMediaUploadSpinner.style.display = 'inline';

            const formData = new FormData();
            formData.append('file', fileToUpload);

            const params = new URLSearchParams();
            if (missionMediaCaption && missionMediaCaption.value.trim()) {
                params.append('caption', missionMediaCaption.value.trim());
            }
            if (missionMediaOperation && missionMediaOperation.value) {
                params.append('operation_type', missionMediaOperation.value);
            }
            const queryString = params.toString();
            const uploadUrl = `/api/missions/${missionId}/media/upload${queryString ? `?${queryString}` : ''}`;

            try {
                const response = await fetchWithAuth(uploadUrl, {
                    method: 'POST',
                    body: formData
                });
                if (!response.ok) {
                    const err = await response.json();
                    throw new Error(err.detail || 'Media upload failed.');
                }
                const media = await response.json();
                if (media.approval_status === 'pending') {
                    showToast('Media submitted for admin approval.', 'info');
                } else {
                    showToast('Media uploaded successfully!', 'success');
                }
                if (missionMediaFile) missionMediaFile.value = '';
                if (missionMediaCaption) missionMediaCaption.value = '';
                if (missionMediaOperation) missionMediaOperation.value = '';
                await loadMissionMedia();
            } catch (error) {
                showToast(`Upload failed: ${error.message}`, 'danger');
            } finally {
                if (missionMediaUploadBtn) missionMediaUploadBtn.disabled = false;
                if (missionMediaUploadSpinner) missionMediaUploadSpinner.style.display = 'none';
            }
        });
    }

    // PIC submission form link: open form for current mission in a new tab.
    // Use click handler so we always resolve mission at click time (avoids href="#" opening same page in new tab).
    const dashboardPicFormLink = document.getElementById('dashboardPicFormLink');
    if (dashboardPicFormLink) {
        const formUrl = () => {
            const mid = document.body.dataset.missionId || new URLSearchParams(window.location.search).get('mission');
            return mid ? `/mission/${encodeURIComponent(mid)}/form/pic_handoff_checklist.html` : null;
        };
        dashboardPicFormLink.href = formUrl() || '#';
        dashboardPicFormLink.addEventListener('click', (e) => {
            const url = formUrl();
            if (!url) {
                e.preventDefault();
                showToast('Select a mission first.', 'danger');
                return;
            }
            e.preventDefault();
            window.open(url, '_blank', 'noopener,noreferrer');
        });
    }

    // PIC Submissions tab lazy-load
    const picTabButton = document.getElementById('dashboard-pic-tab');
    if (picTabButton) {
        picTabButton.addEventListener('shown.bs.tab', () => {
            loadPicHandoffsForMission({ days: 30, offset: 0, append: false, allHistory: false });
        });
    }
    if (dashboardPicHandoffsRefreshBtn) {
        dashboardPicHandoffsRefreshBtn.addEventListener('click', () => {
            loadPicHandoffsForMission({
                days: picHandoffListMeta.allHistory ? 0 : (picHandoffListMeta.days || 30),
                offset: 0,
                append: false,
                allHistory: picHandoffListMeta.allHistory,
            });
        });
    }
    if (dashboardPicHandoffsLoadOlderBtn) {
        dashboardPicHandoffsLoadOlderBtn.addEventListener('click', () => {
            if (picHandoffListMeta.has_more) {
                loadPicHandoffsForMission({
                    days: picHandoffListMeta.allHistory ? 0 : (picHandoffListMeta.days || 30),
                    offset: picHandoffListItems.length,
                    append: true,
                    allHistory: picHandoffListMeta.allHistory,
                });
                return;
            }
            loadPicHandoffsForMission({ days: 0, offset: 0, append: false, allHistory: true });
        });
    }

    if (missionMediaGallery) {
        missionMediaGallery.addEventListener('click', async (event) => {
            const approveBtn = event.target.closest('.mission-media-approve-btn');
            if (approveBtn && USER_ROLE === 'admin') {
                const mediaId = approveBtn.dataset.mediaId;
                if (!mediaId) return;
                try {
                    await apiRequest(`/api/missions/${missionId}/media/${mediaId}/approve`, 'PUT');
                    showToast('Media approved.', 'success');
                    await loadMissionMedia();
                } catch (error) {
                    showToast(`Approval failed: ${error.message}`, 'danger');
                }
                return;
            }

            const rejectBtn = event.target.closest('.mission-media-reject-btn');
            if (rejectBtn && USER_ROLE === 'admin') {
                const mediaId = rejectBtn.dataset.mediaId;
                if (!mediaId) return;
                if (!confirm('Reject this media item?')) return;
                try {
                    await apiRequest(`/api/missions/${missionId}/media/${mediaId}/reject`, 'PUT');
                    showToast('Media rejected.', 'success');
                    await loadMissionMedia();
                } catch (error) {
                    showToast(`Rejection failed: ${error.message}`, 'danger');
                }
                return;
            }

            const deleteBtn = event.target.closest('.mission-media-delete-btn');
            if (!deleteBtn || !missionId) return;
            const mediaId = deleteBtn.dataset.mediaId;
            if (!mediaId) return;
            if (!confirm('Delete this media item?')) return;

            try {
                await apiRequest(`/api/missions/${missionId}/media/${mediaId}`, 'DELETE');
                showToast('Media deleted.', 'success');
                await loadMissionMedia();
            } catch (error) {
                showToast(`Delete failed: ${error.message}`, 'danger');
            }
        });
    }

    document.body.addEventListener('click', async (event) => {
        const addNoteBtn = event.target.closest('.add-mission-note-btn');
        if (addNoteBtn) {
            event.preventDefault();
            if (!missionId) return;
            const textarea = document.querySelector('.new-mission-note-content');
            const content = textarea ? textarea.value.trim() : '';
            if (!content) {
                showToast('Comment cannot be empty.', 'danger');
                return;
            }
            try {
                await apiRequest(`/api/missions/${missionId}/notes`, 'POST', { content });
                if (USER_ROLE === 'admin') {
                    showToast('Comment added successfully.', 'success');
                } else {
                    showToast('Comment submitted for admin approval.', 'success');
                }
                if (textarea) textarea.value = '';
                await loadMissionOverview();
            } catch (error) {
                showToast(`Failed to add comment: ${error.message}`, 'danger');
            }
            return;
        }

        const editNoteBtn = event.target.closest('.edit-note-btn');
        if (editNoteBtn) {
            event.preventDefault();
            if (!missionId || !missionNoteModal) return;
            const noteId = editNoteBtn.dataset.noteId;
            if (!noteId) return;
            const note = lastMissionNotesForEdit.find((n) => String(n.id) === String(noteId));
            if (!note) {
                showToast('Could not load that comment. Refresh the page and try again.', 'warning');
                return;
            }
            if (missionNoteModalLabel) missionNoteModalLabel.textContent = 'Edit mission comment';
            if (missionNoteIdInput) missionNoteIdInput.value = noteId;
            if (missionNoteContentInput) missionNoteContentInput.value = note.content || '';
            if (missionNoteIncludeReportWrap && missionNoteIncludeReport) {
                missionNoteIncludeReport.checked = Boolean(note.include_in_report);
                missionNoteIncludeReportWrap.classList.remove('d-none');
            }
            missionNoteModal.show();
            return;
        }

        const deleteNoteBtn = event.target.closest('.delete-note-btn');
        if (deleteNoteBtn) {
            event.preventDefault();
            if (!missionId) return;
            const noteId = deleteNoteBtn.dataset.noteId;
            if (!noteId) return;
            if (!confirm('Delete this comment?')) return;
            try {
                await apiRequest(`/api/missions/notes/${noteId}`, 'DELETE');
                showToast('Comment deleted.', 'success');
                await loadMissionOverview();
            } catch (error) {
                showToast(`Failed to delete comment: ${error.message}`, 'danger');
            }
            return;
        }

        const addGoalBtn = event.target.closest('.add-goal-btn');
        if (addGoalBtn) {
            event.preventDefault();
            if (USER_ROLE !== 'admin' || !goalModal) return;
            goalForm.reset();
            goalIdInput.value = '';
            goalModalLabel.textContent = `Add Goal for Mission ${missionId}`;
            goalForm.dataset.missionId = missionId;
            goalModal.show();
            return;
        }

        const editGoalBtn = event.target.closest('.edit-goal-btn');
        if (editGoalBtn) {
            event.preventDefault();
            if (USER_ROLE !== 'admin' || !goalModal) return;
            const goalId = editGoalBtn.dataset.goalId;
            const description = editGoalBtn.dataset.description || '';
            goalForm.reset();
            goalIdInput.value = goalId;
            goalDescriptionInput.value = description;
            goalModalLabel.textContent = `Edit Goal for Mission ${missionId}`;
            goalForm.dataset.missionId = missionId;
            goalModal.show();
            return;
        }

        const deleteGoalBtn = event.target.closest('.delete-goal-btn');
        if (deleteGoalBtn) {
            event.preventDefault();
            if (USER_ROLE !== 'admin') return;
            const goalId = deleteGoalBtn.dataset.goalId;
            if (!goalId) return;
            if (!confirm('Delete this goal?')) return;
            try {
                await apiRequest(`/api/missions/goals/${goalId}`, 'DELETE');
                showToast('Goal deleted.', 'success');
                await loadMissionOverview();
            } catch (error) {
                showToast(`Failed to delete goal: ${error.message}`, 'danger');
            }
            return;
        }
    });

    document.body.addEventListener('change', async (event) => {
        const goalCheckbox = event.target.closest('.mission-goal-checkbox');
        if (!goalCheckbox) return;
        if (!missionId) return;
        const goalId = goalCheckbox.dataset.goalId;
        if (!goalId) return;
        const isCompleted = goalCheckbox.checked;
        try {
            await apiRequest(`/api/missions/${missionId}/goals/${goalId}/toggle`, 'POST', { is_completed: isCompleted });
            await loadMissionOverview();
        } catch (error) {
            goalCheckbox.checked = !isCompleted;
            showToast(`Failed to update goal: ${error.message}`, 'danger');
        }
    });

    if (saveGoalBtn) {
        saveGoalBtn.addEventListener('click', async () => {
            if (USER_ROLE !== 'admin') return;
            const goalId = goalIdInput.value;
            const description = goalDescriptionInput.value.trim();
            if (!description) {
                showToast('Goal description cannot be empty.', 'danger');
                return;
            }
            const isEditing = !!goalId;
            const url = isEditing ? `/api/missions/goals/${goalId}` : `/api/missions/${missionId}/goals`;
            const method = isEditing ? 'PUT' : 'POST';
            try {
                await apiRequest(url, method, { description });
                if (goalModal) goalModal.hide();
                await loadMissionOverview();
            } catch (error) {
                showToast(`Failed to save goal: ${error.message}`, 'danger');
            }
        });
    }

    if (saveMissionNoteBtn && missionNoteModal) {
        saveMissionNoteBtn.addEventListener('click', async () => {
            const id = missionNoteIdInput?.value;
            const content = missionNoteContentInput?.value.trim() || '';
            if (!id || !content) {
                showToast('Comment cannot be empty.', 'danger');
                return;
            }
            const payload = { content };
            if (missionNoteIncludeReportWrap && !missionNoteIncludeReportWrap.classList.contains('d-none') && missionNoteIncludeReport) {
                payload.include_in_report = missionNoteIncludeReport.checked;
            }
            try {
                await apiRequest(`/api/missions/notes/${id}`, 'PUT', payload);
                missionNoteModal.hide();
                showToast('Comment updated.', 'success');
                await loadMissionOverview();
            } catch (error) {
                showToast(`Failed to update comment: ${error.message}`, 'danger');
            }
        });
    }

    const loadMissionOverview = async () => {
        if (!missionId) return;
        try {
            const missionInfo = await apiRequest(`/api/missions/${missionId}/info`, 'GET');
            const overview = missionInfo?.overview || null;
            const weeklyReportUrl = overview?.weekly_report_url || null;
            const endReportUrl = overview?.end_of_mission_report_url || null;
            const planUrl = overview?.document_url || null;

            if (planUrl && overviewPlanLink && overviewPlanContainer && overviewPlanEmpty) {
                overviewPlanLink.href = planUrl;
                overviewPlanLink.textContent = planUrl.split('/').pop();
                overviewPlanContainer.style.display = 'block';
                overviewPlanEmpty.style.display = 'none';
            } else if (overviewPlanEmpty && overviewPlanContainer) {
                overviewPlanContainer.style.display = 'none';
                overviewPlanEmpty.style.display = 'block';
            }

            let hasReports = false;
            if (weeklyReportUrl && overviewWeeklyReportContainer && overviewWeeklyReportLink) {
                overviewWeeklyReportLink.href = weeklyReportUrl;
                overviewWeeklyReportLink.textContent = weeklyReportUrl.split('/').pop();
                overviewWeeklyReportContainer.style.display = 'block';
                hasReports = true;
            } else if (overviewWeeklyReportContainer) {
                overviewWeeklyReportContainer.style.display = 'none';
            }
            if (endReportUrl && overviewEndReportContainer && overviewEndReportLink) {
                overviewEndReportLink.href = endReportUrl;
                overviewEndReportLink.textContent = endReportUrl.split('/').pop();
                overviewEndReportContainer.style.display = 'block';
                hasReports = true;
            } else if (overviewEndReportContainer) {
                overviewEndReportContainer.style.display = 'none';
            }
            if (overviewNoReports) {
                overviewNoReports.style.display = hasReports ? 'none' : 'block';
            }

            const deployment = missionInfo?.sensor_tracker_deployment || null;
            const instruments = missionInfo?.sensor_tracker_instruments || [];
            if (deployment && overviewSensorTrackerContainer && overviewSensorTrackerEmpty) {
                overviewSensorTrackerContainer.style.display = 'block';
                overviewSensorTrackerEmpty.style.display = 'none';
                if (overviewStTitle) overviewStTitle.textContent = deployment.title || '-';
                if (overviewStStart) overviewStStart.textContent = deployment.start_time ? formatUtcDateTime(deployment.start_time) : '-';
                if (overviewStEnd) overviewStEnd.textContent = deployment.end_time ? formatUtcDateTime(deployment.end_time) : '-';
                if (overviewStPlatform) overviewStPlatform.textContent = deployment.platform_name || '-';
                if (overviewStDataRepo) {
                    if (deployment.data_repository_link) {
                        overviewStDataRepo.innerHTML = '';
                        const link = document.createElement('a');
                        link.href = deployment.data_repository_link;
                        link.target = '_blank';
                        link.rel = 'noopener noreferrer';
                        link.textContent = deployment.data_repository_link;
                        overviewStDataRepo.appendChild(link);
                    } else {
                        overviewStDataRepo.textContent = '-';
                    }
                }
                if (overviewStDescription) overviewStDescription.textContent = deployment.deployment_comment || '-';

                renderSensorTrackerInstrumentColumns(instruments, {
                    prefix: 'overviewSt',
                    wrapId: 'overviewStInstruments',
                });
            } else if (overviewSensorTrackerContainer && overviewSensorTrackerEmpty) {
                overviewSensorTrackerContainer.style.display = 'none';
                overviewSensorTrackerEmpty.style.display = 'block';
            }

            renderMissionNotes(missionInfo?.notes || []);
            renderMissionGoals(missionInfo?.goals || []);
        } catch (error) {
            if (overviewPlanEmpty) overviewPlanEmpty.textContent = 'Failed to load overview.';
        }
    };

    // Initial media load
    loadMissionMedia();
    loadMissionOverview();


    // --- Declarative time-series charts ---
    // Spectrum / doughnut stay imperative (waveSpectrumChartInstance below).
    let waveSpectrumChartInstance = null;
    const WG_PLOT_STYLE_PREFIX = 'wgPlotStyle:';
    const chartInstancesByCanvasId = {};
    /** @type {Record<string, { generation: number, fetchInFlight: boolean, bySource: Record<string, object> }>} */
    const wgSeriesCache = {};

    /**
     * Create a WG time-series Chart with shared plot-style, zoom, and hover defaults.
     * New declarative cards in WG_TIME_SERIES_CARD_CONFIGS inherit these automatically.
     * Spectrum / doughnut charts should keep using bare `new Chart(...)`.
     */
    function createWgTimeSeriesChart(canvasId, ctx, config) {
        const prev = chartInstancesByCanvasId[canvasId];
        if (prev) {
            try { prev.destroy(); } catch (_) { /* ignore */ }
        }
        if (!config.data) config.data = {};
        if (!Array.isArray(config.data.datasets)) config.data.datasets = [];
        applyPlotStyleToDatasets(config.data.datasets, WG_PLOT_STYLE_PREFIX, canvasId);
        ensureDatasetHitRadius(config.data.datasets);
        if (!config.options || typeof config.options !== 'object') config.options = {};
        const { options, plugins } = applyTimeSeriesHoverDefaults(config.options);
        config.options = options;
        applyTimeAxisZoom(config.options);
        const existingPlugins = Array.isArray(config.plugins) ? config.plugins : [];
        config.plugins = [...existingPlugins, ...plugins];
        const instance = new Chart(ctx, config);
        chartInstancesByCanvasId[canvasId] = instance;
        return instance;
    }

    function clearWgChartInstance(canvasId) {
        const prev = chartInstancesByCanvasId[canvasId];
        if (prev) {
            try { prev.destroy(); } catch (_) { /* ignore */ }
            delete chartInstancesByCanvasId[canvasId];
        }
    }

    function findWgChartByCanvasId(canvasId) {
        return chartInstancesByCanvasId[canvasId] || null;
    }

    function resizeWgChartsInCategory(category) {
        const key = category === 'telemetry' ? 'navigation' : category;
        const cfg = WG_TIME_SERIES_CARD_CONFIGS[key];
        if (!cfg) return;
        for (const chart of cfg.charts || []) {
            const instance = chartInstancesByCanvasId[chart.canvasId];
            if (instance && typeof instance.resize === 'function') {
                try { instance.resize(); } catch (_) { /* ignore */ }
            }
        }
    }

    function setCategoryChartSpinners(category, visible) {
        const cfg = WG_TIME_SERIES_CARD_CONFIGS[category];
        if (!cfg) return;
        for (const chart of cfg.charts || []) {
            const canvas = document.getElementById(chart.canvasId);
            const spinner = canvas?.parentElement?.querySelector('.chart-spinner');
            if (visible) showChartSpinner(spinner);
            else hideChartSpinner(spinner);
        }
    }

    function resolveSeriesLabel(spec) {
        if (spec.labelKey) {
            const labels = window.FLUOROMETER_CHANNEL_LABELS || {};
            const entry = labels[spec.labelKey];
            if (entry && entry.text) {
                return entry.subscript ? `${entry.text} (${entry.subscript})` : entry.text;
            }
        }
        return spec.label || spec.field;
    }

    /** Enrich telemetry rows with HeadingDiff before pivot (serializable config field). */
    function enrichRowsForSource(category, source, rows) {
        if (!Array.isArray(rows)) return rows || [];
        if (category === 'navigation' && source === 'telemetry') {
            return rows.map((row) => {
                let headingDiff = null;
                if (row.HeadingSubDegrees != null && row.DesiredBearingDegrees != null) {
                    let diff = Number(row.HeadingSubDegrees) - Number(row.DesiredBearingDegrees);
                    while (diff > 180) diff -= 360;
                    while (diff < -180) diff += 360;
                    headingDiff = Number.isFinite(diff) ? diff : null;
                }
                return { ...row, HeadingDiff: headingDiff };
            });
        }
        return rows;
    }

    function reportTypeForWgCategory(category) {
        return category === 'navigation' ? 'telemetry' : category;
    }

    function isOutlierSuppressEnabledForCategory(category) {
        const reportType = reportTypeForWgCategory(category);
        const el = document.querySelector(`.outlier-suppress-toggle[data-report-type="${reportType}"]`);
        return Boolean(el?.checked);
    }

    function reRenderWgCategoryFromCache(category) {
        const cfg = WG_TIME_SERIES_CARD_CONFIGS[category];
        const cached = wgSeriesCache[category];
        if (!cfg || !cached || cached.fetchInFlight) return;
        for (const chartCfg of cfg.charts || []) {
            renderWgTimeSeriesChart(category, chartCfg, cached);
        }
    }

    function renderWgTimeSeriesChart(category, chartCfg, cacheEntry) {
        // New WG time-series sensors: add to wg_chart_config.js — outlier suppress applies
        // in render unless shouldSkipOutlierSuppress(field/label) (circular/geo).
        const canvas = document.getElementById(chartCfg.canvasId);
        if (!canvas || typeof Chart === 'undefined') return;
        const ctx = canvas.getContext('2d');
        if (!ctx) return;

        const suppressOutliers = isOutlierSuppressEnabledForCategory(category);
        const datasets = [];
        for (const spec of chartCfg.series || []) {
            const seriesSource = spec.source || chartCfg.source;
            const records = cacheEntry?.bySource?.[seriesSource]?.[spec.field];
            if (!seriesHasPlottableData(records)) continue;
            let points = recordsToPoints(records, { keepGaps: true });
            const skipSuppress = shouldSkipOutlierSuppress(spec.field)
                || shouldSkipOutlierSuppress(spec.label)
                || shouldSkipOutlierSuppress(resolveSeriesLabel(spec));
            if (suppressOutliers && !skipSuppress) {
                points = maskOutlierPointsByZScore(points).points;
            }
            const borderColor = resolveColor(CHART_COLORS, spec.color, spec.alpha);
            datasets.push({
                type: 'line',
                label: resolveSeriesLabel(spec),
                data: points,
                borderColor,
                backgroundColor: borderColor,
                borderDash: spec.dashed ? [5, 5] : undefined,
                yAxisID: spec.yAxisID || 'y',
                tension: 0.1,
                fill: false,
            });
        }

        if (!datasets.length) {
            clearWgChartInstance(chartCfg.canvasId);
            drawNoDataOnCanvas(chartCfg.canvasId, chartCfg.noDataMessage || 'No data available');
            return;
        }

        const scales = {
            x: buildTimeScaleX({
                tickColor: chartTextColor,
                gridColor: chartGridColor,
                titleColor: chartTextColor,
                titleText: 'Time',
            }),
        };
        for (const axis of chartCfg.yAxes || []) {
            scales[axis.id] = buildLinearScale({
                ...axis,
                textColor: chartTextColor,
                gridColor: chartGridColor,
            });
        }

        createWgTimeSeriesChart(chartCfg.canvasId, ctx, {
            type: 'line',
            data: { datasets },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales,
                plugins: {
                    legend: { position: 'top', labels: { color: chartTextColor } },
                },
            },
        });
    }

    async function loadWgTimeSeriesCategory(category) {
        const cfg = WG_TIME_SERIES_CARD_CONFIGS[category];
        if (!cfg) return;
        if (!isSensorEnabled(cfg.enabledSensor)) return;

        const prev = wgSeriesCache[category] || { generation: 0, fetchInFlight: false, bySource: {} };
        const generation = (prev.generation || 0) + 1;
        wgSeriesCache[category] = { generation, fetchInFlight: true, bySource: prev.bySource || {} };
        setCategoryChartSpinners(category, true);

        try {
            const sourceRows = await Promise.all(
                (cfg.sources || []).map(async (source) => {
                    const rows = await fetchChartData(source, missionId, { manageSpinner: false });
                    return [source, enrichRowsForSource(category, source, rows)];
                })
            );

            if (wgSeriesCache[category]?.generation !== generation) return;

            const bySource = {};
            for (const [source, rows] of sourceRows) {
                const fields = fieldsForSource(cfg, source);
                bySource[source] = rowsToSeries(rows, fields);
            }
            wgSeriesCache[category] = { generation, fetchInFlight: false, bySource };

            for (const chartCfg of cfg.charts || []) {
                renderWgTimeSeriesChart(category, chartCfg, wgSeriesCache[category]);
            }
        } catch (error) {
            if (wgSeriesCache[category]?.generation === generation) {
                wgSeriesCache[category].fetchInFlight = false;
            }
            showToast(`Error loading ${category} data: ${error.message}`, 'danger');
            for (const chartCfg of cfg.charts || []) {
                clearWgChartInstance(chartCfg.canvasId);
                drawNoDataOnCanvas(chartCfg.canvasId, chartCfg.noDataMessage || 'No data available');
            }
        } finally {
            if (wgSeriesCache[category]?.generation === generation) {
                wgSeriesCache[category].fetchInFlight = false;
            }
            setCategoryChartSpinners(category, false);
        }
    }

    function initWgChartControls() {
        bindPlotStyleControls({
            selectSelector: '.chart-plot-style',
            storagePrefix: WG_PLOT_STYLE_PREFIX,
            onChange(canvasId) {
                const category = findWgCategoryForCanvas(canvasId);
                if (!category) return;
                reRenderWgCategoryFromCache(category);
            },
        });
        const zoomAvailable = isChartZoomPluginAvailable();
        document.querySelectorAll('.chart-reset-zoom').forEach((button) => {
            const canvasId = button.dataset.canvasId;
            if (!canvasId) return;
            if (!zoomAvailable) {
                button.disabled = true;
                button.title = 'Chart zoom plugin not loaded';
                return;
            }
            bindResetZoomButton(button, () => findWgChartByCanvasId(canvasId));
        });
        document.querySelectorAll('.chart-zoom-hint').forEach((el) => {
            el.textContent = CHART_ZOOM_HINT;
        });
    }


    // --- Chart Color Variables ---
    // We use 'let' so we can update them when the theme changes.
    let chartTextColor, chartGridColor, miniChartLineColor;

    // Function to update the color variables from CSS
    function updateChartColorVariables() {
        const styles = getComputedStyle(document.documentElement);
        chartTextColor = styles.getPropertyValue('--text-color').trim();
        chartGridColor = styles.getPropertyValue('--card-border').trim();
        miniChartLineColor = styles.getPropertyValue('--active-card-accent').trim();
    }

    // Initial call to set colors on page load
    updateChartColorVariables();

    // Helper function to show spinner with animation restart.
    // Uses a generation token so a pending rAF cannot re-show after hide
    // (common when cached API responses return within the same frame).
    function showChartSpinner(spinner) {
        if (!spinner) return;
        const nextGen = String(Number(spinner.dataset.spinnerGen || 0) + 1);
        spinner.dataset.spinnerGen = nextGen;
        spinner.dataset.spinnerVisible = '1';
        spinner.classList.remove('spinner-border');
        requestAnimationFrame(() => {
            if (spinner.dataset.spinnerGen !== nextGen) return;
            if (spinner.dataset.spinnerVisible !== '1') return;
            spinner.style.display = 'block';
            spinner.classList.add('spinner-border');
        });
    }

    // Helper function to hide spinner
    function hideChartSpinner(spinner) {
        if (!spinner) return;
        spinner.dataset.spinnerVisible = '0';
        spinner.dataset.spinnerGen = String(Number(spinner.dataset.spinnerGen || 0) + 1);
        spinner.style.display = 'none';
    }

    const currentSource = urlParams.get('source') || 'remote';
    const currentLocalPath = urlParams.get('local_path') || '';
    // auotrefresh timer and countdown
    const autoRefreshIntervalMinutes = 5;
    let autoRefreshEnabled = true; // Default to true, will be updated by checkbox/localStorage
    let countdownTimer = null;

    // Date range functionality is now handled per-report-type by checking input values directly

    // Date range utility functions
    function initializeDateRangeInputs() {
        const dateRangeInputs = document.querySelectorAll('.date-range-input');
        dateRangeInputs.forEach(input => {
            // Don't set default values - let users choose their own dates
            // Only add event listeners
            input.addEventListener('change', handleDateRangeChange);
            input.addEventListener('input', handleDateRangeChange); // Also listen to input events for real-time updates
            
            // Check if this input already has a value and trigger the change handler
            if (input.value) {
                handleDateRangeChange({ target: input });
            }
        });
    }

    function initializeClearButtons() {
        const clearButtons = document.querySelectorAll('[id^="clear-date-"]');
        clearButtons.forEach(button => {
            button.addEventListener('click', function() {
                const reportType = this.id.replace('clear-date-', '');
                clearDateRange(reportType);
            });
        });
    }

    function initializeAllDateRangeStates() {
        // Get all unique report types from date range inputs
        const reportTypes = new Set();
        document.querySelectorAll('.date-range-input').forEach(input => {
            if (input.dataset.reportType) {
                reportTypes.add(input.dataset.reportType);
            }
        });
        
        // Initialize state for each report type
        reportTypes.forEach(reportType => {
            const startInput = document.getElementById(`start-date-${reportType}`);
            const endInput = document.getElementById(`end-date-${reportType}`);
            const clearButton = document.getElementById(`clear-date-${reportType}`);
            
            if (startInput && endInput) {
                const startValue = startInput.value;
                const endValue = endInput.value;
                
                // Show/hide clear button based on existing values
                if (clearButton) {
                    if (startValue || endValue) {
                        clearButton.style.display = 'inline-block';
                    } else {
                        clearButton.style.display = 'none';
                    }
                }
                
                // Set hours input state based on date range
                const hoursInput = document.getElementById(`hours-back-${reportType}`);
                if (hoursInput) {
                    if (startValue && endValue) {
                        hoursInput.disabled = true;
                        hoursInput.style.opacity = '0.5';
                    } else {
                        hoursInput.disabled = false;
                        hoursInput.style.opacity = '1';
                    }
                }
            }
        });
    }

    function handleDateRangeChange(event) {
        const input = event.target;
        const reportType = input.dataset.reportType;
        
        // Get both start and end inputs for this report type
        const startInput = document.getElementById(`start-date-${reportType}`);
        const endInput = document.getElementById(`end-date-${reportType}`);
        const clearButton = document.getElementById(`clear-date-${reportType}`);
        
        if (startInput && endInput) {
            const startValue = startInput.value;
            const endValue = endInput.value;
            
            // Show/hide clear button based on whether any date is set
            if (clearButton) {
                if (startValue || endValue) {
                    clearButton.style.display = 'inline-block';
                } else {
                    clearButton.style.display = 'none';
                }
            }
            
            // Check if both dates are provided
            if (startValue && endValue) {
                const startIso = datetimeLocalToUtcIso(startValue);
                const endIso = datetimeLocalToUtcIso(endValue);
                if (!startIso || !endIso) {
                    displayGlobalError('Invalid UTC date range provided.');
                    return;
                }
                const startDate = new Date(startIso);
                const endDate = new Date(endIso);
                
                // Validate date range
                if (startDate >= endDate) {
                    displayGlobalError('Start date must be before end date.');
                    return;
                }
                
                // Disable hours back input when date range is active
                const hoursInput = document.getElementById(`hours-back-${reportType}`);
                if (hoursInput) {
                    hoursInput.disabled = true;
                    hoursInput.style.opacity = '0.5';
                }
            } else {
                // If either date is cleared, re-enable hours back input
                const hoursInput = document.getElementById(`hours-back-${reportType}`);
                if (hoursInput) {
                    hoursInput.disabled = false;
                    hoursInput.style.opacity = '1';
                }
            }
            
            // Always reload chart data when date inputs change
            const loader = getSensorLoader(reportType);
            if (loader) {
                loader();
            }
            if (reportType === 'waves') {
                fetchAndRenderWaveSpectrum(missionId);
            }
        }
    }

    function clearDateRange(reportType) {
        const startInput = document.getElementById(`start-date-${reportType}`);
        const endInput = document.getElementById(`end-date-${reportType}`);
        const clearButton = document.getElementById(`clear-date-${reportType}`);
        
        if (startInput) {
            startInput.value = '';
        }
        if (endInput) {
            endInput.value = '';
        }
        
        // Hide the clear button
        if (clearButton) {
            clearButton.style.display = 'none';
        }
        
        // Re-enable hours back input
        const hoursInput = document.getElementById(`hours-back-${reportType}`);
        if (hoursInput) {
            hoursInput.disabled = false;
            hoursInput.style.opacity = '1';
        }
        
        // Reload chart data
        const loader = getSensorLoader(reportType);
        if (loader) {
            loader();
        }
        if (reportType === 'waves') {
            fetchAndRenderWaveSpectrum(missionId);
        }
    }


    function startCountdownTimer() {
        const countdownElement = document.getElementById('refreshCountdown');
        if (!countdownElement) return;
        if (!autoRefreshEnabled) return; // Don't start if disabled

        let remainingSeconds = autoRefreshIntervalMinutes * 60;

        function updateCountdownDisplay() {
            const minutes = Math.floor(remainingSeconds / 60);
            const seconds = remainingSeconds % 60;
            const display = `${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
            countdownElement.textContent = ` (Next refresh in ${display})`;

            if (remainingSeconds <= 0) {
                clearInterval(countdownTimer); // Stop the countdown
                countdownElement.textContent = ''; // Clear when done
            } else {
                remainingSeconds--;
            }
        }
        updateCountdownDisplay();
        countdownTimer = setInterval(updateCountdownDisplay, 1000);
    }

    const dataSourceModalEl = document.getElementById('dataSourceModal'); // Get the modal element
    if (dataSourceModalEl) {
        const localPathInputGroup = document.getElementById('localPathInputGroup');
        const customLocalPathInput = document.getElementById('customLocalPath');
        const applyDataSourceBtn = document.getElementById('applyDataSource');

        document.querySelectorAll('input[name="dataSourceOption"]').forEach(radio => {
            radio.addEventListener('change', function() {
                if (this.value === 'local') {
                    localPathInputGroup.style.display = 'block';
                } else {
                    localPathInputGroup.style.display = 'none';
                }
            });
        });

        applyDataSourceBtn.addEventListener('click', function() {
            const selectedSource = document.querySelector('input[name="dataSourceOption"]:checked').value;
            let newLocalPath = '';
            if (selectedSource === 'local') {
                newLocalPath = customLocalPathInput.value.trim();
            }

            const currentUrl = new URL(window.location.href);
            currentUrl.searchParams.set('source', selectedSource);
            if (newLocalPath) {
                currentUrl.searchParams.set('local_path', newLocalPath);
            } else {
                currentUrl.searchParams.delete('local_path');
            }
            const modalInstance = bootstrap.Modal.getInstance(dataSourceModalEl);
            if (modalInstance) {
                modalInstance.hide();
            }
            setTimeout(() => { window.location.href = currentUrl.toString(); }, 150);
        });
    }

    // Fetch and populate missions *after* auth check and other initial setup


    // --- Auto-Refresh Toggle Logic ---
    const autoRefreshToggle = document.getElementById('autoRefreshToggleBanner');
    // Store cache timestamps for each report type
    const cacheTimestamps = new Map(); // reportType -> { cache_timestamp, last_data_timestamp, file_modification_time }
    // Track which sensor categories have been loaded so soft refresh can reload them quietly.
    // Declared early so cache-poll soft refresh can run before the rest of UI init.
    const loadedCategories = new Set();

    // Cache polling for real-time missions
    // Note: Background cache refresh runs every 10 minutes (configured in .env)
    // Polling every 30 seconds ensures we detect updates within 30 seconds of cache refresh
    let cachePollInterval = null;
    const CACHE_POLL_INTERVAL_MS = 30000; // Poll every 30 seconds (cache refreshes every 10 min)

    function formatCardSummaryValue(value, digits = 1) {
        if (value === null || value === undefined || Number.isNaN(Number(value))) return 'N/A';
        return Number(value).toFixed(digits);
    }

    function updateWgDetailLastDataFooter(category, summary) {
        const detailView = document.getElementById(`detail-${category}`);
        if (!detailView || !summary) return;
        const footer = detailView.querySelector('.card-footer');
        if (!footer) return;
        const latest = summary.latest_timestamp_str || 'N/A';
        const timeAgo = summary.time_ago_str || 'N/A';
        if (latest !== 'N/A') {
            footer.textContent = `Last data: ${latest} (${timeAgo})`;
        } else {
            footer.textContent = 'Last data: N/A';
        }
    }

    function updateWgDetailLastDataFromTimestamp(category, isoTimestamp) {
        if (!category || !isoTimestamp) return;
        const detailView = document.getElementById(`detail-${category}`);
        if (!detailView) return;
        const footer = detailView.querySelector('.card-footer');
        if (!footer) return;
        const formatted = formatUtcDateTime(isoTimestamp);
        if (!formatted || formatted === '-') {
            footer.textContent = 'Last data: N/A';
            return;
        }
        footer.textContent = `Last data: ${formatted}`;
    }

    function updateWgCardFromSummary(category, summary) {
        const card = document.querySelector(`#left-nav-panel .summary-card[data-category="${category}"]`);
        if (!card || !summary) return;

        const values = summary.values || {};
        const miniSummary = card.querySelector('.mini-summary');
        const footer = card.querySelector('.summary-card-footer');

        if (category === 'navigation' && miniSummary) {
            const sog = values.SpeedOverGround != null ? `${formatCardSummaryValue(values.SpeedOverGround, 1)} kn` : 'N/A';
            const pog = values.GliderHeading != null ? `${formatCardSummaryValue(values.GliderHeading, 0)} °` : 'N/A';
            miniSummary.innerHTML = `SOG: ${sog}<br>POG: ${pog}`;
        } else if (category === 'power' && miniSummary) {
            const batt = values.BatteryPercentage != null ? `${formatCardSummaryValue(values.BatteryPercentage, 0)}%` : 'N/A';
            const net = values.BatteryChargeRateW != null ? `${formatCardSummaryValue(values.BatteryChargeRateW, 1)} W` : 'N/A';
            miniSummary.innerHTML = `Batt: ${batt}<br>Net: ${net}`;
        } else if (category === 'ctd' && miniSummary) {
            const temp = values.WaterTemperature != null ? `${formatCardSummaryValue(values.WaterTemperature, 1)} °C` : 'N/A';
            const sal = values.Salinity != null ? `${formatCardSummaryValue(values.Salinity, 1)} PSU` : 'N/A';
            miniSummary.innerHTML = `Temp: ${temp}<br>Sal: ${sal}`;
        } else if (category === 'weather' && miniSummary) {
            const air = values.AirTemperature != null ? `${formatCardSummaryValue(values.AirTemperature, 1)} °C` : 'N/A';
            const wind = values.WindSpeed != null ? `${formatCardSummaryValue(values.WindSpeed, 1)} kt` : 'N/A';
            miniSummary.innerHTML = `Air: ${air}<br>Wind: ${wind}`;
        } else if (category === 'waves' && miniSummary) {
            const hs = values.SignificantWaveHeight != null ? `${formatCardSummaryValue(values.SignificantWaveHeight, 1)} m` : 'N/A';
            const dp = values.MeanDirectionDisplay != null ? values.MeanDirectionDisplay : 'N/A';
            const dpClass = values.MeanDirectionStatus === 'outlier' ? ' class="text-warning"' : '';
            const dpTitle = values.MeanDirectionStatus === 'outlier'
                ? ' title="Latest data point was an invalid outlier (e.g., 9999)."'
                : '';
            miniSummary.innerHTML = `Hs: ${hs}<br>Dp: <span${dpTitle}${dpClass}>${dp}</span>`;
            if (summary.ess_state) {
                card.dataset.essState = summary.ess_state;
            } else {
                delete card.dataset.essState;
            }
            const titleEl = card.querySelector('h5');
            if (titleEl) {
                let essSpan = titleEl.querySelector('.ess-indicator');
                if (summary.ess_state) {
                    if (!essSpan) {
                        essSpan = document.createElement('span');
                        titleEl.appendChild(document.createTextNode(' '));
                        titleEl.appendChild(essSpan);
                    }
                    essSpan.className = `ess-indicator ess-${summary.ess_state}`;
                    const titles = {
                        extreme: 'Extreme sea state (≥4.5 m) — figure-8 pattern required',
                        increasing: 'Increasing seas (2.5–4.5 m)',
                        calm: 'Calm seas (<2.5 m)',
                    };
                    essSpan.title = titles[summary.ess_state] || '';
                    essSpan.setAttribute('aria-label', `Sea state: ${summary.ess_state}`);
                } else if (essSpan) {
                    essSpan.remove();
                }
            }
        } else if (category === 'vr2c' && miniSummary) {
            const dc = values.DetectionCount != null ? values.DetectionCount : 'N/A';
            const pc = values.PingCount != null ? values.PingCount : 'N/A';
            miniSummary.innerHTML = `DC: ${dc}<br>PC: ${pc}`;
        } else if (category === 'fluorometer' && miniSummary) {
            const c1 = values.C1_Avg != null ? formatCardSummaryValue(values.C1_Avg, 1) : 'N/A';
            const temp = values.Temperature_Fluor != null ? `${formatCardSummaryValue(values.Temperature_Fluor, 1)} °C` : 'N/A';
            miniSummary.innerHTML = `C1 Avg: ${c1}<br>Temp: ${temp}`;
        } else if (category === 'wg_vm4' && miniSummary) {
            const sn = values.SerialNumber != null ? values.SerialNumber : 'N/A';
            const ch0 = values.Channel0DetectionCount != null ? values.Channel0DetectionCount : 'N/A';
            miniSummary.innerHTML = `SN: ${sn}<br>Ch0 DC: ${ch0}`;
        }

        if (footer) {
            footer.textContent = summary.time_ago_str || 'N/A';
        }
        const miniTrend = Array.isArray(summary.mini_trend) ? summary.mini_trend : [];
        card.dataset.miniTrend = JSON.stringify(miniTrend);
        updateWgDetailLastDataFooter(category, summary);
    }

    async function refreshWgSummaryCards() {
        if (!missionId) return;
        try {
            const params = new URLSearchParams();
            if (currentSource) params.set('source', currentSource);
            if (currentSource === 'local' && currentLocalPath) {
                params.set('local_path', currentLocalPath);
            }
            const qs = params.toString();
            const sensors = await apiRequest(
                `/api/wave_glider/sensor-summaries/${encodeURIComponent(missionId)}${qs ? `?${qs}` : ''}`,
                'GET',
            );
            if (!sensors || typeof sensors !== 'object') return;
            Object.entries(sensors).forEach(([category, summary]) => {
                updateWgCardFromSummary(category, summary);
            });
            initializeMiniCharts();
        } catch (err) {
            console.debug('Wave Glider summary card refresh failed:', err);
        }
    }

    function refreshAllLoadedWgChartsQuiet() {
        loadedCategories.forEach((category) => {
            const loader = getSensorLoader(category);
            if (loader) loader();
            if (category === 'waves') {
                fetchAndRenderWaveSpectrum(missionId);
            }
        });
    }

    async function pollCacheStatus() {
        // Debug logging
        if (!isRealtimeMission) {
            console.debug('Cache polling skipped: Not a real-time mission');
            return;
        }
        if (!autoRefreshEnabled) {
            console.debug('Cache polling skipped: Auto-refresh disabled');
            return;
        }

        try {
            console.debug(`Polling cache status for mission ${missionId}...`);
            // Always include core Wave Glider report types so science updates can trigger reloads
            // even before a user manually opens each science detail card in this session.
            const defaultPolledReportTypes = [
                'telemetry',
                'power',
                'solar',
                'ctd',
                'weather',
                'waves',
                'fluorometer',
                'wg_vm4',
                'vr2c',
            ];
            const polledReportTypes = Array.from(
                new Set([...defaultPolledReportTypes, ...Array.from(cacheTimestamps.keys())])
            );
            const cacheStatusQueryParams = new URLSearchParams();
            if (polledReportTypes.length > 0) cacheStatusQueryParams.set('report_types', polledReportTypes.join(','));
            if (currentSource) cacheStatusQueryParams.set('source', currentSource);
            if (currentSource === 'local' && currentLocalPath) cacheStatusQueryParams.set('local_path', currentLocalPath);

            const cacheStatusEndpoint = cacheStatusQueryParams.toString()
                ? `/api/cache-status/${missionId}?${cacheStatusQueryParams.toString()}`
                : `/api/cache-status/${missionId}`;
            const cacheStatus = await apiRequest(cacheStatusEndpoint, 'GET');
            console.debug('Cache status received:', cacheStatus);
            
            // Track if any cache has been updated
            let cacheUpdated = false;
            let updatedReportTypes = [];
            
            // Check each report type for updates
            for (const [reportType, status] of Object.entries(cacheStatus)) {
                const stored = cacheTimestamps.get(reportType);
                
                // If we have stored timestamps, compare with server
                if (stored && status.cache_timestamp) {
                    const storedTime = new Date(stored.cache_timestamp);
                    const serverTime = new Date(status.cache_timestamp);
                    const storedLastDataTime = stored.last_data_timestamp ? new Date(stored.last_data_timestamp) : null;
                    const serverLastDataTime = status.last_data_timestamp ? new Date(status.last_data_timestamp) : null;
                    const hasDataAdvanced =
                        storedLastDataTime instanceof Date &&
                        !Number.isNaN(storedLastDataTime.getTime()) &&
                        serverLastDataTime instanceof Date &&
                        !Number.isNaN(serverLastDataTime.getTime()) &&
                        serverLastDataTime > storedLastDataTime;
                    
                    // Prefer true data progression signal over cache refresh-attempt signal.
                    // Fallback to cache timestamp only if we do not yet have last_data_timestamp.
                    const shouldReloadFromCacheTimestamp = !storedLastDataTime && serverTime > storedTime;
                    if (hasDataAdvanced || shouldReloadFromCacheTimestamp) {
                        const timeDiff = (serverTime - storedTime) / 1000; // seconds
                        console.log(
                            `Cache updated for ${reportType}: stored=${stored.cache_timestamp}, `
                            + `server=${status.cache_timestamp}, diff=${timeDiff.toFixed(1)}s, `
                            + `stored_last_data=${stored.last_data_timestamp || 'none'}, `
                            + `server_last_data=${status.last_data_timestamp || 'none'}`
                        );
                        cacheUpdated = true;
                        updatedReportTypes.push(reportType);
                        // Update stored timestamp
                        cacheTimestamps.set(reportType, {
                            cache_timestamp: status.cache_timestamp,
                            last_data_timestamp: status.last_data_timestamp
                        });
                    } else {
                        console.debug(`Cache for ${reportType} unchanged: stored=${stored.cache_timestamp}, server=${status.cache_timestamp}`);
                    }
                } else if (status.cache_timestamp && !stored) {
                    // First time seeing this report type with cache data
                    console.debug(`Initializing cache timestamp for ${reportType}: ${status.cache_timestamp}`);
                    cacheTimestamps.set(reportType, {
                        cache_timestamp: status.cache_timestamp,
                        last_data_timestamp: status.last_data_timestamp
                    });
                } else if (!status.cache_timestamp) {
                    console.debug(`No cache timestamp available for ${reportType}`);
                }
            }
            
            // Soft refresh: update charts + summary cards without a full page reload
            // (parity with Slocum). Fallback timer below still hard-reloads as safety net.
            if (cacheUpdated) {
                console.log(
                    `Cache refresh detected for: ${updatedReportTypes.join(', ')}. Soft-refreshing charts and summaries...`
                );
                refreshAllLoadedWgChartsQuiet();
                refreshWgSummaryCards();
            } else {
                console.debug('No cache updates detected in this poll');
            }
        } catch (error) {
            console.warn('Error polling cache status:', error);
            // Don't show toast for polling errors to avoid spam
        }
    }

    function updateAutoRefreshState(isEnabled) {
        autoRefreshEnabled = isEnabled;
        localStorage.setItem('autoRefreshEnabled', isEnabled);
        if (isEnabled && isRealtimeMission) {
            startCountdownTimer(); // Restart countdown if enabled and on a real-time mission
            // Start cache polling
            if (!cachePollInterval) {
                console.log(`Starting cache polling: interval=${CACHE_POLL_INTERVAL_MS}ms, mission=${missionId}, isRealtime=${isRealtimeMission}`);
                cachePollInterval = setInterval(pollCacheStatus, CACHE_POLL_INTERVAL_MS);
                // Do an initial poll immediately
                pollCacheStatus();
            }
        } else {
            clearInterval(countdownTimer);
            // Stop cache polling
            if (cachePollInterval) {
                console.log('Stopping cache polling');
                clearInterval(cachePollInterval);
                cachePollInterval = null;
            }
            const countdownElement = document.getElementById('refreshCountdown');
            if (countdownElement) countdownElement.textContent = ''; // Clear countdown display
        }
    }

    if (autoRefreshToggle) {
        const savedPreference = localStorage.getItem('autoRefreshEnabled');
        if (savedPreference !== null) {
            autoRefreshToggle.checked = JSON.parse(savedPreference);
        }
        updateAutoRefreshState(autoRefreshToggle.checked); // Initialize based on current state (saved or default)

        autoRefreshToggle.addEventListener('change', function() {
            updateAutoRefreshState(this.checked);
        });
    }

    // Legacy auto-refresh (full page reload) - keep as fallback for very long periods
    // Cache polling will handle most refreshes, but this ensures we refresh even if polling fails
    if (isRealtimeMission) {
        setTimeout(function() {
            if (autoRefreshEnabled && !document.querySelector('.modal.show')) { 
                // Fallback: refresh after the configured interval even if polling didn't detect changes
                // This handles edge cases where cache timestamps might not change but data did
                console.log('Fallback auto-refresh triggered after interval');
                window.location.reload(true); 
            }
        }, autoRefreshIntervalMinutes * 60 * 1000);
    }

    function displayGlobalError(message) {
        const errorDiv = document.getElementById('generalErrorDisplay');
        errorDiv.textContent = message || 'An error occurred. Please check console or try again later.';
        errorDiv.style.display = 'block';
    }
    // Refresh Data Button Logic
    /**
     * Fetches chart data from the API for a given report type and mission.
     * @param {string} reportType - The type of report (e.g., 'power', 'ctd').
     * @param {string} mission - The mission ID.
     * @param {number} hours - The number of hours back to fetch data for.
     * @returns {Promise<Array<Object>|null>} A promise that resolves with the chart data array or null if fetching fails.
     */
    async function fetchChartData(reportType, mission, options = {}) {
        const manageSpinner = options.manageSpinner !== false;
        const chartCanvas = document.getElementById(`${reportType}Chart`); 
        const spinner = chartCanvas ? chartCanvas.parentElement.querySelector('.chart-spinner') : null;
        if (manageSpinner) showChartSpinner(spinner);

        // Find controls specific to this report type, if they exist.
        const hoursInput = document.querySelector(`.hours-back-input[data-report-type="${reportType}"]`);
        const granularitySelect = document.querySelector(`.granularity-select[data-report-type="${reportType}"]`);

        const hours = hoursInput ? hoursInput.value : 72; // Default to 72 if no input found
        const granularity = granularitySelect ? granularitySelect.value : 0; // Default: all points (no resample)

        try {
            // Check if date range is enabled for this report type
            const startInput = document.getElementById(`start-date-${reportType}`);
            const endInput = document.getElementById(`end-date-${reportType}`);
            const isDateRangeActive = startInput && endInput && startInput.value && endInput.value;
            
            let apiUrl;
            if (isDateRangeActive) {
                // Use date range mode - don't include hours_back parameter
                apiUrl = `/api/data/${reportType}/${mission}?granularity_minutes=${granularity}`;
                
                // Add date range parameters
                const startISO = datetimeLocalToUtcIso(startInput.value);
                const endISO = datetimeLocalToUtcIso(endInput.value);
                if (!startISO || !endISO) throw new Error('Invalid UTC date range values.');
                apiUrl += `&start_date=${encodeURIComponent(startISO)}&end_date=${encodeURIComponent(endISO)}`;
                
                // Date range mode
            } else {
                // Use hours back mode
                apiUrl = `/api/data/${reportType}/${mission}?hours_back=${hours}&granularity_minutes=${granularity}`;
            }
            
            apiUrl += `&source=${currentSource}`;
            if (currentSource === 'local' && currentLocalPath) {
                apiUrl += `&local_path=${encodeURIComponent(currentLocalPath)}`;
            }
            if (urlParams.has('refresh') && urlParams.get('refresh') === 'true') {
                apiUrl += `&refresh=true`;
            }
            
            const response = await apiRequest(apiUrl, 'GET');
            
            // Handle new response format with cache metadata
            let data;
            if (response && typeof response === 'object' && 'data' in response) {
                // New format with cache_metadata
                data = response.data;
                // Store cache timestamps
                if (response.cache_metadata) {
                    cacheTimestamps.set(reportType, {
                        cache_timestamp: response.cache_metadata.cache_timestamp,
                        last_data_timestamp: response.cache_metadata.last_data_timestamp,
                        file_modification_time: response.cache_metadata.file_modification_time
                    });
                    // Keep detail "Last data" footer in sync when charts fetch fresh rows
                    const footerCategory = reportType === 'telemetry' ? 'navigation' : reportType;
                    if (
                        response.cache_metadata.last_data_timestamp
                        && [
                            'navigation', 'power', 'ctd', 'weather', 'waves',
                            'vr2c', 'fluorometer', 'wg_vm4',
                        ].includes(footerCategory)
                    ) {
                        updateWgDetailLastDataFromTimestamp(
                            footerCategory,
                            response.cache_metadata.last_data_timestamp,
                        );
                    }
                }
            } else {
                // Legacy format (array directly) - backward compatibility
                data = response;
            }
            
            return data;
        } catch (error) {
            showToast(`Error loading ${reportType} data: ${error.message}`, 'danger');
            displayGlobalError(`Network error while fetching ${reportType} chart data.`);
            return null;
        } finally {
            if (manageSpinner) hideChartSpinner(spinner);
        }
    }
    // --- Weather Forecast ---
    async function fetchForecastData(mission) {
        try {
            const initialForecastArea = document.getElementById('forecastInitial');
            // Spinner management removed for forecast
            if (initialForecastArea) initialForecastArea.style.display = 'none'; // Ensure content area is hidden

            // Check if this is a historical mission
            const isHistorical = document.body.dataset.isHistorical === 'true';

            let forecastApiUrl = `/api/forecast/${mission}`;
            const forecastParams = new URLSearchParams();
            forecastParams.append('source', currentSource);
            if (currentSource === 'local' && currentLocalPath) {
                forecastParams.append('local_path', currentLocalPath);
            }
            // Pass refresh parameter to forecast API if present in main page URL
            if (urlParams.has('refresh') && urlParams.get('refresh') === 'true') {
                forecastParams.append('refresh', 'true');
            }
            // Pass is_historical parameter
            if (isHistorical) {
                forecastParams.append('is_historical', 'true');
            }
            
            // Add date range parameters if date range is enabled for weather
            const startInput = document.getElementById('start-date-weather');
            const endInput = document.getElementById('end-date-weather');
            if (startInput && endInput && startInput.value && endInput.value) {
                const startISO = datetimeLocalToUtcIso(startInput.value);
                const endISO = datetimeLocalToUtcIso(endInput.value);
                if (startISO && endISO) {
                    forecastParams.append('start_date', startISO);
                    forecastParams.append('end_date', endISO);
                }
            }
            const forecastData = await apiRequest(`${forecastApiUrl}?${forecastParams.toString()}`, 'GET');
            return forecastData;
        } catch (error) {
            showToast(`Error loading forecast: ${error.message}`, 'danger');
            displayGlobalError('Failed to load weather forecast.');
            return null;
        }
    }

    // WMO Weather code descriptions (simplified)
    // Source: https://open-meteo.com/en/docs (Weather WMO Code Table)
    const WMO_WEATHER_CODES = {
        0: 'Clear sky',
        1: 'Mainly clear',
        2: 'Partly cloudy',
        3: 'Overcast',
        45: 'Fog',
        48: 'Depositing rime fog',
        51: 'Light drizzle',
        53: 'Moderate drizzle',
        55: 'Dense drizzle',
        56: 'Light freezing drizzle',
        57: 'Dense freezing drizzle',
        61: 'Slight rain',
        63: 'Moderate rain',
        65: 'Heavy rain',
        66: 'Light freezing rain',
        67: 'Heavy freezing rain',
        71: 'Slight snow fall',
        73: 'Moderate snow fall',
        75: 'Heavy snow fall',
        77: 'Snow grains',
        80: 'Slight rain showers',
        81: 'Moderate rain showers',
        82: 'Violent rain showers',
        85: 'Slight snow showers',
        86: 'Heavy snow showers',
        95: 'Thunderstorm', // Slight or moderate
        96: 'Thunderstorm with slight hail',
        99: 'Thunderstorm with heavy hail',
    };

    function getWeatherDescription(code) {
        return WMO_WEATHER_CODES[code] || 'Unknown';
    }

    /**
     * Renders the weather forecast table.
     * @param {Object|null} forecastData - The forecast data object fetched from the API.
     */

    function renderForecast(forecastData) {
        const initialContainer = document.getElementById('forecastInitial');
        const extendedContainer = document.getElementById('forecastExtendedContent');
        const toggleButton = document.getElementById('toggleForecastBtn');
        // Spinner management removed for forecast

        if (!forecastData || !forecastData.hourly || !forecastData.hourly.time || forecastData.hourly.time.length === 0) {
            initialContainer.innerHTML = '<p class="text-muted">Forecast data is currently unavailable.</p>';
            if (extendedContainer) extendedContainer.innerHTML = '';
            if (toggleButton) toggleButton.style.display = 'none';
        } else {
            // Add a title indicating the forecast type
            let forecastTitle = 'Weather Forecast';
 // The 'forecast_type' is added by our backend wrapper in forecast.py
            if (forecastData.forecast_type === 'marine') {
                forecastTitle += ' (Marine & General)';
            } else if (forecastData.forecast_type === 'general') {
                forecastTitle += ' (General Weather)'; // Simplified title
            }
            const nearestUtcLegend = '<p class="small text-muted mb-2">Nearest UTC forecast <span class="sampling-hint-icon" title="Rows are anchored to the forecast timestamp closest to the current UTC time." aria-label="Nearest UTC forecast help">?</span></p>';
            initialContainer.innerHTML = `<h5 class="text-muted fst-italic">${forecastTitle}</h5>${nearestUtcLegend}`; // Prepend title

            const hourly = forecastData.hourly;
            const units = forecastData.hourly_units || {}; // Get units from the forecast data
            const windSpeedUnit = units.windspeed_10m === 'kn' ? 'kt' : (units.windspeed_10m || 'kt');
            const totalHoursAvailable = hourly.time.length;
            const nearestForecastIndex = findNearestTimeIndexUtc(hourly.time);

            const createTableHtml = (startHour, endHour, highlightedIndex) => {
                let tableHtml = '<table class="table table-sm table-striped table-hover">';
                tableHtml += '<thead><tr>' +
                             '<th>Time</th>' +
                             '<th>Weather</th>' +
                             `<th>Air Temp (${units.temperature_2m || '°C'})</th>` + // Default unit if not provided
                             `<th>Precip (${units.precipitation || 'mm'})</th>` +   // Default unit
                             `<th>Wind (${windSpeedUnit} @ ${units.winddirection_10m || '°'})</th>`;
                tableHtml += '</tr></thead>';
                tableHtml += '<tbody>';

                for (let i = startHour; i < endHour && i < totalHoursAvailable; i++) {
                    const time = formatUtcDateTime(hourly.time[i]);
                    
                    const weatherCode = (hourly.weathercode && hourly.weathercode[i] !== null) ? hourly.weathercode[i] : 'N/A';
                    const weatherDisplay = getWeatherDescription(weatherCode);

                    const airTemp = (hourly.temperature_2m && hourly.temperature_2m[i] !== null) ? hourly.temperature_2m[i].toFixed(1) : 'N/A';
                    const precip = (hourly.precipitation && hourly.precipitation[i] !== null) ? hourly.precipitation[i].toFixed(1) : 'N/A';
                    
                    // Wind data (speed and direction)
                    const windSpeed = (hourly.windspeed_10m && hourly.windspeed_10m[i] !== null) ? hourly.windspeed_10m[i].toFixed(1) : 'N/A';
                    const windDir = (hourly.winddirection_10m && hourly.winddirection_10m[i] !== null) ? hourly.winddirection_10m[i].toFixed(0) : 'N/A';
                    const windDisplay = windSpeed !== 'N/A' ? `${windSpeed} @ ${windDir}°` : 'N/A';
                    const nearestClass = i === highlightedIndex ? ' class="forecast-current-row"' : '';

                    tableHtml += `<tr${nearestClass}>` +
                                 `<td>${time}</td>` +
                                 `<td>${weatherDisplay}</td>` +
                                 `<td>${airTemp}</td>` +
                                 `<td>${precip}</td>` +
                                 `<td>${windDisplay}</td>` +
                                 `</tr>`;
                }
                tableHtml += '</tbody></table>';
                return tableHtml;
            };

            const initialHours = 12;
            const maxHoursAcrossViews = 48;
            const boundedStartHour = nearestForecastIndex >= 0 ? nearestForecastIndex : 0;
            const maxEndHour = Math.min(totalHoursAvailable, boundedStartHour + maxHoursAcrossViews);
            const initialEndHour = Math.min(maxEndHour, boundedStartHour + initialHours);
            // Append the table to the initial container, after the title
            initialContainer.innerHTML += createTableHtml(boundedStartHour, initialEndHour, nearestForecastIndex);

            const extendedStartHour = initialEndHour;

            if (maxEndHour > initialEndHour) {
                extendedContainer.innerHTML = createTableHtml(extendedStartHour, maxEndHour, nearestForecastIndex);
                toggleButton.style.display = 'block'; // Show the button
                
                const collapseElement = document.getElementById('forecastExtended');
                // Listener to update button text
                collapseElement.addEventListener('show.bs.collapse', function () {
                    toggleButton.textContent = 'Show Less';
                });
                collapseElement.addEventListener('hide.bs.collapse', function () {
                    toggleButton.textContent = 'Show More';
                });
                // Set initial text
                if (!collapseElement.classList.contains('show')) {
                     toggleButton.textContent = 'Show More';
                } else {
                     toggleButton.textContent = 'Show Less';
                }
            } else {
                if (extendedContainer) extendedContainer.innerHTML = '';
                if (toggleButton) toggleButton.style.display = 'none';
         }          }
         // Ensure spinner is hidden and content area is visible
         // Spinner management removed for forecast

        initialContainer.style.display = 'block';

        // Populate forecast metadata
        const metaInfoContainer = document.getElementById('forecastMetaInfo');
        if (metaInfoContainer) {
            if (forecastData && forecastData.fetched_at_utc && forecastData.latitude_used !== undefined && forecastData.longitude_used !== undefined) {
                const fetchedDate = new Date(forecastData.fetched_at_utc);
                const formattedTime = formatUtcDateTime(fetchedDate);
                const lat = parseFloat(forecastData.latitude_used).toFixed(3); // Corrected: Use forecastData
                const lon = parseFloat(forecastData.longitude_used).toFixed(3); // Corrected: Use forecastData
            metaInfoContainer.textContent = `Forecast fetched: ${formattedTime} for Lat: ${lat}, Lon: ${lon}`;
             metaInfoContainer.style.display = 'block';
            } else {
                metaInfoContainer.textContent = ''; // Clear if no data
                metaInfoContainer.style.display = 'none'; // Hide if no data
            }
        }
    }

    async function fetchMarineForecastData(mission) {
        try {
            const initialMarineForecastArea = document.getElementById('marineForecastInitial');
            if (initialMarineForecastArea) initialMarineForecastArea.style.display = 'none';

            // Check if this is a historical mission
            const isHistorical = document.body.dataset.isHistorical === 'true';

            let marineForecastApiUrl = `/api/marine_forecast/${mission}`;
            const forecastParams = new URLSearchParams();
            // Marine forecast might need lat/lon explicitly if not inferred by backend for this specific endpoint
            // For now, assuming backend handles it or we pass lat/lon if available from telemetry summary
            // Example: if (currentGliderLat && currentGliderLon) {
            //    forecastParams.append('lat', currentGliderLat);
            //    forecastParams.append('lon', currentGliderLon);
            // }
            forecastParams.append('source', currentSource); // Keep consistent with other data calls
            if (currentSource === 'local' && currentLocalPath) {
                forecastParams.append('local_path', currentLocalPath);
            }
            if (urlParams.has('refresh') && urlParams.get('refresh') === 'true') {
                forecastParams.append('refresh', 'true');
            }
            // Pass is_historical parameter
            if (isHistorical) {
                forecastParams.append('is_historical', 'true');
            }
            
            // Add date range parameters if date range is enabled for waves
            const startInput = document.getElementById('start-date-waves');
            const endInput = document.getElementById('end-date-waves');
            if (startInput && endInput && startInput.value && endInput.value) {
                const startISO = datetimeLocalToUtcIso(startInput.value);
                const endISO = datetimeLocalToUtcIso(endInput.value);
                if (startISO && endISO) {
                    forecastParams.append('start_date', startISO);
                    forecastParams.append('end_date', endISO);
                }
            }
            const marineForecastData = await apiRequest(`${marineForecastApiUrl}?${forecastParams.toString()}`, 'GET');
            return marineForecastData;
        } catch (error) {
            showToast(`Error loading marine forecast: ${error.message}`, 'danger');
            displayGlobalError('Failed to load marine forecast.');
            return null;
        }
    }


    // Fetch and render forecast
    fetchForecastData(missionId).then(data => {
        renderForecast(data);
    });
    const ESS_WAVE_HEIGHT_THRESHOLD_M = 4.5;
    const ESS_APPROACHING_THRESHOLD_M = 2.5;

    function getEssStateFromWaveHeight(h) {
        if (h == null || typeof h !== 'number' || Number.isNaN(h)) return null;
        if (h >= ESS_WAVE_HEIGHT_THRESHOLD_M) return 'extreme';
        if (h >= ESS_APPROACHING_THRESHOLD_M) return 'increasing';
        return 'calm';
    }

    function renderMarineForecast(marineForecastData) {
        const initialContainer = document.getElementById('marineForecastInitial');
        const extendedContainer = document.getElementById('marineForecastExtendedContent');
        const toggleButton = document.getElementById('toggleMarineForecastBtn');
        const metaInfoContainer = document.getElementById('marineForecastMetaInfo');

        if (!initialContainer || !extendedContainer || !toggleButton || !metaInfoContainer) {
            return; // Missing DOM elements - silent fail (DOM issue)
        }

        if (!marineForecastData || !marineForecastData.hourly || !marineForecastData.hourly.time || marineForecastData.hourly.time.length === 0) {
            initialContainer.innerHTML = '<p class="text-muted">Marine forecast data is currently unavailable.</p>';
            initialContainer.style.display = 'block';
            extendedContainer.innerHTML = '';
            toggleButton.style.display = 'none';
            metaInfoContainer.style.display = 'none';
            updateEssCourseGuidance(null, null);
            return;
        }

        let forecastTitle = 'Marine Forecast'; // Already specific
        const essLegend = '<p class="small text-muted mb-2"><span class="ess-legend-dot ess-calm" aria-label="Calm seas"></span> Calm (&lt;2.5 m) &nbsp; <span class="ess-legend-dot ess-increasing" aria-label="Increasing seas"></span> Increasing (2.5–4.5 m) &nbsp; <span class="ess-legend-dot ess-extreme" aria-label="Extreme sea state"></span> ESS (≥4.5 m)</p>';
        const nearestUtcLegend = '<p class="small text-muted mb-2">Nearest UTC forecast <span class="sampling-hint-icon" title="Rows are anchored to the forecast timestamp closest to the current UTC time." aria-label="Nearest UTC forecast help">?</span></p>';
        initialContainer.innerHTML = `<h5 class="text-muted fst-italic">${forecastTitle}</h5>${nearestUtcLegend}${essLegend}`;

        const hourly = marineForecastData.hourly;
        const units = marineForecastData.hourly_units || {};
        const currentSpeedUnit = units.ocean_current_velocity === 'kn' ? 'kt' : (units.ocean_current_velocity || 'kt');
        const totalHoursAvailable = hourly.time.length;
        const nearestForecastIndex = findNearestTimeIndexUtc(hourly.time);

        const createMarineTableHtml = (startHour, endHour, highlightedIndex) => {
            let tableHtml = '<table class="table table-sm table-striped table-hover">';
            tableHtml += '<thead><tr>' +
                         '<th>Time</th>' +
                         `<th>Wave Ht (${units.wave_height || 'm'})</th>` +
                         `<th>Wave Prd (${units.wave_period || 's'})</th>` +
                         `<th>Wave Dir (${units.wave_direction || '°'})</th>` +
                         `<th>Current (${currentSpeedUnit} @ ${units.ocean_current_direction || '°'})</th>`;
            tableHtml += '</tr></thead>';
            tableHtml += '<tbody>';

            for (let i = startHour; i < endHour && i < totalHoursAvailable; i++) {
                const time = formatUtcDateTime(hourly.time[i]);
                const waveHeightVal = (hourly.wave_height && hourly.wave_height[i] !== null) ? hourly.wave_height[i] : null;
                const waveHeight = waveHeightVal !== null ? waveHeightVal.toFixed(1) : 'N/A';
                const essState = getEssStateFromWaveHeight(waveHeightVal);
                const essClass = essState ? `ess-${essState}` : '';
                const essTitle = essState === 'extreme' ? ' title="Extreme sea state (≥4.5 m)"' : (essState === 'increasing' ? ' title="Increasing seas (2.5–4.5 m)"' : (essState === 'calm' ? ' title="Calm seas (<2.5 m)"' : ''));
                const nearestClass = i === highlightedIndex ? ' forecast-current-row' : '';
                const wavePeriod = (hourly.wave_period && hourly.wave_period[i] !== null) ? hourly.wave_period[i].toFixed(1) : 'N/A';
                const waveDir = (hourly.wave_direction && hourly.wave_direction[i] !== null) ? hourly.wave_direction[i].toFixed(0) : 'N/A';
                const currentSpeed = (hourly.ocean_current_velocity && hourly.ocean_current_velocity[i] !== null) ? hourly.ocean_current_velocity[i].toFixed(2) : 'N/A';
                const currentDir = (hourly.ocean_current_direction && hourly.ocean_current_direction[i] !== null) ? hourly.ocean_current_direction[i].toFixed(0) : 'N/A';
                const currentDisplay = currentSpeed !== 'N/A' ? `${currentSpeed} @ ${currentDir}°` : 'N/A';

                tableHtml += `<tr class="${essClass}${nearestClass}"${essTitle}><td>${time}</td><td>${waveHeight}</td><td>${wavePeriod}</td><td>${waveDir}</td><td>${currentDisplay}</td></tr>`;
            }
            tableHtml += '</tbody></table>';
            return tableHtml;
        };

        const initialHours = 12;
        const maxHoursAcrossViews = 48;
        const boundedStartHour = nearestForecastIndex >= 0 ? nearestForecastIndex : 0;
        const maxEndHour = Math.min(totalHoursAvailable, boundedStartHour + maxHoursAcrossViews);
        const initialEndHour = Math.min(maxEndHour, boundedStartHour + initialHours);
        initialContainer.innerHTML += createMarineTableHtml(boundedStartHour, initialEndHour, nearestForecastIndex);
        initialContainer.style.display = 'block';

        const extendedStartHour = initialEndHour;

        if (maxEndHour > initialEndHour) {
            extendedContainer.innerHTML = createMarineTableHtml(extendedStartHour, maxEndHour, nearestForecastIndex);
            toggleButton.style.display = 'block';
            const collapseElement = document.getElementById('marineForecastExtended');
            collapseElement.addEventListener('show.bs.collapse', () => { toggleButton.textContent = 'Show Less'; });
            collapseElement.addEventListener('hide.bs.collapse', () => { toggleButton.textContent = 'Show More'; });
            toggleButton.textContent = collapseElement.classList.contains('show') ? 'Show Less' : 'Show More';
        } else {
            extendedContainer.innerHTML = '';
            toggleButton.style.display = 'none';
        }

        if (marineForecastData.fetched_at_utc && marineForecastData.latitude_used !== undefined) {
            const fetchedDate = new Date(marineForecastData.fetched_at_utc);
            metaInfoContainer.textContent = `Forecast fetched: ${formatUtcDateTime(fetchedDate)} for Lat: ${parseFloat(marineForecastData.latitude_used).toFixed(3)}, Lon: ${parseFloat(marineForecastData.longitude_used).toFixed(3)}`;
            metaInfoContainer.style.display = 'block';
        } else {
            metaInfoContainer.style.display = 'none';
        }

        const forecastDir = (nearestForecastIndex >= 0 && hourly.wave_direction && hourly.wave_direction[nearestForecastIndex] !== null)
            ? Math.round(Number(hourly.wave_direction[nearestForecastIndex]))
            : null;
        const measurementDir = readMeasuredWaveDirectionFromDom();
        updateEssCourseGuidance(measurementDir, forecastDir);
    }

    function readMeasuredWaveDirectionFromDom() {
        const box = document.getElementById('waveDetailSummaryBox');
        if (!box) return null;
        const raw = box.getAttribute('data-wave-direction-numeric');
        if (raw === '' || raw === null) return null;
        const n = parseInt(raw, 10);
        if (Number.isNaN(n)) return null;
        return n;
    }

    function formatEssCourseFromWaveDirection(deg) {
        if (deg == null || Number.isNaN(deg)) return 'N/A';
        const waveFrom = ((Math.round(Number(deg)) % 360) + 360) % 360;
        const longLeg1 = (waveFrom - 90 + 360) % 360;
        const longLeg2 = (waveFrom + 90) % 360;
        return `Steer ${waveFrom}° at turns; long legs ${longLeg1}° / ${longLeg2}°`;
    }

    function updateEssCourseGuidance(measurementDir, forecastDir) {
        const fromMeas = document.getElementById('essCourseFromMeasurement');
        const fromForecast = document.getElementById('essCourseFromForecast');
        if (fromMeas) fromMeas.textContent = formatEssCourseFromWaveDirection(measurementDir);
        if (fromForecast) fromForecast.textContent = formatEssCourseFromWaveDirection(forecastDir);
    }

    /**
     * Fetches and renders the latest wave spectrum data.
     * @param {string} mission - The mission ID.
     */
    async function fetchAndRenderWaveSpectrum(mission) {
        const canvas = document.getElementById('waveSpectrumChart');
        if (!canvas) { return; } // Canvas not found - silent fail (DOM issue)
        const ctx = canvas.getContext('2d');
        const spinner = ctx.canvas.parentElement.querySelector('.chart-spinner');
        showChartSpinner(spinner);

        try {
            let apiUrl = `/api/wave_spectrum/${mission}`;
            const spectrumParams = new URLSearchParams();
            spectrumParams.append('source', currentSource);
            if (currentSource === 'local' && currentLocalPath) {
                spectrumParams.append('local_path', currentLocalPath);
            }
            if (urlParams.has('refresh') && urlParams.get('refresh') === 'true') {
                spectrumParams.append('refresh', 'true');
            }
            
            // Add date range parameters if date range is enabled for waves
            const startInput = document.getElementById('start-date-waves');
            const endInput = document.getElementById('end-date-waves');
            if (startInput && endInput && startInput.value && endInput.value) {
                const startISO = datetimeLocalToUtcIso(startInput.value);
                const endISO = datetimeLocalToUtcIso(endInput.value);
                if (startISO && endISO) {
                    spectrumParams.append('start_date', startISO);
                    spectrumParams.append('end_date', endISO);
                }
            }
            // Note: We are NOT passing a specific timestamp here, relying on the backend to get the latest
            // unless a specific timestamp selection UI is added later.
            const spectrumData = await apiRequest(`${apiUrl}?${spectrumParams.toString()}`, 'GET');
            renderWaveSpectrumChart(spectrumData);
        } catch (error) {
            showToast(`Error loading wave spectrum: ${error.message}`, 'danger');
            displayGlobalError('Network error while fetching wave spectrum data.');
            renderWaveSpectrumChart(null); // Render empty chart
        } finally {
            hideChartSpinner(spinner);
        }
    }

    /**
     * Renders the Wave Energy Spectrum Chart using Chart.js.
     * @param {Array<Object>|null} spectrumData - The data array [{x: freq, y: efth}] fetched from the API.
     */
    function renderWaveSpectrumChart(spectrumData) {
        const canvas = document.getElementById('waveSpectrumChart');
        if (!canvas) return; 
        const ctx = canvas.getContext('2d');

        if (waveSpectrumChartInstance) { waveSpectrumChartInstance.destroy(); }

        if (!spectrumData || spectrumData.length === 0) {
            ctx.font = "16px Arial"; ctx.fillStyle = "grey"; ctx.textAlign = "center";
            ctx.fillText("No wave spectrum data available.", ctx.canvas.width / 2, ctx.canvas.height / 2);
            return;
        }

        waveSpectrumChartInstance = new Chart(ctx, {
            type: 'line', 
            data: { datasets: [{ label: 'Energy Density (m²/Hz)', data: spectrumData, borderColor: CHART_COLORS.WAVE_SPECTRUM, borderWidth: 2, pointRadius: 0, tension: 0.1, fill: false }] },
            options: {
                responsive: true, maintainAspectRatio: false,
                scales: {
                    x: { type: 'linear', position: 'bottom', title: { display: true, text: 'Frequency (Hz)', color: chartTextColor }, ticks: { color: chartTextColor }, grid: { color: chartGridColor } },
                    y: { type: 'linear', position: 'left', title: { display: true, text: 'Energy Density (m²/Hz)', color: chartTextColor }, ticks: { color: chartTextColor, beginAtZero: true }, grid: { color: chartGridColor } }
                },
                plugins: { tooltip: { mode: 'index', intersect: false }, legend: { position: 'top', labels: { color: chartTextColor } } }
            }
        });
    }
    // Refresh Data Button Logic (Moved here for better organization)
    const refreshDataBtn = document.getElementById('refreshDataBtnBanner');
    if (refreshDataBtn) {
        refreshDataBtn.addEventListener('click', function() {
            const currentUrl = new URL(window.location.href);
            currentUrl.searchParams.set('refresh', 'true'); // Add refresh parameter
            window.location.href = currentUrl.toString(); // Reload the page
        });
    }
    // Reminder: Revisit threshold highlighting values

    // --- Error Category Chart Rendering ---
    function renderErrorCategoryChart() {
        const canvas = document.getElementById('errorCategoryChart');
        if (!canvas) {
            return; // Canvas not found - silent fail (DOM issue)
        }
        
        const ctx = canvas.getContext('2d');
        
        // Get error analysis data from the template
        const errorAnalysis = window.errorAnalysisData || {};
        const categories = errorAnalysis.categories || {};
        
        if (Object.keys(categories).length === 0) {
            // Hide the chart container and show no data message
            const container = canvas.closest('.chart-container');
            const noDataMessage = document.getElementById('noErrorDataMessage');
            if (container) {
                container.style.display = 'none';
            }
            if (noDataMessage) {
                noDataMessage.style.display = 'block';
            }
            return;
        }
        
        // Show the chart container and hide no data message
        const container = canvas.closest('.chart-container');
        const noDataMessage = document.getElementById('noErrorDataMessage');
        if (container) {
            container.style.display = 'block';
        }
        if (noDataMessage) {
            noDataMessage.style.display = 'none';
        }
        
        // Prepare chart data
        const labels = Object.keys(categories).map(cat => cat.charAt(0).toUpperCase() + cat.slice(1));
        const data = Object.values(categories).map(cat => cat.count);
        
        // Color mapping to match Bootstrap card colors
        const colorMap = {
            'navigation': '#0d6efd',      // Primary blue
            'communication': '#ffc107',    // Warning yellow
            'system_operations': '#dc3545', // Danger red
            'environmental': '#0dcaf0',    // Info teal
            'unknown': '#6c757d'          // Secondary gray
        };
        
        const colors = Object.keys(categories).map(cat => colorMap[cat] || '#6c757d');
        
        // Destroy existing chart if it exists
        if (window.errorCategoryChartInstance) {
            window.errorCategoryChartInstance.destroy();
        }
        
        window.errorCategoryChartInstance = new Chart(ctx, {
            type: 'doughnut',
            data: {
                labels: labels,
                datasets: [{
                    data: data,
                    backgroundColor: colors.slice(0, labels.length),
                    borderWidth: 2,
                    borderColor: (getComputedStyle(document.documentElement).getPropertyValue('--bs-body-bg').trim() || '#fff')
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                aspectRatio: 1,
                layout: {
                    padding: {
                        top: 10,
                        bottom: 10,
                        left: 10,
                        right: 10
                    }
                },
                plugins: {
                    legend: {
                        position: 'bottom',
                        labels: {
                            usePointStyle: true,
                            padding: 15,
                            font: {
                                size: 11
                            },
                            boxWidth: 12
                        }
                    },
                    tooltip: {
                        callbacks: {
                            label: function(context) {
                                const category = context.label.toLowerCase();
                                const categoryData = categories[category];
                                const total = data.reduce((a, b) => a + b, 0);
                                const percentage = ((context.parsed / total) * 100).toFixed(1);
                                return `${context.label}: ${context.parsed} errors (${percentage}%)`;
                            }
                        }
                    }
                },
                onResize: function(chart, size) {
                    // Ensure chart doesn't exceed container bounds
                    if (size.height > 300) {
                        chart.resize(300, 300);
                    }
                }
            }
        });
    }

    // Mini charts: shared module (/static/js/mini_charts.js)
    // loadedCategories is declared earlier (near cache polling) for soft-refresh.
    let isWgVm4OffloadSectionInitialized = false;

    // --- NEW: Left Panel Click Handler ---
    function handleLeftPanelClicks() {
        const summaryCards = document.querySelectorAll('#left-nav-panel .summary-card');
        const detailViews = document.querySelectorAll('#main-display-area .category-detail-view');

        summaryCards.forEach(card => {
            card.addEventListener('click', function() {
                summaryCards.forEach(c => c.classList.remove('active-card'));
                this.classList.add('active-card');
                const category = this.dataset.category;
                detailViews.forEach(view => view.style.display = 'none');
                const activeDetailView = document.getElementById(`detail-${category}`);
                if (activeDetailView) {
                    activeDetailView.style.display = 'block';

                    // Special handling for Waves to trigger spectrum load when its detail view is shown
                    if (category === 'waves') {
                        // The main wave charts are reloaded by the generic loader below
                        fetchAndRenderWaveSpectrum(missionId);
                        // Fetch and render marine forecast when Waves detail is shown
                        fetchMarineForecastData(missionId).then(data => renderMarineForecast(data));
                    } else if (category === 'wg_vm4') {
                        // Initialize the offload log section specific to WG-VM4
                        if (!isWgVm4OffloadSectionInitialized) {
                            initializeWgVm4OffloadSection();
                            isWgVm4OffloadSectionInitialized = true;
                        }
                    }
                    // Generic loader for all cards to ensure data is refreshed on click
                    const loader = getSensorLoader(category);
                    if (loader) {
                        loadedCategories.add(category);
                        Promise.resolve(loader()).finally(() => {
                            resizeWgChartsInCategory(category);
                        });
                    } else {
                        resizeWgChartsInCategory(category);
                    }
                }
            });
        });
    }

    function getSensorLoader(reportType) {
        // Map UI category 'navigation' for any legacy callers; configs use UI keys directly.
        if (reportType === 'telemetry') {
            reportType = 'navigation';
        }
        if (WG_TIME_SERIES_CARD_CONFIGS[reportType]) {
            return () => loadWgTimeSeriesCategory(reportType);
        }
        if (reportType === 'errors') {
            return () => isSensorEnabled('errors')
                ? Promise.resolve().then(() => { renderErrorCategoryChart(); })
                : Promise.resolve();
        }
        return undefined;
    }

    function initializeInteractiveControls() {
        document.querySelectorAll('.hours-back-input, .granularity-select, .date-range-input').forEach(input => {
            input.addEventListener('change', () => {
                // Refresh all already-loaded charts so they use the new Resample/hours/date
                loadedCategories.forEach(category => {
                    const loader = getSensorLoader(category);
                    if (loader) loader();
                    // Spectrum is imperative and must refresh with waves controls (not on plot-style).
                    if (category === 'waves') {
                        fetchAndRenderWaveSpectrum(missionId);
                    }
                });
            });
        });
        document.querySelectorAll('.outlier-suppress-toggle').forEach((input) => {
            input.addEventListener('change', () => {
                const reportType = input.dataset.reportType || '';
                const category = reportType === 'telemetry' ? 'navigation' : reportType;
                if (WG_TIME_SERIES_CARD_CONFIGS[category]) {
                    reRenderWgCategoryFromCache(category);
                }
            });
        });
    }

    // --- Theme Change Handler ---
    function updateAllChartInstances() {
        // Declarative time-series: re-render from series cache (theme colors read at render time).
        const categoriesToRefresh = new Set([
            ...loadedCategories,
            ...Object.keys(wgSeriesCache),
        ]);
        categoriesToRefresh.forEach((category) => {
            const key = category === 'telemetry' ? 'navigation' : category;
            if (WG_TIME_SERIES_CARD_CONFIGS[key]) {
                reRenderWgCategoryFromCache(key);
            }
        });

        // Imperative charts (spectrum): patch theme colors in place.
        const imperative = [waveSpectrumChartInstance];
        imperative.forEach((chart) => {
            if (!chart) return;
            Object.keys(chart.options.scales || {}).forEach((scaleKey) => {
                const scale = chart.options.scales[scaleKey];
                if (scale.title) scale.title.color = chartTextColor;
                if (scale.ticks) scale.ticks.color = chartTextColor;
                if (scale.grid && scale.grid.drawOnChartArea !== false) {
                    scale.grid.color = chartGridColor;
                }
            });
            if (chart.options.plugins?.legend) {
                chart.options.plugins.legend.labels.color = chartTextColor;
            }
            chart.update('none');
        });

        initializeMiniCharts();
    }

    function initializeDownloadButtons() {
        document.querySelectorAll('.download-csv-btn').forEach(button => {
            button.addEventListener('click', function(e) {
                e.preventDefault();
                const reportType = this.dataset.reportType;
                downloadChartDataAsCsv(reportType);
            });
        });

        document.querySelectorAll('.save-charts-btn').forEach(button => {
            button.addEventListener('click', function(e) {
                e.preventDefault();
                const category = this.dataset.reportType; // This is the category like 'navigation'
                const highRes = this.dataset.highRes === 'true';
                saveChartsAsPng(category, highRes);
            });
        });
    }

    function downloadChartDataAsCsv(reportType) {
        const mission = document.body.dataset.missionId;
        const hoursInput = document.querySelector(`.hours-back-input[data-report-type="${reportType}"]`);
        const granularitySelect = document.querySelector(`.granularity-select[data-report-type="${reportType}"]`);

        const hours = hoursInput ? hoursInput.value : 72;
        const granularity = granularitySelect ? granularitySelect.value : 0;

        // Use the new unified CSV download endpoint
        let apiUrl = `/api/sensor_csv/${reportType}?mission=${mission}&hours_back=${hours}&granularity_minutes=${granularity}`;
        
        // Add date range parameters if date range is enabled
        const startInput = document.getElementById(`start-date-${reportType}`);
        const endInput = document.getElementById(`end-date-${reportType}`);
        if (startInput && endInput && startInput.value && endInput.value) {
            const startISO = datetimeLocalToUtcIso(startInput.value);
            const endISO = datetimeLocalToUtcIso(endInput.value);
            if (!startISO || !endISO) throw new Error('Invalid UTC date range values.');
            apiUrl += `&start_date=${encodeURIComponent(startISO)}&end_date=${encodeURIComponent(endISO)}`;
        }

        // Trigger download by navigating to the URL
        window.location.href = apiUrl;
    }

    // Function to enhance Chart.js for high-resolution rendering
    function enhanceChartForHighRes(chartInstance) {
        if (!chartInstance) return;
        
        // Store original options for restoration
        const originalOptions = JSON.parse(JSON.stringify(chartInstance.options));
        
        // Enhance font sizes for high-resolution
        const fontMultiplier = 1.5; // Moderate font size increase 
        
        // Update scales
        Object.keys(chartInstance.options.scales).forEach(scaleKey => {
            const scale = chartInstance.options.scales[scaleKey];
            if (scale.title) {
                scale.title.font = { size: (scale.title.font?.size || 14) * fontMultiplier };
            }
            if (scale.ticks) {
                scale.ticks.font = { size: (scale.ticks.font?.size || 12) * fontMultiplier };
            }
        });
        
        // Update legend
        if (chartInstance.options.plugins.legend) {
            chartInstance.options.plugins.legend.labels.font = { 
                size: (chartInstance.options.plugins.legend.labels.font?.size || 12) * fontMultiplier 
            };
        }
        
        // Update tooltip
        if (chartInstance.options.plugins.tooltip) {
            chartInstance.options.plugins.tooltip.titleFont = { 
                size: (chartInstance.options.plugins.tooltip.titleFont?.size || 12) * fontMultiplier 
            };
            chartInstance.options.plugins.tooltip.bodyFont = { 
                size: (chartInstance.options.plugins.tooltip.bodyFont?.size || 12) * fontMultiplier 
            };
        }
        
        // Update datasets for thicker lines
        chartInstance.data.datasets.forEach(dataset => {
            if (dataset.borderWidth) {
                dataset.borderWidth = dataset.borderWidth * 2; // Thicker lines
            }
            if (dataset.pointRadius !== undefined) {
                dataset.pointRadius = dataset.pointRadius * 2; // Larger points
            }
        });
        
        // Force update
        chartInstance.update('none');
        
        return originalOptions;
    }
    
    // Function to restore Chart.js to original state
    function restoreChartFromHighRes(chartInstance, originalOptions) {
        if (!chartInstance || !originalOptions) return;
        
        // Restore options
        chartInstance.options = originalOptions;
        chartInstance.update('none');
    }

    function saveChartsAsPng(category, highResolution = false) {
        const detailView = document.getElementById(`detail-${category}`);
        if (!detailView) {
            return; // Detail view not found - silent fail (DOM issue)
        }

        const mission = document.body.dataset.missionId;
        const canvases = detailView.querySelectorAll('canvas');
        if (canvases.length === 0) {
            alert(`No charts found to save for the ${category} view.`);
            return;
        }

        const resolveChartInstance = (chartId) => {
            if (chartId === 'waveSpectrumChart') return waveSpectrumChartInstance;
            return chartInstancesByCanvasId[chartId] || null;
        };

        // Store original chart states for restoration
        const originalStates = {};

        canvases.forEach(canvas => {
            const chartId = canvas.id;
            const chartInstance = resolveChartInstance(chartId);

            if (chartInstance) {
                // Enhance chart for high-resolution if needed
                if (highResolution) {
                    originalStates[chartId] = enhanceChartForHighRes(chartInstance);
                }
                
                const newCanvas = document.createElement('canvas');
                
                if (highResolution) {
                    // Enhanced high-resolution scaling: 4x for dramatic quality improvement
                    const scaleFactor = 4;
                    newCanvas.width = chartInstance.canvas.width * scaleFactor;
                    newCanvas.height = chartInstance.canvas.height * scaleFactor;
                    const newCtx = newCanvas.getContext('2d');
                    
                    // Enhanced image smoothing for better quality
                    newCtx.imageSmoothingEnabled = true;
                    newCtx.imageSmoothingQuality = 'high';
                    
                    // Set background color
                    const bodyStyles = getComputedStyle(document.body);
                    const bgColor = bodyStyles.getPropertyValue('--bs-body-bg').trim();
                    newCtx.fillStyle = bgColor;
                    newCtx.fillRect(0, 0, newCanvas.width, newCanvas.height);
                    
                    // Scale and draw the chart with enhanced quality
                    newCtx.scale(scaleFactor, scaleFactor);
                    newCtx.drawImage(chartInstance.canvas, 0, 0);
                    
                    // Additional quality enhancements
                    newCtx.textRenderingOptimization = 'optimizeQuality';
                    newCtx.textBaseline = 'alphabetic';
                } else {
                    // Standard resolution
                    newCanvas.width = chartInstance.canvas.width;
                    newCanvas.height = chartInstance.canvas.height;
                    const newCtx = newCanvas.getContext('2d');
                    const bodyStyles = getComputedStyle(document.body);
                    const bgColor = bodyStyles.getPropertyValue('--bs-body-bg').trim();
                    newCtx.fillStyle = bgColor;
                    newCtx.fillRect(0, 0, newCanvas.width, newCanvas.height);
                    newCtx.drawImage(chartInstance.canvas, 0, 0);
                }
                
                const image = newCanvas.toDataURL('image/png');
                const link = document.createElement('a');
                link.href = image;
                const suffix = highResolution ? '_high_res' : '';
                link.download = `${mission}_${chartId}${suffix}.png`;
                document.body.appendChild(link);
                link.click();
                document.body.removeChild(link);
            } else {
                console.warn(`No chart instance found for canvas with ID: ${chartId}`);
            }
        });
        
        // Restore all charts to original state after high-res export
        if (highResolution) {
            canvases.forEach(canvas => {
                const chartId = canvas.id;
                const chartInstance = resolveChartInstance(chartId);
                if (chartInstance && originalStates[chartId]) {
                    restoreChartFromHighRes(chartInstance, originalStates[chartId]);
                }
            });
        }
    }

    // Observer to watch for theme changes on the <html> element
    const observer = new MutationObserver((mutations) => {
        for (const mutation of mutations) {
            if (mutation.type === 'attributes' && (mutation.attributeName === 'data-bs-theme' || mutation.attributeName === 'data-theme')) {
                // A brief delay allows the browser to compute the new CSS variable values
                setTimeout(() => {
                    updateChartColorVariables(); // Get new colors from CSS
                    updateAllChartInstances();   // Apply new colors to existing charts
                }, 50);
                break; // No need to check other mutations
            }
        }
    });
    observer.observe(document.documentElement, { attributes: true });

    // Initialize new UI features
    initializeMiniCharts();
    handleLeftPanelClicks();
    initializeInteractiveControls();
    initializeDownloadButtons();
    initWgChartControls();
    initializeDateRangeInputs();
    initializeClearButtons();
    
    // Ensure all date range inputs are properly initialized
    initializeAllDateRangeStates();


    // Eager-load time-series categories that previously prefetched on page load.
    // Spectrum still loads only when the waves detail is shown / refreshed.
    ['navigation', 'power', 'ctd', 'weather', 'waves', 'vr2c', 'fluorometer', 'wg_vm4'].forEach((category) => {
        if (isSensorEnabled(WG_TIME_SERIES_CARD_CONFIGS[category]?.enabledSensor || category)) {
            loadWgTimeSeriesCategory(category);
            loadedCategories.add(category);
        }
    });

    // Default active view extras (spectrum / marine for waves)
    const defaultActiveCategory = document.querySelector('#left-nav-panel .summary-card.active-card')?.dataset.category;
    if (defaultActiveCategory === 'waves') {
        fetchAndRenderWaveSpectrum(missionId);
        fetchMarineForecastData(missionId).then(data => renderMarineForecast(data));
    }

    // Open ESS waypoint planner with same data source as dashboard (use form; when local and no custom path, use config default)
    document.addEventListener('click', function (e) {
        const link = e.target.closest && e.target.closest('#openEssPlannerLink');
        if (!link) return;
        e.preventDefault();
        const mission = link.dataset.mission;
        const checked = document.querySelector('input[name="dataSourceOption"]:checked');
        const pathInput = document.getElementById('customLocalPath');
        const source = (checked && checked.value) ? checked.value : (new URLSearchParams(window.location.search).get('source') || '');
        let localPath = (pathInput && pathInput.value != null) ? String(pathInput.value).trim() : (new URLSearchParams(window.location.search).get('local_path') || '');
        if (source === 'local' && !localPath && link.dataset.defaultLocalPath) localPath = link.dataset.defaultLocalPath;
        let url = '/wave-glider/ess-planning?mission=' + encodeURIComponent(mission);
        if (source) url += '&source=' + encodeURIComponent(source);
        if (localPath) url += '&local_path=' + encodeURIComponent(localPath);
        window.open(url, '_blank', 'noopener,noreferrer');
    });
});