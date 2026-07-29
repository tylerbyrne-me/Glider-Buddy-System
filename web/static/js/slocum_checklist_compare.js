/**
 * Slocum daily checklist side-by-side compare (read-only).
 * Locks one submission as reference; navigates the other pane with arrows/picker.
 */
import { apiRequest, escapeHTML } from '/static/js/api.js';
import { formatUtcDateTime } from '/static/js/datetime_utils.js';

const TRUNCATE_LEN = 160;

/** @type {Array<{id:number, submission_timestamp?:string, submitted_by_username?:string, form_title?:string}>} */
let formsIndex = [];
/** Newest-first id list for navigation */
let orderedIds = [];
let referenceId = null;
let otherId = null;
let showChangedOnly = true;
let includeNotes = false;
let lastPayload = null;
let scrollSyncBound = false;
let syncingScroll = false;
let modalInstance = null;

function escapeHtml(value) {
    return escapeHTML(String(value ?? ''));
}

function formatTimestamp(value) {
    return value ? formatUtcDateTime(value) : '—';
}

function displayValue(value) {
    if (value == null || String(value).trim() === '') return '—';
    return String(value);
}

function formMetaById(id) {
    return formsIndex.find((f) => Number(f.id) === Number(id)) || null;
}

function defaultOtherId(refId) {
    const idx = orderedIds.indexOf(Number(refId));
    if (idx < 0) return null;
    // Prefer next-older (higher index in newest-first list)
    if (idx + 1 < orderedIds.length) return orderedIds[idx + 1];
    if (idx - 1 >= 0) return orderedIds[idx - 1];
    return null;
}

function buildPickerOptions() {
    const select = document.getElementById('slocumChecklistCompareSelect');
    if (!select) return;
    select.innerHTML = '';
    orderedIds.forEach((id) => {
        const meta = formMetaById(id);
        const opt = document.createElement('option');
        opt.value = String(id);
        const when = formatTimestamp(meta?.submission_timestamp);
        const who = meta?.submitted_by_username || 'Unknown';
        opt.textContent = `${when} · ${who}`;
        if (Number(id) === Number(referenceId)) {
            opt.disabled = true;
            opt.textContent += ' (reference)';
        }
        select.appendChild(opt);
    });
    if (otherId != null) select.value = String(otherId);
}

function updateNavButtons() {
    const prevBtn = document.getElementById('slocumChecklistComparePrevBtn');
    const nextBtn = document.getElementById('slocumChecklistCompareNextBtn');
    if (!prevBtn || !nextBtn) return;
    prevBtn.disabled = !canMoveOther('older');
    nextBtn.disabled = !canMoveOther('newer');
}

function canMoveOther(direction) {
    let idx = orderedIds.indexOf(Number(otherId));
    if (idx < 0) return false;
    const step = direction === 'older' ? 1 : -1;
    let next = idx + step;
    while (next >= 0 && next < orderedIds.length) {
        if (Number(orderedIds[next]) !== Number(referenceId)) return true;
        next += step;
    }
    return false;
}

function moveOther(direction) {
    // direction: 'older' | 'newer'
    let idx = orderedIds.indexOf(Number(otherId));
    if (idx < 0) return;
    const step = direction === 'older' ? 1 : -1;
    let next = idx + step;
    while (next >= 0 && next < orderedIds.length) {
        if (Number(orderedIds[next]) !== Number(referenceId)) {
            otherId = orderedIds[next];
            refreshCompare();
            return;
        }
        next += step;
    }
}

function renderPaneHeader(side, form) {
    const titleEl = document.getElementById(
        side === 'reference'
            ? 'slocumChecklistCompareRefTitle'
            : 'slocumChecklistCompareOtherTitle'
    );
    const metaEl = document.getElementById(
        side === 'reference'
            ? 'slocumChecklistCompareRefMeta'
            : 'slocumChecklistCompareOtherMeta'
    );
    if (!titleEl || !metaEl || !form) return;
    const when = formatTimestamp(form.submission_timestamp);
    const who = form.submitted_by_username || 'Unknown';
    titleEl.textContent =
        side === 'reference' ? `Reference · ${when}` : `Compare · ${when}`;
    let meta = `Submitted by ${who}`;
    if (form.edited_by_username) {
        meta += ` · Last edited by ${form.edited_by_username} at ${formatTimestamp(form.last_edited_timestamp)}`;
    }
    metaEl.textContent = meta;
}

