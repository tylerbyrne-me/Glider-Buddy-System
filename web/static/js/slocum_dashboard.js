/**
 * Slocum Glider mission dashboard – Overview briefing (plan/reports/ST/comments/goals/media)
 * plus CTD depth-vs-time Chart.js scatter charts colored with cmocean stops.
 * Active datasets: auto-refresh via /api/slocum/cache-status. Historical: no auto-refresh.
 */
import { apiRequest, showToast, escapeHTML, fetchWithAuth } from '/static/js/api.js';
import { datetimeLocalToUtcIso, formatUtcDateTime, toUtcDate } from '/static/js/datetime_utils.js';
import { openSlocumChecklistCompare } from '/static/js/slocum_checklist_compare.js';
import {
    registerForceUtcTimeDisplayPlugin,
} from '/static/js/chart_utc_utils.js';
import { initializeMiniCharts } from '/static/js/mini_charts.js';
import {
    applyTimeAxisZoom,
    bindResetZoomButton,
    CHART_ZOOM_HINT,
    isChartZoomPluginAvailable,
} from '/static/js/chart_zoom_utils.js';
import {
    bindPlotStyleControls,
    getPlotStyleForCanvas,
    plotStyleDatasetProps,
} from '/static/js/chart_plot_style_utils.js';
import {
    bindOverlayToggleControls,
    buildBackgroundOverlayDataset,
    buildHiddenOverlayScale,
    filterOverlayFromLegend,
    formatOverlayMeters,
    getOverlayEnabledForCanvas,
    nearestOverlayValue,
    registerNearestXByDatasetInteractionMode,
} from '/static/js/chart_overlay_utils.js';
import {
    applyProfileScatterHoverDefaults,
    applyTimeSeriesHoverDefaults,
    ensureDatasetHitRadius,
} from '/static/js/chart_hover_defaults.js';
import {
    recordsToPoints as recordsToPointsShared,
    drawNoDataOnCanvas,
    buildTimeScaleX,
} from '/static/js/chart_time_series_utils.js';

registerForceUtcTimeDisplayPlugin();
registerNearestXByDatasetInteractionMode();

const DEFAULT_HOURS = 24;
const DEFAULT_GRANULARITY = 0;
const DASHBOARD_RECENT_NOTE_LIMIT = 4;
const PLOT_STYLE_STORAGE_PREFIX = 'slocumPlotStyle:';
const DEPTH_OVERLAY_STORAGE_PREFIX = 'slocumDepthOverlay:';
const DEPTH_OVERLAY_COLOR = 'rgba(108, 117, 125, 0.85)';
const DEPTH_OVERLAY_LABEL = 'Depth (m)';

let currentDeploymentId = null;
let currentOverviewInfo = null;
let lastMissionNotesForEdit = [];
let activeChartCategory = null;
let ctdProfilesLoaded = false;
let ctdProfilePayloadCache = null;
const ctdChartInstances = {};
const timeSeriesLoaded = new Set();
const timeSeriesChartInstances = {};
/** Cached checklist submissions for the Compare modal (newest first). */
let lastSlocumChecklists = [];

let chartTextColor = '#212529';
let chartGridColor = '#dee2e6';

const USER_ROLE = document.body.dataset.userRole || '';
const USERNAME = document.body.dataset.username || '';

const escapeHtml = (str) => escapeHTML(String(str ?? ''));
const formatTimestamp = (value) => (value ? formatUtcDateTime(value) : '-');

const CTD_PROFILE_CHARTS = [
    { variable: 'temperature', canvasId: 'slocumCtdTempChart', spinnerId: 'slocumCtdTempSpinner', label: 'Sea Water Temperature' },
    { variable: 'conductivity', canvasId: 'slocumCtdConductivityChart', spinnerId: 'slocumCtdConductivitySpinner', label: 'Conductivity' },
    { variable: 'density', canvasId: 'slocumCtdDensityChart', spinnerId: 'slocumCtdDensitySpinner', label: 'Sea Water Density' },
];

const SERIES_COLORS = [
    'rgba(13, 110, 253, 1)',
    'rgba(255, 159, 64, 1)',
    'rgba(40, 167, 69, 1)',
    'rgba(220, 53, 69, 1)',
    'rgba(111, 66, 193, 1)',
    'rgba(23, 162, 184, 1)',
];

/** Chart.js time axis with UTC tick/tooltip display. */
function buildSlocumTimeScaleX() {
    return buildTimeScaleX({
        tickColor: chartTextColor,
        gridColor: chartGridColor,
        titleColor: chartTextColor,
        titleText: 'Time (UTC)',
    });
}

/** Declarative time-series card configs (Power / Flight / Navigation / Vehicle Health / DO).
 * Hover defaults (time-aligned tooltips, crosshair, hit radius) come from
 * applyTimeSeriesHoverDefaults in renderTimeSeriesChart — new sensors inherit them.
 */
const TIME_SERIES_CARD_CONFIGS = {
    power: {
        variables: [
            'm_battery', 'm_coulomb_amphr_total', 'coulomb_amphr_daily',
            'm_bms_pitch_current', 'm_bms_aft_current', 'm_bms_ebay_current',
            'm_depth',
        ],
        footerId: 'slocumPowerLastDataFooter',
        charts: [
            {
                canvasId: 'slocumPowerBatteryChart',
                spinnerId: 'slocumPowerBatterySpinner',
                yLabel: 'Voltage (V)',
                series: [{ key: 'm_battery', label: 'Battery' }],
            },
            {
                canvasId: 'slocumPowerCoulombChart',
                spinnerId: 'slocumPowerCoulombSpinner',
                yLabel: 'Ah/day (rolling 24h)',
                y2Label: 'Total AmpHr',
                series: [
                    { key: 'coulomb_amphr_daily', label: 'Daily consumption', type: 'bar', yAxisID: 'y' },
                    { key: 'm_coulomb_amphr_total', label: 'Total AmpHr', type: 'line', yAxisID: 'y1' },
                ],
            },
            {
                canvasId: 'slocumPowerBmsChart',
                spinnerId: 'slocumPowerBmsSpinner',
                yLabel: 'Current (A)',
                series: [
                    { key: 'm_bms_pitch_current', label: 'Pitch' },
                    { key: 'm_bms_aft_current', label: 'Aft' },
                    { key: 'm_bms_ebay_current', label: 'Ebay' },
                ],
            },
        ],
    },
    flight: {
        variables: [
            'm_pitch', 'c_pitch', 'm_roll', 'c_roll', 'm_fin', 'c_fin',
            'm_thruster_power', 'c_thruster_on', 'm_depth',
        ],
        footerId: 'slocumFlightLastDataFooter',
        charts: [
            {
                canvasId: 'slocumFlightPitchChart',
                spinnerId: 'slocumFlightPitchSpinner',
                yLabel: 'Pitch (°)',
                series: [
                    { key: 'm_pitch', label: 'Measured' },
                    { key: 'c_pitch', label: 'Commanded', dashed: true },
                ],
            },
            {
                canvasId: 'slocumFlightRollChart',
                spinnerId: 'slocumFlightRollSpinner',
                yLabel: 'Roll (°)',
                series: [
                    { key: 'm_roll', label: 'Measured' },
                    { key: 'c_roll', label: 'Commanded', dashed: true },
                ],
            },
            {
                canvasId: 'slocumFlightFinChart',
                spinnerId: 'slocumFlightFinSpinner',
                yLabel: 'Fin (°)',
                series: [
                    { key: 'm_fin', label: 'Measured' },
                    { key: 'c_fin', label: 'Commanded', dashed: true },
                ],
            },
            {
                canvasId: 'slocumFlightThrusterChart',
                spinnerId: 'slocumFlightThrusterSpinner',
                yLabel: 'Power (W)',
                y2Label: 'Commanded on (%)',
                series: [
                    { key: 'm_thruster_power', label: 'Thruster power', yAxisID: 'y' },
                    { key: 'c_thruster_on', label: 'Commanded on', yAxisID: 'y1', dashed: true },
                ],
            },
        ],
    },
    navigation: {
        variables: [
            'm_heading', 'c_heading', 'm_depth_rate_avg_final',
            'm_depth', 'm_water_depth', 'water_depth_altimeter',
            'm_speed', 'm_final_water_vx', 'm_final_water_vy', 'water_current_speed',
        ],
        footerId: 'slocumNavigationLastDataFooter',
        charts: [
            {
                canvasId: 'slocumNavHeadingChart',
                spinnerId: 'slocumNavHeadingSpinner',
                yLabel: 'Heading (°)',
                series: [
                    { key: 'm_heading', label: 'Measured' },
                    { key: 'c_heading', label: 'Commanded', dashed: true },
                ],
            },
            {
                canvasId: 'slocumNavDepthRateChart',
                spinnerId: 'slocumNavDepthRateSpinner',
                yLabel: 'Depth rate (m/s)',
                series: [{ key: 'm_depth_rate_avg_final', label: 'Depth rate' }],
            },
            {
                canvasId: 'slocumNavDepthChart',
                spinnerId: 'slocumNavDepthSpinner',
                yLabel: 'Depth (m)',
                invertY: true,
                skipDepthOverlay: true,
                series: [
                    { key: 'm_depth', label: 'Depth' },
                    { key: 'water_depth_altimeter', label: 'Depth + altitude', dashed: true },
                    { key: 'm_water_depth', label: 'm_water_depth' },
                ],
            },
            {
                canvasId: 'slocumNavSpeedChart',
                spinnerId: 'slocumNavSpeedSpinner',
                yLabel: 'Speed (m/s)',
                series: [{ key: 'm_speed', label: 'Speed over ground' }],
            },
            {
                canvasId: 'slocumNavCurrentChart',
                spinnerId: 'slocumNavCurrentSpinner',
                yLabel: 'Current (m/s)',
                series: [
                    { key: 'm_final_water_vx', label: 'Vx' },
                    { key: 'm_final_water_vy', label: 'Vy' },
                    { key: 'water_current_speed', label: 'Speed', dashed: true },
                ],
            },
        ],
    },
    vehicle_health: {
        variables: [
            'm_vacuum',
            'm_leakdetect_voltage',
            'm_leakdetect_voltage_forward',
            'm_leakdetect_voltage_science',
            'm_digifin_leakdetect_reading',
            'm_depth',
        ],
        footerId: 'slocumVehicleHealthLastDataFooter',
        charts: [
            {
                canvasId: 'slocumHealthVacuumChart',
                spinnerId: 'slocumHealthVacuumSpinner',
                yLabel: 'Vacuum (inHg)',
                series: [{ key: 'm_vacuum', label: 'Vacuum' }],
            },
            {
                canvasId: 'slocumHealthLeakChart',
                spinnerId: 'slocumHealthLeakSpinner',
                yLabel: 'Leak detect (V)',
                y2Label: 'Digifin (V)',
                series: [
                    { key: 'm_leakdetect_voltage', label: 'Leak detect' },
                    { key: 'm_leakdetect_voltage_forward', label: 'Forward' },
                    { key: 'm_leakdetect_voltage_science', label: 'Science' },
                    { key: 'm_digifin_leakdetect_reading', label: 'Digifin', yAxisID: 'y1' },
                ],
            },
        ],
        sfmcCallChart: {
            canvasId: 'slocumHealthCallChart',
            spinnerId: 'slocumHealthCallSpinner',
            noteId: 'slocumHealthSfmcNote',
        },
    },
    dissolved_oxygen: {
        placeholder: true,
        variables: [],
        footerId: 'slocumDoLastDataFooter',
        charts: [
            {
                canvasId: 'slocumDoConcentrationChart',
                spinnerId: 'slocumDoConcentrationSpinner',
                yLabel: 'Concentration',
                series: [],
                noDataMessage: 'Dissolved oxygen concentration coming soon',
            },
            {
                canvasId: 'slocumDoSaturationChart',
                spinnerId: 'slocumDoSaturationSpinner',
                yLabel: 'Saturation',
                series: [],
                noDataMessage: 'Dissolved oxygen saturation coming soon',
            },
        ],
    },
};

