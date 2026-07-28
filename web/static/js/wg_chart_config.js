/**
 * @file wg_chart_config.js
 * @description Serializable Wave Glider time-series card configs and chart colors.
 * Configs are plain data (no closures) so they can later move server-side for ERDDAP.
 */

export const CHART_COLORS = {
    POWER_BATTERY: 'rgba(54, 162, 235, 1)',
    POWER_SOLAR: 'rgba(255, 159, 64, 1)',
    POWER_DRAW: 'rgba(255, 99, 132, 1)',
    CTD_TEMP: 'rgba(0, 191, 255, 1)',
    CTD_SALINITY: 'rgba(255, 105, 180, 1)',
    CTD_CONDUCTIVITY: 'rgba(123, 104, 238, 1)',
    CTD_DO: 'rgba(60, 179, 113, 1)',
    WEATHER_AIR_TEMP: 'rgba(255, 99, 71, 1)',
    WEATHER_WIND_SPEED: 'rgba(60, 179, 113, 1)',
    WAVES_SIG_HEIGHT: 'rgba(255, 206, 86, 1)',
    WAVES_PERIOD: 'rgba(153, 102, 255, 1)',
    VR2C_DETECTION: 'rgba(75, 192, 192, 1)',
    WG_VM4_CH0_DETECTION: 'rgba(255, 159, 64, 1)',
    WAVE_SPECTRUM: 'rgba(255, 99, 132, 1)',
    FLUORO_C_AVG_PRIMARY: 'rgba(75, 192, 192, 1)',
    SOLAR_PANEL_1: 'rgba(255, 215, 0, 1)',
    SOLAR_PANEL_2: 'rgba(173, 216, 230, 1)',
    SOLAR_PANEL_4: 'rgba(144, 238, 144, 1)',
    FLUORO_TEMP: 'rgba(255, 99, 132, 1)',
    NAV_SPEED: 'rgba(138, 43, 226, 1)',
    NAV_SOG: 'rgba(0, 128, 0, 0.7)',
    NAV_HEADING: 'rgba(255, 140, 0, 1)',
    OCEAN_CURRENT_SPEED: 'rgba(30, 144, 255, 1)',
    OCEAN_CURRENT_DIRECTION: 'rgba(255, 69, 0, 1)',
    HEADING_DIFF: 'rgba(218, 112, 214, 1)',
};

/**
 * UI category → declarative time-series charts.
 * @typedef {object} WgSeriesSpec
 * @property {string} field
 * @property {string} [label]
 * @property {string} [labelKey] Fluorometer channel key for window.FLUOROMETER_CHANNEL_LABELS
 * @property {string} color CHART_COLORS key
 * @property {string} [yAxisID]
 * @property {string} [source] Override chart-level source for this series
 * @property {boolean} [dashed]
 * @property {number} [alpha] Override rgba alpha (0–1)
 *
 * @typedef {object} WgAxisSpec
 * @property {string} id
 * @property {'left'|'right'} [position]
 * @property {string} [label]
 * @property {number} [min]
 * @property {number} [max]
 * @property {boolean} [beginAtZero]
 * @property {boolean} [display]
 * @property {boolean} [drawGrid]
 */

