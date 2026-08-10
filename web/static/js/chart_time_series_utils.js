/**
 * @file chart_time_series_utils.js
 * @description Platform-agnostic pure helpers for declarative Chart.js time-series cards.
 * No Chart.js instance handling — platforms own create/destroy/registry.
 */
import { toUtcDate } from '/static/js/datetime_utils.js';
import { buildUtcTimeScaleX } from '/static/js/chart_utc_utils.js';

/**
 * Pivot wide API rows into narrow series maps.
 * Non-finite values become null (gap points). Rows without Timestamp are skipped.
 * @param {Array<Record<string, unknown>>|null|undefined} rows
 * @param {string[]} fields
 * @returns {Record<string, Array<{ Timestamp: unknown, Value: number|null }>>}
 */
export function rowsToSeries(rows, fields) {
    const series = {};
    (fields || []).forEach((field) => {
        series[field] = [];
    });
    if (!Array.isArray(rows) || !fields?.length) return series;

    for (const row of rows) {
        if (!row || row.Timestamp == null) continue;
        for (const field of fields) {
            const raw = row[field];
            if (raw == null || raw === '') {
                series[field].push({ Timestamp: row.Timestamp, Value: null });
                continue;
            }
            const num = typeof raw === 'number' ? raw : Number(raw);
            series[field].push({
                Timestamp: row.Timestamp,
                Value: Number.isFinite(num) ? num : null,
            });
        }
    }
    return series;
}

/**
 * Convert {Timestamp, Value} records to Chart.js {x, y} points.
 * @param {Array<{ Timestamp?: unknown, Value?: unknown }>|null|undefined} records
 * @param {{ keepGaps?: boolean }} [options] keepGaps=true preserves null y (WG parity); false drops them (Slocum).
 * @returns {Array<{ x: Date, y: number|null }>}
 */
export function recordsToPoints(records, options = {}) {
    const keepGaps = options.keepGaps !== false;
    if (!Array.isArray(records)) return [];
    const points = [];
    for (const row of records) {
        if (!row || row.Timestamp == null) continue;
        const x = toUtcDate(row.Timestamp);
        if (!x) continue;
        if (row.Value == null || row.Value === '') {
            if (keepGaps) points.push({ x, y: null });
            continue;
        }
        const y = typeof row.Value === 'number' ? row.Value : Number(row.Value);
        if (!Number.isFinite(y)) {
            if (keepGaps) points.push({ x, y: null });
            continue;
        }
        points.push({ x, y });
    }
    return points;
}

/**
 * True when series has at least one finite y value.
 * @param {Array<{ Timestamp?: unknown, Value?: unknown }>|null|undefined} records
 * @returns {boolean}
 */
export function seriesHasPlottableData(records) {
    if (!Array.isArray(records) || !records.length) return false;
    return records.some((row) => {
        if (!row || row.Value == null || row.Value === '') return false;
        const y = typeof row.Value === 'number' ? row.Value : Number(row.Value);
        return Number.isFinite(y);
    });
}

/** Whole-series |z| threshold for display-only outlier suppression. */
export const OUTLIER_Z_THRESHOLD = 2.5;
export const OUTLIER_Z_MIN_SAMPLES = 10;

const OUTLIER_SKIP_FIELD_RE = /heading|course|direction|compass|bearing|yaw|pitch|roll|latitude|longitude|\blat\b|\blon\b/i;

/**
 * True when a series field/key/label should not use z-score masking (circular / geo).
 * @param {string|null|undefined} fieldOrLabel
 * @returns {boolean}
 */
export function shouldSkipOutlierSuppress(fieldOrLabel) {
    return OUTLIER_SKIP_FIELD_RE.test(String(fieldOrLabel || ''));
}

/**
 * Mask Chart.js points whose y has |z-score| > threshold (display-only).
 * Non-finite / null y values are preserved as-is (gaps). Short series are unchanged.
 * @param {Array<{ x?: unknown, y?: number|null }>|null|undefined} points
 * @param {{ threshold?: number, minSamples?: number }} [options]
 * @returns {{ points: Array<{ x?: unknown, y?: number|null }>, suppressedCount: number }}
 */