const TIME_SERIES_CATEGORIES = Object.keys(TIME_SERIES_CARD_CONFIGS);
const timeSeriesSeriesCache = {};
let sfmcCallPointsCache = null;

// Auto-refresh via cache-status polling (no full page reload)
const AUTO_REFRESH_INTERVAL_MINUTES = 5;
const AUTO_REFRESH_POLL_INTERVAL_MS = 60 * 1000;
let autoRefreshEnabled = true;
let countdownTimer = null;
let cachePollIntervalId = null;
const slocumCacheTimestamps = new Map();

function getDatasetId() {
    return document.body.dataset.dataset || '';
}

function isHistoricalDataset() {
    return document.body.dataset.isHistorical === 'true';
}

function getHoursBack() {
    const el = document.getElementById('slocumHoursBack');
    return el ? parseInt(el.value, 10) || DEFAULT_HOURS : DEFAULT_HOURS;
}

function getGranularity() {
    const el = document.getElementById('slocumGranularity');
    if (!el) return DEFAULT_GRANULARITY;
    const n = parseInt(el.value, 10);
    return Number.isFinite(n) ? n : DEFAULT_GRANULARITY;
}

/** @returns {{ startISO: string, endISO: string } | null} when both From/To are set. */
function getSlocumDateRange() {
    const startEl = document.getElementById('start-date-slocum');
    const endEl = document.getElementById('end-date-slocum');
    const startVal = startEl?.value?.trim();
    const endVal = endEl?.value?.trim();
    if (!startVal || !endVal) return null;
    const startISO = datetimeLocalToUtcIso(startVal);
    const endISO = datetimeLocalToUtcIso(endVal);
    if (!startISO || !endISO) return null;
    return { startISO, endISO };
}

function isSlocumDateRangeActive() {
    return getSlocumDateRange() !== null;
}

function updateSlocumDateRangeState() {
    const startEl = document.getElementById('start-date-slocum');
    const endEl = document.getElementById('end-date-slocum');
    const clearBtn = document.getElementById('clear-date-slocum');
    const hoursEl = document.getElementById('slocumHoursBack');
    const startVal = startEl?.value?.trim();
    const endVal = endEl?.value?.trim();
    const hasRange = !!(startVal && endVal);
    if (clearBtn) clearBtn.style.display = startVal || endVal ? 'inline-block' : 'none';
    if (hoursEl) {
        hoursEl.disabled = hasRange;
        hoursEl.style.opacity = hasRange ? '0.5' : '1';
    }
}

function handleSlocumDateRangeChange() {
    const startEl = document.getElementById('start-date-slocum');
    const endEl = document.getElementById('end-date-slocum');
    updateSlocumDateRangeState();
    const startVal = startEl?.value?.trim();
    const endVal = endEl?.value?.trim();
    if (!startVal || !endVal) return;
    const startISO = datetimeLocalToUtcIso(startVal);
    const endISO = datetimeLocalToUtcIso(endVal);
    if (!startISO || !endISO) {
        const rangeInfoEl = document.getElementById('slocumDateRangeInfo');
        if (rangeInfoEl) {
            rangeInfoEl.textContent = 'Invalid UTC date range.';
            rangeInfoEl.className = 'text-danger small';
        }
        return;
    }
    const startDate = new Date(startISO);
    const endDate = new Date(endISO);
    if (startDate >= endDate) {
        showToast('Start date must be before end date.', 'warning');
        return;
    }
    refreshLoadedChartTabs();
}

function clearSlocumDateRange() {
    const startEl = document.getElementById('start-date-slocum');
    const endEl = document.getElementById('end-date-slocum');
    if (startEl) startEl.value = '';
    if (endEl) endEl.value = '';
    updateSlocumDateRangeState();
    refreshLoadedChartTabs();
}

function initSlocumDateRangeControls() {
    const startEl = document.getElementById('start-date-slocum');
    const endEl = document.getElementById('end-date-slocum');
    const clearBtn = document.getElementById('clear-date-slocum');
    [startEl, endEl].filter(Boolean).forEach((el) => {
        el.addEventListener('change', handleSlocumDateRangeChange);
        el.addEventListener('input', handleSlocumDateRangeChange);
    });
    if (clearBtn) clearBtn.addEventListener('click', clearSlocumDateRange);
    updateSlocumDateRangeState();
}

function updateChartColorVariables() {
    const styles = getComputedStyle(document.documentElement);
    chartTextColor = styles.getPropertyValue('--text-color').trim() || chartTextColor;
    chartGridColor = styles.getPropertyValue('--card-border').trim() || chartGridColor;
}

function showProfileSpinner(spinnerId) {
    const el = document.getElementById(spinnerId);
    if (!el) return;
    el.style.display = 'block';
    el.classList.remove('spinner-border');
    // Restart CSS animation
    void el.offsetWidth;
    el.classList.add('spinner-border');
}

function hideProfileSpinner(spinnerId) {
    const el = document.getElementById(spinnerId);
    if (el) el.style.display = 'none';
}

function setGranularityControlEnabled(isEnabled) {
    const el = document.getElementById('slocumGranularity');
    if (!el) return;
    el.disabled = !isEnabled;
    el.style.opacity = isEnabled ? '1' : '0.5';
    el.title = isEnabled
        ? 'Set the data resampling interval.'
        : 'Resampling is not applied to CTD depth profiles.';
}

function colorForValue(value, min, max, stops) {
    if (value == null || !Number.isFinite(value) || !stops?.length) return 'rgba(128,128,128,0.6)';
    if (min == null || max == null || !Number.isFinite(min) || !Number.isFinite(max) || min === max) {
        return stops[Math.floor(stops.length / 2)];
    }
    const t = Math.max(0, Math.min(1, (value - min) / (max - min)));
    const idx = Math.min(stops.length - 1, Math.max(0, Math.round(t * (stops.length - 1))));
    return stops[idx];
}

/** Chart.js plugin: draw a vertical cmocean colorbar in the chart's right layout padding. */
const slocumColorbarPlugin = {
    id: 'slocumColorbar',
    afterDraw(chart) {
        const meta = chart.options.plugins?.slocumColorbar;
        if (!meta || !meta.stops?.length) return;
        const { ctx, chartArea } = chart;
        if (!chartArea) return;
        const barWidth = 14;
        const gap = 10;
        const x = chartArea.right + gap;
        const top = chartArea.top;
        const bottom = chartArea.bottom;
        const height = bottom - top;
        if (height <= 0) return;

        const gradient = ctx.createLinearGradient(0, bottom, 0, top);
        const n = meta.stops.length;
        meta.stops.forEach((stop, i) => {
            gradient.addColorStop(i / Math.max(1, n - 1), stop);
        });
        ctx.save();
        ctx.fillStyle = gradient;
        ctx.fillRect(x, top, barWidth, height);
        ctx.strokeStyle = chartGridColor;
        ctx.lineWidth = 1;
        ctx.strokeRect(x, top, barWidth, height);

        const labelColor = chartTextColor;
        ctx.fillStyle = labelColor;
        ctx.font = '11px sans-serif';
        ctx.textAlign = 'left';
        ctx.textBaseline = 'middle';
        const labelX = x + barWidth + 4;
        // Whole-number colorbar labels (server supplies nicified integer ranges).
        const fmt = (v) => (v == null || !Number.isFinite(Number(v)) ? '' : String(Math.round(Number(v))));
        if (meta.max != null) ctx.fillText(fmt(meta.max), labelX, top);
        if (meta.min != null) ctx.fillText(fmt(meta.min), labelX, bottom);
        if (meta.unit) {
            ctx.save();
            ctx.translate(labelX + 28, (top + bottom) / 2);
            ctx.rotate(-Math.PI / 2);
            ctx.textAlign = 'center';
            ctx.fillText(meta.unit, 0, 0);
            ctx.restore();
        }
        ctx.restore();
    },
};

function destroyCtdCharts() {
    Object.keys(ctdChartInstances).forEach((key) => {
        try { ctdChartInstances[key]?.destroy(); } catch (_) { /* ignore */ }
        delete ctdChartInstances[key];
    });
}

function recordsToPoints(records) {
    return recordsToPointsShared(records, { keepGaps: false });
}

function buildProfileDataset(points, variable, range, stops) {
    const min = range?.min;
    const max = range?.max;
    const data = [];
    const colors = [];
    for (const p of points || []) {
        const value = p[variable];
        if (value == null || !Number.isFinite(value) || p.depth == null || !Number.isFinite(p.depth) || !p.t) {
            continue;
        }
        const x = toUtcDate(p.t);
        if (!x) continue;
        data.push({ x, y: p.depth, v: value });
        colors.push(colorForValue(value, min, max, stops));
    }
    return { data, colors };
}

function buildCtdDepthOverlayPoints(records) {
    return recordsToPoints(records || []);
}

function reRenderCtdProfilesFromCache() {
    if (!ctdProfilePayloadCache) return;
    updateChartColorVariables();
    CTD_PROFILE_CHARTS.forEach((cfg) => renderOneProfileChart(cfg, ctdProfilePayloadCache));
}