function clampValueHtml(raw) {
    const text = displayValue(raw);
    if (text === '—' || text.length <= TRUNCATE_LEN) {
        return `<span class="slocum-checklist-compare-value">${escapeHtml(text)}</span>`;
    }
    const short = text.slice(0, TRUNCATE_LEN);
    return `
        <span class="slocum-checklist-compare-value is-clamped">
            <span class="slocum-checklist-compare-value-short">${escapeHtml(short)}…</span>
            <span class="slocum-checklist-compare-value-full" hidden>${escapeHtml(text)}</span>
            <button type="button" class="btn btn-link btn-sm p-0 ms-1 slocum-checklist-compare-expand">Show more</button>
        </span>
    `;
}

function buildItemLookup(sectionsData) {
    /** @type {Map<string, {sectionId:string, sectionTitle:string, item:object|null, sectionComment?:string}>} */
    const map = new Map();
    const sectionOrder = [];
    (sectionsData || []).forEach((section) => {
        if (!section?.id) return;
        const sid = String(section.id);
        sectionOrder.push({
            id: sid,
            title: section.title || sid,
            itemIds: (section.items || []).map((i) => String(i.id)).filter(Boolean),
            sectionComment: section.section_comment,
        });
        (section.items || []).forEach((item) => {
            if (!item?.id) return;
            map.set(String(item.id), {
                sectionId: sid,
                sectionTitle: section.title || sid,
                item,
            });
        });
        if (Object.prototype.hasOwnProperty.call(section, 'section_comment')) {
            map.set(`section:${sid}:comment`, {
                sectionId: sid,
                sectionTitle: section.title || sid,
                item: null,
                sectionComment: section.section_comment,
            });
        }
    });
    return { map, sectionOrder };
}

function mergeSectionOrder(refOrder, otherOrder) {
    const seen = new Set();
    const merged = [];
    refOrder.forEach((s) => {
        if (!seen.has(s.id)) {
            merged.push({ ...s, itemIds: [...s.itemIds] });
            seen.add(s.id);
        }
    });
    otherOrder.forEach((s) => {
        if (!seen.has(s.id)) {
            merged.push({ ...s, itemIds: [...s.itemIds] });
            seen.add(s.id);
            return;
        }
        const existing = merged.find((m) => m.id === s.id);
        s.itemIds.forEach((iid) => {
            if (!existing.itemIds.includes(iid)) existing.itemIds.push(iid);
        });
    });
    return merged;
}

