import { apiRequest, showToast } from '/static/js/api.js';

document.addEventListener('DOMContentLoaded', () => {
    const state = {
        units: [],
        selectedId: null,
        detailSeq: 0,
        loadSeq: 0,
        syncDryRunOk: false,
        lastSyncPreview: null,
    };

    const tableBody = document.getElementById('vmtTableBody');
    const detailBody = document.getElementById('vmtDetailBody');
    const countBadge = document.getElementById('vmtCountBadge');
    const filterInput = document.getElementById('vmtFilter');
    const filterCustody = document.getElementById('vmtFilterCustody');
    const filterLink = document.getElementById('vmtFilterLink');
    const includeInactive = document.getElementById('vmtIncludeInactive');
    const syncSummary = document.getElementById('vmtSyncSummary');
    const syncApplyBtn = document.getElementById('vmtSyncApplyBtn');

    const unitModalEl = document.getElementById('vmtUnitModal');
    const batteryModalEl = document.getElementById('vmtBatteryModal');
    const serviceModalEl = document.getElementById('vmtServiceModal');
    const unitModal = unitModalEl ? new bootstrap.Modal(unitModalEl) : null;
    const batteryModal = batteryModalEl ? new bootstrap.Modal(batteryModalEl) : null;
    const serviceModal = serviceModalEl ? new bootstrap.Modal(serviceModalEl) : null;

    const escapeHtml = (value) => {
        const div = document.createElement('div');
        div.textContent = value == null ? '' : String(value);
        return div.innerHTML;
    };

    const custodyLabel = (value) => {
        const map = {
            on_loan: 'On loan',
            cove: 'COVE',
            servicing: 'Servicing',
            missing: 'Missing',
            lost: 'Lost',
            other: 'Other',
        };
        return map[value] || value || '—';
    };

    const AUDIT_FIELD_LABELS = {
        tag_id: 'Tag ID',
        code_map: 'Code map',
        always_tx: 'Always Tx',
        comments: 'Comments',
        custody_status: 'Custody',
        custody_status_other: 'Custody note',
        sensor_tracker_instrument_id: 'ST instrument id',
        is_active: 'Active',
    };

    const formatAuditWhen = (value) => {
        if (!value) return '—';
        const text = String(value);
        const match = text.match(/^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2})/);
        if (match) return `${match[1]} ${match[2]}`;
        return text;
    };

    const formatAuditValue = (field, value) => {
        if (value == null || value === '') return '(empty)';
        if (field === 'custody_status') return custodyLabel(value);
        if (field === 'always_tx' || field === 'is_active') return value ? 'Yes' : 'No';
        return String(value);
    };

    const formatAuditChanges = (changes) => {
        const entries = Object.entries(changes || {});
        if (!entries.length) return '<span class="text-muted">No field changes</span>';
        return `<ul class="list-unstyled mb-0 ms-2">
            ${entries.map(([field, delta]) => {
                const label = AUDIT_FIELD_LABELS[field] || field.replace(/_/g, ' ');
                const after = formatAuditValue(field, delta?.after);
                return `<li><span class="text-muted">${escapeHtml(label)}:</span> ${escapeHtml(after)}</li>`;
            }).join('')}
        </ul>`;
    };

    const linkBadge = (unit) => {
        const status = unit.sensor_tracker_link_status || 'never_linked';
        if (status === 'linked') {
            const href = unit.st_browser_url
                ? `<a href="${escapeHtml(unit.st_browser_url)}">#${escapeHtml(unit.sensor_tracker_instrument_id)}</a>`
                : 'linked';
            return `<span class="badge text-bg-success">linked ${href}</span>`;
        }
        if (status === 'not_found') {
            return `<span class="badge text-bg-warning">ST link lost</span>`;
        }
        if (status === 'stale') {
            return `<span class="badge text-bg-warning">stale</span>`;
        }
        return `<span class="badge text-bg-secondary">never linked</span>`;
    };

    const locationCell = (unit) => {
        if (unit.is_attached) {
            return `<span class="badge text-bg-info">Attached: ${escapeHtml(unit.attached_platform_name || 'platform')}</span>`;
        }
        if (unit.custody_status === 'other' && unit.custody_status_other) {
            return escapeHtml(`Other: ${unit.custody_status_other}`);
        }
        return escapeHtml(custodyLabel(unit.custody_status));
    };

    const batteryCell = (unit) => {
        const pct = unit.latest_percent_remaining;
        const days = unit.latest_days_remaining;
        const checked = unit.latest_battery_checked_at || '';
        if (pct == null && days == null) return '—';
        const warn = unit.low_battery ? ' text-danger fw-semibold' : '';
        return `<span class="${warn}">${escapeHtml(pct == null ? '—' : `${pct}%`)} / ${escapeHtml(days == null ? '—' : `${days}d`)}</span>`
            + (checked ? `<div class="small text-muted">${escapeHtml(checked)}</div>` : '');
    };

    const filteredUnits = () => {
        const q = (filterInput.value || '').trim().toLowerCase();
        const custody = filterCustody.value;
        const link = filterLink.value;
        return state.units.filter((unit) => {
            if (custody === 'attached' && !unit.is_attached) return false;
            if (custody && custody !== 'attached' && unit.custody_status !== custody) return false;
            if (link && unit.sensor_tracker_link_status !== link) return false;
            if (!q) return true;
            const hay = [
                unit.serial_number,
                unit.tag_id,
                unit.comments,
                unit.attached_platform_name,
                unit.custody_status,
            ].map((v) => (v == null ? '' : String(v).toLowerCase())).join(' ');
            return hay.includes(q);
        });
    };

    const renderTable = () => {
        const rows = filteredUnits();
        countBadge.textContent = String(rows.length);
        if (!rows.length) {
            tableBody.innerHTML = '<tr><td colspan="6" class="text-muted p-3">No VMTs match.</td></tr>';
            return;
        }
        tableBody.innerHTML = rows.map((unit) => `
            <tr data-id="${unit.id}" class="${unit.id === state.selectedId ? 'table-active' : ''}" style="cursor:pointer;">
                <td><code>${escapeHtml(unit.serial_number)}</code></td>
                <td>${escapeHtml(unit.tag_id || '—')}</td>
                <td>${locationCell(unit)}</td>
                <td>${batteryCell(unit)}</td>
                <td>${unit.always_tx ? 'Y' : 'N'}</td>
                <td>${linkBadge(unit)}</td>
            </tr>
        `).join('');
    };

    const renderMetrics = (analytics) => {
        if (!analytics || !(analytics.metrics || []).length) {
            return '<p class="small text-muted mb-0">No service-time metrics.</p>';
        }
        const rows = (analytics.metrics || []).map((m) => `
            <tr><th class="text-nowrap">${escapeHtml(m.label || m.key)}</th>
            <td>${escapeHtml(m.value == null ? '—' : m.value)}</td></tr>
        `).join('');
        const notes = (analytics.notes || []).length
            ? `<p class="small text-muted mt-2 mb-0">${analytics.notes.map(escapeHtml).join(' ')}</p>`
            : '';
        return `<div class="table-responsive"><table class="table table-sm mb-0"><tbody>${rows}</tbody></table></div>${notes}`;
    };

    const renderAttachmentHistory = (rows) => {
        if (!rows || !rows.length) {
            return '<p class="small text-muted mb-0">No attachment history.</p>';
        }
        return `<ul class="list-unstyled small mb-0">
            ${rows.map((row) => `
                <li class="mb-1">
                    <strong>${escapeHtml(row.platform_name || row.platform_serial || (row.platform_id != null ? `#${row.platform_id}` : '—'))}</strong>
                    ${row.currently_open ? '<span class="badge text-bg-info ms-1">open</span>' : ''}
                    <span class="text-muted"> · ${escapeHtml(row.start_time || '?')} → ${escapeHtml(row.end_time || 'open')}</span>
                    ${row.via ? `<span class="text-muted"> · via ${escapeHtml(row.via)}</span>` : ''}
                </li>
            `).join('')}
        </ul>`;
    };

    const renderDetail = async (unitId) => {
        const seq = (state.detailSeq += 1);
        state.selectedId = unitId;
        renderTable();
        detailBody.innerHTML = '<p class="text-muted mb-0">Loading detail&hellip;</p>';
        try {
            const detail = await apiRequest(`/api/team/vmt-logbook/units/${unitId}`, 'GET');
            if (seq !== state.detailSeq || state.selectedId !== unitId) return;
            let accountingHtml = '<p class="small text-muted mb-0">Loading Sensor Tracker accounting&hellip;</p>';
            detailBody.innerHTML = `
                <div class="d-flex flex-wrap gap-2 mb-3">
                    <button type="button" class="btn btn-sm btn-outline-primary" id="vmtEditBtn">Edit</button>
                    <button type="button" class="btn btn-sm btn-outline-secondary" id="vmtAddBattBtn">Battery check</button>
                    <button type="button" class="btn btn-sm btn-outline-secondary" id="vmtAddSvcBtn">Service event</button>
                    ${detail.st_browser_url
                        ? `<a class="btn btn-sm btn-outline-info" href="${escapeHtml(detail.st_browser_url)}">Open in ST browser</a>`
                        : ''}
                </div>
                <h3 class="h5 mb-1"><code>${escapeHtml(detail.serial_number)}</code>
                    ${detail.tag_id ? `<span class="text-muted">· tag ${escapeHtml(detail.tag_id)}</span>` : ''}
                </h3>
                <p class="small mb-2">${linkBadge(detail)}
                    ${detail.is_attached
                        ? `<span class="badge text-bg-info ms-1">Attached: ${escapeHtml(detail.attached_platform_name || '')}</span>`
                        : `<span class="badge text-bg-light text-dark ms-1">${escapeHtml(custodyLabel(detail.custody_status))}</span>`}
                    ${detail.low_battery ? '<span class="badge text-bg-danger ms-1">Low battery</span>' : ''}
                </p>
                <dl class="row small mb-3">
                    <dt class="col-4">Code map</dt><dd class="col-8">${escapeHtml(detail.code_map)}</dd>
                    <dt class="col-4">Always Tx</dt><dd class="col-8">${detail.always_tx ? 'Y' : 'N'}</dd>
                    <dt class="col-4">Created via</dt><dd class="col-8">${escapeHtml(detail.created_via)}</dd>
                    <dt class="col-4">Comments</dt><dd class="col-8" style="white-space: pre-wrap;">${escapeHtml(detail.comments || '—')}</dd>
                </dl>
                <h4 class="h6">Sensor Tracker accounting</h4>
                <div id="vmtStAccounting" class="mb-3">${accountingHtml}</div>
                <h4 class="h6">Battery checks</h4>
                <div class="table-responsive mb-3">
                    <table class="table table-sm">
                        <thead><tr><th>Date</th><th>%</th><th>Days</th><th>By</th></tr></thead>
                        <tbody>
                            ${(detail.battery_checks || []).length
                                ? detail.battery_checks.map((b) => `
                                    <tr>
                                        <td>${escapeHtml(b.checked_at)}</td>
                                        <td>${escapeHtml(b.percent_remaining == null ? '—' : b.percent_remaining)}</td>
                                        <td>${escapeHtml(b.days_remaining == null ? '—' : b.days_remaining)}</td>
                                        <td class="small">${escapeHtml(b.recorded_by_username || '—')}</td>
                                    </tr>`).join('')
                                : '<tr><td colspan="4" class="text-muted">None yet</td></tr>'}
                        </tbody>
                    </table>
                </div>
                <h4 class="h6">Service events</h4>
                <ul class="small mb-3">
                    ${(detail.service_events || []).length
                        ? detail.service_events.map((s) => `
                            <li><strong>${escapeHtml(s.event_type)}</strong>
                                ${s.event_date ? ` (${escapeHtml(s.event_date)})` : ''}
                                — ${escapeHtml(s.description || '')}</li>`).join('')
                        : '<li class="text-muted">None yet</li>'}
                </ul>
                <h4 class="h6">Field audit</h4>
                <ul class="list-unstyled small mb-0">
                    ${(detail.audit_logs || []).length
                        ? detail.audit_logs.map((a) => `
                            <li class="mb-2">
                                <div class="text-muted">${escapeHtml(formatAuditWhen(a.changed_at_utc))} · ${escapeHtml(a.changed_by_username || '?')}</div>
                                ${formatAuditChanges(a.changes_json)}
                            </li>`).join('')
                        : '<li class="text-muted">No field changes yet</li>'}
                </ul>
            `;

            document.getElementById('vmtEditBtn')?.addEventListener('click', () => openEditModal(detail));
            document.getElementById('vmtAddBattBtn')?.addEventListener('click', () => {
                document.getElementById('vmtBattDate').value = new Date().toISOString().slice(0, 10);
                document.getElementById('vmtBattDays').value = '';
                document.getElementById('vmtBattPct').value = '';
                document.getElementById('vmtBattNotes').value = '';
                batteryModal?.show();
            });
            document.getElementById('vmtAddSvcBtn')?.addEventListener('click', () => {
                document.getElementById('vmtSvcDate').value = '';
                document.getElementById('vmtSvcDesc').value = '';
                document.getElementById('vmtSvcType').value = 'rebattery';
                serviceModal?.show();
            });

            try {
                const accounting = await apiRequest(
                    `/api/team/vmt-logbook/units/${unitId}/st-accounting`,
                    'GET'
                );
                if (seq !== state.detailSeq || state.selectedId !== unitId) return;
                const wrap = document.getElementById('vmtStAccounting');
                if (!wrap) return;
                if (accounting.message && !accounting.analytics) {
                    wrap.innerHTML = `<div class="alert alert-warning py-2 small mb-0">${escapeHtml(accounting.message)}</div>`;
                    return;
                }
                wrap.innerHTML = `
                    ${accounting.message
                        ? `<div class="alert alert-warning py-2 small">${escapeHtml(accounting.message)}</div>`
                        : ''}
                    <div class="mb-2">${renderMetrics(accounting.analytics)}</div>
                    <h5 class="h6">Attachment / deployment history</h5>
                    ${renderAttachmentHistory(accounting.attachment_history)}
                `;
            } catch (err) {
                const wrap = document.getElementById('vmtStAccounting');
                if (wrap) {
                    wrap.innerHTML = `<p class="small text-muted mb-0">ST accounting unavailable: ${escapeHtml(err.message || err)}</p>`;
                }
            }
        } catch (err) {
            if (seq !== state.detailSeq || state.selectedId !== unitId) return;
            detailBody.innerHTML = `<p class="text-danger mb-0">${escapeHtml(err.message || err)}</p>`;
        }
    };

    const openAddModal = () => {
        document.getElementById('vmtUnitModalTitle').textContent = 'Add VMT';
        document.getElementById('vmtEditId').value = '';
        document.getElementById('vmtSerial').value = '';
        document.getElementById('vmtSerial').disabled = false;
        document.getElementById('vmtTagId').value = '';
        document.getElementById('vmtCodeMap').value = 'A69-9001';
        document.getElementById('vmtCustody').value = '';
        document.getElementById('vmtCustodyOther').value = '';
        document.getElementById('vmtStId').value = '';
        document.getElementById('vmtAlwaysTx').checked = false;
        document.getElementById('vmtIsActive').checked = true;
        document.getElementById('vmtComments').value = '';
        unitModal?.show();
    };

    const openEditModal = (detail) => {
        document.getElementById('vmtUnitModalTitle').textContent = 'Edit VMT';
        document.getElementById('vmtEditId').value = String(detail.id);
        document.getElementById('vmtSerial').value = detail.serial_number;
        document.getElementById('vmtSerial').disabled = true;
        document.getElementById('vmtTagId').value = detail.tag_id || '';
        document.getElementById('vmtCodeMap').value = detail.code_map || 'A69-9001';
        document.getElementById('vmtCustody').value = detail.custody_status || '';
        document.getElementById('vmtCustodyOther').value = detail.custody_status_other || '';
        document.getElementById('vmtStId').value = detail.sensor_tracker_instrument_id || '';
        document.getElementById('vmtAlwaysTx').checked = !!detail.always_tx;
        document.getElementById('vmtIsActive').checked = detail.is_active !== false;
        document.getElementById('vmtComments').value = detail.comments || '';
        unitModal?.show();
    };

    const loadUnits = async () => {
        const seq = (state.loadSeq += 1);
        tableBody.innerHTML = '<tr><td colspan="6" class="text-muted p-3">Loading&hellip;</td></tr>';
        try {
            const qs = includeInactive.checked ? '?include_inactive=true' : '';
            const payload = await apiRequest(`/api/team/vmt-logbook/units${qs}`, 'GET');
            if (seq !== state.loadSeq) return;
            state.units = payload.units || [];
            renderTable();
            if (state.selectedId) {
                const stillThere = state.units.some((u) => u.id === state.selectedId);
                if (stillThere) await renderDetail(state.selectedId);
            }
        } catch (err) {
            if (seq !== state.loadSeq) return;
            tableBody.innerHTML = `<tr><td colspan="6" class="text-danger p-3">${escapeHtml(err.message || err)}</td></tr>`;
            showToast(err.message || String(err), 'error');
        }
    };

    tableBody.addEventListener('click', (ev) => {
        const tr = ev.target.closest('tr[data-id]');
        if (!tr) return;
        renderDetail(Number(tr.dataset.id));
    });

    [filterInput, filterCustody, filterLink].forEach((el) => {
        el.addEventListener('input', renderTable);
        el.addEventListener('change', renderTable);
    });
    includeInactive.addEventListener('change', loadUnits);

    document.getElementById('vmtAddBtn').addEventListener('click', openAddModal);

    document.getElementById('vmtUnitForm').addEventListener('submit', async (ev) => {
        ev.preventDefault();
        const editId = (document.getElementById('vmtEditId').value || '').trim();
        const stRaw = (document.getElementById('vmtStId').value || '').trim();
        const body = {
            tag_id: (document.getElementById('vmtTagId').value || '').trim() || null,
            code_map: (document.getElementById('vmtCodeMap').value || '').trim() || 'A69-9001',
            always_tx: !!document.getElementById('vmtAlwaysTx').checked,
            comments: (document.getElementById('vmtComments').value || '').trim() || null,
            custody_status: document.getElementById('vmtCustody').value || null,
            custody_status_other: (document.getElementById('vmtCustodyOther').value || '').trim() || null,
            sensor_tracker_instrument_id: stRaw ? Number(stRaw) : null,
            is_active: !!document.getElementById('vmtIsActive').checked,
        };
        try {
            let detail;
            if (editId) {
                detail = await apiRequest(`/api/team/vmt-logbook/units/${editId}`, 'PATCH', body);
            } else {
                body.serial_number = (document.getElementById('vmtSerial').value || '').trim();
                detail = await apiRequest('/api/team/vmt-logbook/units', 'POST', body);
            }
            unitModal?.hide();
            showToast(editId ? 'VMT updated' : 'VMT created', 'success');
            if (!editId && detail?.id) {
                state.selectedId = detail.id;
            }
            await loadUnits();
        } catch (err) {
            showToast(err.message || String(err), 'error');
        }
    });

    document.getElementById('vmtBatteryForm').addEventListener('submit', async (ev) => {
        ev.preventDefault();
        if (!state.selectedId) return;
        const daysRaw = (document.getElementById('vmtBattDays').value || '').trim();
        const pctRaw = (document.getElementById('vmtBattPct').value || '').trim();
        const body = {
            checked_at: document.getElementById('vmtBattDate').value,
            days_remaining: daysRaw === '' ? null : Number(daysRaw),
            percent_remaining: pctRaw === '' ? null : Number(pctRaw),
            notes: (document.getElementById('vmtBattNotes').value || '').trim() || null,
        };
        try {
            await apiRequest(
                `/api/team/vmt-logbook/units/${state.selectedId}/battery-checks`,
                'POST',
                body
            );
            batteryModal?.hide();
            showToast('Battery check saved', 'success');
            await loadUnits();
            await renderDetail(state.selectedId);
        } catch (err) {
            showToast(err.message || String(err), 'error');
        }
    });

    document.getElementById('vmtServiceForm').addEventListener('submit', async (ev) => {
        ev.preventDefault();
        if (!state.selectedId) return;
        const body = {
            event_type: document.getElementById('vmtSvcType').value,
            event_date: document.getElementById('vmtSvcDate').value || null,
            description: (document.getElementById('vmtSvcDesc').value || '').trim() || null,
        };
        try {
            await apiRequest(
                `/api/team/vmt-logbook/units/${state.selectedId}/service-events`,
                'POST',
                body
            );
            serviceModal?.hide();
            showToast('Service event saved', 'success');
            await loadUnits();
            await renderDetail(state.selectedId);
        } catch (err) {
            showToast(err.message || String(err), 'error');
        }
    });

    const runSync = async (dryRun) => {
        syncSummary.style.display = 'block';
        syncSummary.textContent = dryRun ? 'Running dry-run…' : 'Applying sync…';
        try {
            const result = await apiRequest(
                `/api/team/vmt-logbook/sync-from-sensor-tracker?dry_run=${dryRun ? 'true' : 'false'}`,
                'POST'
            );
            state.lastSyncPreview = result;
            state.syncDryRunOk = !!dryRun && result.errors === 0;
            syncApplyBtn.disabled = !state.syncDryRunOk;
            const lines = (result.items || [])
                .filter((i) => i.action !== 'unchanged')
                .slice(0, 40)
                .map((i) => `${i.action}: ${i.serial_number || '—'} ${i.detail || ''}`)
                .join('\n');
            syncSummary.innerHTML = `<strong>${escapeHtml(result.summary)}</strong>`
                + (lines ? `<pre class="small mb-0 mt-2">${escapeHtml(lines)}</pre>` : '');
            if (!dryRun) {
                state.syncDryRunOk = false;
                syncApplyBtn.disabled = true;
                await loadUnits();
                showToast('Sync applied', 'success');
            }
        } catch (err) {
            state.syncDryRunOk = false;
            syncApplyBtn.disabled = true;
            syncSummary.textContent = err.message || String(err);
            showToast(err.message || String(err), 'error');
        }
    };

    document.getElementById('vmtSyncDryBtn').addEventListener('click', () => runSync(true));
    syncApplyBtn.addEventListener('click', () => runSync(false));

    loadUnits();
});