export function maskOutlierPointsByZScore(points, options = {}) {
    const threshold = options.threshold ?? OUTLIER_Z_THRESHOLD;
    const minSamples = options.minSamples ?? OUTLIER_Z_MIN_SAMPLES;
    if (!Array.isArray(points) || !points.length) {
        return { points: Array.isArray(points) ? points.slice() : [], suppressedCount: 0 };
    }
    const finiteIdx = [];
    const finiteVals = [];
    for (let i = 0; i < points.length; i += 1) {
        const y = points[i]?.y;
        if (typeof y === 'number' && Number.isFinite(y)) {
            finiteIdx.push(i);
            finiteVals.push(y);
        }
    }
    if (finiteVals.length < minSamples) {
        return { points: points.slice(), suppressedCount: 0 };
    }
    let sum = 0;
    for (const v of finiteVals) sum += v;
    const mean = sum / finiteVals.length;
    let varSum = 0;
    for (const v of finiteVals) {
        const d = v - mean;
        varSum += d * d;
    }
    const std = Math.sqrt(varSum / finiteVals.length);
    if (!Number.isFinite(std) || std === 0) {
        return { points: points.slice(), suppressedCount: 0 };
    }
    const out = points.map((p) => ({ ...p }));
    let suppressedCount = 0;
    for (const i of finiteIdx) {
        const z = Math.abs((out[i].y - mean) / std);
        if (z > threshold) {
            out[i] = { ...out[i], y: null };
            suppressedCount += 1;
        }
    }
    return { points: out, suppressedCount };
}

/**
 * Draw a centered no-data message on a canvas (destroys any prior chart content).
 * @param {string} canvasId
 * @param {string} [message]
 */
export function drawNoDataOnCanvas(canvasId, message = 'No data available') {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    const width = canvas.parentElement?.clientWidth || canvas.width || 300;
    const height = canvas.parentElement?.clientHeight || canvas.height || 300;
    canvas.width = width;
    canvas.height = height;
    ctx.clearRect(0, 0, width, height);
    const styles = getComputedStyle(document.documentElement);
    ctx.fillStyle = styles.getPropertyValue('--secondary-color').trim()
        || styles.getPropertyValue('--text-color').trim()
        || '#6c757d';
    ctx.font = '16px Arial';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(message, width / 2, height / 2);
}

/**
 * Resolve a color map key (or raw rgba string) with optional alpha override.
 * Replaces the final alpha channel in `rgba(r, g, b, a)`.
 * @param {Record<string, string>|null|undefined} colorMap
 * @param {string} key
 * @param {number} [alpha]
 * @returns {string}
 */
export function resolveColor(colorMap, key, alpha) {
    const base = (colorMap && colorMap[key]) || key || 'rgba(128, 128, 128, 1)';
    if (alpha == null || !Number.isFinite(alpha)) return base;
    if (/^rgba?\(/i.test(base)) {
        return base.replace(/,\s*[\d.]+\s*\)$/, `, ${alpha})`);
    }
    return base;
}

/**
 * Build a Chart.js linear Y scale from a declarative axis spec.
 * @param {object} spec
 * @param {string} spec.id
 * @param {'left'|'right'} [spec.position]
 * @param {string} [spec.label]
 * @param {number} [spec.min]
 * @param {number} [spec.max]
 * @param {boolean} [spec.beginAtZero]
 * @param {boolean} [spec.display]
 * @param {boolean} [spec.drawGrid]
 * @param {string} [spec.textColor]
 * @param {string} [spec.gridColor]
 * @returns {Record<string, unknown>}
 */
export function buildLinearScale(spec = {}) {
    const {
        position = 'left',
        label = '',
        min,
        max,
        beginAtZero = false,
        display = true,
        drawGrid,
        textColor,
        gridColor,
    } = spec;

    const drawOnChartArea = drawGrid != null
        ? drawGrid
        : position !== 'right';

    const scale = {
        type: 'linear',
        position,
        display: display !== false,
        title: {
            display: display !== false && !!label,
            text: label || '',
            ...(textColor != null ? { color: textColor } : {}),
        },
        ticks: {
            ...(textColor != null ? { color: textColor } : {}),
            ...(beginAtZero ? { beginAtZero: true } : {}),
            ...(min != null ? { min } : {}),
            ...(max != null ? { max } : {}),
        },
        grid: {
            drawOnChartArea,
            ...(gridColor != null && drawOnChartArea ? { color: gridColor } : {}),
        },
    };

    // Chart.js v3+ prefers min/max on the scale, not only ticks
    if (min != null) scale.min = min;
    if (max != null) scale.max = max;
    if (beginAtZero) scale.beginAtZero = true;

    return scale;
}

/**
 * Build a Chart.js UTC time X scale (delegates to chart_utc_utils).
 * @param {object} [options] Same options as buildUtcTimeScaleX
 * @returns {Record<string, unknown>}
 */
export function buildTimeScaleX(options = {}) {
    return buildUtcTimeScaleX(options);
}
