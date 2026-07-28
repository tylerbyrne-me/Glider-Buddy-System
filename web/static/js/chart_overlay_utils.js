/**
 * Platform-agnostic Chart.js background overlay helpers (e.g. depth behind a sensor series).
 * Mark datasets with isBackgroundOverlay so tooltips/legend can filter them.
 */

export const DEFAULT_OVERLAY_COLOR = 'rgba(108, 117, 125, 0.85)';
export const DEFAULT_DEPTH_OVERLAY_LABEL = 'Depth (m)';
export const DEFAULT_OVERLAY_AXIS_ID = 'yDepth';

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
 * Tooltip: hide overlay series rows; append "Label: X.Xm" from nearest overlay point.
 * @param {{ overlayLabel?: string }} [opts]
 * @returns {Record<string, unknown>}
 */
export function buildOverlayAwareTooltipOptions(opts = {}) {
    const overlayLabel = opts.overlayLabel || 'Depth';
    return {
        mode: 'index',
        intersect: false,
        filter(tooltipItem) {
            const ds = tooltipItem?.dataset;
            return !(ds?.isBackgroundOverlay || ds?.isDepthOverlay);
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
    return !(ds?.isBackgroundOverlay || ds?.isDepthOverlay);
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
