// NAVWARN schedule stamps look like "15:00 UTC 2026-04-21" (wall clock + zone label + date).

const STAMP_RE = /^\s*(\d{1,2}):(\d{2})\s+(\S+)\s+(\d{4})-(\d{2})-(\d{2})\s*$/;
const PICKER_RE = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/;

const pad = (value) => String(value).padStart(2, '0');

export function zoneLabel(timezone) {
    return timezone === 'local' ? 'Local' : 'UTC';
}

export function wallFromDate(date, timezone) {
    if (timezone === 'local') {
        return {
            year: date.getFullYear(),
            month: date.getMonth() + 1,
            day: date.getDate(),
            hour: date.getHours(),
            minute: date.getMinutes(),
        };
    }
    return {
        year: date.getUTCFullYear(),
        month: date.getUTCMonth() + 1,
        day: date.getUTCDate(),
        hour: date.getUTCHours(),
        minute: date.getUTCMinutes(),
    };
}

export function wallToDate(wall, timezone) {
    if (timezone === 'local') {
        return new Date(wall.year, wall.month - 1, wall.day, wall.hour, wall.minute);
    }
    return new Date(Date.UTC(wall.year, wall.month - 1, wall.day, wall.hour, wall.minute));
}

export function formatWall(wall, timezone) {
    return `${pad(wall.hour)}:${pad(wall.minute)} ${zoneLabel(timezone)} ${wall.year}-${pad(wall.month)}-${pad(wall.day)}`;
}

export function parseStamp(text) {
    const match = STAMP_RE.exec(text || '');
    if (!match) return null;
    return {
        hour: Number(match[1]),
        minute: Number(match[2]),
        label: match[3],
        year: Number(match[4]),
        month: Number(match[5]),
        day: Number(match[6]),
    };
}

export function nowStamp(timezone) {
    return formatWall(wallFromDate(new Date(), timezone), timezone);
}

export function wallToPickerValue(wall) {
    return `${wall.year}-${pad(wall.month)}-${pad(wall.day)}T${pad(wall.hour)}:${pad(wall.minute)}`;
}

export function pickerValueToWall(value) {
    const match = PICKER_RE.exec(value || '');
    if (!match) return null;
    return {
        year: Number(match[1]),
        month: Number(match[2]),
        day: Number(match[3]),
        hour: Number(match[4]),
        minute: Number(match[5]),
    };
}

export function addDays(wall, days) {
    const shifted = new Date(Date.UTC(wall.year, wall.month - 1, wall.day + days, wall.hour, wall.minute));
    return wallFromDate(shifted, 'utc');
}

/** Re-express a stamp written in ``fromTz`` in ``toTz``; leaves hand-written text alone. */
export function convertStamp(text, fromTz, toTz) {
    const parsed = parseStamp(text);
    if (!parsed || fromTz === toTz) return text;
    if (parsed.label.toLowerCase() !== zoneLabel(fromTz).toLowerCase()) return text;
    return formatWall(wallFromDate(wallToDate(parsed, fromTz), toTz), toTz);
}

export function stampFromIso(iso, timezone) {
    if (!iso) return '';
    const hasZone = /[zZ]$|[+-]\d{2}:?\d{2}$/.test(iso);
    const date = new Date(hasZone ? iso : `${iso}Z`);
    if (Number.isNaN(date.getTime())) return '';
    return formatWall(wallFromDate(date, timezone), timezone);
}
