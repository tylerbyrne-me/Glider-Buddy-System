/**
 * Platform-agnostic Chart.js background overlay helpers (e.g. depth behind a sensor series).
 * Mark datasets with isBackgroundOverlay so tooltips/legend can filter them.
 */

export const DEFAULT_OVERLAY_COLOR = 'rgba(108, 117, 125, 0.85)';
export const DEFAULT_DEPTH_OVERLAY_LABEL = 'Depth (m)';
export const DEFAULT_OVERLAY_AXIS_ID = 'yDepth';

/** Chart.js interaction mode: nearest-in-x per visible non-overlay dataset. */
export const NEAREST_X_BY_DATASET_MODE = 'nearestXByDataset';

let nearestXByDatasetRegistered = false;

/**
 * @param {unknown} value
 * @returns {string | null}
 */
export function formatOverlayMeters(value) {
    if (value == null || !Number.isFinite(Number(value))) return null;
    return `${Number(value).toFixed(1)} m`;
}

/**
 * Nearest overlay y-value at the hovered x time (ms).
 * @param {import('chart.js').Chart | null | undefined} chart
 * @param {number} xMs
 * @returns {number | null}
 */
export function nearestOverlayValue(chart, xMs) {
    if (!chart?.data?.datasets || xMs == null || !Number.isFinite(xMs)) return null;
    const overlayDs = chart.data.datasets.find(
        (ds) => ds && (ds.isBackgroundOverlay || ds.isDepthOverlay),
    );
    if (!overlayDs || !Array.isArray(overlayDs.data) || !overlayDs.data.length) return null;
    let best = null;
    let bestDist = Infinity;
    overlayDs.data.forEach((pt) => {
        if (!pt || pt.x == null || pt.y == null || !Number.isFinite(Number(pt.y))) return;
        const px = pt.x instanceof Date ? pt.x.getTime() : new Date(pt.x).getTime();
        if (!Number.isFinite(px)) return;
        const dist = Math.abs(px - xMs);
        if (dist < bestDist) {
            bestDist = dist;
            best = Number(pt.y);
        }
    });
    return best;
}

/**
 * @param {Record<string, unknown> | null | undefined} dataset
 * @returns {boolean}
 */
function isOverlayDataset(dataset) {
    return !!(dataset?.isBackgroundOverlay || dataset?.isDepthOverlay);
}

/**
 * Register Chart.js interaction mode that pairs series by time (pixel X), not array index.
 * Idempotent — safe to call from multiple page modules.
 */
export function registerNearestXByDatasetInteractionMode() {
    if (nearestXByDatasetRegistered) return;
    if (typeof Chart === 'undefined' || !Chart.Interaction?.modes) return;
    if (typeof Chart.Interaction.modes[NEAREST_X_BY_DATASET_MODE] === 'function') {
        nearestXByDatasetRegistered = true;
        return;
    }

    const getRelativePosition = Chart.helpers?.getRelativePosition;
    if (typeof getRelativePosition !== 'function') return;

    Chart.Interaction.modes[NEAREST_X_BY_DATASET_MODE] = function nearestXByDataset(
        chart,
        e,
        _options,
        useFinalPosition,
    ) {
        const position = getRelativePosition(e, chart);
        if (!position || !Number.isFinite(position.x)) return [];

        const area = chart.chartArea;
        if (!area) return [];
        const items = [];

        chart.data.datasets.forEach((dataset, datasetIndex) => {
            if (!dataset || isOverlayDataset(dataset)) return;
            if (!chart.isDatasetVisible(datasetIndex)) return;
            const meta = chart.getDatasetMeta(datasetIndex);
            if (!meta || meta.hidden) return;

            let bestIndex = -1;
            let bestDist = Infinity;
            const elements = meta.data || [];
            for (let index = 0; index < elements.length; index += 1) {
                const el = elements[index];
                if (!el || el.skip) continue;
                const px = useFinalPosition && typeof el.getProps === 'function'
                    ? el.getProps(['x'], true).x
                    : el.x;
                if (!Number.isFinite(px)) continue;
                // Only consider points inside the visible chart area (critical when zoomed).
                if (px < area.left || px > area.right) continue;
                const dist = Math.abs(px - position.x);
                if (dist < bestDist) {
                    bestDist = dist;
                    bestIndex = index;
                }
            }
            if (bestIndex >= 0) {
                items.push({
                    datasetIndex,
                    index: bestIndex,
                    element: elements[bestIndex],
                });
            }
        });

        return items;
    };

    nearestXByDatasetRegistered = true;
}

/**
 * Shared interaction options for time-series charts (keep in sync with tooltip mode).
 * @returns {Record<string, unknown>}
 */