/** @type {Record<string, { enabledSensor: string, sources: string[], charts: object[] }>} */
export const WG_TIME_SERIES_CARD_CONFIGS = {
    power: {
        enabledSensor: 'power',
        sources: ['power', 'solar'],
        charts: [
            {
                canvasId: 'powerChart',
                source: 'power',
                noDataMessage: 'No power trend data available to display.',
                yAxes: [
                    { id: 'ySolar', position: 'left', label: 'Watts (W)' },
                    { id: 'yBattery', position: 'right', label: 'Watt-hours (Wh)', drawGrid: false },
                ],
                series: [
                    { field: 'BatteryWattHours', label: 'Battery (Wh)', color: 'POWER_BATTERY', yAxisID: 'yBattery' },
                    { field: 'PowerDrawWatts', label: 'Power Draw (W)', color: 'POWER_DRAW', yAxisID: 'ySolar' },
                ],
            },
            {
                canvasId: 'solarPanelChart',
                source: 'solar',
                noDataMessage: 'No solar panel trend data available.',
                yAxes: [
                    { id: 'yIndividualPanels', position: 'left', label: 'Panel Power (W)', beginAtZero: true },
                    { id: 'yTotalSolar', position: 'right', label: 'Total Solar (W)', beginAtZero: true, drawGrid: false },
                ],
                series: [
                    {
                        field: 'SolarInputWatts',
                        label: 'Total Solar Input (W)',
                        color: 'POWER_SOLAR',
                        yAxisID: 'yTotalSolar',
                        source: 'power',
                        dashed: true,
                    },
                    { field: 'Panel1Power', label: 'Panel 1 Power (W)', color: 'SOLAR_PANEL_1', yAxisID: 'yIndividualPanels' },
                    { field: 'Panel2Power', label: 'Panel 2 Power (W)', color: 'SOLAR_PANEL_2', yAxisID: 'yIndividualPanels' },
                    { field: 'Panel4Power', label: 'Panel 4 Power (W)', color: 'SOLAR_PANEL_4', yAxisID: 'yIndividualPanels' },
                ],
            },
        ],
    },
    navigation: {
        enabledSensor: 'navigation',
        sources: ['telemetry'],
        charts: [
            {
                canvasId: 'telemetryChart',
                source: 'telemetry',
                noDataMessage: 'No navigation trend data available.',
                yAxes: [
                    { id: 'ySpeed', position: 'left', label: 'Speed (knots)', beginAtZero: true },
                    { id: 'yHeading', position: 'right', label: 'Heading (°)', min: 0, max: 360, drawGrid: false },
                ],
                series: [
                    { field: 'GliderSpeed', label: 'Glider Speed (knots)', color: 'NAV_SPEED', yAxisID: 'ySpeed' },
                    { field: 'SpeedOverGround', label: 'SOG (knots)', color: 'NAV_SOG', yAxisID: 'ySpeed', dashed: true },
                    { field: 'GliderHeading', label: 'Glider Heading (°)', color: 'NAV_HEADING', yAxisID: 'yHeading' },
                ],
            },
            {
                canvasId: 'telemetryCurrentChart',
                source: 'telemetry',
                noDataMessage: 'No ocean current data available.',
                yAxes: [
                    { id: 'ySpeed', position: 'left', label: 'Speed (knots)', beginAtZero: true },
                    { id: 'yDirection', position: 'right', label: 'Direction (°)', min: 0, max: 360, drawGrid: false },
                ],
                series: [
                    { field: 'OceanCurrentSpeed', label: 'Ocean Current Speed (kn)', color: 'OCEAN_CURRENT_SPEED', yAxisID: 'ySpeed' },
                    { field: 'OceanCurrentDirection', label: 'Ocean Current Dir (°)', color: 'OCEAN_CURRENT_DIRECTION', yAxisID: 'yDirection' },
                    { field: 'SpeedOverGround', label: 'SOG (knots)', color: 'NAV_SOG', yAxisID: 'ySpeed', dashed: true, alpha: 0.5 },
                ],
            },
            {
                canvasId: 'telemetryHeadingDiffChart',
                source: 'telemetry',
                noDataMessage: 'No heading difference data available.',
                yAxes: [
                    { id: 'ySpeed', position: 'left', label: 'Ocean Current (kn)', beginAtZero: true },
                    { id: 'yDiff', position: 'right', label: 'Heading Diff (°)', min: -180, max: 180, drawGrid: false },
                ],
                series: [
                    { field: 'HeadingDiff', label: 'Sub Heading Diff (°)', color: 'HEADING_DIFF', yAxisID: 'yDiff' },
                    {
                        field: 'OceanCurrentSpeed',
                        label: 'Ocean Current Speed (kn)',
                        color: 'OCEAN_CURRENT_SPEED',
                        yAxisID: 'ySpeed',
                        dashed: true,
                        alpha: 0.7,
                    },
                ],
            },
        ],
    },
    ctd: {
        enabledSensor: 'ctd',
        sources: ['ctd'],
        charts: [
            {
                canvasId: 'ctdChart',
                source: 'ctd',
                noDataMessage: 'No CTD trend data available to display.',
                yAxes: [
                    { id: 'yTemp', position: 'left', label: 'Temperature (°C)' },
                    { id: 'ySalinity', position: 'right', label: 'Salinity (PSU)', drawGrid: false },
                ],
                series: [
                    { field: 'WaterTemperature', label: 'Water Temp (°C)', color: 'CTD_TEMP', yAxisID: 'yTemp' },
                    { field: 'Salinity', label: 'Salinity (PSU)', color: 'CTD_SALINITY', yAxisID: 'ySalinity' },
                ],
            },
            {
                canvasId: 'ctdProfileChart',
                source: 'ctd',
                noDataMessage: 'No CTD profile data available.',
                yAxes: [
                    { id: 'yTemp', position: 'left', label: 'Temperature (°C)' },
                    { id: 'yCond', position: 'right', label: 'Conductivity (S/m)', drawGrid: false },
                    { id: 'yDO', position: 'left', label: '', display: false, drawGrid: false },
                ],
                series: [
                    { field: 'WaterTemperature', label: 'Water Temp (°C)', color: 'CTD_TEMP', yAxisID: 'yTemp', alpha: 0.2 },
                    { field: 'Conductivity', label: 'Conductivity (S/m)', color: 'CTD_CONDUCTIVITY', yAxisID: 'yCond', alpha: 0.2 },
                    { field: 'DissolvedOxygen', label: 'DO (Hz)', color: 'CTD_DO', yAxisID: 'yDO' },
                ],
            },
        ],
    },
    weather: {
        enabledSensor: 'weather',
        sources: ['weather'],
        charts: [
            {
                canvasId: 'weatherSensorChart',
                source: 'weather',
                noDataMessage: 'No weather sensor trend data available to display.',
                yAxes: [
                    { id: 'yTemp', position: 'left', label: 'Temperature (°C)' },
                    { id: 'yWind', position: 'right', label: 'Wind (kt)', beginAtZero: true, drawGrid: false },
                ],
                series: [
                    { field: 'AirTemperature', label: 'Air Temp (°C)', color: 'WEATHER_AIR_TEMP', yAxisID: 'yTemp' },
                    { field: 'WindSpeed', label: 'Wind Speed (kt)', color: 'WEATHER_WIND_SPEED', yAxisID: 'yWind' },
                    {
                        field: 'WindGust',
                        label: 'Wind Gust (kt)',
                        color: 'WEATHER_WIND_SPEED',
                        yAxisID: 'yWind',
                        dashed: true,
                        alpha: 0.7,
                    },
                ],
            },
        ],
    },
    waves: {
        enabledSensor: 'waves',
        sources: ['waves'],
        charts: [
            {
                canvasId: 'waveChart',
                source: 'waves',
                noDataMessage: 'No wave trend data available to display.',
                yAxes: [
                    { id: 'yHeight', position: 'left', label: 'Wave Height (m)' },
                    { id: 'yPeriod', position: 'right', label: 'Wave Period (s)', drawGrid: false },
                ],
                series: [
                    { field: 'SignificantWaveHeight', label: 'Sig. Wave Height (m)', color: 'WAVES_SIG_HEIGHT', yAxisID: 'yHeight' },
                    { field: 'WavePeriod', label: 'Wave Period (s)', color: 'WAVES_PERIOD', yAxisID: 'yPeriod' },
                ],
            },
            {
                canvasId: 'waveHeightDirectionChart',
                source: 'waves',
                noDataMessage: 'No wave Ht/Dir data available.',
                yAxes: [
                    { id: 'yHeight', position: 'left', label: 'Wave Height (m)', beginAtZero: true },
                    { id: 'yDirection', position: 'right', label: 'Wave Direction (°)', min: 0, max: 360, drawGrid: false },
                ],
                series: [
                    { field: 'SignificantWaveHeight', label: 'Sig. Wave Height (m)', color: 'WAVES_SIG_HEIGHT', yAxisID: 'yHeight' },
                    { field: 'MeanWaveDirection', label: 'Mean Wave Dir (°)', color: 'CTD_SALINITY', yAxisID: 'yDirection', alpha: 0.7 },
                ],
            },
        ],
    },
    vr2c: {
        enabledSensor: 'vr2c',
        sources: ['vr2c'],
        charts: [
            {
                canvasId: 'vr2cChart',
                source: 'vr2c',
                noDataMessage: 'No VR2C trend data available to display.',
                yAxes: [
                    { id: 'yCounts', position: 'left', label: 'Detection Count (DC)', beginAtZero: true },
                    { id: 'yDelta', position: 'right', label: 'Ping Count Delta (ΔPC/hr)', drawGrid: false },
                ],
                series: [
                    { field: 'DetectionCount', label: 'Detection Count (DC)', color: 'VR2C_DETECTION', yAxisID: 'yCounts' },
                    {
                        field: 'PingCountDelta',
                        label: 'Ping Count Delta (ΔPC/hr)',
                        color: 'POWER_DRAW',
                        yAxisID: 'yDelta',
                        dashed: true,
                    },
                ],
            },
        ],
    },
    fluorometer: {
        enabledSensor: 'fluorometer',
        sources: ['fluorometer'],
        charts: [
            {
                canvasId: 'fluorometerChart',
                source: 'fluorometer',
                noDataMessage: 'No fluorometer data available.',
                yAxes: [
                    { id: 'yPrimary', position: 'left', label: 'Fluorescence Units' },
                    { id: 'yTemp', position: 'right', label: 'Temperature (°C)', drawGrid: false },
                ],
                series: [
                    { field: 'C1_Avg', label: 'C1 Avg', labelKey: 'C1_Avg', color: 'FLUORO_C_AVG_PRIMARY', yAxisID: 'yPrimary' },
                    { field: 'C2_Avg', label: 'C2 Avg', labelKey: 'C2_Avg', color: 'WAVES_SIG_HEIGHT', yAxisID: 'yPrimary' },
                    { field: 'C3_Avg', label: 'C3 Avg', labelKey: 'C3_Avg', color: 'WAVES_PERIOD', yAxisID: 'yPrimary' },
                    { field: 'Temperature_Fluor', label: 'Temperature (°C)', color: 'FLUORO_TEMP', yAxisID: 'yTemp' },
                ],
            },
        ],
    },
    wg_vm4: {
        enabledSensor: 'wg_vm4',
        sources: ['wg_vm4'],
        charts: [
            {
                canvasId: 'wgVm4Chart',
                source: 'wg_vm4',
                noDataMessage: 'No WG-VM4 trend data available.',
                yAxes: [
                    { id: 'yDetections', position: 'left', label: 'Detection Counts', beginAtZero: true },
                ],
                series: [
                    { field: 'Channel0DetectionCount', label: 'Ch0 Detections', color: 'WG_VM4_CH0_DETECTION', yAxisID: 'yDetections' },
                    {
                        field: 'Channel1DetectionCount',
                        label: 'Ch1 Detections',
                        color: 'CTD_SALINITY',
                        yAxisID: 'yDetections',
                        dashed: true,
                    },
                ],
            },
        ],
    },
};

/**
 * Collect all field names needed from a source for a category config.
 * @param {object} cfg
 * @param {string} source
 * @returns {string[]}
 */
export function fieldsForSource(cfg, source) {
    const fields = new Set();
    for (const chart of cfg.charts || []) {
        for (const spec of chart.series || []) {
            const seriesSource = spec.source || chart.source;
            if (seriesSource === source) fields.add(spec.field);
        }
    }
    return Array.from(fields);
}

/**
 * Find UI category for a canvas id.
 * @param {string} canvasId
 * @returns {string|null}
 */
export function findWgCategoryForCanvas(canvasId) {
    for (const [category, cfg] of Object.entries(WG_TIME_SERIES_CARD_CONFIGS)) {
        if ((cfg.charts || []).some((c) => c.canvasId === canvasId)) return category;
    }
    return null;
}
