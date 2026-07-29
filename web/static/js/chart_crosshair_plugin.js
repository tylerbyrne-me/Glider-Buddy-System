/**
 * Lightweight Chart.js plugin: vertical crosshair at the active tooltip X.
 * Helps inspect zoomed time-series without changing pan/zoom controls.
 */

export const TIME_SERIES_CROSSHAIR_PLUGIN_ID = 'timeSeriesCrosshair';

/**
 * @type {import('chart.js').Plugin}
 */
export const timeSeriesCrosshairPlugin = {
    id: TIME_SERIES_CROSSHAIR_PLUGIN_ID,
    afterDraw(chart) {
        const tooltip = chart.tooltip;
        if (!tooltip || !tooltip.opacity) return;
        const active = typeof tooltip.getActiveElements === 'function'
            ? tooltip.getActiveElements()
            : [];
        if (!active?.length) return;

        const x = tooltip.caretX;
        const area = chart.chartArea;
        if (!area || !Number.isFinite(x)) return;
        if (x < area.left || x > area.right) return;

        const ctx = chart.ctx;
        ctx.save();
        ctx.beginPath();
        ctx.moveTo(x, area.top);
        ctx.lineTo(x, area.bottom);
        ctx.lineWidth = 1;
        ctx.strokeStyle = 'rgba(160, 160, 160, 0.65)';
        ctx.setLineDash([4, 3]);
        ctx.stroke();
        ctx.restore();
    },
};