function renderOneProfileChart(config, payload) {
    if (typeof Chart === 'undefined') {
        console.error('Chart.js is not loaded');
        return;
    }
    const canvas = document.getElementById(config.canvasId);
    if (!canvas) return;

    const unit = payload?.units?.[config.variable] || '';
    const range = payload?.ranges?.[config.variable] || {};
    const stops = payload?.colormaps?.[config.variable] || [];
    const { data, colors } = buildProfileDataset(payload?.points, config.variable, range, stops);

    if (ctdChartInstances[config.canvasId]) {
        try { ctdChartInstances[config.canvasId].destroy(); } catch (_) { /* ignore */ }
        delete ctdChartInstances[config.canvasId];
    }

    if (!data.length) {
        drawNoDataOnCanvas(config.canvasId, `No ${config.label} data available`);
        return;
    }

    const showDepth = getOverlayEnabledForCanvas(DEPTH_OVERLAY_STORAGE_PREFIX, config.canvasId);
    const depthPoints = showDepth ? buildCtdDepthOverlayPoints(payload?.depth_overlay) : [];
    const datasets = [];
    if (depthPoints.length) {
        // Same Y axis as CTD sample depth so vehicle depth aligns in meters.
        datasets.push(buildBackgroundOverlayDataset({
            points: depthPoints,
            label: DEPTH_OVERLAY_LABEL,
            color: DEPTH_OVERLAY_COLOR,
            yAxisID: 'y',
        }));
    }
    datasets.push({
        label: config.label,
        data,
        backgroundColor: colors,
        borderColor: colors,
        pointRadius: 2.5,
        pointHoverRadius: 4,
        pointBorderWidth: 0,
    });
    ensureDatasetHitRadius(datasets);

    const chartOptions = {
        responsive: true,
        maintainAspectRatio: false,
        layout: {
            padding: { right: 72 },
        },
        scales: {
            x: buildSlocumTimeScaleX(),
            y: {
                type: 'linear',
                reverse: true,
                title: { display: true, text: 'Depth (m)', color: chartTextColor },
                ticks: { color: chartTextColor },
                grid: { color: chartGridColor },
            },
        },
        plugins: {
            legend: {
                display: false,
                labels: { filter: filterOverlayFromLegend },
            },
            slocumColorbar: {
                stops,
                min: range.min,
                max: range.max,
                unit,
            },
        },
    };
    const { options: profileOptions, plugins: profilePlugins } = applyProfileScatterHoverDefaults(
        chartOptions,
        {
            tooltip: {
                filter(tooltipItem) {
                    const ds = tooltipItem?.dataset;
                    return !(ds?.isBackgroundOverlay || ds?.isDepthOverlay);
                },
                callbacks: {
                    title(items) {
                        const raw = items?.[0]?.raw;
                        if (!raw?.x) return '';
                        return formatUtcDateTime(raw.x);
                    },
                    label(item) {
                        const raw = item.raw || {};
                        const depth = Number.isFinite(raw.y) ? raw.y.toFixed(1) : '-';
                        const value = Number.isFinite(raw.v) ? raw.v.toFixed(3) : '-';
                        return [`CTD depth: ${depth} m`, `${config.label}: ${value}${unit ? ` ${unit}` : ''}`];
                    },
                    afterBody(tooltipItems) {
                        if (!showDepth || !tooltipItems?.length) return [];
                        const chart = tooltipItems[0].chart;
                        const xMs = tooltipItems[0].parsed?.x;
                        const formatted = formatOverlayMeters(nearestOverlayValue(chart, xMs));
                        if (!formatted) return [];
                        return [`Vehicle depth: ${formatted}`];
                    },
                },
            },
            extraPlugins: [slocumColorbarPlugin],
        },
    );
    applyTimeAxisZoom(profileOptions);

    const ctx = canvas.getContext('2d');
    ctdChartInstances[config.canvasId] = new Chart(ctx, {
        type: 'scatter',
        data: { datasets },
        options: profileOptions,
        plugins: profilePlugins,
    });
}

function applyThemeToCtdCharts() {
    updateChartColorVariables();
    Object.values(ctdChartInstances).forEach((chart) => {
        if (!chart) return;
        const x = chart.options.scales?.x;
        const y = chart.options.scales?.y;
        if (x) {
            if (x.title) x.title.color = chartTextColor;
            if (x.ticks) x.ticks.color = chartTextColor;
            if (x.grid) x.grid.color = chartGridColor;
        }
        if (y) {
            if (y.title) y.title.color = chartTextColor;
            if (y.ticks) y.ticks.color = chartTextColor;
            if (y.grid) y.grid.color = chartGridColor;
        }
        chart.update('none');
    });
}

function updateAllChartInstances() {
    updateChartColorVariables();
    if (ctdProfilesLoaded) applyThemeToCtdCharts();
    timeSeriesLoaded.forEach((category) => reRenderCategoryFromCache(category));
    initializeMiniCharts();
}

function watchThemeForCharts() {
    const observer = new MutationObserver((mutations) => {
        const themeChanged = mutations.some(
            (m) => m.type === 'attributes' && (m.attributeName === 'data-bs-theme' || m.attributeName === 'data-theme')
        );
        if (!themeChanged) return;
        setTimeout(() => updateAllChartInstances(), 50);
    });
    observer.observe(document.documentElement, {
        attributes: true,
        attributeFilter: ['data-bs-theme', 'data-theme'],
    });
}

function buildProfileDataUrl() {
    const datasetId = getDatasetId();
    if (!datasetId) return '';
    const params = new URLSearchParams();
    const dateRange = getSlocumDateRange();
    if (dateRange) {
        params.set('start_date', dateRange.startISO);
        params.set('end_date', dateRange.endISO);
    } else {
        params.set('hours_back', String(getHoursBack()));
    }
    if (isHistoricalDataset()) params.set('is_historical', 'true');
    return `/api/slocum/profile-data/${encodeURIComponent(datasetId)}?${params.toString()}`;
}

function formatRelativeTimeAgo(isoTimestamp) {
    if (!isoTimestamp) return 'N/A';
    const then = toUtcDate(isoTimestamp);
    if (!then) return 'N/A';
    const seconds = Math.max(0, Math.floor((Date.now() - then.getTime()) / 1000));
    if (seconds < 60) return seconds <= 1 ? '1 second ago' : `${seconds} seconds ago`;
    const minutes = Math.floor(seconds / 60);
    if (minutes < 60) return minutes === 1 ? '1 minute ago' : `${minutes} minutes ago`;
    const hours = Math.floor(minutes / 60);
    if (hours < 24) return hours === 1 ? '1 hour ago' : `${hours} hours ago`;
    const days = Math.floor(hours / 24);
    return days === 1 ? '1 day ago' : `${days} days ago`;
}

function setSlocumCtdLastDataFooter(lastTs) {
    const footer = document.getElementById('slocumCtdLastDataFooter');
    if (!footer) return;
    if (!lastTs) {
        footer.textContent = 'Last data: N/A';
        return;
    }
    const absolute = formatUtcDateTime(lastTs);
    const relative = formatRelativeTimeAgo(lastTs);
    footer.textContent = `Last data: ${absolute} (${relative})`;
}

function setSlocumDataSourceBadge(cacheMetadata) {
    const badge = document.getElementById('slocumDataSourceBadge');
    if (!badge) return;
    const source = cacheMetadata?.data_source || '';
    const labels = {
        mirror: { text: 'Source: 72h mirror', cls: 'text-bg-success' },
        overage_cache: { text: 'Source: temporary cache', cls: 'text-bg-info' },
        erddap_overage: { text: 'Source: ERDDAP (on demand)', cls: 'text-bg-warning' },
    };
    const mapped = labels[source] || { text: 'Source: —', cls: 'text-bg-secondary' };
    badge.className = `badge ms-1 ${mapped.cls}`;
    badge.textContent = mapped.text;
    if (cacheMetadata?.cache_expires_at) {
        badge.title = `Expires: ${cacheMetadata.cache_expires_at}`;
    } else if (source === 'mirror') {
        badge.title = 'Loaded from the rolling local mirror.';
    } else {
        badge.title = 'Where the displayed data was loaded from.';
    }
}

async function refreshCtdProfileCharts() {
    const url = buildProfileDataUrl();
    if (!url) return;
    CTD_PROFILE_CHARTS.forEach((cfg) => showProfileSpinner(cfg.spinnerId));
    const badge = document.getElementById('slocumDataSourceBadge');
    if (badge) {
        badge.className = 'badge text-bg-secondary ms-1';
        badge.textContent = 'Source: loading…';
    }
    try {
        const payload = await apiRequest(url, 'GET');
        ctdProfilePayloadCache = payload || null;
        updateChartColorVariables();
        CTD_PROFILE_CHARTS.forEach((cfg) => renderOneProfileChart(cfg, payload));
        setSlocumDataSourceBadge(payload?.cache_metadata || {});
        setSlocumCtdLastDataFooter(payload?.cache_metadata?.last_data_timestamp);
    } catch (err) {
        console.error('Failed to load CTD profile data:', err);
        showToast(`CTD profile load failed: ${err.message || err}`, 'danger');
        ctdProfilePayloadCache = null;
        destroyCtdCharts();
        CTD_PROFILE_CHARTS.forEach((cfg) => drawNoDataOnCanvas(cfg.canvasId, 'Failed to load profile data'));
        setSlocumDataSourceBadge({});
        setSlocumCtdLastDataFooter(null);
    } finally {
        CTD_PROFILE_CHARTS.forEach((cfg) => hideProfileSpinner(cfg.spinnerId));
    }
}

function loadCtdProfileCharts() {
    ctdProfilesLoaded = true;
    return refreshCtdProfileCharts();
}

function setSharedChartToolbarVisible(isVisible) {
    const toolbar = document.getElementById('slocumSharedChartToolbar');
    if (toolbar) toolbar.style.display = isVisible ? 'block' : 'none';
}

function destroyTimeSeriesCharts(category) {
    const prefix = `${category}::`;
    Object.keys(timeSeriesChartInstances).forEach((key) => {
        if (category && !key.startsWith(prefix)) return;
        try {
            timeSeriesChartInstances[key].destroy();
        } catch (_) { /* ignore */ }
        delete timeSeriesChartInstances[key];
    });
}

function buildBulkChartDataUrl(variables) {
    const datasetId = getDatasetId();
    if (!datasetId || !variables?.length) return '';
    const params = buildSlocumQueryParams({
        granularity_minutes: getGranularity(),
        hours_back: getHoursBack(),
        dateRange: getSlocumDateRange(),
        is_historical: isHistoricalDataset(),
    });
    params.set('variables', variables.join(','));
    return `/api/slocum/chart-data-bulk/${encodeURIComponent(datasetId)}?${params.toString()}`;
}

function setCategoryLastDataFooter(footerId, lastTs) {
    const footer = document.getElementById(footerId);
    if (!footer) return;
    if (!lastTs) {
        footer.textContent = 'Last data: N/A';
        return;
    }
    const absolute = formatUtcDateTime(lastTs);
    const relative = formatRelativeTimeAgo(lastTs);
    footer.textContent = `Last data: ${absolute} (${relative})`;
}