function renderCompareBody(payload) {
    // Left = navigable compare (past); right = locked reference (present)
    const leftBody = document.getElementById('slocumChecklistCompareOtherBody');
    const rightBody = document.getElementById('slocumChecklistCompareRefBody');
    const countEl = document.getElementById('slocumChecklistCompareDiffCount');
    if (!leftBody || !rightBody) return;

    const changed = new Set(payload.changed_item_ids || []);
    if (countEl) {
        const n = payload.difference_count ?? changed.size;
        countEl.textContent = n === 1 ? '1 difference' : `${n} differences`;
    }

    const refLookup = buildItemLookup(payload.reference?.sections_data);
    const otherLookup = buildItemLookup(payload.other?.sections_data);
    const sections = mergeSectionOrder(refLookup.sectionOrder, otherLookup.sectionOrder);

    const leftParts = [];
    const rightParts = [];

    sections.forEach((section) => {
        const rowPartsLeft = [];
        const rowPartsRight = [];

        section.itemIds.forEach((itemId) => {
            const isChanged = changed.has(itemId);
            const commentChanged = changed.has(`${itemId}__comment`);
            if (showChangedOnly && !isChanged && !(includeNotes && commentChanged)) {
                return;
            }
            const refEntry = refLookup.map.get(itemId);
            const otherEntry = otherLookup.map.get(itemId);
            const label =
                refEntry?.item?.label ||
                otherEntry?.item?.label ||
                itemId;
            const changedClass = isChanged ? ' slocum-checklist-item-changed' : '';
            const refVal = refEntry?.item?.value;
            const otherVal = otherEntry?.item?.value;
            const refComment = refEntry?.item?.comment;
            const otherComment = otherEntry?.item?.comment;

            let refExtra = '';
            let otherExtra = '';
            if (includeNotes && (refComment || otherComment || commentChanged)) {
                const noteChangedClass = commentChanged
                    ? ' slocum-checklist-item-changed'
                    : '';
                refExtra = `<div class="slocum-checklist-compare-note small text-muted${noteChangedClass}">Note: ${escapeHtml(displayValue(refComment))}</div>`;
                otherExtra = `<div class="slocum-checklist-compare-note small text-muted${noteChangedClass}">Note: ${escapeHtml(displayValue(otherComment))}</div>`;
            }

            rowPartsLeft.push(`
                <div class="slocum-checklist-compare-row${changedClass}" data-item-id="${escapeHtml(itemId)}">
                    <div class="slocum-checklist-compare-label">${escapeHtml(label)}</div>
                    <div class="slocum-checklist-compare-value-wrap">${clampValueHtml(otherVal)}${otherExtra}</div>
                </div>
            `);
            rowPartsRight.push(`
                <div class="slocum-checklist-compare-row${changedClass}" data-item-id="${escapeHtml(itemId)}">
                    <div class="slocum-checklist-compare-label">${escapeHtml(label)}</div>
                    <div class="slocum-checklist-compare-value-wrap">${clampValueHtml(refVal)}${refExtra}</div>
                </div>
            `);
        });

        if (includeNotes) {
            const noteKey = `section:${section.id}:comment`;
            const noteChanged = changed.has(noteKey);
            if (!showChangedOnly || noteChanged) {
                const refNote = refLookup.map.get(noteKey)?.sectionComment;
                const otherNote = otherLookup.map.get(noteKey)?.sectionComment;
                const refHas = refLookup.map.has(noteKey);
                const otherHas = otherLookup.map.has(noteKey);
                if (refHas || otherHas || noteChanged) {
                    const noteClass = noteChanged ? ' slocum-checklist-item-changed' : '';
                    rowPartsLeft.push(`
                        <div class="slocum-checklist-compare-row${noteClass}" data-item-id="${escapeHtml(noteKey)}">
                            <div class="slocum-checklist-compare-label">Section notes</div>
                            <div class="slocum-checklist-compare-value-wrap">${clampValueHtml(otherNote)}</div>
                        </div>
                    `);
                    rowPartsRight.push(`
                        <div class="slocum-checklist-compare-row${noteClass}" data-item-id="${escapeHtml(noteKey)}">
                            <div class="slocum-checklist-compare-label">Section notes</div>
                            <div class="slocum-checklist-compare-value-wrap">${clampValueHtml(refNote)}</div>
                        </div>
                    `);
                }
            }
        }

        if (rowPartsLeft.length === 0) return;

        leftParts.push(`
            <div class="slocum-checklist-compare-section" data-section-id="${escapeHtml(section.id)}">
                <h6 class="slocum-checklist-compare-section-title">${escapeHtml(section.title)}</h6>
                ${rowPartsLeft.join('')}
            </div>
        `);
        rightParts.push(`
            <div class="slocum-checklist-compare-section" data-section-id="${escapeHtml(section.id)}">
                <h6 class="slocum-checklist-compare-section-title">${escapeHtml(section.title)}</h6>
                ${rowPartsRight.join('')}
            </div>
        `);
    });

    if (leftParts.length === 0) {
        const emptyMsg = showChangedOnly
            ? '<p class="text-muted small mb-0">No differences for the current filters.</p>'
            : '<p class="text-muted small mb-0">No checklist items to display.</p>';
        leftBody.innerHTML = emptyMsg;
        rightBody.innerHTML = emptyMsg;
        return;
    }

    leftBody.innerHTML = leftParts.join('');
    rightBody.innerHTML = rightParts.join('');
}

async function refreshCompare() {
    const statusEl = document.getElementById('slocumChecklistCompareStatus');
    const leftBody = document.getElementById('slocumChecklistCompareOtherBody');
    const rightBody = document.getElementById('slocumChecklistCompareRefBody');
    if (referenceId == null || otherId == null) {
        if (statusEl) {
            statusEl.textContent = 'Select another checklist to compare.';
        }
        if (leftBody) leftBody.innerHTML = '';
        if (rightBody) rightBody.innerHTML = '';
        return;
    }
    if (statusEl) statusEl.textContent = 'Loading comparison…';
    buildPickerOptions();
    updateNavButtons();
    try {
        const params = new URLSearchParams({
            reference_id: String(referenceId),
            other_id: String(otherId),
            include_notes: includeNotes ? 'true' : 'false',
        });
        const payload = await apiRequest(
            `/api/slocum/checklists/compare?${params.toString()}`,
            'GET'
        );
        lastPayload = payload;
        renderPaneHeader('reference', payload.reference);
        renderPaneHeader('other', payload.other);
        renderCompareBody(payload);
        if (statusEl) statusEl.textContent = '';
        // Reset scroll tops together
        const refScroll = document.getElementById('slocumChecklistCompareRefScroll');
        const otherScroll = document.getElementById('slocumChecklistCompareOtherScroll');
        if (refScroll) refScroll.scrollTop = 0;
        if (otherScroll) otherScroll.scrollTop = 0;
    } catch (err) {
        if (statusEl) {
            statusEl.textContent = `Failed to compare: ${err.message || err}`;
        }
        if (leftBody) leftBody.innerHTML = '';
        if (rightBody) rightBody.innerHTML = '';
    }
}

