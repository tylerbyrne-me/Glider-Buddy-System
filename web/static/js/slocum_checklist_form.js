/**
 * Slocum daily pilot checklist form: render schema, refresh autofill, submit/edit,
 * and Plot-it popups for selected autofilled series.
 */
import { apiRequest, showToast } from '/static/js/api.js';
import { checkAuth } from '/static/js/auth.js';
import { formatUtcDateTime, toUtcDate } from '/static/js/datetime_utils.js';
import {
    buildUtcTimeScaleX,
    registerForceUtcTimeDisplayPlugin,
} from '/static/js/chart_utc_utils.js';
import {
    applyTimeAxisZoom,
    bindResetZoomButton,
    CHART_ZOOM_HINT,
} from '/static/js/chart_zoom_utils.js';

registerForceUtcTimeDisplayPlugin();

/** Mirror of backend CHECKLIST_PLOTTABLE_ITEMS keys — add entries there first. */
const PLOTTABLE_ITEM_IDS = new Set([
    'depth_rate_val',
    'vacuum_val',
    'roll_val',
    'pitch_val',
    'fin_val',
    'battpos_val',
    'oil_vol_val',
    'water_depth_val',
    'bms_currents_val',
    'leakdetect_val',
    'thruster_val',
    'dmon_msg_byte_count_val',
]);

const MULTI_SERIES_COLORS = [
    '#fd7e14',
    '#2f9e44',
    '#ae3ec9',
    '#e03131',
    '#1098ad',
    '#f08c00',
];

