import { createThemedTileLayer, observeThemeChange, swapMapTileLayer } from '/static/js/map_tiles.js';
import { bindVectorOverlayContext, initVectorOverlay } from '/static/js/vector_map_layer.js';
import { bindNavwarnOverlayContext, initNavwarnOverlay } from '/static/js/navwarn_map_layer.js';
import { bindVesselDensityOverlayContext, initVesselDensityOverlay } from '/static/js/vessel_density_map_layer.js';
import { bindCiopsIceOverlayContext, initCiopsIceOverlay } from '/static/js/ciops_ice_map_layer.js';

const AREA_COLOR = '#b23a48';
const TRACK_COLOR = '#3d5a80';

function formatDecimal(value) {
    return value.toFixed(6).replace(/\.?0+$/, '') || '0';
}

function splitDm(absDegrees) {
    const degrees = Math.floor(absDegrees);
    return { degrees, minutes: (absDegrees - degrees) * 60 };
}

/** Mirrors ``format_position_parts`` in navwarn_form.py (what the form's position rows print). */
export function previewPosition(lat, lon, positionFormat) {
    if (lat == null || lon == null) return '—';
    const latH = lat >= 0 ? 'N' : 'S';
    const lonH = lon >= 0 ? 'E' : 'W';
    const dm = (value) => {
        const { degrees, minutes } = splitDm(Math.abs(value));
        return `${degrees} ${formatDecimal(minutes)}`;
    };
    const dms = (value) => {
        const { degrees, minutes } = splitDm(Math.abs(value));
        const wholeMinutes = Math.floor(minutes);
        const seconds = (minutes - wholeMinutes) * 60;
        return `${degrees} ${String(wholeMinutes).padStart(2, '0')} ${formatDecimal(seconds)}`;
    };
    if (positionFormat === 'dm') return `${dm(lat)} ${latH}, ${dm(lon)} ${lonH}`;
    if (positionFormat === 'dms') return `${dms(lat)} ${latH}, ${dms(lon)} ${lonH}`;
    return `${formatDecimal(lat)} ${latH}, ${formatDecimal(lon)} ${lonH}`;
}

/** Same decimal degrees style as the primary lat/lon inputs (signed lon). */
export function formatAreaPoint(point) {
    return `${formatDecimal(Number(point.lat))}, ${formatDecimal(Number(point.lon))}`;
}

function numberedList(points) {
    return points.map((point, index) => `${index + 1}) ${formatAreaPoint(point)}`).join(', ');
}

export function describeArea(area, _positionFormat) {
    const points = area?.points || [];
    if (!points.length) return '';
    if (area.mode === 'hold') {
        const where = formatAreaPoint(points[0]);
        const radius = Number(area.radius_km);
        return Number.isFinite(radius) && radius > 0
            ? `Hold station within a ${formatDecimal(radius)} km radius of ${where}.`
            : `Hold station at ${where}.`;
    }
    if (area.mode === 'course') {
        if (points.length === 1) return `Course from ${formatAreaPoint(points[0])}.`;
        return `Course through the following positions: ${numberedList(points)}.`;
    }
    if (points.length < 3) return `Area points: ${numberedList(points)}.`;
    return `Operating within the area bounded by: ${numberedList(points)}.`;
}

/** Point that goes in the form's single position rows. */
export function areaAnchor(area) {
    const points = area?.points || [];
    if (!points.length) return null;
    if (area.mode !== 'polygon' || points.length < 3) return points[0];
    const sum = points.reduce((acc, point) => ({ lat: acc.lat + point.lat, lon: acc.lon + point.lon }), { lat: 0, lon: 0 });
    return { lat: sum.lat / points.length, lon: sum.lon / points.length };
}

const round6 = (value) => Number(value.toFixed(6));