export function buildTimeSeriesInteractionOptions() {
    registerNearestXByDatasetInteractionMode();
    return {
        mode: NEAREST_X_BY_DATASET_MODE,
        intersect: false,
        axis: 'x',
    };
}

/**
 * @param {{
 *   points: Array<{ x: Date | number, y: number }>,
 *   label?: string,
 *   color?: string,
 *   yAxisID?: string,
 * }} opts
 * @returns {Record<string, unknown>}
 */
export function buildBackgroundOverlayDataset(opts) {
    const {
        points,
        label = DEFAULT_DEPTH_OVERLAY_LABEL,
        color = DEFAULT_OVERLAY_COLOR,
        yAxisID = DEFAULT_OVERLAY_AXIS_ID,
    } = opts || {};
    return {
        type: 'line',
        label,
        data: points || [],
        borderColor: color,
        backgroundColor: color,
        yAxisID,
        isBackgroundOverlay: true,
        pointRadius: 0,
        pointHoverRadius: 0,
        pointHitRadius: 0,
        showLine: true,
        borderWidth: 1.5,
        tension: 0.15,
        fill: false,
    };
}

/**
 * Hidden secondary axis for background overlays.
 * @param {string} [yAxisID]
 * @param {{ reverse?: boolean }} [opts]
 * @returns {Record<string, unknown>}
 */
export function buildHiddenOverlayScale(_yAxisID = DEFAULT_OVERLAY_AXIS_ID, opts = {}) {
    return {
        type: 'linear',
        position: 'left',
        display: false,
        reverse: opts.reverse !== false,
        grid: { drawOnChartArea: false },
    };
}

/**
 * Tooltip: time-align series (not index); hide overlay rows; append nearest Depth.
 * @param {{ overlayLabel?: string }} [opts]
 * @returns {Record<string, unknown>}
 */
export function buildOverlayAwareTooltipOptions(opts = {}) {
    const overlayLabel = opts.overlayLabel || 'Depth';
    registerNearestXByDatasetInteractionMode();
    return {
        mode: NEAREST_X_BY_DATASET_MODE,
        intersect: false,
        axis: 'x',
        position: 'nearest',
        filter(tooltipItem) {
            const ds = tooltipItem?.dataset;
            return !isOverlayDataset(ds);
        },
        callbacks: {
            afterBody(tooltipItems) {
                if (!tooltipItems?.length) return [];
                const chart = tooltipItems[0].chart;
                const xMs = tooltipItems[0].parsed?.x;
                const value = nearestOverlayValue(chart, xMs);
                const formatted = formatOverlayMeters(value);
                if (!formatted) return [];
                return [`${overlayLabel}: ${formatted}`];
            },
        },
    };
}

/**
 * Legend label filter that hides background overlays.
 * @param {{ text?: string, datasetIndex?: number }} item
 * @param {{ datasets?: Array<Record<string, unknown>> }} chartData
 * @returns {boolean}
 */
export function filterOverlayFromLegend(item, chartData) {
    const ds = chartData?.datasets?.[item.datasetIndex];
    return !isOverlayDataset(ds);
}

/**
 * @param {string} storagePrefix
 * @param {string} canvasId
 * @returns {boolean}
 */
export function getOverlayEnabledForCanvas(storagePrefix, canvasId) {
    if (!storagePrefix || !canvasId) return false;
    try {
        return localStorage.getItem(`${storagePrefix}${canvasId}`) === '1';
    } catch (_) {
        return false;
    }
}

/**
 * @param {string} storagePrefix
 * @param {string} canvasId
 * @param {boolean} enabled
 */
export function setOverlayEnabledForCanvas(storagePrefix, canvasId, enabled) {
    if (!storagePrefix || !canvasId) return;
    try {
        localStorage.setItem(`${storagePrefix}${canvasId}`, enabled ? '1' : '0');
    } catch (_) { /* ignore */ }
}

/**
 * Wire overlay toggle checkboxes.
 * @param {{
 *   checkboxSelector?: string,
 *   storagePrefix: string,
 *   onChange?: (canvasId: string, enabled: boolean) => void,
 * }} opts
 */
export function bindOverlayToggleControls(opts) {
    const {
        checkboxSelector = '.chart-depth-overlay',
        storagePrefix,
        onChange,
    } = opts || {};
    if (!storagePrefix) return;
    document.querySelectorAll(checkboxSelector).forEach((checkbox) => {
        const canvasId = checkbox.dataset.canvasId;
        if (!canvasId) return;
        checkbox.checked = getOverlayEnabledForCanvas(storagePrefix, canvasId);
        checkbox.addEventListener('change', () => {
            setOverlayEnabledForCanvas(storagePrefix, canvasId, checkbox.checked);
            if (typeof onChange === 'function') onChange(canvasId, checkbox.checked);
        });
    });
}