function renderTimeSeriesChart(category, chartCfg, seriesPayload) {
    const canvas = document.getElementById(chartCfg.canvasId);
    if (!canvas || typeof Chart === 'undefined') return;
    const instanceKey = `${category}::${chartCfg.canvasId}`;
    if (timeSeriesChartInstances[instanceKey]) {
        try { timeSeriesChartInstances[instanceKey].destroy(); } catch (_) { /* ignore */ }
        delete timeSeriesChartInstances[instanceKey];
    }

    const plotStyle = getPlotStyleForCanvas(PLOT_STYLE_STORAGE_PREFIX, chartCfg.canvasId);
    const showDepth = !chartCfg.skipDepthOverlay
        && getOverlayEnabledForCanvas(DEPTH_OVERLAY_STORAGE_PREFIX, chartCfg.canvasId);

    const datasets = [];
    (chartCfg.series || []).forEach((spec, idx) => {
        const points = recordsToPoints(seriesPayload?.[spec.key] || []);
        if (!points.length) return;
        const color = SERIES_COLORS[idx % SERIES_COLORS.length];
        const isBar = spec.type === 'bar';
        const styleProps = plotStyleDatasetProps(plotStyle, isBar);
        datasets.push({
            type: isBar ? 'bar' : 'line',
            label: spec.label || spec.key,
            data: points,
            borderColor: color,
            backgroundColor: isBar ? color.replace(', 1)', ', 0.55)') : color,
            borderDash: spec.dashed ? [6, 4] : undefined,
            yAxisID: spec.yAxisID || 'y',
            pointRadius: styleProps.pointRadius,
            pointHoverRadius: styleProps.pointRadius ? styleProps.pointRadius + 1.5 : 3,
            pointHitRadius: styleProps.pointHitRadius,
            showLine: styleProps.showLine,
            borderWidth: 1.5,
            tension: 0.15,
            fill: false,
        });
    });

    if (showDepth) {
        const depthPoints = recordsToPoints(seriesPayload?.m_depth || []);
        if (depthPoints.length) {
            datasets.push(buildBackgroundOverlayDataset({
                points: depthPoints,
                label: DEPTH_OVERLAY_LABEL,
                color: DEPTH_OVERLAY_COLOR,
                yAxisID: 'yDepth',
            }));
        }
    }

    if (!datasets.length) {
        drawNoDataOnCanvas(chartCfg.canvasId, 'No data for selected window');
        return;
    }
    ensureDatasetHitRadius(datasets);

    const hasBar = datasets.some((ds) => ds.type === 'bar');
    const scales = {
        x: buildSlocumTimeScaleX(),
        y: {
            position: 'left',
            reverse: !!chartCfg.invertY,
            title: { display: !!chartCfg.yLabel, text: chartCfg.yLabel || '', color: chartTextColor },
            ticks: { color: chartTextColor },
            grid: { color: chartGridColor },
        },
    };
    if (chartCfg.y2Label || (chartCfg.series || []).some((s) => s.yAxisID === 'y1')) {
        scales.y1 = {
            position: 'right',
            title: { display: true, text: chartCfg.y2Label || '', color: chartTextColor },
            ticks: { color: chartTextColor },
            grid: { drawOnChartArea: false },
        };
    }
    if (showDepth) {
        scales.yDepth = buildHiddenOverlayScale('yDepth', { reverse: true });
    }

    const chartOptions = {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
            legend: {
                display: datasets.length > 1,
                labels: {
                    color: chartTextColor,
                    filter: filterOverlayFromLegend,
                },
            },
        },
        scales,
    };
    const { options: tsOptions, plugins: tsPlugins } = applyTimeSeriesHoverDefaults(chartOptions, {
        overlayTooltip: { overlayLabel: 'Depth' },
    });
    applyTimeAxisZoom(tsOptions);

    timeSeriesChartInstances[instanceKey] = new Chart(canvas.getContext('2d'), {
        type: hasBar ? 'bar' : 'line',
        data: { datasets },
        options: tsOptions,
        plugins: tsPlugins,
    });
}

function renderSfmcCallChartFromCache(categoryCfg) {
    const callCfg = categoryCfg?.sfmcCallChart;
    if (!callCfg) return;
    const canvas = document.getElementById(callCfg.canvasId);
    if (!canvas || typeof Chart === 'undefined') return;

    const instanceKey = `vehicle_health::${callCfg.canvasId}`;
    if (timeSeriesChartInstances[instanceKey]) {
        try { timeSeriesChartInstances[instanceKey].destroy(); } catch (_) { /* ignore */ }
        delete timeSeriesChartInstances[instanceKey];
    }

    const points = Array.isArray(sfmcCallPointsCache) ? sfmcCallPointsCache : [];
    const plotStyle = getPlotStyleForCanvas(PLOT_STYLE_STORAGE_PREFIX, callCfg.canvasId);
    const showDepth = getOverlayEnabledForCanvas(DEPTH_OVERLAY_STORAGE_PREFIX, callCfg.canvasId);
    const datasets = [];
    if (points.length) {
        const callStyle = plotStyleDatasetProps(plotStyle, false);
        // Discrete call events: keep visible points even in "line" style.
        const pointRadius = callStyle.pointRadius || 2.5;
        datasets.push({
            type: 'line',
            label: 'Call length (min)',
            data: points,
            borderColor: 'rgba(220, 53, 69, 1)',
            backgroundColor: 'rgba(220, 53, 69, 0.55)',
            yAxisID: 'y',
            pointRadius,
            pointHoverRadius: pointRadius + 1.5,
            pointHitRadius: callStyle.pointHitRadius,
            showLine: callStyle.showLine,
            borderWidth: 1.5,
            tension: 0.1,
            fill: false,
        });
    }
    if (showDepth) {
        const depthPoints = recordsToPoints(timeSeriesSeriesCache.vehicle_health?.m_depth || []);
        if (depthPoints.length) {
            datasets.push(buildBackgroundOverlayDataset({
                points: depthPoints,
                label: DEPTH_OVERLAY_LABEL,
                color: DEPTH_OVERLAY_COLOR,
                yAxisID: 'yDepth',
            }));
        }
    }

    if (!datasets.length) {
        drawNoDataOnCanvas(callCfg.canvasId, 'No cached SFMC connection durations');
        return;
    }
    ensureDatasetHitRadius(datasets);

    const scales = {
        x: buildSlocumTimeScaleX(),
        y: {
            title: { display: true, text: 'Duration (min)', color: chartTextColor },
            ticks: { color: chartTextColor },
            grid: { color: chartGridColor },
            beginAtZero: true,
        },
    };
    if (showDepth) {
        scales.yDepth = buildHiddenOverlayScale('yDepth', { reverse: true });
    }

    const chartOptions = {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
            legend: {
                display: datasets.length > 1,
                labels: {
                    color: chartTextColor,
                    filter: filterOverlayFromLegend,
                },
            },
        },
        scales,
    };
    const { options: tsOptions, plugins: tsPlugins } = applyTimeSeriesHoverDefaults(chartOptions, {
        overlayTooltip: { overlayLabel: 'Depth' },
    });
    applyTimeAxisZoom(tsOptions);

    timeSeriesChartInstances[instanceKey] = new Chart(canvas.getContext('2d'), {
        type: 'line',
        data: { datasets },
        options: tsOptions,
        plugins: tsPlugins,
    });
}

async function refreshSfmcCallLengthChart(categoryCfg) {
    const callCfg = categoryCfg?.sfmcCallChart;
    if (!callCfg) return;
    const datasetId = getDatasetId();
    if (!datasetId) return;
    showProfileSpinner(callCfg.spinnerId);
    const noteEl = document.getElementById(callCfg.noteId);
    try {
        const payload = await apiRequest(
            `/api/slocum/sfmc/connection-durations/${encodeURIComponent(datasetId)}`,
            'GET',
        );
        const connections = Array.isArray(payload?.connections) ? payload.connections : [];
        sfmcCallPointsCache = connections
            .filter((row) => row?.start && row?.duration_seconds != null)
            .map((row) => ({
                x: toUtcDate(row.start),
                y: Number(row.duration_seconds) / 60.0,
            }))
            .filter((p) => p.x != null && Number.isFinite(p.y));

        const showNote = !payload?.sfmc_configured || sfmcCallPointsCache.length === 0;
        if (noteEl) noteEl.style.display = showNote ? 'block' : 'none';

        if (!sfmcCallPointsCache.length) {
            drawNoDataOnCanvas(callCfg.canvasId, payload?.sfmc_configured
                ? 'No cached SFMC connection durations'
                : 'SFMC not configured');
            return;
        }
        renderSfmcCallChartFromCache(categoryCfg);
    } catch (err) {
        console.error('SFMC connection durations failed:', err);
        if (noteEl) noteEl.style.display = 'block';
        sfmcCallPointsCache = null;
        drawNoDataOnCanvas(callCfg.canvasId, 'Failed to load connection durations');
    } finally {
        hideProfileSpinner(callCfg.spinnerId);
    }
}

function reRenderCategoryFromCache(category) {
    const cfg = TIME_SERIES_CARD_CONFIGS[category];
    if (!cfg) return;
    if (cfg.placeholder) {
        updateChartColorVariables();
        cfg.charts.forEach((chartCfg) => {
            drawNoDataOnCanvas(
                chartCfg.canvasId,
                chartCfg.noDataMessage || 'Chart coming soon',
            );
        });
        return;
    }
    const series = timeSeriesSeriesCache[category];
    if (!series) return;
    updateChartColorVariables();
    cfg.charts.forEach((chartCfg) => renderTimeSeriesChart(category, chartCfg, series));
    if (category === 'vehicle_health' && Array.isArray(sfmcCallPointsCache)) {
        renderSfmcCallChartFromCache(cfg);
    }
}

async function refreshTimeSeriesCategory(category) {
    const cfg = TIME_SERIES_CARD_CONFIGS[category];
    if (!cfg) return;

    if (cfg.placeholder) {
        updateChartColorVariables();
        destroyTimeSeriesCharts(category);
        timeSeriesSeriesCache[category] = {};
        cfg.charts.forEach((chartCfg) => {
            drawNoDataOnCanvas(
                chartCfg.canvasId,
                chartCfg.noDataMessage || 'Chart coming soon',
            );
        });
        setSlocumDataSourceBadge({});
        setCategoryLastDataFooter(cfg.footerId, null);
        return;
    }

    const url = buildBulkChartDataUrl(cfg.variables);
    if (!url) return;

    cfg.charts.forEach((chartCfg) => showProfileSpinner(chartCfg.spinnerId));
    const badge = document.getElementById('slocumDataSourceBadge');
    if (badge) {
        badge.className = 'badge text-bg-secondary ms-1';
        badge.textContent = 'Source: loading…';
    }

    try {
        updateChartColorVariables();
        const payload = await apiRequest(url, 'GET');
        const series = payload?.series || {};
        timeSeriesSeriesCache[category] = series;
        destroyTimeSeriesCharts(category);
        cfg.charts.forEach((chartCfg) => renderTimeSeriesChart(category, chartCfg, series));
        setSlocumDataSourceBadge(payload?.cache_metadata || {});
        setCategoryLastDataFooter(cfg.footerId, payload?.cache_metadata?.last_data_timestamp);
        if (category === 'vehicle_health') {
            await refreshSfmcCallLengthChart(cfg);
        }
    } catch (err) {
        console.error(`Failed to load ${category} charts:`, err);
        showToast(`${category} chart load failed: ${err.message || err}`, 'danger');
        destroyTimeSeriesCharts(category);
        cfg.charts.forEach((chartCfg) => drawNoDataOnCanvas(chartCfg.canvasId, 'Failed to load chart data'));
        setSlocumDataSourceBadge({});
        setCategoryLastDataFooter(cfg.footerId, null);
    } finally {
        cfg.charts.forEach((chartCfg) => hideProfileSpinner(chartCfg.spinnerId));
    }
}

