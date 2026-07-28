/**
 * @file datetime_utils.js
 * @description Shared UTC datetime parsing/formatting helpers.
 */

const UTC_DATE_TIME_FORMATTER = new Intl.DateTimeFormat('en-GB', {
    timeZone: 'UTC',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false
});

const UTC_DATE_FORMATTER = new Intl.DateTimeFormat('en-GB', {
    timeZone: 'UTC',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit'
});

/**
 * Parse any timestamp-like value as UTC and return a Date, or null if invalid.
 * Bare ISO strings without a timezone suffix are treated as UTC (Z appended).
 */
export function toUtcDate(value) {
    if (value == null || value === '') return null;
    const date = parseUtcTimestamp(value);
    if (!date || Number.isNaN(date.getTime())) return null;
    return date;
}

export function parseUtcTimestamp(value) {
    if (value == null || value === '') return null;
    if (value instanceof Date) return new Date(value.getTime());
    if (typeof value === 'number') return new Date(value);
    if (typeof value !== 'string') return new Date(value);

    const trimmedValue = value.trim();
    if (!trimmedValue) return null;

    // Treat timezone-less ISO (and space-separated) as UTC wall clock.
    // Allow optional fractional seconds.
    const isTimezoneMissing = /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?$/.test(trimmedValue);
    const normalizedValue = isTimezoneMissing
        ? `${trimmedValue.replace(' ', 'T')}Z`
        : trimmedValue;
    return new Date(normalizedValue);
}

export function formatUtcDateTime(value) {
    const date = toUtcDate(value);
    if (!date) return '-';
    const parts = UTC_DATE_TIME_FORMATTER.formatToParts(date);
    const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));
    return `${values.year}-${values.month}-${values.day} ${values.hour}:${values.minute}:${values.second} UTC`;
}

export function formatUtcDate(value) {
    const date = toUtcDate(value);
    if (!date) return '-';
    const parts = UTC_DATE_FORMATTER.formatToParts(date);
    const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));
    return `${values.year}-${values.month}-${values.day}`;
}

/**
 * Parse a UTC datetime input string (text or former datetime-local value).
 * Accepts YYYY-MM-DDTHH:mm with optional seconds and optional Z suffix.
 */
export function parseDatetimeLocalAsUtc(value) {
    if (!value) return null;
    const trimmedValue = String(value).trim();
    if (!trimmedValue) return null;

    // Strip trailing Z so we can re-append consistently; also accept space separator.
    const withoutZ = trimmedValue.replace(/Z$/i, '').replace(' ', 'T');
    if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?$/.test(withoutZ)) {
        // Fall back to general UTC parser for full ISO with offset.
        return toUtcDate(trimmedValue);
    }
    const utcDate = new Date(`${withoutZ}Z`);
    if (Number.isNaN(utcDate.getTime())) return null;
    return utcDate;
}

/**
 * Convert a UTC datetime input to an ISO 8601 string with Z suffix.
 */
export function utcDatetimeInputToIso(value) {
    const utcDate = parseDatetimeLocalAsUtc(value);
    if (!utcDate) return null;
    return utcDate.toISOString();
}

/** @deprecated Prefer utcDatetimeInputToIso; kept as alias for existing call sites. */
export function datetimeLocalToUtcIso(value) {
    return utcDatetimeInputToIso(value);
}

export function findNearestTimeIndexUtc(timeValues, nowDate = new Date()) {
    if (!Array.isArray(timeValues) || timeValues.length === 0) return -1;
    const nowUtcDate = toUtcDate(nowDate);
    if (!nowUtcDate) return -1;

    let nearestIndex = -1;
    let smallestDiffMs = Number.POSITIVE_INFINITY;
    for (let i = 0; i < timeValues.length; i++) {
        const candidateDate = toUtcDate(timeValues[i]);
        if (!candidateDate) continue;
        const diffMs = Math.abs(candidateDate.getTime() - nowUtcDate.getTime());
        if (diffMs < smallestDiffMs) {
            smallestDiffMs = diffMs;
            nearestIndex = i;
        }
    }
    return nearestIndex;
}