function bindScrollSync() {
    if (scrollSyncBound) return;
    const refScroll = document.getElementById('slocumChecklistCompareRefScroll');
    const otherScroll = document.getElementById('slocumChecklistCompareOtherScroll');
    if (!refScroll || !otherScroll) return;

    const sync = (source, target) => {
        if (syncingScroll) return;
        syncingScroll = true;
        target.scrollTop = source.scrollTop;
        syncingScroll = false;
    };
    refScroll.addEventListener('scroll', () => sync(refScroll, otherScroll));
    otherScroll.addEventListener('scroll', () => sync(otherScroll, refScroll));
    scrollSyncBound = true;
}

function bindExpandDelegation() {
    const modal = document.getElementById('slocumChecklistCompareModal');
    if (!modal || modal.dataset.expandBound === '1') return;
    modal.addEventListener('click', (e) => {
        const btn = e.target.closest('.slocum-checklist-compare-expand');
        if (!btn) return;
        const wrap = btn.closest('.slocum-checklist-compare-value');
        if (!wrap) return;
        const short = wrap.querySelector('.slocum-checklist-compare-value-short');
        const full = wrap.querySelector('.slocum-checklist-compare-value-full');
        const expanding = full && full.hasAttribute('hidden');
        if (expanding) {
            if (short) short.hidden = true;
            if (full) full.removeAttribute('hidden');
            btn.textContent = 'Show less';
        } else {
            if (short) short.hidden = false;
            if (full) full.setAttribute('hidden', '');
            btn.textContent = 'Show more';
        }
    });
    modal.dataset.expandBound = '1';
}

function bindControlsOnce() {
    const modal = document.getElementById('slocumChecklistCompareModal');
    if (!modal || modal.dataset.controlsBound === '1') return;

    document.getElementById('slocumChecklistComparePrevBtn')?.addEventListener('click', () => {
        moveOther('older');
    });
    document.getElementById('slocumChecklistCompareNextBtn')?.addEventListener('click', () => {
        moveOther('newer');
    });
    document.getElementById('slocumChecklistCompareSelect')?.addEventListener('change', (e) => {
        const val = Number(e.target.value);
        if (!Number.isFinite(val) || val === Number(referenceId)) return;
        otherId = val;
        refreshCompare();
    });
    document.getElementById('slocumChecklistCompareSwapBtn')?.addEventListener('click', () => {
        if (referenceId == null || otherId == null) return;
        const tmp = referenceId;
        referenceId = otherId;
        otherId = tmp;
        refreshCompare();
    });
    document.getElementById('slocumChecklistCompareChangedOnly')?.addEventListener('change', (e) => {
        showChangedOnly = Boolean(e.target.checked);
        if (lastPayload) renderCompareBody(lastPayload);
    });
    document.getElementById('slocumChecklistCompareIncludeNotes')?.addEventListener('change', (e) => {
        includeNotes = Boolean(e.target.checked);
        refreshCompare();
    });

    modal.dataset.controlsBound = '1';
}

/**
 * Open the compare modal with a locked reference submission.
 * @param {{ forms: Array<object>, referenceId: number }} opts
 */
export function openSlocumChecklistCompare({ forms, referenceId: refId }) {
    const list = Array.isArray(forms) ? forms : [];
    if (list.length < 2) return;

    formsIndex = list.map((f) => ({
        id: Number(f.id),
        submission_timestamp: f.submission_timestamp,
        submitted_by_username: f.submitted_by_username,
        form_title: f.form_title,
    }));
    orderedIds = formsIndex.map((f) => f.id);
    referenceId = Number(refId);
    otherId = defaultOtherId(referenceId);

    const changedOnlyEl = document.getElementById('slocumChecklistCompareChangedOnly');
    const includeNotesEl = document.getElementById('slocumChecklistCompareIncludeNotes');
    if (changedOnlyEl) {
        changedOnlyEl.checked = true;
        showChangedOnly = true;
    }
    if (includeNotesEl) {
        includeNotesEl.checked = false;
        includeNotes = false;
    }

    bindControlsOnce();
    bindScrollSync();
    bindExpandDelegation();

    const modalEl = document.getElementById('slocumChecklistCompareModal');
    if (modalEl && window.bootstrap) {
        modalInstance = bootstrap.Modal.getOrCreateInstance(modalEl);
        modalInstance.show();
    }

    refreshCompare();
}