function findCategoryForCanvas(canvasId) {
    for (const [category, cfg] of Object.entries(TIME_SERIES_CARD_CONFIGS)) {
        if ((cfg.charts || []).some((c) => c.canvasId === canvasId)) return category;
        if (cfg.sfmcCallChart?.canvasId === canvasId) return category;
    }
    return null;
}

function findTimeSeriesChartByCanvasId(canvasId) {
    if (!canvasId) return null;
    if (ctdChartInstances[canvasId]) return ctdChartInstances[canvasId];
    return Object.values(timeSeriesChartInstances).find((inst) => inst?.canvas?.id === canvasId) || null;
}

function initSlocumChartControls() {
    bindPlotStyleControls({
        selectSelector: '.chart-plot-style',
        storagePrefix: PLOT_STYLE_STORAGE_PREFIX,
        onChange(canvasId) {
            const category = findCategoryForCanvas(canvasId);
            if (category) reRenderCategoryFromCache(category);
        },
    });
    bindOverlayToggleControls({
        checkboxSelector: '.chart-depth-overlay',
        storagePrefix: DEPTH_OVERLAY_STORAGE_PREFIX,
        onChange(canvasId) {
            if (CTD_PROFILE_CHARTS.some((c) => c.canvasId === canvasId)) {
                reRenderCtdProfilesFromCache();
                return;
            }
            const category = findCategoryForCanvas(canvasId);
            if (category) reRenderCategoryFromCache(category);
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
        bindResetZoomButton(button, () => findTimeSeriesChartByCanvasId(canvasId));
    });
    const zoomHint = document.getElementById('slocumChartZoomHint');
    if (zoomHint) zoomHint.textContent = CHART_ZOOM_HINT;
}

function loadTimeSeriesCategory(category) {
    timeSeriesLoaded.add(category);
    return refreshTimeSeriesCategory(category);
}

function saveSlocumChartsAsPng(highResolution = false) {
    const category = activeChartCategory;
    if (!category || category === 'overview') {
        showToast('Open a sensor tab with charts first.', 'info');
        return;
    }
    const detailView = document.getElementById(`detail-${category}`);
    if (!detailView) return;
    const datasetId = getDatasetId() || 'slocum';
    const canvases = detailView.querySelectorAll('canvas');
    let count = 0;
    const bodyStyles = getComputedStyle(document.body);
    const bgColor = bodyStyles.getPropertyValue('--bs-body-bg').trim() || '#ffffff';
    const scaleFactor = highResolution ? 4 : 1;

    canvases.forEach((canvas) => {
        const chartInstance = ctdChartInstances[canvas.id]
            || Object.values(timeSeriesChartInstances).find((inst) => inst?.canvas?.id === canvas.id);
        if (!chartInstance) return;
        const source = chartInstance.canvas;
        const out = document.createElement('canvas');
        out.width = source.width * scaleFactor;
        out.height = source.height * scaleFactor;
        const ctx = out.getContext('2d');
        ctx.imageSmoothingEnabled = true;
        ctx.imageSmoothingQuality = 'high';
        ctx.fillStyle = bgColor;
        ctx.fillRect(0, 0, out.width, out.height);
        if (scaleFactor !== 1) ctx.scale(scaleFactor, scaleFactor);
        ctx.drawImage(source, 0, 0);
        const link = document.createElement('a');
        link.href = out.toDataURL('image/png');
        const suffix = highResolution ? '_high_res' : '';
        link.download = `${datasetId}_${canvas.id}${suffix}.png`;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        count += 1;
    });
    if (count === 0) showToast('No charts available to save.', 'info');
}

function refreshLoadedChartTabs() {
    if (ctdProfilesLoaded) refreshCtdProfileCharts();
    TIME_SERIES_CATEGORIES.forEach((category) => {
        if (timeSeriesLoaded.has(category)) refreshTimeSeriesCategory(category);
    });
}

/** Build query params for Slocum chart-data or CSV (time window + granularity). */
function buildSlocumQueryParams(opts) {
    const { variable, granularity_minutes, hours_back, dateRange, is_historical } = opts;
    const params = new URLSearchParams();
    if (variable != null) params.set('variable', variable);
    params.set('granularity_minutes', String(granularity_minutes));
    if (dateRange) {
        params.set('start_date', dateRange.startISO);
        params.set('end_date', dateRange.endISO);
    } else {
        params.set('hours_back', String(hours_back));
    }
    if (is_historical) params.set('is_historical', 'true');
    return params;
}

/** Build URL for CSV download using same time/granularity as chart controls. */
function buildSlocumCsvUrl() {
    const datasetId = getDatasetId();
    if (!datasetId) return '';
    const params = buildSlocumQueryParams({
        granularity_minutes: getGranularity(),
        hours_back: getHoursBack(),
        dateRange: getSlocumDateRange(),
        is_historical: isHistoricalDataset(),
    });
    return `/api/slocum/csv/${encodeURIComponent(datasetId)}?${params.toString()}`;
}

function handleLeftPanelClicks() {
    const summaryCards = document.querySelectorAll('#left-nav-panel .summary-card');
    const detailViews = document.querySelectorAll('#main-display-area .category-detail-view');

    summaryCards.forEach(card => {
        card.addEventListener('click', function () {
            summaryCards.forEach(c => c.classList.remove('active-card'));
            this.classList.add('active-card');
            const category = this.dataset.category;
            detailViews.forEach(view => { view.style.display = 'none'; });
            const activeDetailView = document.getElementById(`detail-${category}`);
            if (activeDetailView) {
                activeDetailView.style.display = 'block';
            }
            const isOverview = category === 'overview';
            const isChartCategory = category === 'ctd' || TIME_SERIES_CATEGORIES.includes(category);
            setSharedChartToolbarVisible(isChartCategory);
            // CTD profiles must keep full resolution; time-mean resample would destroy structure.
            // DO placeholder has no live series yet — keep resample enabled for consistency.
            setGranularityControlEnabled(!isOverview && category !== 'ctd');
            activeChartCategory = isOverview ? null : category;
            if (category === 'ctd') loadCtdProfileCharts();
            if (TIME_SERIES_CATEGORIES.includes(category)) loadTimeSeriesCategory(category);
        });
    });
}

async function pollSlocumCacheStatus() {
    const datasetId = getDatasetId();
    if (!datasetId || !autoRefreshEnabled || isHistoricalDataset()) return;
    try {
        const status = await apiRequest(`/api/slocum/cache-status/${encodeURIComponent(datasetId)}`, 'GET');
        let cacheUpdated = false;
        for (const [bundle, bundleStatus] of Object.entries(status || {})) {
            const stored = slocumCacheTimestamps.get(bundle);
            const serverLast = bundleStatus?.last_data_timestamp;
            const storedLast = stored?.last_data_timestamp;
            if (storedLast && serverLast && new Date(serverLast) > new Date(storedLast)) {
                cacheUpdated = true;
            } else if (!storedLast && serverLast) {
                slocumCacheTimestamps.set(bundle, {
                    cache_timestamp: bundleStatus.cache_timestamp,
                    last_data_timestamp: serverLast,
                });
            }
            if (bundleStatus?.cache_timestamp) {
                slocumCacheTimestamps.set(bundle, {
                    cache_timestamp: bundleStatus.cache_timestamp,
                    last_data_timestamp: serverLast,
                });
            }
        }
        if (cacheUpdated) {
            refreshAllLoadedChartsQuiet();
            refreshSlocumSummaryCards();
        }
    } catch (err) {
        console.debug('Slocum cache status poll failed:', err);
    }
}

function formatCardSummaryValue(value, digits = 1) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) return 'N/A';
    return Number(value).toFixed(digits);
}

function updateSlocumCardFromSummary(category, summary) {
    const card = document.querySelector(`#left-nav-panel .summary-card[data-category="${category}"]`);
    if (!card || !summary) return;

    const values = summary.values || {};
    const miniSummary = card.querySelector('.mini-summary');
    const footer = card.querySelector('.summary-card-footer');

    if (category === 'ctd' && miniSummary) {
        const temp = formatCardSummaryValue(values.Temperature);
        const sal = formatCardSummaryValue(values.Salinity);
        miniSummary.innerHTML = `Temp: ${temp} °C<br>Sal: ${sal} PSU`;
    } else if (category === 'power' && miniSummary) {
        const batt = formatCardSummaryValue(values.MBattery, 2);
        const ah = formatCardSummaryValue(values.MCoulombAmphrTotal, 1);
        miniSummary.innerHTML = `Batt: ${batt} V<br>Ah: ${ah}`;
    } else if (category === 'flight' && miniSummary) {
        const pitch = formatCardSummaryValue(values.MPitch, 1);
        const roll = formatCardSummaryValue(values.MRoll, 1);
        miniSummary.innerHTML = `Pitch: ${pitch}°<br>Roll: ${roll}°`;
    } else if (category === 'navigation' && miniSummary) {
        const hdg = formatCardSummaryValue(values.MHeading, 1);
        const spd = formatCardSummaryValue(values.MSpeed, 2);
        miniSummary.innerHTML = `Hdg: ${hdg}°<br>Spd: ${spd} m/s`;
    } else if (category === 'vehicle_health' && miniSummary) {
        const vac = formatCardSummaryValue(values.MVacuum, 2);
        const leak = formatCardSummaryValue(values.MLeakdetectVoltage, 2);
        miniSummary.innerHTML = `Vac: ${vac} inHg<br>Leak: ${leak} V`;
    }
    if (footer) {
        footer.textContent = summary.time_ago_str || 'N/A';
    }
    const miniTrend = Array.isArray(summary.mini_trend) ? summary.mini_trend : [];
    card.dataset.miniTrend = JSON.stringify(miniTrend);
}

