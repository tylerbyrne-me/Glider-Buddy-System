import { apiRequest, showToast } from '/static/js/api.js';

const RELATION_LABELS = {
    deployments: 'Deployments',
    loggers: 'Loggers',
    instruments: 'Instruments',
    sensors: 'Sensors',
    platform: 'Platform',
    platforms: 'Platforms',
    components: 'Components',
};

document.addEventListener('DOMContentLoaded', () => {
    const statusEl = document.getElementById('stStatus');
    const tabsEl = document.getElementById('stEntityTabs');
    const searchForm = document.getElementById('stSearchForm');
    const searchInput = document.getElementById('stSearchInput');
    const searchHint = document.getElementById('stSearchHint');
    const asOfWrap = document.getElementById('stAsOfWrap');
    const asOfInput = document.getElementById('stAsOfInput');
    const clearBtn = document.getElementById('stClearBtn');
    const resultsHead = document.getElementById('stResultsHead');
    const resultsBody = document.getElementById('stResultsBody');
    const pageInfo = document.getElementById('stPageInfo');
    const prevBtn = document.getElementById('stPrevBtn');
    const nextBtn = document.getElementById('stNextBtn');
    const detailBody = document.getElementById('stDetailBody');

    const state = {
        meta: null,
        entity: 'platform',
        q: '',
        page: 1,
        pageSize: 25,
        hasNext: false,
        hasPrev: false,
        selectedId: null,
        columns: ['id'],
        relatedRelation: null,
        currentAttached: true,
    };

    const escapeHtml = (value) => {
        const div = document.createElement('div');
        div.textContent = value == null ? '' : String(value);
        return div.innerHTML;
    };

    const availableEntities = () => {
        const all = (state.meta && state.meta.entities) || [];
        return all.filter((item) => item.available);
    };

    const specFor = (key) => availableEntities().find((item) => item.key === key)
        || ((state.meta && state.meta.entities) || []).find((item) => item.key === key);

    const writeUrl = () => {
        const params = new URLSearchParams();
        params.set('type', state.entity);
        if (state.q) params.set('q', state.q);
        if (state.page > 1) params.set('page', String(state.page));
        if (state.selectedId != null) params.set('id', String(state.selectedId));
        const asOf = (asOfInput.value || '').trim();
        if (asOf) params.set('as_of', asOf);
        const next = `${window.location.pathname}?${params.toString()}`;
        window.history.replaceState({}, '', next);
    };

    const readUrl = () => {
        const params = new URLSearchParams(window.location.search);
        state.entity = params.get('type') || 'platform';
        state.q = params.get('q') || '';
        state.page = Math.max(1, parseInt(params.get('page') || '1', 10) || 1);
        const id = params.get('id');
        state.selectedId = id ? parseInt(id, 10) : null;
        if (state.selectedId != null && !state.q) {
            state.q = String(state.selectedId);
            searchInput.value = state.q;
        }
        if (params.get('as_of')) asOfInput.value = params.get('as_of');
    };

    const setStatus = (connected, host, error) => {
        statusEl.classList.remove('alert-secondary', 'alert-success', 'alert-danger', 'alert-warning');
        if (connected) {
            statusEl.classList.add('alert-success');
            statusEl.textContent = `Connected to ${host || 'Sensor Tracker'} (live).`;
        } else {
            statusEl.classList.add('alert-danger');
            statusEl.textContent = error
                ? `Sensor Tracker unreachable: ${error}`
                : 'Sensor Tracker unreachable.';
        }
    };

    const renderTabs = () => {
        const entities = availableEntities();
        if (!entities.length) {
            tabsEl.innerHTML = '<li class="nav-item"><span class="nav-link disabled">No entity types available</span></li>';
            return;
        }
        if (!entities.some((item) => item.key === state.entity) && state.selectedId == null) {
            state.entity = entities[0].key;
        }
        tabsEl.innerHTML = entities.map((item) => `
            <li class="nav-item" role="presentation">
                <button type="button" class="nav-link ${item.key === state.entity ? 'active' : ''}"
                    data-entity="${escapeHtml(item.key)}">${escapeHtml(item.label)}</button>
            </li>
        `).join('');
        const spec = specFor(state.entity);
        searchHint.textContent = spec ? spec.search_hint : '';
        const hasRelations = !!(spec && spec.relations && spec.relations.length);
        asOfWrap.style.display = hasRelations ? 'block' : 'none';
    };

    const renderHead = () => {
        const spec = specFor(state.entity);
        state.columns = (spec && spec.columns && spec.columns.length) ? spec.columns : ['id', 'title'];
        resultsHead.innerHTML = state.columns.map((col) => `<th>${escapeHtml(col.replace(/_/g, ' '))}</th>`).join('');
    };

    const renderRows = (results) => {
        if (!results || !results.length) {
            resultsBody.innerHTML = `<tr><td colspan="${state.columns.length}" class="text-muted">No results.</td></tr>`;
            return;
        }
        resultsBody.innerHTML = results.map((row) => {
            const selected = row.id != null && row.id === state.selectedId;
            const cells = state.columns.map((col) => {
                const value = col === 'id' ? row.id : (row.cells && row.cells[col]);
                return `<td>${escapeHtml(value == null ? '' : value)}</td>`;
            }).join('');
            return `<tr class="${selected ? 'table-active' : ''}" data-id="${row.id == null ? '' : row.id}" style="cursor: pointer;">${cells}</tr>`;
        }).join('');
    };

    const renderPager = (payload) => {
        state.hasNext = !!payload.has_next;
        state.hasPrev = !!payload.has_prev;
        prevBtn.disabled = !state.hasPrev;
        nextBtn.disabled = !state.hasNext;
        const count = typeof payload.count === 'number' ? payload.count : (payload.results || []).length;
        pageInfo.textContent = `${count} result${count === 1 ? '' : 's'} · page ${payload.page || state.page}`;
    };

    const relationLabel = (key) => RELATION_LABELS[key] || key;

    const asOfParam = () => {
        const value = (asOfInput.value || '').trim();
        if (!value) return '';
        return `&as_of=${encodeURIComponent(value.replace('T', ' '))}`;
    };

    const relatedQuery = () => {
        const current = state.currentAttached ? 'true' : 'false';
        return `?page=1&page_size=50&current=${current}${asOfParam()}`;
    };

    const timeKey = (value) => {
        if (value == null || value === '') return '';
        return String(value).trim().replace('T', ' ');
    };

    const isCurrentlyAttached = (row, asOf) => {
        const start = timeKey(row && row.start_time);
        const end = timeKey(row && row.end_time);
        const asOfKey = timeKey(asOf);
        if (asOfKey && start && start > asOfKey) return false;
        if (!end) return true;
        if (!asOfKey) return false;
        return end > asOfKey;
    };

    const visibleRelatedRows = (rows, asOf) => {
        const source = Array.isArray(rows) ? rows.slice() : [];
        const filtered = state.currentAttached
            ? source.filter((row) => isCurrentlyAttached(row, asOf))
            : source;
        if (!state.currentAttached) return filtered;
        return filtered.sort((a, b) => {
            const aOpen = !timeKey(a.end_time);
            const bOpen = !timeKey(b.end_time);
            if (aOpen !== bOpen) return aOpen ? -1 : 1;
            return timeKey(b.start_time).localeCompare(timeKey(a.start_time));
        });
    };

    const syncRelButtons = () => {
        document.querySelectorAll('.st-rel-btn').forEach((btn) => {
            const isOpen = btn.dataset.rel === state.relatedRelation;
            btn.classList.toggle('btn-primary', isOpen);
            btn.classList.toggle('btn-outline-primary', !isOpen);
            btn.setAttribute('aria-pressed', isOpen ? 'true' : 'false');
        });
    };

    const collapseRelated = () => {
        state.relatedRelation = null;
        const wrap = document.getElementById('stRelResults');
        if (wrap) wrap.innerHTML = '';
        syncRelButtons();
    };

    const renderDetail = (detail) => {
        if (!detail) {
            detailBody.innerHTML = '<p class="text-muted mb-0">Select a row to inspect it.</p>';
            return;
        }
        const summaryRows = Object.entries(detail.summary || {}).map(([key, value]) => `
            <tr><th class="text-nowrap">${escapeHtml(key.replace(/_/g, ' '))}</th>
            <td>${escapeHtml(value == null ? '' : value)}</td></tr>
        `).join('');
        const buddy = detail.buddy;
        const buddyHtml = buddy
            ? `<div class="alert alert-info py-2 small mb-3">
                    Synced in Buddy as <strong>${escapeHtml(buddy.mission_id)}</strong>
                    ${buddy.sync_status ? ` · ${escapeHtml(buddy.sync_status)}` : ''}
                    ${buddy.last_synced_at ? ` · ${escapeHtml(buddy.last_synced_at)}` : ''}
               </div>`
            : (detail.entity === 'deployment'
                ? '<p class="small text-muted">Not synced into a Buddy mission yet.</p>'
                : '');
        const links = [];
        if (detail.st_web_url) {
            links.push(`<a href="${escapeHtml(detail.st_web_url)}" target="_blank" rel="noopener noreferrer">Open in Sensor Tracker</a>`);
        }
        if (detail.st_api_url && detail.st_api_url !== detail.st_web_url) {
            links.push(`<a href="${escapeHtml(detail.st_api_url)}" target="_blank" rel="noopener noreferrer">API JSON</a>`);
        }
        const relations = (detail.relations || []).map((rel) => `
            <button type="button" class="btn btn-sm btn-outline-primary me-1 mb-1 st-rel-btn" data-rel="${escapeHtml(rel)}" aria-pressed="false">
                ${escapeHtml(relationLabel(rel))}
            </button>
        `).join('');
        let rawText = '';
        try {
            rawText = JSON.stringify(detail.raw || {}, null, 2);
        } catch {
            rawText = String(detail.raw || '');
        }
        detailBody.innerHTML = `
            <h3 class="h5 mb-1">${escapeHtml(detail.title || '')}</h3>
            <p class="small text-muted mb-2">${escapeHtml(detail.entity)} ${detail.id == null ? '' : `#${detail.id}`}</p>
            ${buddyHtml}
            <div class="mb-2">${links.join(' · ')}</div>
            <div class="table-responsive mb-3">
                <table class="table table-sm mb-0"><tbody>${summaryRows}</tbody></table>
            </div>
            <div id="stAnalytics" class="mb-3">
                <p class="small text-muted mb-0">Loading service time&hellip;</p>
            </div>
            <h4 class="h6">Related</h4>
            <div id="stRelButtons" class="mb-2">${relations || '<span class="text-muted small">None</span>'}</div>
            <div id="stRelResults"></div>
            <details class="mt-3">
                <summary class="small text-muted">Raw JSON</summary>
                <pre class="bg-body-secondary p-2 rounded small mt-2 mb-0" style="max-height: 18rem; overflow: auto;">${escapeHtml(rawText)}</pre>
            </details>
        `;
    };

    const renderAnalytics = (payload) => {
        const wrap = document.getElementById('stAnalytics');
        if (!wrap) return;
        const metrics = payload.metrics || [];
        const notes = payload.notes || [];
        if (!metrics.length && !notes.length) {
            wrap.innerHTML = '';
            return;
        }
        const rows = metrics.map((item) => `
            <tr>
                <th class="text-nowrap">${escapeHtml(item.label || item.key)}</th>
                <td>${escapeHtml(item.value == null ? '—' : item.value)}</td>
            </tr>
        `).join('');
        const noteHtml = notes.length
            ? `<p class="small text-muted mb-0">${notes.map((note) => escapeHtml(note)).join(' ')}</p>`
            : '';
        wrap.innerHTML = `
            <h4 class="h6 mb-2">Service time</h4>
            ${rows ? `<div class="table-responsive mb-2">
                <table class="table table-sm mb-0"><tbody>${rows}</tbody></table>
            </div>` : ''}
            ${noteHtml}
            ${payload.as_of ? `<p class="small text-muted mb-0">As of ${escapeHtml(payload.as_of)}</p>` : ''}
        `;
    };

    const loadAnalytics = async (entity, id) => {
        const wrap = document.getElementById('stAnalytics');
        if (!wrap || !entity || id == null) return;
        const seq = (state.analyticsSeq = (state.analyticsSeq || 0) + 1);
        try {
            const payload = await apiRequest(
                `/api/team/sensor-tracker/${encodeURIComponent(entity)}/${id}/analytics`,
                'GET'
            );
            if (seq !== state.analyticsSeq) return;
            renderAnalytics(payload);
        } catch (err) {
            if (seq !== state.analyticsSeq) return;
            wrap.innerHTML = `<p class="small text-muted mb-0">Service time unavailable: ${escapeHtml(err.message || String(err))}</p>`;
        }
    };

    const renderRelated = (payload) => {
        const wrap = document.getElementById('stRelResults');
        if (!wrap) return;
        const asOf = (asOfInput.value || '').trim();
        const rows = visibleRelatedRows(payload.results || [], asOf);
        const filterNote = state.currentAttached
            ? (asOf ? `currently attached as of ${asOf.replace('T', ' ')}` : 'currently attached (no end date)')
            : 'full history';
        const items = rows.length
            ? `<ul class="list-unstyled mb-0">
                ${rows.map((row) => {
                    const start = row.start_time;
                    const end = row.end_time;
                    let when = '';
                    if (start && end) when = `${start} → ${end}`;
                    else if (start) when = `${start} → current`;
                    else if (end) when = `until ${end}`;
                    else if (state.currentAttached) when = 'current';
                    const disabled = row.id == null ? ' disabled' : '';
                    return `<li class="mb-1">
                        <button type="button" class="btn btn-link btn-sm p-0 st-goto-btn"${disabled}
                            data-entity="${escapeHtml(row.entity)}" data-id="${row.id == null ? '' : row.id}">
                            ${escapeHtml(row.title)}
                        </button>
                        ${when ? `<span class="small text-muted"> · ${escapeHtml(when)}</span>` : ''}
                    </li>`;
                }).join('')}
            </ul>`
            : `<p class="small text-muted mb-0">No ${escapeHtml(filterNote)} records.</p>`;
        wrap.innerHTML = `
            <div class="d-flex flex-wrap align-items-center gap-2 mb-2">
                <p class="small text-muted mb-0">${escapeHtml(relationLabel(payload.relation))} (${rows.length}) · ${escapeHtml(filterNote)}</p>
                <button type="button" class="btn btn-sm btn-outline-secondary st-rel-collapse">Hide</button>
            </div>
            <div class="form-check mb-2">
                <input class="form-check-input" type="checkbox" id="stCurrentAttached" ${state.currentAttached ? 'checked' : ''}>
                <label class="form-check-label small" for="stCurrentAttached">Currently attached (no end date)</label>
            </div>
            ${items}
        `;
        syncRelButtons();
    };

    const loadRelated = async (relation) => {
        if (state.selectedId == null) return;
        const wrap = document.getElementById('stRelResults');
        if (wrap) wrap.innerHTML = '<p class="small text-muted">Loading&hellip;</p>';
        try {
            const payload = await apiRequest(
                `/api/team/sensor-tracker/${encodeURIComponent(state.entity)}/${state.selectedId}/related/${encodeURIComponent(relation)}${relatedQuery()}`,
                'GET'
            );
            state.relatedRelation = relation;
            renderRelated(payload);
        } catch (err) {
            state.relatedRelation = relation;
            if (wrap) wrap.innerHTML = `<p class="small text-danger mb-0">${escapeHtml(err.message || String(err))}</p>`;
            syncRelButtons();
        }
    };

    const loadDetail = async (id) => {
        state.selectedId = id;
        writeUrl();
        detailBody.innerHTML = '<p class="text-muted mb-0">Loading&hellip;</p>';
        try {
            const detail = await apiRequest(
                `/api/team/sensor-tracker/${encodeURIComponent(state.entity)}/${id}`,
                'GET'
            );
            state.relatedRelation = null;
            renderDetail(detail);
            loadAnalytics(detail.entity, detail.id);
        } catch (err) {
            detailBody.innerHTML = `<p class="text-danger mb-0">${escapeHtml(err.message || String(err))}</p>`;
            showToast(err.message || 'Failed to load detail.', 'danger');
        }
    };

    const loadList = async () => {
        renderHead();
        resultsBody.innerHTML = `<tr><td colspan="${state.columns.length}" class="text-center"><div class="spinner-border spinner-border-sm" role="status"></div></td></tr>`;
        const params = new URLSearchParams();
        if (state.q) params.set('q', state.q);
        params.set('page', String(state.page));
        params.set('page_size', String(state.pageSize));
        try {
            const payload = await apiRequest(
                `/api/team/sensor-tracker/${encodeURIComponent(state.entity)}?${params.toString()}`,
                'GET'
            );
            renderRows(payload.results || []);
            renderPager(payload);
            if (state.selectedId != null) {
                await loadDetail(state.selectedId);
            } else {
                renderDetail(null);
            }
        } catch (err) {
            resultsBody.innerHTML = `<tr><td colspan="${state.columns.length}" class="text-danger">${escapeHtml(err.message || String(err))}</td></tr>`;
            pageInfo.textContent = '';
            prevBtn.disabled = true;
            nextBtn.disabled = true;
            showToast(err.message || 'Search failed.', 'danger');
        }
        writeUrl();
    };

    const switchEntity = (key, { keepQuery = false } = {}) => {
        state.entity = key;
        state.page = 1;
        state.selectedId = null;
        if (!keepQuery) state.q = '';
        searchInput.value = state.q;
        renderTabs();
        loadList();
    };

    tabsEl.addEventListener('click', (event) => {
        const button = event.target.closest('[data-entity]');
        if (!button) return;
        switchEntity(button.dataset.entity);
    });

    resultsBody.addEventListener('click', (event) => {
        const row = event.target.closest('tr[data-id]');
        if (!row || row.dataset.id === '') return;
        const id = parseInt(row.dataset.id, 10);
        if (Number.isNaN(id)) return;
        Array.from(resultsBody.querySelectorAll('tr')).forEach((el) => el.classList.remove('table-active'));
        row.classList.add('table-active');
        loadDetail(id);
    });

    detailBody.addEventListener('click', (event) => {
        const collapseBtn = event.target.closest('.st-rel-collapse');
        if (collapseBtn) {
            collapseRelated();
            return;
        }
        const relBtn = event.target.closest('.st-rel-btn');
        if (relBtn) {
            const relation = relBtn.dataset.rel;
            if (state.relatedRelation === relation) {
                collapseRelated();
                return;
            }
            loadRelated(relation);
            return;
        }
        const gotoBtn = event.target.closest('.st-goto-btn');
        if (!gotoBtn || !gotoBtn.dataset.entity || !gotoBtn.dataset.id) return;
        state.entity = gotoBtn.dataset.entity;
        state.selectedId = parseInt(gotoBtn.dataset.id, 10);
        state.q = String(state.selectedId);
        state.page = 1;
        state.relatedRelation = null;
        searchInput.value = state.q;
        renderTabs();
        loadList();
    });

    detailBody.addEventListener('change', (event) => {
        const checkbox = event.target.closest('#stCurrentAttached');
        if (!checkbox) return;
        state.currentAttached = checkbox.checked;
        if (state.relatedRelation) loadRelated(state.relatedRelation);
    });

    searchForm.addEventListener('submit', (event) => {
        event.preventDefault();
        state.q = (searchInput.value || '').trim();
        state.page = 1;
        state.selectedId = null;
        loadList();
    });

    clearBtn.addEventListener('click', () => {
        searchInput.value = '';
        asOfInput.value = '';
        state.q = '';
        state.page = 1;
        state.selectedId = null;
        state.relatedRelation = null;
        loadList();
    });

    asOfInput.addEventListener('change', () => {
        writeUrl();
        if (state.relatedRelation) loadRelated(state.relatedRelation);
    });

    prevBtn.addEventListener('click', () => {
        if (!state.hasPrev) return;
        state.page = Math.max(1, state.page - 1);
        state.selectedId = null;
        loadList();
    });

    nextBtn.addEventListener('click', () => {
        if (!state.hasNext) return;
        state.page += 1;
        state.selectedId = null;
        loadList();
    });

    (async () => {
        readUrl();
        try {
            state.meta = await apiRequest('/api/team/sensor-tracker/meta', 'GET');
            setStatus(state.meta.connected, state.meta.host, state.meta.error);
            renderTabs();
            await loadList();
        } catch (err) {
            setStatus(false, '', err.message || String(err));
            showToast(err.message || 'Failed to load Sensor Tracker metadata.', 'danger');
        }
    })();
});