function escapeHtmlValue(value) {
    if (value == null) return '';
    return String(value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

function parseDmonAscPayload(rawValue) {
    if (rawValue == null || rawValue === '') {
        return { summary: 'N/A', has_gap_over_16h: false, files: [] };
    }
    if (typeof rawValue === 'object') {
        return {
            summary: rawValue.summary || 'N/A',
            has_gap_over_16h: Boolean(rawValue.has_gap_over_16h),
            hours_since_last: rawValue.hours_since_last,
            files: Array.isArray(rawValue.files) ? rawValue.files : [],
        };
    }
    const text = String(rawValue);
    try {
        const parsed = JSON.parse(text);
        if (parsed && typeof parsed === 'object') {
            return {
                summary: parsed.summary || text,
                has_gap_over_16h: Boolean(parsed.has_gap_over_16h),
                hours_since_last: parsed.hours_since_last,
                files: Array.isArray(parsed.files) ? parsed.files : [],
            };
        }
    } catch (_err) {
        // plain text summary
    }
    return { summary: text, has_gap_over_16h: false, files: [] };
}

function renderDmonAscChecklistHtml(rawValue) {
    const payload = parseDmonAscPayload(rawValue);
    const summaryEsc = escapeHtmlValue(payload.summary || 'N/A');
    const gapClass = payload.has_gap_over_16h ? ' alert alert-warning py-1 px-2 mb-2' : '';
    const files = [...(payload.files || [])].reverse();
    let listHtml = '';
    if (files.length) {
        listHtml = `<ul class="list-unstyled small mb-0 mt-1" id="dmon_asc_files_list">
            ${files.map((row) => {
                const gapOver = Boolean(row.gap_over_threshold);
                const gapText = row.gap_after_prev_hours != null
                    ? ` · gap ${Number(row.gap_after_prev_hours).toFixed(1)}h`
                    : '';
                const cls = gapOver ? 'text-danger fw-semibold' : 'text-muted';
                return `<li class="${cls}">
                    <span class="font-monospace">${escapeHtmlValue(row.fileName || '—')}</span>
                    <span class="ms-1">${escapeHtmlValue(row.dateTimeModified || '')}${escapeHtmlValue(gapText)}</span>
                </li>`;
            }).join('')}
        </ul>`;
    }
    return `<div class="dmon-asc-checklist-wrap">
        <div class="autofilled-value${gapClass}" id="dmon_asc_files_val">${summaryEsc}</div>
        ${listHtml}
    </div>`;
}

document.addEventListener('DOMContentLoaded', async () => {
    registerForceUtcTimeDisplayPlugin();
    if (!(await checkAuth())) return;

    const datasetId = document.body.dataset.datasetId;
    const editFormId = document.body.dataset.editFormId
        ? Number(document.body.dataset.editFormId)
        : null;

    const formTitle = document.getElementById('formTitle');
    const formDescription = document.getElementById('formDescription');
    const formSpinner = document.getElementById('formSpinner');
    const checklistForm = document.getElementById('slocumChecklistForm');
    const formSectionsContainer = document.getElementById('formSectionsContainer');
    const submissionStatus = document.getElementById('submissionStatus');
    const editModeBanner = document.getElementById('editModeBanner');
    const submitBtn = document.getElementById('submitChecklistBtn');
    const backLink = document.getElementById('backToDashboardLink');

    let currentSchema = null;
    let unverifiedModal = null;
    let plotModal = null;
    let plotChart = null;
    let activePlotItemId = null;
    let lastPlotRenderArgs = null;

    const modalEl = document.getElementById('unverifiedConfirmModal');
    if (modalEl && window.bootstrap) {
        unverifiedModal = new bootstrap.Modal(modalEl);
    }

    const plotModalEl = document.getElementById('checklistPlotModal');
    if (plotModalEl && window.bootstrap) {
        plotModal = new bootstrap.Modal(plotModalEl);
        plotModalEl.addEventListener('hidden.bs.modal', () => {
            applyPlotReviewToForm();
            destroyPlotChart();
            lastPlotRenderArgs = null;
            setPlotStatus('');
            activePlotItemId = null;
            const commentEl = document.getElementById('checklistPlotComment');
            const verifiedEl = document.getElementById('checklistPlotVerified');
            if (commentEl) commentEl.value = '';
            if (verifiedEl) verifiedEl.checked = false;
        });
        // Keep chart sized when the fullscreen modal finishes opening / window resizes
        plotModalEl.addEventListener('shown.bs.modal', () => {
            if (plotChart) plotChart.resize();
        });
        window.addEventListener('resize', () => {
            if (plotChart && plotModalEl.classList.contains('show')) plotChart.resize();
        });
        const themeObserver = new MutationObserver((mutations) => {
            const themeChanged = mutations.some(
                (m) => m.type === 'attributes'
                    && (m.attributeName === 'data-bs-theme' || m.attributeName === 'data-theme')
            );
            if (!themeChanged || !lastPlotRenderArgs || !plotModalEl.classList.contains('show')) return;
            setTimeout(() => {
                const args = lastPlotRenderArgs;
                if (!args) return;
                renderPlotChart(
                    args.label,
                    args.unit,
                    args.depthPts,
                    args.valuePts,
                    args.chartTitleLines,
                    args.extras,
                );
            }, 50);
        });
        themeObserver.observe(document.documentElement, {
            attributes: true,
            attributeFilter: ['data-bs-theme', 'data-theme'],
        });
    }

    if (!datasetId) {
        if (formSpinner) formSpinner.style.display = 'none';
        if (submissionStatus) {
            submissionStatus.innerHTML = '<div class="alert alert-danger">Missing dataset id.</div>';
        }
        return;
    }

    if (backLink) {
        const isHistorical = /_delayed$/.test(datasetId);
        backLink.href = isHistorical
            ? `/slocum/historical?dataset=${encodeURIComponent(datasetId)}`
            : `/slocum?dataset=${encodeURIComponent(datasetId)}`;
    }

    function escapeHtml(value) {
        if (value === null || value === undefined) return '';
        return String(value)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    function chartThemeColors() {
        const styles = getComputedStyle(document.documentElement);
        const pageText = styles.getPropertyValue('--text-color').trim() || '#212529';
        const pageBorder = styles.getPropertyValue('--card-border').trim() || '#dee2e6';
        const pageMuted = styles.getPropertyValue('--secondary-color').trim() || '#6c757d';
        const dropdownBg = styles.getPropertyValue('--dropdown-bg').trim() || '#212529';
        return {
            text: pageText,
            muted: pageMuted,
            border: pageBorder,
            depth: '#4dabf7',
            value: '#fd7e14',
            commanded: '#2f9e44',
            tooltipBg: dropdownBg,
        };
    }

    function nearestWholeDepthMeters(depthPts, dataIndex, timestamp) {
        if (Array.isArray(depthPts) && dataIndex >= 0 && dataIndex < depthPts.length) {
            const aligned = depthPts[dataIndex]?.y;
            if (aligned != null && !Number.isNaN(Number(aligned))) {
                return Math.round(Number(aligned));
            }
        }
        if (!timestamp || !Array.isArray(depthPts) || !depthPts.length) return null;
        const target = toUtcDate(timestamp)?.getTime();
        if (target == null || Number.isNaN(target)) return null;
        let best = null;
        let bestDelta = Infinity;
        for (const pt of depthPts) {
            if (pt?.y == null || Number.isNaN(Number(pt.y))) continue;
            const t = toUtcDate(pt.x)?.getTime();
            if (t == null || Number.isNaN(t)) continue;
            const delta = Math.abs(t - target);
            if (delta < bestDelta) {
                bestDelta = delta;
                best = Math.round(Number(pt.y));
            }
        }
        return best;
    }

    function destroyPlotChart() {
        if (plotChart) {
            plotChart.destroy();
            plotChart = null;
        }
    }

    function setPlotStatus(message, isError = false) {
        const el = document.getElementById('checklistPlotStatus');
        if (!el) return;
        el.textContent = message || '';
        el.classList.toggle('text-danger', !!isError);
        el.classList.toggle('text-muted', !isError);
    }

    function loadPlotReviewFromForm(itemId) {
        const commentEl = document.getElementById('checklistPlotComment');
        const verifiedEl = document.getElementById('checklistPlotVerified');
        const formComment = document.querySelector(`[name="${itemId}_comment"]`);
        const formVerified = document.getElementById(`${itemId}_verified`);
        if (commentEl) commentEl.value = formComment ? formComment.value : '';
        if (verifiedEl) verifiedEl.checked = formVerified ? !!formVerified.checked : false;
    }

    function applyPlotReviewToForm() {
        if (!activePlotItemId) return;
        const commentEl = document.getElementById('checklistPlotComment');
        const verifiedEl = document.getElementById('checklistPlotVerified');
        const formComment = document.querySelector(`[name="${activePlotItemId}_comment"]`);
        const formVerified = document.getElementById(`${activePlotItemId}_verified`);
        if (formComment && commentEl) formComment.value = commentEl.value;
        if (formVerified && verifiedEl) formVerified.checked = !!verifiedEl.checked;
    }

    function buildSavedItemsById(sectionsData) {
        const map = {};
        (sectionsData || []).forEach((section) => {
            (section.items || []).forEach((item) => {
                if (item && item.id) map[item.id] = item;
            });
        });
        return map;
    }

    function applySavedValuesToForm(savedItemsById, sectionsData) {
        Object.entries(savedItemsById).forEach(([id, item]) => {
            const el = document.getElementById(id);
            if (!el) return;
            const itemType = item.item_type || '';
            if (itemType === 'autofilled_value' || itemType === 'static_text') {
                // keep live/static display; restore verify + comment only
            } else if (el.tagName === 'SELECT' || el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') {
                if (item.value != null) el.value = item.value;
            }
            const commentEl = document.querySelector(`[name="${id}_comment"]`);
            if (commentEl && item.comment != null) commentEl.value = item.comment;
            const verifiedEl = document.getElementById(`${id}_verified`);
            if (verifiedEl && item.is_verified != null) verifiedEl.checked = !!item.is_verified;
            if (itemType === 'checkbox' && el.type === 'checkbox') {
                el.checked = !!item.is_checked;
            }
        });
        (sectionsData || []).forEach((section) => {
            if (!section?.id || section.section_comment == null) return;
            const sectionCommentEl = document.getElementById(`${section.id}_comment`);
            if (sectionCommentEl) sectionCommentEl.value = section.section_comment;
        });
    }

    function wirePlotButtons(root) {
        (root || document).querySelectorAll('[data-checklist-plot-item]').forEach((btn) => {
            btn.addEventListener('click', () => {
                const itemId = btn.getAttribute('data-checklist-plot-item');
                if (itemId) openChecklistPlot(itemId);
            });
        });
    }

    function parseGliderNameFromDatasetId(id) {
        const match = String(id || '').trim().match(/^([A-Za-z0-9]+)_(\d{8})_(\d+)(?:_(realtime|delayed))?$/i);
        if (match) return match[1];
        const fallback = String(id || '').trim().match(/^([A-Za-z0-9]+)_/);
        return fallback ? fallback[1] : (id || 'unknown');
    }

    function formatYYYYMMDD(isoOrDate) {
        if (isoOrDate == null || isoOrDate === '') return null;
        const d = toUtcDate(isoOrDate);
        if (!d) return null;
        const y = d.getUTCFullYear();
        const m = String(d.getUTCMonth() + 1).padStart(2, '0');
        const day = String(d.getUTCDate()).padStart(2, '0');
        return `${y}${m}${day}`;
    }

    function dataWindowYYYYMMDD(...seriesList) {
        const times = [];
        for (const series of seriesList) {
            for (const pt of series || []) {
                if (pt?.x == null) continue;
                const t = toUtcDate(pt.x)?.getTime();
                if (t != null && !Number.isNaN(t)) times.push(t);
            }
        }
        if (!times.length) return null;
        times.sort((a, b) => a - b);
        const start = formatYYYYMMDD(times[0]);
        const end = formatYYYYMMDD(times[times.length - 1]);
        if (!start || !end) return null;
        return start === end ? start : `${start}–${end}`;
    }

    function buildPlotHeading({ vehicleName, variableLabel, unit, windowLabel, commandedLabel, seriesLabels }) {
        let varBit;
        if (Array.isArray(seriesLabels) && seriesLabels.length) {
            varBit = seriesLabels.join(' / ');
        } else {
            varBit = unit ? `${variableLabel} (${unit})` : variableLabel;
            if (commandedLabel) {
                varBit += unit
                    ? ` / ${commandedLabel} (${unit})`
                    : ` / ${commandedLabel}`;
            }
        }
        const dateBit = windowLabel ? ` · ${windowLabel}` : '';
        return {
            modalTitle: `${vehicleName} · ${varBit}${dateBit}`,
            chartTitle: [
                `${vehicleName} · ${varBit}`,
                windowLabel ? `Data window (UTC): ${windowLabel}` : 'Data window (UTC): N/A',
            ],
        };
    }

    function mapSeriesPoints(rawPoints) {
        return (rawPoints || [])
            .map((p) => ({ x: toUtcDate(p.t), y: p.v }))
            .filter((p) => p.x != null);
    }

    function seriesAxisTitle(seriesList, axisId) {
        const matching = (seriesList || []).filter((s) => s.axis === axisId);
        if (!matching.length) return null;
        const parts = matching.map((s) => (s.unit ? `${s.label} (${s.unit})` : s.label));
        // Deduplicate identical titles
        return [...new Set(parts)].join(' / ');
    }

    async function openChecklistPlot(itemId) {
        if (!plotModal || typeof Chart === 'undefined') {
            showToast('Charting is unavailable in this browser session.', 'danger');
            return;
        }
        activePlotItemId = itemId;
        loadPlotReviewFromForm(itemId);
        const vehicleName = parseGliderNameFromDatasetId(datasetId);
        const titleEl = document.getElementById('checklistPlotModalLabel');
        if (titleEl) titleEl.textContent = `${vehicleName} · Loading plot…`;
        destroyPlotChart();
        setPlotStatus('Loading series…');
        plotModal.show();

        try {
            const payload = await apiRequest(
                `/api/slocum/checklists/${encodeURIComponent(datasetId)}/series?item_id=${encodeURIComponent(itemId)}`,
                'GET',
            );
            const label = payload.label || itemId;
            const unit = payload.unit || '';
            const commandedLabel = payload.commanded_label || null;
            const depthPts = mapSeriesPoints(payload.depth);
            const valuePts = mapSeriesPoints(payload.values);
            const commandedPts = mapSeriesPoints(payload.commanded);
            const multiSeries = (payload.series || []).map((s, idx) => ({
                id: s.id || s.column || `series_${idx}`,
                label: s.label || s.id || `series_${idx}`,
                unit: s.unit || '',
                axis: s.axis === 'y3' ? 'y3' : 'y2',
                points: mapSeriesPoints(s.points),
            }));

            const windowSeries = [depthPts, valuePts, commandedPts, ...multiSeries.map((s) => s.points)];
            const windowLabel = dataWindowYYYYMMDD(...windowSeries);
            const seriesLabels = multiSeries.length
                ? multiSeries.map((s) => (s.unit ? `${s.label} (${s.unit})` : s.label))
                : null;
            const heading = buildPlotHeading({
                vehicleName,
                variableLabel: label,
                unit,
                windowLabel,
                commandedLabel,
                seriesLabels,
            });
            if (titleEl) titleEl.textContent = heading.modalTitle;

            const depthValid = depthPts.filter((p) => p.y != null && !Number.isNaN(p.y)).length;
            const valueValid = valuePts.filter((p) => p.y != null && !Number.isNaN(p.y)).length;
            const commandedValid = commandedPts.filter((p) => p.y != null && !Number.isNaN(p.y)).length;
            const multiValidCounts = multiSeries.map((s) => ({
                label: s.label,
                n: s.points.filter((p) => p.y != null && !Number.isNaN(p.y)).length,
            }));
            const multiValidTotal = multiValidCounts.reduce((acc, s) => acc + s.n, 0);
            if (!depthValid && !valueValid && !commandedValid && !multiValidTotal) {
                setPlotStatus('No samples in the checklist window.', true);
                return;
            }

            let statusDetail;
            if (multiSeries.length) {
                statusDetail = multiValidCounts
                    .map((s) => `${s.n} ${s.label}`)
                    .join(' / ');
            } else {
                const cmdStatus = commandedLabel ? ` / ${commandedValid} commanded` : '';
                statusDetail = `${valueValid} measured${cmdStatus}`;
            }
            setPlotStatus(
                `${vehicleName} · ${windowLabel || 'no dates'} · `
                + `${statusDetail} / ${depthValid} depth sample(s) (full resolution)`,
            );
            renderPlotChart(label, unit, depthPts, valuePts, heading.chartTitle, {
                commandedPts,
                commandedLabel,
                multiSeries,
            });
        } catch (error) {
            setPlotStatus(`Failed to load plot: ${error.message}`, true);
            showToast(`Plot failed: ${error.message}`, 'danger');
        }
    }

    function renderPlotChart(label, unit, depthPts, valuePts, chartTitleLines = null, extras = {}) {
        lastPlotRenderArgs = { label, unit, depthPts, valuePts, chartTitleLines, extras };
        destroyPlotChart();
        const canvas = document.getElementById('checklistPlotCanvas');
        if (!canvas) return;
        const colors = chartThemeColors();
        const commandedPts = extras.commandedPts || [];
        const commandedLabel = extras.commandedLabel || null;
        const multiSeries = extras.multiSeries || [];
        const measuredAxisTitle = unit ? `${label} (${unit})` : label;
        const commandedAxisTitle = commandedLabel
            ? (unit ? `${commandedLabel} (${unit})` : commandedLabel)
            : null;
        const depthAxisTitle = 'Depth (m)';
        const y2Title = multiSeries.length
            ? (seriesAxisTitle(multiSeries, 'y2') || 'Value')
            : (commandedAxisTitle
                ? `${measuredAxisTitle} / ${commandedAxisTitle}`
                : measuredAxisTitle);
        const y3Title = multiSeries.length ? seriesAxisTitle(multiSeries, 'y3') : null;
        const titleText = Array.isArray(chartTitleLines) && chartTitleLines.length
            ? chartTitleLines
            : [`${y2Title}${y3Title ? ` · ${y3Title}` : ''}  ·  ${depthAxisTitle}`];

        const datasets = [
            {
                type: 'line',
                label: depthAxisTitle,
                data: depthPts,
                borderColor: colors.depth,
                backgroundColor: colors.depth,
                yAxisID: 'y',
                showLine: true,
                pointRadius: 0,
                pointHoverRadius: 0,
                borderWidth: 1.75,
                tension: 0.05,
                spanGaps: false,
                order: 3,
            },
        ];

        if (multiSeries.length) {
            multiSeries.forEach((s, idx) => {
                if (!s.points.length) return;
                const color = MULTI_SERIES_COLORS[idx % MULTI_SERIES_COLORS.length];
                const seriesLabel = s.unit ? `${s.label} (${s.unit})` : s.label;
                datasets.push({
                    type: 'scatter',
                    label: seriesLabel,
                    data: s.points,
                    borderColor: color,
                    backgroundColor: color,
                    pointBackgroundColor: color,
                    pointBorderColor: color,
                    yAxisID: s.axis === 'y3' ? 'y3' : 'y2',
                    pointRadius: 3.5,
                    pointHoverRadius: 6,
                    pointStyle: s.axis === 'y3' ? 'rectRot' : 'circle',
                    order: 1,
                });
            });
        } else {
            datasets.push({
                type: 'scatter',
                label: measuredAxisTitle,
                data: valuePts,
                borderColor: colors.value,
                backgroundColor: colors.value,
                pointBackgroundColor: colors.value,
                pointBorderColor: colors.value,
                yAxisID: 'y2',
                pointRadius: 3.5,
                pointHoverRadius: 6,
                order: 1,
            });
            if (commandedAxisTitle && commandedPts.length) {
                datasets.push({
                    type: 'scatter',
                    label: commandedAxisTitle,
                    data: commandedPts,
                    borderColor: colors.commanded,
                    backgroundColor: colors.commanded,
                    pointBackgroundColor: colors.commanded,
                    pointBorderColor: colors.commanded,
                    yAxisID: 'y2',
                    pointRadius: 3.5,
                    pointHoverRadius: 6,
                    pointStyle: 'triangle',
                    order: 2,
                });
            }
        }

        const chartOptions = {
            responsive: true,
            maintainAspectRatio: false,
            layout: {
                padding: { top: 8, right: y3Title ? 18 : 12, bottom: 4, left: 8 },
            },
            interaction: { mode: 'nearest', intersect: true, axis: 'xy' },
            plugins: {
                title: {
                    display: true,
                    text: titleText,
                    color: colors.text,
                    font: { size: 15, weight: '600' },
                    padding: { bottom: 10 },
                },
                legend: {
                    display: true,
                    position: 'top',
                    labels: {
                        color: colors.text,
                        usePointStyle: true,
                        pointStyle: 'rectRounded',
                        padding: 16,
                        font: { size: 13 },
                        generateLabels(chart) {
                            const dsList = chart.data.datasets || [];
                            return dsList.map((ds, i) => ({
                                text: ds.label || `Series ${i + 1}`,
                                fillStyle: ds.borderColor || ds.backgroundColor,
                                strokeStyle: ds.borderColor || ds.backgroundColor,
                                fontColor: colors.text,
                                hidden: !chart.isDatasetVisible(i),
                                datasetIndex: i,
                                pointStyle: ds.type === 'scatter'
                                    ? (ds.pointStyle || 'circle')
                                    : 'line',
                            }));
                        },
                    },
                },
                tooltip: {
                    backgroundColor: colors.tooltipBg,
                    titleColor: colors.text,
                    bodyColor: colors.text,
                    borderColor: colors.border,
                    borderWidth: 1,
                    callbacks: {
                        title(items) {
                            const ts = items?.[0]?.parsed?.x;
                            if (ts == null) return '';
                            return formatUtcDateTime(ts);
                        },
                        label(ctx) {
                            const v = ctx.parsed?.y;
                            const name = ctx.dataset.label || 'Value';
                            if (v == null || Number.isNaN(v)) return `${name}: N/A`;

                            if (
                                ctx.dataset.type === 'scatter'
                                || ctx.dataset.yAxisID === 'y2'
                                || ctx.dataset.yAxisID === 'y3'
                            ) {
                                const depthM = nearestWholeDepthMeters(
                                    depthPts,
                                    -1,
                                    ctx.parsed?.x ?? ctx.raw?.x,
                                );
                                const depthBit = depthM == null ? 'Depth: N/A' : `Depth: ${depthM} m`;
                                return [
                                    `${name}: ${Number(v).toFixed(3)}`,
                                    depthBit,
                                ];
                            }

                            return `${name}: ${Math.round(Number(v))} m`;
                        },
                    },
                },
            },
            scales: {
                x: {
                    ...buildUtcTimeScaleX({
                        tickColor: colors.muted,
                        gridColor: colors.border,
                        titleColor: colors.text,
                        titleText: 'Time (UTC)',
                    }),
                    title: {
                        display: true,
                        text: 'Time (UTC)',
                        color: colors.text,
                        font: { size: 13, weight: '600' },
                        padding: { top: 8 },
                    },
                    ticks: { color: colors.muted, maxRotation: 0 },
                    grid: { color: colors.border },
                },
                y: {
                    type: 'linear',
                    position: 'left',
                    reverse: true,
                    title: {
                        display: true,
                        text: depthAxisTitle,
                        color: colors.depth,
                        font: { size: 13, weight: '600' },
                    },
                    ticks: { color: colors.depth },
                    grid: { color: colors.border },
                },
                y2: {
                    type: 'linear',
                    position: 'right',
                    title: {
                        display: true,
                        text: y2Title,
                        color: colors.value,
                        font: { size: 13, weight: '600' },
                    },
                    ticks: { color: colors.value },
                    grid: { drawOnChartArea: false },
                },
            },
        };
        if (y3Title) {
            chartOptions.scales.y3 = {
                type: 'linear',
                position: 'right',
                offset: true,
                title: {
                    display: true,
                    text: y3Title,
                    color: MULTI_SERIES_COLORS[3],
                    font: { size: 13, weight: '600' },
                },
                ticks: { color: MULTI_SERIES_COLORS[3] },
                grid: { drawOnChartArea: false },
            };
        }
        applyTimeAxisZoom(chartOptions);

        plotChart = new Chart(canvas.getContext('2d'), {
            data: { datasets },
            options: chartOptions,
        });
    }

    const resetZoomBtn = document.getElementById('checklistPlotResetZoomBtn');
    bindResetZoomButton(resetZoomBtn, () => plotChart);

    const plotZoomHint = document.getElementById('checklistPlotZoomHint');
    if (plotZoomHint) plotZoomHint.textContent = CHART_ZOOM_HINT;

    function renderSchema(schema, savedSubmission = null) {
        currentSchema = schema;
        if (formTitle) formTitle.textContent = schema.title || 'Slocum Daily Checklist';
        if (formDescription) formDescription.textContent = schema.description || '';
        formSectionsContainer.innerHTML = '';

        (schema.sections || []).forEach((section) => {
            const sectionDiv = document.createElement('div');
            sectionDiv.className = 'form-section';
            sectionDiv.dataset.sectionId = section.id;
            sectionDiv.innerHTML = `<h3 class="h5 mb-3">${section.title || section.id}</h3>`;

            (section.items || []).forEach((item) => {
                const itemDiv = document.createElement('div');
                itemDiv.className = 'form-item mb-3';
                itemDiv.dataset.itemId = item.id;

                let inputHtml = '';
                let labelContent = `${escapeHtml(item.label || item.id)}${item.required ? '<span class="text-danger">*</span>' : ''}`;
                const value = item.value != null && item.value !== '' ? item.value : '';
                const valueEsc = escapeHtml(value);
                const placeholderEsc = escapeHtml(item.placeholder || '');
                const isPlottable = item.item_type === 'autofilled_value' && PLOTTABLE_ITEM_IDS.has(item.id);

                switch (item.item_type) {
                    case 'autofilled_value':
                        if (item.id === 'dmon_asc_files_val') {
                            inputHtml = renderDmonAscChecklistHtml(value);
                        } else {
                            inputHtml = isPlottable
                                ? `<div class="checklist-plot-wrap">
                                <div class="autofilled-value" id="${item.id}">${valueEsc || 'N/A'}</div>
                                <button type="button" class="btn btn-outline-secondary btn-sm checklist-plot-btn"
                                    data-checklist-plot-item="${escapeHtml(item.id)}" title="Plot over time with depth">
                                    Plot
                                </button>
                               </div>`
                                : `<div class="autofilled-value" id="${item.id}">${valueEsc || 'N/A'}</div>`;
                        }
                        break;
                    case 'static_text':
                        inputHtml = `<div class="static-text" id="${item.id}">${valueEsc || '—'}</div>`;
                        break;
                    case 'text_input':
                        inputHtml = `<input type="text" class="form-control" id="${item.id}" name="${item.id}" value="${valueEsc}" placeholder="${placeholderEsc}" ${item.required ? 'required' : ''}>`;
                        break;
                    case 'text_area':
                        inputHtml = `<textarea class="form-control" id="${item.id}" name="${item.id}" rows="3" placeholder="${placeholderEsc}" ${item.required ? 'required' : ''}>${valueEsc}</textarea>`;
                        break;
                    case 'dropdown': {
                        const options = (item.options || [])
                            .map((opt) => {
                                const optEsc = escapeHtml(opt);
                                return `<option value="${optEsc}" ${value === opt ? 'selected' : ''}>${optEsc}</option>`;
                            })
                            .join('');
                        inputHtml = `<select class="form-select" id="${item.id}" name="${item.id}" ${item.required ? 'required' : ''}>
                            <option value="" ${!value ? 'selected' : ''} disabled>Select…</option>
                            ${options}
                        </select>`;
                        break;
                    }
                    case 'checkbox':
                        inputHtml = `<div class="form-check">
                            <input class="form-check-input" type="checkbox" id="${item.id}" name="${item.id}" ${item.is_checked ? 'checked' : ''}>
                            <label class="form-check-label" for="${item.id}">Checked</label>
                        </div>`;
                        break;
                    default:
                        inputHtml = `<input type="text" class="form-control" id="${item.id}" name="${item.id}" value="${value}">`;
                }

                const showItemComment = item.item_type !== 'text_area';
                const showVerified = item.item_type === 'autofilled_value' || item.item_type === 'static_text';

                itemDiv.innerHTML = `
                    <div class="row align-items-center">
                        <div class="col-md-3">
                            <label for="${item.id}" class="form-label mb-0">${labelContent}</label>
                        </div>
                        <div class="col-md-4">${inputHtml}</div>
                        <div class="col-md-3">
                            ${showItemComment ? `<textarea class="form-control form-control-sm" name="${item.id}_comment" rows="1" placeholder="Comment..."></textarea>` : ''}
                        </div>
                        <div class="col-md-2">
                            ${showVerified ? `
                            <div class="form-check">
                                <input class="form-check-input" type="checkbox" id="${item.id}_verified" name="${item.id}_verified" value="true">
                                <label class="form-check-label" for="${item.id}_verified">Verified</label>
                            </div>` : ''}
                        </div>
                    </div>
                `;
                sectionDiv.appendChild(itemDiv);
            });

            if (section.section_comment != null) {
                const notes = document.createElement('div');
                notes.className = 'mt-3';
                notes.innerHTML = `
                    <label for="${section.id}_comment" class="form-label">Section Notes:</label>
                    <textarea class="form-control" id="${section.id}_comment" name="${section.id}_comment" rows="2" placeholder="Overall notes for this section...">${section.section_comment || ''}</textarea>
                `;
                sectionDiv.appendChild(notes);
            }

            formSectionsContainer.appendChild(sectionDiv);
        });

        wirePlotButtons(formSectionsContainer);

        checklistForm.style.display = 'block';
        if (formSpinner) formSpinner.style.display = 'none';

        if (savedSubmission) {
            applySavedValuesToForm(
                buildSavedItemsById(savedSubmission.sections_data),
                savedSubmission.sections_data,
            );
            if (editModeBanner) {
                editModeBanner.style.display = 'block';
                editModeBanner.textContent = `Editing submission #${savedSubmission.id} by ${savedSubmission.submitted_by_username || 'unknown'}. Save will update this record.`;
            }
            if (submitBtn) submitBtn.textContent = 'Save Changes';
        }
    }

    function buildSectionsDataFromForm() {
        if (!currentSchema) return [];
        return (currentSchema.sections || []).map((section) => {
            const sectionCommentEl = document.getElementById(`${section.id}_comment`);
            const items = (section.items || []).map((item) => {
                const el = document.getElementById(item.id);
                const verifiedEl = document.getElementById(`${item.id}_verified`);
                const commentEl = document.querySelector(`[name="${item.id}_comment"]`);
                let value = null;
                let isChecked = null;
                if (item.item_type === 'autofilled_value' || item.item_type === 'static_text') {
                    value = el ? el.textContent : item.value;
                } else if (item.item_type === 'checkbox') {
                    isChecked = el ? el.checked : false;
                    value = isChecked ? 'true' : 'false';
                } else if (el) {
                    value = el.value;
                }
                return {
                    id: item.id,
                    label: item.label,
                    item_type: item.item_type,
                    value,
                    is_checked: isChecked,
                    is_verified: verifiedEl ? verifiedEl.checked : null,
                    comment: commentEl ? commentEl.value : null,
                    required: !!item.required,
                    options: item.options || null,
                    placeholder: item.placeholder || null,
                };
            });
            return {
                id: section.id,
                title: section.title,
                items,
                section_comment: sectionCommentEl ? sectionCommentEl.value : section.section_comment,
            };
        });
    }

    function countUnverified(sectionsData) {
        let count = 0;
        (sectionsData || []).forEach((section) => {
            (section.items || []).forEach((item) => {
                if (
                    (item.item_type === 'autofilled_value' || item.item_type === 'static_text')
                    && item.is_verified === false
                ) {
                    count += 1;
                }
            });
        });
        return count;
    }

    async function performSubmission(sectionsData) {
        if (submissionStatus) submissionStatus.innerHTML = '';
        const payload = {
            mission_id: datasetId,
            form_type: currentSchema?.form_type || 'slocum_daily_checklist',
            form_title: currentSchema?.title || 'Slocum Daily Pilot Checklist',
            sections_data: sectionsData,
        };
        try {
            if (editFormId) {
                await apiRequest(`/api/slocum/checklists/id/${editFormId}`, 'PUT', payload);
                showToast('Checklist updated.', 'success');
            } else {
                await apiRequest(`/api/slocum/checklists/${encodeURIComponent(datasetId)}`, 'POST', payload);
                showToast('Checklist submitted.', 'success');
            }
            window.location.href = backLink?.href || `/slocum?dataset=${encodeURIComponent(datasetId)}`;
        } catch (error) {
            if (submissionStatus) {
                submissionStatus.innerHTML = `<div class="alert alert-danger">Failed to save: ${error.message}</div>`;
            }
            showToast(`Failed to save checklist: ${error.message}`, 'danger');
        }
    }

    async function fetchAndRender() {
        if (formSpinner) formSpinner.style.display = 'block';
        checklistForm.style.display = 'none';
        try {
            const schema = await apiRequest(
                `/api/slocum/checklists/${encodeURIComponent(datasetId)}/template`,
                'GET',
            );
            let saved = null;
            if (editFormId) {
                saved = await apiRequest(`/api/slocum/checklists/id/${editFormId}`, 'GET');
            }
            renderSchema(schema, saved);
        } catch (error) {
            if (formSpinner) formSpinner.style.display = 'none';
            if (submissionStatus) {
                submissionStatus.innerHTML = `<div class="alert alert-danger">Failed to load checklist: ${error.message}</div>`;
            }
        }
    }

    const refreshBtn = document.getElementById('refreshFormDataBtn');
    if (refreshBtn) {
        refreshBtn.addEventListener('click', async () => {
            refreshBtn.disabled = true;
            const original = refreshBtn.textContent;
            refreshBtn.textContent = 'Refreshing…';
            try {
                const schema = await apiRequest(
                    `/api/slocum/checklists/${encodeURIComponent(datasetId)}/sfmc-refresh`,
                    'POST',
                );
                currentSchema = schema;
                let updated = 0;
                for (const section of schema.sections || []) {
                    for (const item of section.items || []) {
                        if (!item.id) continue;
                        const el = document.getElementById(item.id);
                        if (!el) continue;
                        const value = item.value != null && item.value !== '' ? String(item.value) : '';
                        if (
                            item.item_type === 'autofilled_value'
                            || item.item_type === 'static_text'
                        ) {
                            if (item.id === 'dmon_asc_files_val') {
                                const wrap = el.closest('.dmon-asc-checklist-wrap')
                                    || el.parentElement;
                                if (wrap) {
                                    wrap.outerHTML = renderDmonAscChecklistHtml(value);
                                    updated += 1;
                                }
                                continue;
                            }
                            if (
                                el.classList.contains('autofilled-value')
                                || el.classList.contains('static-text')
                            ) {
                                el.textContent = value || 'N/A';
                                updated += 1;
                            }
                            continue;
                        }
                        if (
                            item.item_type === 'text_input'
                            || item.item_type === 'text_area'
                            || item.item_type === 'dropdown'
                        ) {
                            if ('value' in el) {
                                el.value = value;
                                updated += 1;
                            }
                        }
                    }
                }
                // Refresh mission_status section comment (SFMC freshness note).
                for (const section of schema.sections || []) {
                    if (section.id !== 'mission_status' || !section.section_comment) continue;
                    const commentEl = document.querySelector(
                        `[data-section-id="mission_status"] .section-comment, #mission_status .section-comment`,
                    );
                    if (commentEl) commentEl.textContent = section.section_comment;
                }
                showToast(`Refreshed ${updated} field(s) (including SFMC).`, 'success');
            } catch (error) {
                showToast(`Refresh failed: ${error.message}`, 'danger');
            } finally {
                refreshBtn.disabled = false;
                refreshBtn.textContent = original;
            }
        });
    }

    checklistForm.addEventListener('submit', async (event) => {
        event.preventDefault();
        const sectionsData = buildSectionsDataFromForm();
        const unverified = countUnverified(sectionsData);
        if (unverified > 0 && unverifiedModal) {
            const submitAnyway = document.getElementById('unverifiedSubmitBtn');
            const cancelBtn = document.getElementById('unverifiedCancelSubmissionBtn');
            const onSubmit = () => {
                unverifiedModal.hide();
                performSubmission(sectionsData);
                cleanup();
            };
            const onCancel = () => {
                unverifiedModal.hide();
                cleanup();
            };
            function cleanup() {
                submitAnyway?.removeEventListener('click', onSubmit);
                cancelBtn?.removeEventListener('click', onCancel);
            }
            submitAnyway?.addEventListener('click', onSubmit);
            cancelBtn?.addEventListener('click', onCancel);
            unverifiedModal.show();
            return;
        }
        await performSubmission(sectionsData);
    });

    await fetchAndRender();
});
