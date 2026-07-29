/**
 * Platform-agnostic Chart.js plot style (line / line+scatter / scatter) helpers.
 * Storage prefix is required so Slocum and Wave Glider prefs stay separate.
 */

export const PLOT_STYLES = Object.freeze(['line', 'line_scatter', 'scatter']);

/** Invisible hit pad around markers / line samples for easier hover targeting. */
export const DEFAULT_POINT_HIT_RADIUS = 12;

/**
 * @param {string} style
 * @param {boolean} [isBar]
 * @returns {{ showLine: boolean, pointRadius: number, pointHitRadius: number }}
 */
export function plotStyleDatasetProps(style, isBar = false) {
    if (isBar) {
        return { showLine: true, pointRadius: 0, pointHitRadius: DEFAULT_POINT_HIT_RADIUS };
    }
    if (style === 'scatter') {
        return { showLine: false, pointRadius: 2.5, pointHitRadius: DEFAULT_POINT_HIT_RADIUS };
    }
    if (style === 'line_scatter') {
        return { showLine: true, pointRadius: 2.5, pointHitRadius: DEFAULT_POINT_HIT_RADIUS };
    }
    return { showLine: true, pointRadius: 0, pointHitRadius: DEFAULT_POINT_HIT_RADIUS };
}

/**
 * @param {string} storagePrefix
 * @param {string} canvasId
 * @returns {'line' | 'line_scatter' | 'scatter'}
 */
export function getPlotStyleForCanvas(storagePrefix, canvasId) {
    if (!storagePrefix || !canvasId) return 'line';
    try {
        const stored = localStorage.getItem(`${storagePrefix}${canvasId}`);
        if (PLOT_STYLES.includes(stored)) return stored;
    } catch (_) { /* ignore */ }
    return 'line';
}

/**
 * @param {string} storagePrefix
 * @param {string} canvasId
 * @param {string} style
 */
export function setPlotStyleForCanvas(storagePrefix, canvasId, style) {
    if (!storagePrefix || !canvasId) return;
    const next = PLOT_STYLES.includes(style) ? style : 'line';
    try {
        localStorage.setItem(`${storagePrefix}${canvasId}`, next);
    } catch (_) { /* ignore */ }
}

/**
 * Apply plot-style props onto datasets (skips background overlays and bars unless isBar).
 * @param {Array<Record<string, unknown>>} datasets
 * @param {string} storagePrefix
 * @param {string} canvasId
 * @returns {Array<Record<string, unknown>>}
 */
export function applyPlotStyleToDatasets(datasets, storagePrefix, canvasId) {
    const style = getPlotStyleForCanvas(storagePrefix, canvasId);
    (datasets || []).forEach((ds) => {
        if (!ds || ds.isBackgroundOverlay || ds.isDepthOverlay) return;
        const isBar = ds.type === 'bar';
        const props = plotStyleDatasetProps(style, isBar);
        ds.showLine = props.showLine;
        ds.pointRadius = props.pointRadius;
        ds.pointHitRadius = props.pointHitRadius;
        if (ds.pointHoverRadius == null && props.pointRadius) {
            ds.pointHoverRadius = props.pointRadius + 1.5;
        } else if (ds.pointHoverRadius == null) {
            ds.pointHoverRadius = 3;
        }
    });
    return datasets;
}

/**
 * Wire plot-style <select> controls.
 * @param {{
 *   selectSelector?: string,
 *   storagePrefix: string,
 *   onChange?: (canvasId: string, style: string) => void,
 * }} opts
 */
export function bindPlotStyleControls(opts) {
    const {
        selectSelector = '.chart-plot-style',
        storagePrefix,
        onChange,
    } = opts || {};
    if (!storagePrefix) return;
    document.querySelectorAll(selectSelector).forEach((select) => {
        const canvasId = select.dataset.canvasId;
        if (!canvasId) return;
        select.value = getPlotStyleForCanvas(storagePrefix, canvasId);
        select.addEventListener('change', () => {
            setPlotStyleForCanvas(storagePrefix, canvasId, select.value);
            if (typeof onChange === 'function') onChange(canvasId, select.value);
        });
    });
}