export function createAreaMap({ elementId, onChange }) {
    const map = L.map(elementId, { scrollWheelZoom: true }).setView([44.2, -63.0], 6);
    const tileHolder = { current: createThemedTileLayer().addTo(map) };
    observeThemeChange(() => {
        tileHolder.current = swapMapTileLayer(map, tileHolder.current);
    });
    const trackLayer = L.layerGroup().addTo(map);
    const drawLayer = L.layerGroup().addTo(map);
    bindVectorOverlayContext(map);
    bindNavwarnOverlayContext(map);
    bindVesselDensityOverlayContext(map);
    bindCiopsIceOverlayContext(map);
    initVectorOverlay();
    initNavwarnOverlay();
    initVesselDensityOverlay();
    initCiopsIceOverlay();

    let area = { mode: 'hold', points: [], radius_km: null };

    const emit = () => onChange?.(getArea());

    function getArea() {
        return { mode: area.mode, points: area.points.map((point) => ({ ...point })), radius_km: area.radius_km };
    }

    function redraw({ fit = false } = {}) {
        drawLayer.clearLayers();
        const latlngs = area.points.map((point) => [point.lat, point.lon]);
        area.points.forEach((point, index) => {
            const marker = L.marker([point.lat, point.lon], { draggable: true, title: `Point ${index + 1}` }).addTo(drawLayer);
            marker.bindTooltip(area.mode === 'hold' ? 'Hold station' : `Point ${index + 1}`);
            marker.on('click', (event) => {
                if (event.originalEvent) L.DomEvent.stopPropagation(event.originalEvent);
            });
            marker.on('dragend', (event) => {
                const latlng = event.target.getLatLng();
                area.points[index] = { lat: round6(latlng.lat), lon: round6(latlng.lng) };
                redraw();
                emit();
            });
        });
        const style = { color: AREA_COLOR, weight: 2 };
        if (area.mode === 'hold' && latlngs.length && Number(area.radius_km) > 0) {
            L.circle(latlngs[0], { ...style, radius: Number(area.radius_km) * 1000, fillOpacity: 0.08 }).addTo(drawLayer);
        } else if (area.mode === 'polygon' && latlngs.length >= 3) {
            L.polygon(latlngs, { ...style, fillOpacity: 0.08 }).addTo(drawLayer);
        } else if (latlngs.length >= 2) {
            L.polyline(latlngs, style).addTo(drawLayer);
        }
        if (fit) {
            const bounds = drawLayer.getLayers().length ? L.featureGroup(drawLayer.getLayers()).getBounds() : null;
            if (bounds?.isValid()) map.fitBounds(bounds.pad(0.3), { maxZoom: 11 });
        }
    }

    map.on('click', (event) => {
        const point = { lat: round6(event.latlng.lat), lon: round6(event.latlng.lng) };
        if (area.mode === 'hold') {
            area.points = [point];
        } else {
            area.points.push(point);
        }
        redraw();
        emit();
    });

    return {
        map,
        getArea,
        setArea(next, { fit = false } = {}) {
            area = {
                mode: next?.mode || 'hold',
                points: (next?.points || []).map((point) => ({ lat: Number(point.lat), lon: Number(point.lon) })),
                radius_km: next?.radius_km ?? null,
            };
            redraw({ fit });
        },
        setMode(mode) {
            area.mode = mode;
            if (mode === 'hold' && area.points.length > 1) area.points = area.points.slice(0, 1);
            redraw();
            emit();
        },
        setRadius(radiusKm) {
            area.radius_km = radiusKm;
            redraw();
            emit();
        },
        /** Move the hold point without echoing a change back to the lat/lon inputs. */
        setHoldPoint(point) {
            if (area.mode !== 'hold') return;
            area.points = point ? [{ lat: round6(point.lat), lon: round6(point.lon) }] : [];
            redraw();
        },
        undo() {
            area.points.pop();
            redraw();
            emit();
        },
        clear() {
            area.points = [];
            redraw();
            emit();
        },
        setTrack(points, { fit = false } = {}) {
            trackLayer.clearLayers();
            const latlngs = (points || []).map((point) => [point.lat, point.lon]);
            if (!latlngs.length) return;
            if (latlngs.length >= 2) {
                L.polyline(latlngs, { color: TRACK_COLOR, weight: 2, opacity: 0.7, interactive: false }).addTo(trackLayer);
            }
            L.circleMarker(latlngs[latlngs.length - 1], {
                radius: 5,
                color: TRACK_COLOR,
                weight: 1,
                fillOpacity: 0.9,
            }).bindTooltip('Last telemetry fix').addTo(trackLayer);
            if (fit && !area.points.length) map.fitBounds(L.latLngBounds(latlngs).pad(0.3), { maxZoom: 11 });
        },
        clearTrack() {
            trackLayer.clearLayers();
        },
    };
}
