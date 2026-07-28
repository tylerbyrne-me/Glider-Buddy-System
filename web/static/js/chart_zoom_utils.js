/**
 * Platform-agnostic Chart.js time-axis zoom/pan helpers.
 * Requires hammer.js + chartjs-plugin-zoom on the page (see _chart_zoom_scripts.html).
 * Safe to import when the plugin is absent — apply helpers no-op.
 */

export const CHART_ZOOM_HINT =
    'Ctrl+scroll to zoom · drag to pan · Reset zoom restores the full window.';

/**
 * Default plugins.zoom config for time-series charts (X-axis only).
 * Wheel zoom requires Ctrl so page scroll still works on multi-chart pages.
 * @param {Record<string, unknown>} [overrides]
 * @returns {Record<string, unknown>}
 */
export function buildTimeAxisZoomOptions(overrides = {}) {
    const base = {
        limits: {
            x: { min: 'original', max: 'original' },
        },
        pan: {
            enabled: true,
            mode: 'x',
        },
        zoom: {
            wheel: { enabled: true, modifierKey: 'ctrl' },
            pinch: { enabled: true },
            mode: 'x',
        },
    };
    return deepMergeZoom(base, overrides || {});
}

/**
 * @returns {boolean}
 */
export function isChartZoomPluginAvailable() {
    try {
        const Chart = typeof window !== 'undefined' ? window.Chart : undefined;
        if (!Chart) return false;
        if (typeof Chart.getChart === 'function' && Chart.registry?.plugins?.get) {
            return !!Chart.registry.plugins.get('zoom');
        }
        // Fallback: resetZoom appears on chart instances once plugin is registered
        return !!(Chart.defaults?.plugins && Object.prototype.hasOwnProperty.call(Chart.defaults.plugins, 'zoom'));
    } catch (_) {
        return false;
    }
}

/**
 * Merge time-axis zoom into Chart.js options. No-ops if the zoom plugin is not registered.
 * @param {Record<string, unknown>} chartOptions
 * @param {Record<string, unknown>} [overrides]
 * @returns {Record<string, unknown>}
 */
export function applyTimeAxisZoom(chartOptions, overrides = {}) {
    const options = chartOptions && typeof chartOptions === 'object' ? chartOptions : {};
    if (!isChartZoomPluginAvailable()) return options;
    if (!options.plugins || typeof options.plugins !== 'object') options.plugins = {};
    const existing = options.plugins.zoom && typeof options.plugins.zoom === 'object'
        ? options.plugins.zoom
        : {};
    options.plugins.zoom = deepMergeZoom(
        buildTimeAxisZoomOptions(),
        deepMergeZoom(existing, overrides || {}),
    );
    return options;
}

/**
 * @param {import('chart.js').Chart | null | undefined} chart
 */
export function resetChartZoom(chart) {
    if (chart && typeof chart.resetZoom === 'function') {
        chart.resetZoom();
    }
}

/**
 * Bind a Reset zoom control to a live Chart instance resolved via getChart().
 * @param {HTMLElement | null} button
 * @param {() => (import('chart.js').Chart | null | undefined)} getChart
 */
export function bindResetZoomButton(button, getChart) {
    if (!button || typeof getChart !== 'function') return;
    button.addEventListener('click', (event) => {
        event.preventDefault();
        resetChartZoom(getChart());
    });
}

function deepMergeZoom(target, source) {
    const out = { ...target };
    if (!source || typeof source !== 'object') return out;
    Object.keys(source).forEach((key) => {
        const srcVal = source[key];
        const tgtVal = out[key];
        if (
            srcVal
            && typeof srcVal === 'object'
            && !Array.isArray(srcVal)
            && tgtVal
            && typeof tgtVal === 'object'
            && !Array.isArray(tgtVal)
        ) {
            out[key] = deepMergeZoom(tgtVal, srcVal);
        } else {
            out[key] = srcVal;
        }
    });
    return out;
}
