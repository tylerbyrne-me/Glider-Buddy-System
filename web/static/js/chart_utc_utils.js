/**
 * @file chart_utc_utils.js
 * @description Shared Chart.js helpers that force time-axis ticks and tooltips to UTC.
 */
import { formatUtcDateTime, toUtcDate } from '/static/js/datetime_utils.js';

const UTC_TICK_FORMATTER = new Intl.DateTimeFormat('en-GB', {
    timeZone: 'UTC',
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
});

export function formatUtcChartTick(value) {
    const date = toUtcDate(value);
    if (!date) return '';
    return UTC_TICK_FORMATTER.format(date).replace(',', '');
}

export function ensureUtcTimeDisplayForChart(chart) {
    if (!chart?.options?.scales) return;
    Object.entries(chart.options.scales).forEach(([scaleId, scale]) => {
        if (!scale || scale.type !== 'time') return;
        if (!scale.ticks) scale.ticks = {};
        scale.ticks.callback = (tickValue) => formatUtcChartTick(tickValue);
    });

    if (!chart.options.plugins) chart.options.plugins = {};
    if (!chart.options.plugins.tooltip) chart.options.plugins.tooltip = {};
    if (!chart.options.plugins.tooltip.callbacks) chart.options.plugins.tooltip.callbacks = {};

    const existingTitleCallback = chart.options.plugins.tooltip.callbacks.title;
    chart.options.plugins.tooltip.callbacks.title = (tooltipItems) => {
        const firstPoint = tooltipItems && tooltipItems.length > 0 ? tooltipItems[0] : null;
        if (!firstPoint || !firstPoint.parsed || firstPoint.parsed.x == null) return '';
        const utcTitle = formatUtcDateTime(firstPoint.parsed.x);
        return utcTitle || (existingTitleCallback ? existingTitleCallback(tooltipItems) : '');
    };
}

/**
 * Register the Chart.js plugin that forces UTC tick/tooltip display.
 * Idempotent — safe to call from multiple page modules.
 */
export function registerForceUtcTimeDisplayPlugin() {
    if (typeof Chart === 'undefined') return;
    try {
        if (Chart.registry?.plugins?.get?.('forceUtcTimeDisplay')) return;
        Chart.register({
            id: 'forceUtcTimeDisplay',
            beforeInit(chart) {
                ensureUtcTimeDisplayForChart(chart);
            },
            beforeUpdate(chart) {
                ensureUtcTimeDisplayForChart(chart);
            },
        });
    } catch (_) {
        // Chart.js registry unavailable — skip plugin registration
    }
}

/**
 * Build a Chart.js time scale configured for UTC wall-clock display.
 * @param {object} [options]
 * @param {string} [options.tickColor]
 * @param {string} [options.gridColor]
 * @param {string} [options.titleColor]
 * @param {string} [options.titleText='Time (UTC)']
 * @param {object} [options.extra] Extra scale options merged on top.
 */
export function buildUtcTimeScaleX(options = {}) {
    const {
        tickColor,
        gridColor,
        titleColor,
        titleText = 'Time (UTC)',
        extra = {},
    } = options;
    return {
        type: 'time',
        time: {
            unit: 'hour',
            tooltipFormat: 'MMM d, yyyy HH:mm',
            displayFormats: { hour: 'MMM d HH:mm', day: 'MMM d' },
        },
        title: {
            display: true,
            text: titleText,
            ...(titleColor != null ? { color: titleColor } : {}),
        },
        ticks: {
            maxRotation: 0,
            autoSkip: true,
            autoSkipPadding: 20,
            ...(tickColor != null ? { color: tickColor } : {}),
        },
        grid: {
            ...(gridColor != null ? { color: gridColor } : {}),
        },
        ...extra,
    };
}
