/**
 * Shared Chart.js hover defaults for dashboard time-series and profile charts.
 * Apply via these helpers so new sensors/charts inherit crosshair, hit targets,
 * and time-aligned tooltips without per-chart copy/paste.
 */

import {
    buildOverlayAwareTooltipOptions,
    buildTimeSeriesInteractionOptions,
    registerNearestXByDatasetInteractionMode,
} from '/static/js/chart_overlay_utils.js';
import { timeSeriesCrosshairPlugin } from '/static/js/chart_crosshair_plugin.js';
import { DEFAULT_POINT_HIT_RADIUS } from '/static/js/chart_plot_style_utils.js';

/**
 * Ensure non-overlay datasets have a usable invisible hit pad.
 * @param {Array<Record<string, unknown>> | null | undefined} datasets
 * @param {number} [hitRadius]
 * @returns {Array<Record<string, unknown>>}
 */
export function ensureDatasetHitRadius(datasets, hitRadius = DEFAULT_POINT_HIT_RADIUS) {
    (datasets || []).forEach((ds) => {
        if (!ds || ds.isBackgroundOverlay || ds.isDepthOverlay) return;
        if (ds.pointHitRadius == null) ds.pointHitRadius = hitRadius;
    });
    return datasets || [];
}

/**
 * Platform default hover for multi-series time charts (Slocum Flight/Power/…, WG cards, future DO).
 * Mutates chartOptions; returns plugins to pass to `new Chart(..., { plugins })`.
 *
 * @param {Record<string, unknown>} chartOptions
 * @param {{
 *   overlayTooltip?: { overlayLabel?: string },
 *   tooltip?: Record<string, unknown> | false,
 *   includeCrosshair?: boolean,
 *   extraPlugins?: unknown[],
 * }} [opts]
 * @returns {{ options: Record<string, unknown>, plugins: unknown[] }}
 */
export function applyTimeSeriesHoverDefaults(chartOptions, opts = {}) {
    registerNearestXByDatasetInteractionMode();
    const options = chartOptions && typeof chartOptions === 'object' ? chartOptions : {};
    if (!options.plugins || typeof options.plugins !== 'object') options.plugins = {};

    options.interaction = buildTimeSeriesInteractionOptions();

    if (opts.tooltip === false) {
        // Caller owns tooltip config entirely.
    } else if (opts.tooltip && typeof opts.tooltip === 'object') {
        options.plugins.tooltip = opts.tooltip;
    } else {
        // Replace index-mode tooltips; keep depth-aware afterBody when present.
        options.plugins.tooltip = buildOverlayAwareTooltipOptions(opts.overlayTooltip || {});
    }

    const plugins = [];
    if (opts.includeCrosshair !== false) plugins.push(timeSeriesCrosshairPlugin);
    if (Array.isArray(opts.extraPlugins)) plugins.push(...opts.extraPlugins);

    return { options, plugins };
}

/**
 * Hover defaults for depth-vs-time profile scatter (CTD, future profile sensors).
 * Keeps 2D nearest targeting so depth discrimination still works; adds crosshair + hit pad.
 *
 * @param {Record<string, unknown>} chartOptions
 * @param {{
 *   tooltip?: Record<string, unknown>,
 *   includeCrosshair?: boolean,
 *   extraPlugins?: unknown[],
 * }} [opts]
 * @returns {{ options: Record<string, unknown>, plugins: unknown[] }}
 */
export function applyProfileScatterHoverDefaults(chartOptions, opts = {}) {
    const options = chartOptions && typeof chartOptions === 'object' ? chartOptions : {};
    if (!options.plugins || typeof options.plugins !== 'object') options.plugins = {};

    options.interaction = {
        mode: 'nearest',
        intersect: false,
        axis: 'xy',
    };

    const baseTooltip = {
        mode: 'nearest',
        intersect: false,
        axis: 'xy',
        position: 'nearest',
    };
    options.plugins.tooltip = opts.tooltip && typeof opts.tooltip === 'object'
        ? { ...baseTooltip, ...opts.tooltip }
        : baseTooltip;

    const plugins = [];
    if (opts.includeCrosshair !== false) plugins.push(timeSeriesCrosshairPlugin);
    if (Array.isArray(opts.extraPlugins)) plugins.push(...opts.extraPlugins);

    return { options, plugins };
}
