/**
 * @file sensor_tracker_instruments.js
 * @description Shared Flight / Science / Platform Direct instrument column renderer
 * for Sensor Tracker metadata (admin overviews + mission dashboards).
 * Nested sensors are shown under each instrument when present.
 */

function escapeHtml(value) {
    return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

function sensorDisplayName(sensor) {
    return (
        sensor.sensor_long_name
        || sensor.sensor_short_name
        || sensor.sensor_identifier
        || 'Sensor'
    );
}

function appendInstrumentItem(listEl, inst) {
    const li = document.createElement('li');
    li.className = 'mb-2';
    const name = inst.instrument_name || inst.instrument_long_name || inst.instrument_identifier || 'Instrument';
    const serial = inst.instrument_serial ? ` (${inst.instrument_serial})` : '';
    li.innerHTML = `<strong>${escapeHtml(name)}</strong>${escapeHtml(serial)}`;

    const sensors = Array.isArray(inst.sensors) ? inst.sensors : [];
    if (sensors.length) {
        const sub = document.createElement('ul');
        sub.className = 'list-unstyled small ms-3 mt-1 mb-0 text-muted';
        sensors.forEach((sensor) => {
            const subLi = document.createElement('li');
            subLi.className = 'mb-1';
            const sensorName = sensorDisplayName(sensor);
            const sensorSerial = sensor.sensor_serial ? ` (${sensor.sensor_serial})` : '';
            subLi.innerHTML = `${escapeHtml(sensorName)}${escapeHtml(sensorSerial)}`;
            sub.appendChild(subLi);
        });
        li.appendChild(sub);
    }

    listEl.appendChild(li);
}

/**
 * Fill one instrument column (list + optional data-logger serial line).
 * @returns {boolean} true when the column has items and was shown
 */
export function renderInstrumentGroup(items, containerId, listId, serialId = null) {
    const container = document.getElementById(containerId);
    const list = document.getElementById(listId);
    const serialEl = serialId ? document.getElementById(serialId) : null;
    if (!container || !list) return false;

    if (!items || !items.length) {
        container.style.display = 'none';
        if (serialEl) serialEl.style.display = 'none';
        return false;
    }

    if (serialEl) {
        const loggerSerial = items[0].data_logger_serial;
        if (loggerSerial) {
            serialEl.textContent = `Serial: ${loggerSerial}`;
            serialEl.style.display = 'block';
        } else {
            serialEl.textContent = '';
            serialEl.style.display = 'none';
        }
    }

    list.innerHTML = '';
    items.forEach((inst) => appendInstrumentItem(list, inst));
    container.style.display = 'block';
    return true;
}

/**
 * Partition instruments and render the three-column layout.
 *
 * @param {Array<object>} instruments
 * @param {{ prefix?: string, wrapId?: string | null }} [options]
 * @returns {boolean} true when at least one column was shown
 */
export function renderSensorTrackerInstrumentColumns(instruments, options = {}) {
    const prefix = options.prefix || 'overviewSt';
    const wrapId = options.wrapId !== undefined ? options.wrapId : `${prefix}Instruments`;
    const all = Array.isArray(instruments) ? instruments : [];

    const flight = all.filter((i) => i && i.data_logger_type === 'flight');
    const science = all.filter((i) => i && i.data_logger_type === 'science');
    const platform = all.filter((i) => i && i.is_platform_direct);

    const hasFlight = renderInstrumentGroup(
        flight,
        `${prefix}FlightInstrumentsContainer`,
        `${prefix}FlightInstruments`,
        `${prefix}FlightComputerSerial`
    );
    const hasScience = renderInstrumentGroup(
        science,
        `${prefix}ScienceInstrumentsContainer`,
        `${prefix}ScienceInstruments`,
        `${prefix}ScienceComputerSerial`
    );
    const hasPlatform = renderInstrumentGroup(
        platform,
        `${prefix}PlatformInstrumentsContainer`,
        `${prefix}PlatformInstruments`,
        null
    );

    const hasAny = hasFlight || hasScience || hasPlatform;
    const wrap = wrapId ? document.getElementById(wrapId) : null;
    if (wrap) {
        // Admin wrap is a Bootstrap row (flex); dashboards use a plain div.
        if (wrap.classList.contains('row') || wrap.id === 'stInstrumentsContainer') {
            wrap.style.display = hasAny ? 'flex' : 'none';
        } else {
            wrap.style.display = hasAny ? 'block' : 'none';
        }
    }
    return hasAny;
}