async function refreshSlocumSummaryCards() {
    const datasetId = getDatasetId();
    if (!datasetId) return;
    try {
        const sensors = await apiRequest(
            `/api/slocum/sensor-summaries/${encodeURIComponent(datasetId)}`,
            'GET',
        );
        if (!sensors || typeof sensors !== 'object') return;
        Object.entries(sensors).forEach(([category, summary]) => {
            updateSlocumCardFromSummary(category, summary);
        });
        initializeMiniCharts();
    } catch (err) {
        console.debug('Slocum summary card refresh failed:', err);
    }
}

function refreshAllLoadedChartsQuiet() {
    refreshLoadedChartTabs();
}

function startCountdownTimer() {
    const countdownElement = document.getElementById('refreshCountdown');
    if (!countdownElement) return;
    if (!autoRefreshEnabled) return;

    let remainingSeconds = AUTO_REFRESH_INTERVAL_MINUTES * 60;

    function updateCountdownDisplay() {
        const minutes = Math.floor(remainingSeconds / 60);
        const seconds = remainingSeconds % 60;
        const display = `${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
        countdownElement.textContent = ` (Next refresh in ${display})`;

        if (remainingSeconds <= 0) {
            if (countdownTimer) clearInterval(countdownTimer);
            countdownTimer = null;
            countdownElement.textContent = '';
            pollSlocumCacheStatus();
            remainingSeconds = AUTO_REFRESH_INTERVAL_MINUTES * 60;
            countdownTimer = setInterval(updateCountdownDisplay, 1000);
        } else {
            remainingSeconds--;
        }
    }
    updateCountdownDisplay();
    countdownTimer = setInterval(updateCountdownDisplay, 1000);
}

function updateAutoRefreshState(isEnabled) {
    autoRefreshEnabled = isEnabled;
    try {
        localStorage.setItem('autoRefreshEnabled', JSON.stringify(isEnabled));
    } catch (e) { /* ignore */ }

    const isRealtime = !isHistoricalDataset();
    if (isEnabled && isRealtime) {
        startCountdownTimer();
        if (cachePollIntervalId) clearInterval(cachePollIntervalId);
        cachePollIntervalId = setInterval(pollSlocumCacheStatus, AUTO_REFRESH_POLL_INTERVAL_MS);
        pollSlocumCacheStatus();
    } else {
        if (cachePollIntervalId) {
            clearInterval(cachePollIntervalId);
            cachePollIntervalId = null;
        }
        if (countdownTimer) {
            clearInterval(countdownTimer);
            countdownTimer = null;
        }
        const countdownElement = document.getElementById('refreshCountdown');
        if (countdownElement) countdownElement.textContent = '';
    }
}

function initAutoRefresh() {
    const isRealtime = !isHistoricalDataset();
    if (!isRealtime) return;

    const autoRefreshToggle = document.getElementById('autoRefreshToggleBanner');
    if (!autoRefreshToggle) return;

    const saved = localStorage.getItem('autoRefreshEnabled');
    if (saved !== null) {
        try {
            autoRefreshToggle.checked = JSON.parse(saved);
        } catch (e) { /* use default */ }
    }
    updateAutoRefreshState(autoRefreshToggle.checked);

    autoRefreshToggle.addEventListener('change', function () {
        updateAutoRefreshState(this.checked);
    });
}


// --- Overview briefing (plan / reports / ST / comments / goals / media) ---

function mediaFileUrl(media) {
    if (!media) return '';
    if (media.file_url) return media.file_url;
    const path = media.file_path || '';
    if (!path) return '';
    return path.startsWith('/') ? path : `/static/${path}`;
}

function setDeploymentActionsEnabled(isEnabled) {
    const addMediaBtn = document.getElementById('slocumAddMediaBtn');
    const noteComposer = document.querySelector('#slocumNoteComposerCard .new-mission-note-content');
    const addNoteBtn = document.querySelector('#slocumNoteComposerCard .add-mission-note-btn');
    const addGoalBtn = document.querySelector('.add-goal-btn');
    if (addMediaBtn) addMediaBtn.disabled = !isEnabled;
    if (noteComposer) noteComposer.disabled = !isEnabled;
    if (addNoteBtn) addNoteBtn.disabled = !isEnabled;
    if (addGoalBtn) addGoalBtn.disabled = !isEnabled;
}

function renderMediaEmpty(message) {
    const gallery = document.getElementById('slocumMediaGallery');
    if (!gallery) return;
    gallery.innerHTML = `<div class="text-muted small">${escapeHtml(message)}</div>`;
}

function renderMediaCard(media) {
    const col = document.createElement('div');
    col.className = 'col-md-4 mission-media-item';
    col.dataset.mediaId = media.id;
    const caption = media.caption ? escapeHtml(media.caption) : '';
    const operation = media.operation_type ? escapeHtml(media.operation_type) : 'Unspecified';
    const uploadedBy = escapeHtml(media.uploaded_by_username || 'Unknown');
    const url = mediaFileUrl(media);
    const isVideo = media.media_type === 'video';
    const mediaPreview = isVideo
        ? `<video class="card-img-top" controls preload="metadata" style="height: 150px; object-fit: cover;">
                <source src="${url}">
           </video>`
        : `<a href="${url}" target="_blank" rel="noopener noreferrer">
                <img src="${url}" class="card-img-top" alt="${caption || 'Mission media'}" style="height: 150px; object-fit: cover;">
           </a>`;
    col.innerHTML = `
        <div class="card h-100">
            ${mediaPreview}
            <div class="card-body p-2">
                <div class="small text-muted mb-1">${operation.charAt(0).toUpperCase() + operation.slice(1)} • ${uploadedBy}</div>
                ${caption ? `<div class="small">${caption}</div>` : ''}
            </div>
        </div>
    `;
    return col;
}

function renderMissionNotes(notes) {
    const list = document.getElementById('dashboardMissionNotesList');
    if (!list) return;
    const notesContainer = list.closest('.mission-notes-container');
    const existingHistory = notesContainer ? notesContainer.querySelector('.older-mission-notes-wrapper') : null;
    if (existingHistory) existingHistory.remove();

    if (!currentDeploymentId) {
        lastMissionNotesForEdit = [];
        list.innerHTML = '<li class="list-group-item text-muted no-mission-notes-placeholder">Unable to load comments for this dataset.</li>';
        return;
    }
    if (!notes || notes.length === 0) {
        lastMissionNotesForEdit = [];
        list.innerHTML = '<li class="list-group-item text-muted no-mission-notes-placeholder">No mission comments have been added.</li>';
        return;
    }

    const sortedNotes = [...notes].sort((a, b) => {
        const ta = Date.parse(a.created_at_utc || '');
        const tb = Date.parse(b.created_at_utc || '');
        if (Number.isNaN(ta) && Number.isNaN(tb)) return 0;
        if (Number.isNaN(ta)) return 1;
        if (Number.isNaN(tb)) return -1;
        return tb - ta;
    });
    const recentNotes = sortedNotes.slice(0, DASHBOARD_RECENT_NOTE_LIMIT);
    const olderNotes = sortedNotes.slice(DASHBOARD_RECENT_NOTE_LIMIT);
    lastMissionNotesForEdit = sortedNotes;

    const noteMarkup = (note) => {
        const canEdit = USER_ROLE === 'admin' || (USERNAME && note.created_by_username === USERNAME);
        return `
            <li class="list-group-item d-flex justify-content-between align-items-start" data-note-id="${note.id}">
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
    };

    list.innerHTML = recentNotes.map(noteMarkup).join('');
    if (!notesContainer || olderNotes.length === 0) return;

    const historyWrapper = document.createElement('div');
    historyWrapper.className = 'older-mission-notes-wrapper mt-2';
    historyWrapper.innerHTML = `
        <button type="button" class="btn btn-sm btn-outline-secondary toggle-older-notes-btn">
            Show older comments (${olderNotes.length})
        </button>
        <ul class="list-group older-mission-notes-list d-none mt-2">
            ${olderNotes.map(noteMarkup).join('')}
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
}

function renderMissionGoals(goals) {
    const list = document.getElementById('dashboardMissionGoalsList');
    if (!list) return;
    if (!currentDeploymentId) {
        list.innerHTML = '<li class="list-group-item text-muted no-mission-goals-placeholder">Unable to load goals for this dataset.</li>';
        return;
    }
    if (!goals || goals.length === 0) {
        list.innerHTML = '<li class="list-group-item text-muted no-mission-goals-placeholder">No mission goals have been defined.</li>';
        return;
    }
    list.innerHTML = goals.map((goal) => {
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
}

function renderSlocumMedia(mediaItems) {
    const gallery = document.getElementById('slocumMediaGallery');
    if (!gallery) return;
    if (!currentDeploymentId) {
        renderMediaEmpty('Unable to load media for this dataset.');
        return;
    }
    if (!mediaItems || mediaItems.length === 0) {
        renderMediaEmpty('No media uploaded for this deployment yet.');
        return;
    }
    gallery.innerHTML = '';
    mediaItems.forEach((media) => gallery.appendChild(renderMediaCard(media)));
}

function renderPlanDocument(documentUrl) {
    const container = document.getElementById('overviewPlanContainer');
    const link = document.getElementById('overviewPlanLink');
    const empty = document.getElementById('overviewPlanEmpty');
    if (documentUrl && container && link && empty) {
        link.href = documentUrl;
        link.textContent = documentUrl.split('/').pop();
        container.style.display = 'block';
        empty.style.display = 'none';
    } else if (empty && container) {
        container.style.display = 'none';
        empty.style.display = 'block';
    }
}

function renderSensorTrackerOverview(deployment, instruments) {
    const container = document.getElementById('overviewSensorTrackerContainer');
    const empty = document.getElementById('overviewSensorTrackerEmpty');
    if (deployment && container && empty) {
        container.style.display = 'block';
        empty.style.display = 'none';
        const setText = (id, value) => {
            const el = document.getElementById(id);
            if (el) el.textContent = value || '-';
        };
        setText('overviewStTitle', deployment.title);
        setText('overviewStStart', deployment.start_time ? formatUtcDateTime(deployment.start_time) : '-');
        setText('overviewStEnd', deployment.end_time ? formatUtcDateTime(deployment.end_time) : '-');
        setText('overviewStPlatform', deployment.platform_name);
        const repo = document.getElementById('overviewStDataRepo');
        if (repo) {
            if (deployment.data_repository_link) {
                repo.innerHTML = '';
                const a = document.createElement('a');
                a.href = deployment.data_repository_link;
                a.target = '_blank';
                a.rel = 'noopener noreferrer';
                a.textContent = deployment.data_repository_link;
                repo.appendChild(a);
            } else {
                repo.textContent = '-';
            }
        }
        setText('overviewStDescription', deployment.deployment_comment || '-');
        const instrumentsWrap = document.getElementById('overviewStInstruments');
        const instrumentsList = document.getElementById('overviewStInstrumentsList');
        if (instrumentsWrap && instrumentsList) {
            instrumentsList.innerHTML = '';
            if (instruments && instruments.length) {
                instruments.forEach((inst) => {
                    const li = document.createElement('li');
                    const name = inst.instrument_name || inst.instrument_identifier || 'Instrument';
                    const serial = inst.instrument_serial ? ` (${inst.instrument_serial})` : '';
                    li.textContent = `${name}${serial}`;
                    instrumentsList.appendChild(li);
                });
                instrumentsWrap.style.display = 'block';
            } else {
                instrumentsWrap.style.display = 'none';
            }
        }
    } else if (container && empty) {
        container.style.display = 'none';
        empty.style.display = 'block';
    }
}

async function loadSlocumReports() {
    const datasetId = getDatasetId();
    const weeklyContainer = document.getElementById('overviewWeeklyReportContainer');
    const weeklyLink = document.getElementById('overviewWeeklyReportLink');
    const weeklyList = document.getElementById('overviewWeeklyReportList');
    const noReports = document.getElementById('overviewNoReports');
    if (!datasetId) return;
    try {
        const payload = await apiRequest(`/api/slocum/reporting/datasets/${encodeURIComponent(datasetId)}/reports`, 'GET');
        const reports = payload?.reports || [];
        if (!reports.length) {
            if (weeklyContainer) weeklyContainer.style.display = 'none';
            if (weeklyList) weeklyList.style.display = 'none';
            if (noReports) noReports.style.display = 'block';
            return;
        }
        if (noReports) noReports.style.display = 'none';
        const latest = reports[0];
        if (weeklyContainer && weeklyLink) {
            weeklyLink.href = latest.url;
            weeklyLink.textContent = latest.filename;
            weeklyContainer.style.display = 'block';
        }
        if (weeklyList && reports.length > 1) {
            weeklyList.innerHTML = '<div class="mt-1"><strong>All reports:</strong></div><ul class="mb-0">'
                + reports.map((r) => `<li><a href="${escapeHtml(r.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(r.filename)}</a></li>`).join('')
                + '</ul>';
            weeklyList.style.display = 'block';
        } else if (weeklyList) {
            weeklyList.style.display = 'none';
        }
    } catch (error) {
        if (weeklyContainer) weeklyContainer.style.display = 'none';
        if (weeklyList) weeklyList.style.display = 'none';
        if (noReports) {
            noReports.style.display = 'block';
            noReports.textContent = `Failed to load reports: ${error.message}`;
        }
    }
}

