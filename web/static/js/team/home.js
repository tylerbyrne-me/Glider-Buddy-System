import { apiRequest, showToast } from '/static/js/api.js';

document.addEventListener('DOMContentLoaded', () => {
    const tableBody = document.getElementById('opsScriptsTableBody');
    const outputPanel = document.getElementById('opsScriptOutputPanel');
    const outputEl = document.getElementById('opsScriptOutput');

    const escapeHtml = (value) => {
        const div = document.createElement('div');
        div.textContent = value == null ? '' : String(value);
        return div.innerHTML;
    };

    const renderEmpty = (message) => {
        tableBody.innerHTML = `<tr><td colspan="4" class="text-center text-muted">${escapeHtml(message)}</td></tr>`;
    };

    const actionCell = (script) => {
        if (script.kind === 'page' && script.href) {
            return `<a class="btn btn-sm btn-outline-primary" href="${escapeHtml(script.href)}">Open</a>`;
        }
        return `<button type="button" class="btn btn-sm btn-primary ops-run-btn" data-script-id="${escapeHtml(script.id)}">Run</button>`;
    };

    const renderScripts = (scripts) => {
        if (!scripts || scripts.length === 0) {
            renderEmpty('No ops scripts are registered yet.');
            return;
        }
        tableBody.innerHTML = scripts.map((script) => `
            <tr data-script-id="${escapeHtml(script.id)}">
                <td>${escapeHtml(script.label)}</td>
                <td>${escapeHtml(script.description)}</td>
                <td>${actionCell(script)}</td>
                <td class="ops-status text-muted">${script.kind === 'page' ? 'Tool page' : 'Not run'}</td>
            </tr>
        `).join('');
    };

    const setRowRunning = (row, isRunning) => {
        const button = row.querySelector('.ops-run-btn');
        const statusCell = row.querySelector('.ops-status');
        if (button) button.disabled = isRunning;
        if (statusCell && isRunning) {
            statusCell.innerHTML = '<span class="spinner-border spinner-border-sm" role="status"></span> Running…';
        }
    };

    const showResult = (row, result) => {
        const statusCell = row.querySelector('.ops-status');
        const badgeClass = result.success ? 'bg-success' : 'bg-danger';
        const label = result.success ? 'OK' : 'Failed';
        const duration = typeof result.duration_ms === 'number' ? `${result.duration_ms} ms` : '';
        if (statusCell) {
            statusCell.innerHTML = `<span class="badge ${badgeClass}">${label}</span> <span class="text-muted small">${escapeHtml(duration)}</span>`;
        }
        if (outputPanel && outputEl) {
            const parts = [];
            if (result.error) parts.push(result.error);
            if (result.output) parts.push(result.output);
            outputEl.textContent = parts.join('\n\n') || '(no output)';
            outputPanel.style.display = 'block';
        }
    };

    const runScript = async (scriptId, row) => {
        setRowRunning(row, true);
        try {
            const result = await apiRequest(`/api/team/scripts/${encodeURIComponent(scriptId)}/run`, 'POST');
            showResult(row, result);
            showToast(result.success ? 'Script finished.' : 'Script failed.', result.success ? 'success' : 'danger');
        } catch (err) {
            const statusCell = row.querySelector('.ops-status');
            if (statusCell) {
                statusCell.innerHTML = '<span class="badge bg-danger">Failed</span>';
            }
            if (outputPanel && outputEl) {
                outputEl.textContent = err.message || String(err);
                outputPanel.style.display = 'block';
            }
            showToast(err.message || 'Script failed.', 'danger');
        } finally {
            const button = row.querySelector('.ops-run-btn');
            if (button) button.disabled = false;
        }
    };

    tableBody.addEventListener('click', (event) => {
        const button = event.target.closest('.ops-run-btn');
        if (!button) return;
        const row = button.closest('tr');
        const scriptId = button.dataset.scriptId;
        if (!row || !scriptId) return;
        runScript(scriptId, row);
    });

    (async () => {
        try {
            const scripts = await apiRequest('/api/team/scripts', 'GET');
            renderScripts(scripts);
        } catch (err) {
            renderEmpty(err.message || 'Failed to load ops scripts.');
            showToast(err.message || 'Failed to load ops scripts.', 'danger');
        }
    })();
});
