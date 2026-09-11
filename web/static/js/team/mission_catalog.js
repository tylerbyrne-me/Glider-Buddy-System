import { apiRequest, showToast } from '/static/js/api.js';

document.addEventListener('DOMContentLoaded', () => {
    const statusEl = document.getElementById('mcStatus');
    const listBody = document.getElementById('mcListBody');
    const listInfo = document.getElementById('mcListInfo');
    const detailBody = document.getElementById('mcDetailBody');
    const detailBadge = document.getElementById('mcDetailBadge');
    const listPane = document.getElementById('mcListPane');
    const detailPane = document.getElementById('mcDetailPane');
    const healthPane = document.getElementById('mcHealthPane');
    const unmatchedPane = document.getElementById('mcUnmatchedPane');
    const healthBody = document.getElementById('mcHealthBody');
    const unmatchedBody = document.getElementById('mcUnmatchedBody');
    const refreshBtn = document.getElementById('mcRefreshBtn');
    const tabsEl = document.getElementById('mcTabs');

    const state = {
        tab: 'active',
        selectedId: null,
        missions: [],
    };

    const escapeHtml = (value) => {
        const div = document.createElement('div');
        div.textContent = value == null ? '' : String(value);
        return div.innerHTML;
    };

    const shortId = (id) => {
        const s = String(id || '');
        return s.length > 8 ? `${s.slice(0, 8)}…` : s;
    };

    const readinessBadge = (readiness) => {
        const r = (readiness || 'unknown').toLowerCase();
        let cls = 'text-bg-secondary';
        if (r === 'ready') cls = 'text-bg-success';
        else if (r === 'completed') cls = 'text-bg-dark';
        else if (r.startsWith('waiting') || r === 'not_enrolled') cls = 'text-bg-warning';
        else if (r === 'error' || r.includes('ambiguous')) cls = 'text-bg-danger';
        return `<span class="badge ${cls}">${escapeHtml(r)}</span>`;
    };

    const fmtDate = (iso) => {
        if (!iso) return '—';
        try {
            return new Date(iso).toISOString().slice(0, 10);
        } catch (_err) {
            return String(iso);
        }
    };

    const writeUrl = () => {
        const params = new URLSearchParams();
        params.set('tab', state.tab);
        if (state.selectedId) params.set('id', state.selectedId);
        window.history.replaceState({}, '', `${window.location.pathname}?${params.toString()}`);
    };

    const readUrl = () => {
        const params = new URLSearchParams(window.location.search);
        state.tab = params.get('tab') || 'active';
        state.selectedId = params.get('id') || null;
    };

    const setActiveTabButtons = () => {
        tabsEl.querySelectorAll('[data-mc-tab]').forEach((btn) => {
            btn.classList.toggle('active', btn.getAttribute('data-mc-tab') === state.tab);
        });
    };

    const showPanes = () => {
        const isList = ['active', 'planned', 'completed', 'archived'].includes(state.tab);
        listPane.classList.toggle('d-none', !isList);
        detailPane.classList.toggle('d-none', !isList);
        healthPane.classList.toggle('d-none', state.tab !== 'health');
        unmatchedPane.classList.toggle('d-none', state.tab !== 'unmatched');
    };

    const renderStatus = (status) => {
        if (!status) {
            statusEl.className = 'alert alert-warning py-2 mb-3';
            statusEl.textContent = 'Catalog status unavailable.';
            return;
        }
        const flags = [
            `auto_apply=${status.auto_apply}`,
            `shadow=${status.enrollment_shadow}`,
            `wg_sync=${status.wg_sync_from_catalog}`,
            `slocum_warm=${status.slocum_warm_from_catalog}`,
            `public_map=${status.public_map_from_catalog}`,
        ].join(' · ');
        const age = status.last_success_age_seconds != null
            ? `${Math.round(status.last_success_age_seconds / 60)} min ago`
            : 'never';
        const leader = status.is_startup_leader == null
            ? 'leader=?'
            : `leader=${status.is_startup_leader}`;
        statusEl.className = status.is_stale
            ? 'alert alert-warning py-2 mb-3'
            : 'alert alert-success py-2 mb-3';
        statusEl.innerHTML = [
            `<strong>Cadence:</strong> ${escapeHtml(status.cadence || '—')}`,
            `<strong>Last success:</strong> ${escapeHtml(age)}`,
            escapeHtml(leader),
            escapeHtml(flags),
        ].join(' · ');
    };

    const renderList = () => {
        if (!state.missions.length) {
            listBody.innerHTML = '<tr><td colspan="5" class="text-muted">No missions in this state.</td></tr>';
            listInfo.textContent = '0 missions';
            return;
        }
        listInfo.textContent = `${state.missions.length} mission(s)`;
        listBody.innerHTML = state.missions.map((m) => {
            const selected = m.id === state.selectedId ? 'table-active' : '';
            const title = m.title || `m${m.deployment_number || '?'}`;
            const platform = m.platform_family || m.platform_name || '—';
            const policy = `${m.sync_policy || '—'} / ${m.enrollment_override || 'automatic'}`;
            const dates = `${fmtDate(m.start_time)} → ${fmtDate(m.end_time)}`;
            return `
                <tr class="${selected}" data-mc-id="${escapeHtml(m.id)}" style="cursor:pointer">
                    <td>
                        <div><strong>${escapeHtml(title)}</strong></div>
                        <div class="small text-muted"><code>${escapeHtml(shortId(m.id))}</code>
                        ${m.deployment_number != null ? ` · m${escapeHtml(m.deployment_number)}` : ''}</div>
                    </td>
                    <td class="small">${escapeHtml(platform)}</td>
                    <td class="small">${escapeHtml(policy)}</td>
                    <td>${readinessBadge(m.readiness)}</td>
                    <td class="small text-nowrap">${escapeHtml(dates)}</td>
                </tr>`;
        }).join('');
        listBody.querySelectorAll('[data-mc-id]').forEach((row) => {
            row.addEventListener('click', () => {
                state.selectedId = row.getAttribute('data-mc-id');
                writeUrl();
                renderList();
                loadDetail();
            });
        });
    };

    const renderDetail = (detail) => {
        if (!detail) {
            detailBadge.textContent = 'none';
            detailBody.innerHTML = '<p class="text-muted mb-0">Select a mission to inspect readiness, sources, and live rows.</p>';
            return;
        }
        detailBadge.textContent = detail.readiness || detail.operational_state || 'detail';
        const reasons = (detail.readiness_reasons || []).map((r) => `<li><code>${escapeHtml(r)}</code></li>`).join('')
            || '<li class="text-muted">none</li>';
        const sources = (detail.sources || []).map((s) => `
            <li><code>${escapeHtml(s.kind)}</code> ${escapeHtml(s.external_ref || s.collection || '')}
            <span class="text-muted">(${escapeHtml(s.variant || '—')} / ${escapeHtml(s.match_status || '—')})</span></li>
        `).join('') || '<li class="text-muted">No sources linked</li>';
        const overviews = (detail.overviews || []).map((o) => `<li><code>${escapeHtml(o.mission_id)}</code></li>`).join('')
            || '<li class="text-muted">None</li>';
        const slocum = (detail.slocum_deployments || []).map((d) => `
            <li><code>${escapeHtml(d.mission_key || d.erddap_dataset_id || d.id)}</code>
            ${d.is_active ? '<span class="badge text-bg-success">active</span>' : '<span class="badge text-bg-secondary">inactive</span>'}
            ${escapeHtml(d.status || '')}</li>
        `).join('') || '<li class="text-muted">None</li>';
        const instruments = (detail.instruments || []).slice(0, 12).map((i) => `
            <li>${escapeHtml(i.name || i.identifier || i.id)}</li>
        `).join('') || '<li class="text-muted">None</li>';
        const st = detail.sensor_tracker_deployment;
        const stHtml = st
            ? `<div class="small">ST id <code>${escapeHtml(st.sensor_tracker_deployment_id)}</code>
               · mission <code>${escapeHtml(st.mission_id || '—')}</code>
               · sync <code>${escapeHtml(st.sync_status || '—')}</code></div>`
            : '<div class="small text-muted">No Sensor Tracker deployment row linked.</div>';
        const links = detail.links || {};
        const linkHtml = [
            links.wave_glider_dashboard
                ? `<a class="btn btn-sm btn-outline-primary" href="${escapeHtml(links.wave_glider_dashboard)}">WG dashboard</a>`
                : '',
            links.slocum_dashboard
                ? `<a class="btn btn-sm btn-outline-primary" href="${escapeHtml(links.slocum_dashboard)}">Slocum dashboard</a>`
                : '',
            links.slocum_admin_overviews
                ? `<a class="btn btn-sm btn-outline-secondary" href="${escapeHtml(links.slocum_admin_overviews)}">Slocum admin</a>`
                : '',
        ].filter(Boolean).join(' ') || '<span class="text-muted small">No live-row links yet.</span>';

        detailBody.innerHTML = `
            <div class="mb-2">
                <div><strong>${escapeHtml(detail.title || '—')}</strong></div>
                <div class="small text-muted"><code>${escapeHtml(detail.id)}</code>
                ${detail.deployment_number != null ? ` · m${escapeHtml(detail.deployment_number)}` : ''}</div>
            </div>
            <div class="mb-2">${readinessBadge(detail.readiness)}
                <span class="badge text-bg-light text-dark border">${escapeHtml(detail.operational_state || '')}</span>
                <span class="badge text-bg-light text-dark border">${escapeHtml(detail.sync_policy || '')}</span>
            </div>
            <div class="mb-2 small">
                <strong>Dates:</strong> ${escapeHtml(fmtDate(detail.start_time))} → ${escapeHtml(fmtDate(detail.end_time))}
            </div>
            ${stHtml}
            <div class="mb-2">
                <strong class="small">Readiness reasons</strong>
                <ul class="small mb-0">${reasons}</ul>
            </div>
            <div class="mb-2">
                <strong class="small">Sources</strong>
                <ul class="small mb-0">${sources}</ul>
            </div>
            <div class="mb-2">
                <strong class="small">Live rows</strong>
                <div class="small">Overviews</div>
                <ul class="small mb-1">${overviews}</ul>
                <div class="small">Slocum deployments</div>
                <ul class="small mb-0">${slocum}</ul>
            </div>
            <div class="mb-3">
                <strong class="small">Instruments (sample)</strong>
                <ul class="small mb-0">${instruments}</ul>
            </div>
            <div class="mb-3 d-flex flex-wrap gap-2">${linkHtml}</div>
            <div class="border-top pt-3">
                <label class="form-label small mb-1" for="mcOverrideSelect">Enrollment override</label>
                <div class="input-group input-group-sm mb-2">
                    <select class="form-select" id="mcOverrideSelect">
                        <option value="automatic">automatic</option>
                        <option value="forced_off">forced_off</option>
                        <option value="forced_on">forced_on</option>
                    </select>
                    <button type="button" class="btn btn-outline-warning" id="mcOverrideBtn">Apply override</button>
                </div>
                <button type="button" class="btn btn-sm btn-primary" id="mcProvisionBtn">Retry provision / deep ST sync</button>
                <div class="form-text">Apply does not run catalog reconcile. Forced_on enrolls early; completion still wins.</div>
                <pre class="small bg-body-secondary p-2 mt-2 mb-0 rounded d-none" id="mcActionOut"></pre>
            </div>
        `;
        const overrideSelect = document.getElementById('mcOverrideSelect');
        overrideSelect.value = detail.enrollment_override || 'automatic';
        document.getElementById('mcOverrideBtn').addEventListener('click', () => applyOverride(detail.id, overrideSelect.value));
        document.getElementById('mcProvisionBtn').addEventListener('click', () => retryProvision(detail.id));
    };

    const renderHealth = (health) => {
        if (!health) {
            healthBody.textContent = 'Health unavailable.';
            return;
        }
        const issues = (health.issues || []).map((issue) => `
            <tr>
                <td><code>${escapeHtml(issue.issue)}</code></td>
                <td>${issue.mission_id
                    ? `<button type="button" class="btn btn-link btn-sm p-0" data-mc-jump="${escapeHtml(issue.mission_id)}">${escapeHtml(shortId(issue.mission_id))}</button>`
                    : '—'}</td>
                <td>${escapeHtml(issue.title || '—')}</td>
                <td class="small">${escapeHtml(JSON.stringify(issue.reasons || issue.readiness || ''))}</td>
            </tr>
        `).join('') || '<tr><td colspan="4" class="text-muted">No issues</td></tr>';
        healthBody.innerHTML = `
            <div class="mb-2">
                Missions <strong>${escapeHtml(health.mission_count)}</strong> ·
                enrolled active <strong>${escapeHtml(health.enrolled_active_count)}</strong> ·
                linked WG <strong>${escapeHtml(health.linked_overviews)}</strong> ·
                linked Slocum <strong>${escapeHtml(health.linked_slocum_deployments)}</strong> ·
                unmatched <strong>${escapeHtml(health.unmatched_sources)}</strong> ·
                issues <strong>${escapeHtml(health.issue_count)}</strong>
            </div>
            <div class="table-responsive">
                <table class="table table-sm table-striped align-middle mb-0">
                    <thead><tr><th>Issue</th><th>Mission</th><th>Title</th><th>Detail</th></tr></thead>
                    <tbody>${issues}</tbody>
                </table>
            </div>
        `;
        healthBody.querySelectorAll('[data-mc-jump]').forEach((btn) => {
            btn.addEventListener('click', () => {
                state.tab = 'active';
                state.selectedId = btn.getAttribute('data-mc-jump');
                setActiveTabButtons();
                showPanes();
                writeUrl();
                loadMissions().then(() => loadDetail());
            });
        });
    };

    const renderUnmatched = (rows) => {
        if (!rows || !rows.length) {
            unmatchedBody.innerHTML = '<tr><td colspan="5" class="text-muted">No unmatched sources.</td></tr>';
            return;
        }
        unmatchedBody.innerHTML = rows.map((s) => `
            <tr>
                <td>${s.provider_url
                    ? `<a href="${escapeHtml(s.provider_url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(s.external_ref)}</a>`
                    : `<code>${escapeHtml(s.external_ref)}</code>`}</td>
                <td>${escapeHtml(s.provider_key || '—')}</td>
                <td>${escapeHtml(s.source_variant || '—')}</td>
                <td>${escapeHtml(s.match_status || '—')}</td>
                <td class="small text-nowrap">${escapeHtml(s.last_seen_at || '—')}</td>
            </tr>
        `).join('');
    };

    const loadStatus = async () => {
        try {
            const status = await apiRequest('/api/team/mission-catalog/status');
            renderStatus(status);
        } catch (err) {
            renderStatus(null);
            showToast(err.message || 'Failed to load catalog status', 'error');
        }
    };

    const loadMissions = async () => {
        if (!['active', 'planned', 'completed', 'archived'].includes(state.tab)) return;
        listInfo.textContent = 'Loading…';
        try {
            const rows = await apiRequest(
                `/api/team/mission-catalog/missions?operational_state=${encodeURIComponent(state.tab)}&limit=200`
            );
            state.missions = Array.isArray(rows) ? rows : [];
            if (state.selectedId && !state.missions.some((m) => m.id === state.selectedId)) {
                // Keep selection if jumping from health; still try detail load.
            }
            renderList();
        } catch (err) {
            listBody.innerHTML = `<tr><td colspan="5" class="text-danger">${escapeHtml(err.message || 'Failed to load')}</td></tr>`;
        }
    };

    const loadDetail = async () => {
        if (!state.selectedId) {
            renderDetail(null);
            return;
        }
        detailBody.innerHTML = '<p class="text-muted mb-0">Loading detail…</p>';
        try {
            const detail = await apiRequest(`/api/team/mission-catalog/missions/${encodeURIComponent(state.selectedId)}`);
            renderDetail(detail);
        } catch (err) {
            detailBody.innerHTML = `<p class="text-danger mb-0">${escapeHtml(err.message || 'Failed to load detail')}</p>`;
        }
    };

    const loadHealth = async () => {
        healthBody.textContent = 'Loading health…';
        try {
            const health = await apiRequest('/api/team/mission-catalog/health');
            renderHealth(health);
            if (health && health.status) renderStatus(health.status);
        } catch (err) {
            healthBody.innerHTML = `<p class="text-danger">${escapeHtml(err.message || 'Failed to load health')}</p>`;
        }
    };

    const loadUnmatched = async () => {
        unmatchedBody.innerHTML = '<tr><td colspan="5" class="text-muted">Loading…</td></tr>';
        try {
            const rows = await apiRequest('/api/team/mission-catalog/unmatched-sources?source_kind=erddap');
            renderUnmatched(rows);
        } catch (err) {
            unmatchedBody.innerHTML = `<tr><td colspan="5" class="text-danger">${escapeHtml(err.message || 'Failed')}</td></tr>`;
        }
    };

    const applyOverride = async (missionId, override) => {
        if (!window.confirm(`Set enrollment_override=${override} for this mission?`)) return;
        const out = document.getElementById('mcActionOut');
        try {
            const result = await apiRequest(
                `/api/team/mission-catalog/missions/${encodeURIComponent(missionId)}/enrollment?override=${encodeURIComponent(override)}`,
                { method: 'POST' }
            );
            out.classList.remove('d-none');
            out.textContent = JSON.stringify(result, null, 2);
            showToast(`Override set to ${override}`, 'success');
            await loadMissions();
            await loadDetail();
        } catch (err) {
            showToast(err.message || 'Override failed', 'error');
        }
    };

    const retryProvision = async (missionId) => {
        const out = document.getElementById('mcActionOut');
        try {
            const result = await apiRequest(
                `/api/team/mission-catalog/missions/${encodeURIComponent(missionId)}/provision`,
                { method: 'POST' }
            );
            out.classList.remove('d-none');
            out.textContent = JSON.stringify(result, null, 2);
            showToast(`Provision: ${result.readiness || 'done'}`, 'success');
            await loadMissions();
            await loadDetail();
        } catch (err) {
            showToast(err.message || 'Provision failed', 'error');
        }
    };

    const refresh = async () => {
        await loadStatus();
        if (state.tab === 'health') await loadHealth();
        else if (state.tab === 'unmatched') await loadUnmatched();
        else {
            await loadMissions();
            await loadDetail();
        }
    };

    tabsEl.querySelectorAll('[data-mc-tab]').forEach((btn) => {
        btn.addEventListener('click', () => {
            state.tab = btn.getAttribute('data-mc-tab');
            setActiveTabButtons();
            showPanes();
            writeUrl();
            refresh();
        });
    });
    refreshBtn.addEventListener('click', refresh);

    readUrl();
    setActiveTabButtons();
    showPanes();
    refresh();
});