async function loadSlocumOverview() {
    const datasetId = getDatasetId();
    if (!datasetId) return;
    try {
        const info = await apiRequest(`/api/slocum/datasets/${encodeURIComponent(datasetId)}/info`, 'GET');
        currentOverviewInfo = info;
        currentDeploymentId = info?.deployment?.id || null;
        setDeploymentActionsEnabled(Boolean(currentDeploymentId));
        renderPlanDocument(info?.deployment?.document_url || null);
        renderSensorTrackerOverview(info?.sensor_tracker_deployment || null, info?.sensor_tracker_instruments || []);
        renderMissionNotes(info?.notes || []);
        renderMissionGoals(info?.goals || []);
        renderSlocumMedia(info?.media || []);
        if (!currentDeploymentId) {
            showToast('Unable to create deployment metadata for this dataset id.', 'warning');
        }
    } catch (error) {
        console.error('Failed to load Slocum overview:', error);
        showToast(`Failed to load overview: ${error.message}`, 'danger');
        renderMediaEmpty(`Failed to load media: ${error.message}`);
    }
}

function bindSlocumOverviewInteractions() {
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
    const missionNoteIncludeReport = document.getElementById('missionNoteIncludeReport');
    const saveMissionNoteBtn = document.getElementById('saveMissionNoteBtn');

    const mediaForm = document.getElementById('slocumMediaUploadForm');
    if (mediaForm) {
        mediaForm.addEventListener('submit', async (event) => {
            event.preventDefault();
            if (!currentDeploymentId) {
                showToast('Deployment metadata unavailable for this dataset.', 'warning');
                return;
            }
            const fileInput = document.getElementById('slocumMediaFile');
            const fileToUpload = fileInput ? fileInput.files[0] : null;
            if (!fileToUpload) {
                showToast('Please select a media file to upload.', 'warning');
                return;
            }
            const uploadBtn = document.getElementById('slocumMediaUploadBtn');
            const spinner = document.getElementById('slocumMediaUploadSpinner');
            if (uploadBtn) uploadBtn.disabled = true;
            if (spinner) spinner.style.display = 'inline';
            const formData = new FormData();
            formData.append('file', fileToUpload);
            const caption = document.getElementById('slocumMediaCaption')?.value?.trim();
            const params = new URLSearchParams();
            if (caption) params.append('caption', caption);
            const query = params.toString();
            const uploadUrl = `/api/slocum/deployments/${currentDeploymentId}/media/upload${query ? `?${query}` : ''}`;
            try {
                const response = await fetchWithAuth(uploadUrl, { method: 'POST', body: formData });
                if (!response.ok) {
                    const err = await response.json().catch(() => ({}));
                    throw new Error(err.detail || 'Media upload failed.');
                }
                showToast('Media uploaded successfully!', 'success');
                if (fileInput) fileInput.value = '';
                const captionEl = document.getElementById('slocumMediaCaption');
                if (captionEl) captionEl.value = '';
                const operationEl = document.getElementById('slocumMediaOperation');
                if (operationEl) operationEl.value = '';
                await loadSlocumOverview();
            } catch (error) {
                showToast(`Upload failed: ${error.message}`, 'danger');
            } finally {
                if (uploadBtn) uploadBtn.disabled = false;
                if (spinner) spinner.style.display = 'none';
            }
        });
    }

    document.body.addEventListener('click', async (event) => {
        const addNoteBtn = event.target.closest('.add-mission-note-btn');
        if (addNoteBtn) {
            event.preventDefault();
            if (!currentDeploymentId) return;
            const textarea = document.querySelector('.new-mission-note-content');
            const content = textarea ? textarea.value.trim() : '';
            if (!content) {
                showToast('Comment cannot be empty.', 'danger');
                return;
            }
            try {
                await apiRequest(`/api/slocum/deployments/${currentDeploymentId}/notes`, 'POST', { content });
                showToast('Comment added successfully.', 'success');
                if (textarea) textarea.value = '';
                await loadSlocumOverview();
            } catch (error) {
                showToast(`Failed to add comment: ${error.message}`, 'danger');
            }
            return;
        }

        const editNoteBtn = event.target.closest('.edit-note-btn');
        if (editNoteBtn) {
            event.preventDefault();
            if (!missionNoteModal) return;
            const noteId = editNoteBtn.dataset.noteId;
            const note = lastMissionNotesForEdit.find((n) => String(n.id) === String(noteId));
            if (!note) {
                showToast('Could not load that comment. Refresh and try again.', 'warning');
                return;
            }
            if (missionNoteModalLabel) missionNoteModalLabel.textContent = 'Edit mission comment';
            if (missionNoteIdInput) missionNoteIdInput.value = noteId;
            if (missionNoteContentInput) missionNoteContentInput.value = note.content || '';
            if (missionNoteIncludeReport) missionNoteIncludeReport.checked = Boolean(note.include_in_report);
            missionNoteModal.show();
            return;
        }

        const deleteNoteBtn = event.target.closest('.delete-note-btn');
        if (deleteNoteBtn) {
            event.preventDefault();
            const noteId = deleteNoteBtn.dataset.noteId;
            if (!noteId || !confirm('Delete this comment?')) return;
            try {
                await apiRequest(`/api/slocum/deployments/notes/${noteId}`, 'DELETE');
                showToast('Comment deleted.', 'success');
                await loadSlocumOverview();
            } catch (error) {
                showToast(`Failed to delete comment: ${error.message}`, 'danger');
            }
            return;
        }

        const addGoalBtn = event.target.closest('.add-goal-btn');
        if (addGoalBtn) {
            event.preventDefault();
            if (USER_ROLE !== 'admin' || !goalModal || !currentDeploymentId) return;
            if (goalForm) goalForm.reset();
            if (goalIdInput) goalIdInput.value = '';
            if (goalModalLabel) goalModalLabel.textContent = 'Add Mission Goal';
            goalModal.show();
            return;
        }

        const editGoalBtn = event.target.closest('.edit-goal-btn');
        if (editGoalBtn) {
            event.preventDefault();
            if (USER_ROLE !== 'admin' || !goalModal) return;
            if (goalForm) goalForm.reset();
            if (goalIdInput) goalIdInput.value = editGoalBtn.dataset.goalId || '';
            if (goalDescriptionInput) goalDescriptionInput.value = editGoalBtn.dataset.description || '';
            if (goalModalLabel) goalModalLabel.textContent = 'Edit Mission Goal';
            goalModal.show();
            return;
        }

        const deleteGoalBtn = event.target.closest('.delete-goal-btn');
        if (deleteGoalBtn) {
            event.preventDefault();
            if (USER_ROLE !== 'admin') return;
            const goalId = deleteGoalBtn.dataset.goalId;
            if (!goalId || !confirm('Delete this goal?')) return;
            try {
                await apiRequest(`/api/slocum/deployments/goals/${goalId}`, 'DELETE');
                showToast('Goal deleted.', 'success');
                await loadSlocumOverview();
            } catch (error) {
                showToast(`Failed to delete goal: ${error.message}`, 'danger');
            }
        }
    });

    document.body.addEventListener('change', async (event) => {
        const goalCheckbox = event.target.closest('.mission-goal-checkbox');
        if (!goalCheckbox || !currentDeploymentId) return;
        const goalId = goalCheckbox.dataset.goalId;
        const isCompleted = goalCheckbox.checked;
        try {
            await apiRequest(
                `/api/slocum/deployments/${currentDeploymentId}/goals/${goalId}/toggle`,
                'POST',
                { is_completed: isCompleted }
            );
            await loadSlocumOverview();
        } catch (error) {
            goalCheckbox.checked = !isCompleted;
            showToast(`Failed to update goal: ${error.message}`, 'danger');
        }
    });

    if (saveGoalBtn) {
        saveGoalBtn.addEventListener('click', async () => {
            if (USER_ROLE !== 'admin' || !currentDeploymentId) return;
            const goalId = goalIdInput?.value;
            const description = goalDescriptionInput?.value.trim() || '';
            if (!description) {
                showToast('Goal description cannot be empty.', 'danger');
                return;
            }
            try {
                if (goalId) {
                    await apiRequest(`/api/slocum/deployments/goals/${goalId}`, 'PUT', { description });
                } else {
                    await apiRequest(`/api/slocum/deployments/${currentDeploymentId}/goals`, 'POST', { description });
                }
                if (goalModal) goalModal.hide();
                await loadSlocumOverview();
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
            const payload = {
                content,
                include_in_report: Boolean(missionNoteIncludeReport?.checked),
            };
            try {
                await apiRequest(`/api/slocum/deployments/notes/${id}`, 'PUT', payload);
                missionNoteModal.hide();
                showToast('Comment updated.', 'success');
                await loadSlocumOverview();
            } catch (error) {
                showToast(`Failed to update comment: ${error.message}`, 'danger');
            }
        });
    }
}

function bindSlocumChecklistTab() {
    const datasetId = getDatasetId();
    const newLink = document.getElementById('slocumNewChecklistLink');
    if (newLink && datasetId) {
        newLink.href = `/slocum/dataset/${encodeURIComponent(datasetId)}/checklist.html`;
    }

    const checklistTab = document.getElementById('slocum-checklist-tab');
    if (checklistTab) {
        checklistTab.addEventListener('shown.bs.tab', () => {
            loadSlocumChecklists();
        });
    }
    const refreshBtn = document.getElementById('slocumChecklistsRefreshBtn');
    if (refreshBtn) {
        refreshBtn.addEventListener('click', () => loadSlocumChecklists());
    }
}

function displaySlocumChecklistDetails(form) {
    const content = document.getElementById('slocumChecklistsFormDetailsContent');
    const title = document.getElementById('slocumChecklistsFormDetailsModalLabel');
    if (!content) return;
    if (title) {
        title.textContent = form.form_title || 'Daily Checklist';
    }
    const parts = [];
    parts.push(`<p class="small text-muted mb-3">Submitted by <strong>${escapeHtml(form.submitted_by_username || 'Unknown')}</strong> at ${escapeHtml(formatTimestamp(form.submission_timestamp))}</p>`);
    if (form.edited_by_username) {
        parts.push(`<p class="small text-muted">Last edited by ${escapeHtml(form.edited_by_username)} at ${escapeHtml(formatTimestamp(form.last_edited_timestamp))}</p>`);
    }
    (form.sections_data || []).forEach((section) => {
        parts.push(`<h6 class="mt-3">${escapeHtml(section.title || section.id)}</h6>`);
        parts.push('<dl class="row small mb-0">');
        (section.items || []).forEach((item) => {
            const verified = item.is_verified === true ? ' <span class="badge bg-success">Verified</span>' : '';
            const comment = item.comment ? `<div class="text-muted">Comment: ${escapeHtml(item.comment)}</div>` : '';
            parts.push(`
                <dt class="col-sm-4">${escapeHtml(item.label || item.id)}${verified}</dt>
                <dd class="col-sm-8">${escapeHtml(item.value != null ? String(item.value) : '—')}${comment}</dd>
            `);
        });
        parts.push('</dl>');
        if (section.section_comment) {
            parts.push(`<p class="small text-muted">Section notes: ${escapeHtml(section.section_comment)}</p>`);
        }
    });
    content.innerHTML = parts.join('');
    const modalEl = document.getElementById('slocumChecklistsFormDetailsModal');
    if (modalEl && window.bootstrap) {
        new bootstrap.Modal(modalEl).show();
    }
}

function renderSlocumChecklists(forms) {
    const latestEl = document.getElementById('slocumChecklistsLatest');
    const tableBody = document.getElementById('slocumChecklistsTableBody');
    const emptyEl = document.getElementById('slocumChecklistsEmpty');
    if (!latestEl || !tableBody) return;

    lastSlocumChecklists = Array.isArray(forms) ? forms : [];
    const canCompare = lastSlocumChecklists.length >= 2;

    const hasForms = Array.isArray(forms) && forms.length > 0;
    if (!hasForms) {
        latestEl.innerHTML = '<div class="text-muted small">No daily checklist submissions exist for this dataset.</div>';
        tableBody.innerHTML = '<tr><td colspan="4" class="text-muted small">No daily checklist submissions exist for this dataset.</td></tr>';
        if (emptyEl) emptyEl.style.display = 'block';
        return;
    }
    if (emptyEl) emptyEl.style.display = 'none';

    const latest = forms[0];
    const datasetId = getDatasetId();
    const compareDisabledAttr = canCompare
        ? ''
        : ' disabled title="Need at least two checklist submissions to compare"';
    latestEl.innerHTML = `
        <div class="d-flex justify-content-between align-items-start flex-wrap gap-2">
            <div>
                <div class="fw-bold">${escapeHtml(latest.form_title || 'Slocum Daily Pilot Checklist')}</div>
                <div class="text-muted small">
                    ${escapeHtml(formatTimestamp(latest.submission_timestamp))} • ${escapeHtml(latest.submitted_by_username || 'Unknown')}
                </div>
            </div>
            <div class="d-flex gap-2 flex-wrap">
                <button type="button" class="btn btn-sm btn-info" id="slocumChecklistsViewLatestBtn">View Details</button>
                <button type="button" class="btn btn-sm btn-outline-primary" id="slocumChecklistsCompareLatestBtn"${compareDisabledAttr}>Compare</button>
                ${(USER_ROLE === 'admin' || (USERNAME && latest.submitted_by_username === USERNAME))
                    ? `<a class="btn btn-sm btn-outline-secondary" href="/slocum/dataset/${encodeURIComponent(datasetId)}/checklist.html?edit=${latest.id}" target="_blank" rel="noopener noreferrer">Edit</a>`
                    : ''}
            </div>
        </div>
    `;
    const viewLatestBtn = document.getElementById('slocumChecklistsViewLatestBtn');
    if (viewLatestBtn) {
        viewLatestBtn.addEventListener('click', () => displaySlocumChecklistDetails(latest));
    }
    const compareLatestBtn = document.getElementById('slocumChecklistsCompareLatestBtn');
    if (compareLatestBtn && canCompare) {
        compareLatestBtn.addEventListener('click', () => {
            openSlocumChecklistCompare({
                forms: lastSlocumChecklists,
                referenceId: latest.id,
            });
        });
    }

    tableBody.innerHTML = '';
    forms.forEach((form) => {
        const row = tableBody.insertRow();
        row.insertCell().textContent = form.form_title || '';
        row.insertCell().textContent = formatTimestamp(form.submission_timestamp);
        row.insertCell().textContent = form.submitted_by_username || '';
        const actionsCell = row.insertCell();
        const viewBtn = document.createElement('button');
        viewBtn.type = 'button';
        viewBtn.className = 'btn btn-sm btn-outline-info me-1';
        viewBtn.textContent = 'View';
        viewBtn.addEventListener('click', () => displaySlocumChecklistDetails(form));
        actionsCell.appendChild(viewBtn);
        const compareBtn = document.createElement('button');
        compareBtn.type = 'button';
        compareBtn.className = 'btn btn-sm btn-outline-primary me-1';
        compareBtn.textContent = 'Compare';
        if (!canCompare) {
            compareBtn.disabled = true;
            compareBtn.title = 'Need at least two checklist submissions to compare';
        } else {
            compareBtn.addEventListener('click', () => {
                openSlocumChecklistCompare({
                    forms: lastSlocumChecklists,
                    referenceId: form.id,
                });
            });
        }
        actionsCell.appendChild(compareBtn);
        if (USER_ROLE === 'admin' || (USERNAME && form.submitted_by_username === USERNAME)) {
            const editLink = document.createElement('a');
            editLink.className = 'btn btn-sm btn-outline-secondary';
            editLink.textContent = 'Edit';
            editLink.target = '_blank';
            editLink.rel = 'noopener noreferrer';
            editLink.href = `/slocum/dataset/${encodeURIComponent(datasetId)}/checklist.html?edit=${form.id}`;
            actionsCell.appendChild(editLink);
        }
    });
}

async function loadSlocumChecklists() {
    const datasetId = getDatasetId();
    const spinner = document.getElementById('slocumChecklistsSpinner');
    const latestEl = document.getElementById('slocumChecklistsLatest');
    const tableBody = document.getElementById('slocumChecklistsTableBody');
    if (!datasetId) {
        if (latestEl) latestEl.innerHTML = '<div class="text-muted small">No dataset selected.</div>';
        return;
    }
    if (spinner) spinner.style.display = 'block';
    try {
        const forms = await apiRequest(`/api/slocum/checklists/${encodeURIComponent(datasetId)}`, 'GET');
        renderSlocumChecklists(forms);
    } catch (error) {
        if (latestEl) {
            latestEl.innerHTML = `<div class="text-danger small">Failed to load checklists: ${escapeHtml(error.message)}</div>`;
        }
        if (tableBody) {
            tableBody.innerHTML = `<tr><td colspan="4" class="text-danger small">Failed to load checklists: ${escapeHtml(error.message)}</td></tr>`;
        }
    } finally {
        if (spinner) spinner.style.display = 'none';
    }
}

document.addEventListener('DOMContentLoaded', () => {
    registerForceUtcTimeDisplayPlugin();
    const datasetId = getDatasetId();
    if (!datasetId) {
        const errEl = document.getElementById('slocumDashboardError');
        if (errEl) {
            errEl.textContent = 'Missing dataset. Go to Slocum Home and select a dataset.';
            errEl.style.display = 'block';
        }
        return;
    }

    setGranularityControlEnabled(true);
    updateChartColorVariables();
    loadSlocumOverview();
    loadSlocumReports();
    bindSlocumOverviewInteractions();
    bindSlocumChecklistTab();
    watchThemeForCharts();

    const hoursSelect = document.getElementById('slocumHoursBack');
    function refreshAllLoadedCharts() {
        refreshLoadedChartTabs();
    }

    if (hoursSelect) {
        hoursSelect.addEventListener('change', refreshAllLoadedCharts);
    }

    const granularitySelect = document.getElementById('slocumGranularity');
    if (granularitySelect) {
        // Resample only applies to non-profile chart tabs (future); ignore while on CTD.
        granularitySelect.addEventListener('change', () => {
            if (activeChartCategory && activeChartCategory !== 'ctd') {
                refreshAllLoadedCharts();
            }
        });
    }

    const refreshBtn = document.getElementById('slocumRefreshCharts');
    if (refreshBtn) {
        refreshBtn.addEventListener('click', refreshAllLoadedCharts);
    }

    initSlocumDateRangeControls();

    const csvDownloadBtn = document.getElementById('slocum-download-csv');
    if (csvDownloadBtn) {
        csvDownloadBtn.addEventListener('click', (e) => {
            e.preventDefault();
            const url = buildSlocumCsvUrl();
            if (url) window.location.href = url;
            else showToast('Cannot build download URL. Check dataset.', 'warning');
        });
    }
    document.querySelectorAll('[id^="slocum-save-charts-png"]').forEach((btn) => {
        btn.addEventListener('click', (e) => {
            e.preventDefault();
            const highRes = e.currentTarget.dataset.highRes === 'true';
            saveSlocumChartsAsPng(highRes);
        });
    });

    initAutoRefresh();
    initializeMiniCharts();
    initSlocumChartControls();
    handleLeftPanelClicks();
});
