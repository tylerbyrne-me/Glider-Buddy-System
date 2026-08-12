import { apiRequest, showToast } from '/static/js/api.js';

document.addEventListener('DOMContentLoaded', () => {
    const aliasInput = document.getElementById('aliasInput');
    const jsonText = document.getElementById('jsonText');
    const jsonFile = document.getElementById('jsonFile');
    const afterDate = document.getElementById('afterDate');
    const beforeDate = document.getElementById('beforeDate');
    const noDateFilter = document.getElementById('noDateFilter');
    const includeInReport = document.getElementById('includeInReport');
    const dryRunBtn = document.getElementById('dryRunBtn');
    const postBtn = document.getElementById('postBtn');
    const previewCard = document.getElementById('previewCard');
    const resultSummary = document.getElementById('resultSummary');
    const previewBody = document.getElementById('previewBody');

    let dryRunOk = false;

    const escapeHtml = (value) => {
        const div = document.createElement('div');
        div.textContent = value == null ? '' : String(value);
        return div.innerHTML;
    };

    const buildBody = () => ({
        alias: (aliasInput.value || '').trim(),
        json_text: jsonText.value || '',
        after: afterDate.value || null,
        before: beforeDate.value || null,
        no_date_filter: !!noDateFilter.checked,
        include_in_report: !!includeInReport.checked,
    });

    const invalidateDryRun = () => {
        dryRunOk = false;
        postBtn.disabled = true;
    };

    [aliasInput, jsonText, afterDate, beforeDate, noDateFilter, includeInReport].forEach((el) => {
        el.addEventListener('input', invalidateDryRun);
        el.addEventListener('change', invalidateDryRun);
    });

    jsonFile.addEventListener('change', async () => {
        const file = jsonFile.files && jsonFile.files[0];
        if (!file) return;
        jsonText.value = await file.text();
        invalidateDryRun();
    });

    const renderResult = (result) => {
        previewCard.style.display = 'block';
        resultSummary.textContent = result.summary || result.error || '';
        const items = result.items || [];
        if (!items.length) {
            previewBody.innerHTML = '<tr><td colspan="4" class="text-muted">No items</td></tr>';
            return;
        }
        previewBody.innerHTML = items.map((item) => `
            <tr>
                <td>${escapeHtml(item.sfmc_id)}</td>
                <td><code>${escapeHtml(item.action)}</code></td>
                <td>${escapeHtml(item.reason || '')}</td>
                <td class="small"><code>${escapeHtml((item.content || '').slice(0, 160))}</code></td>
            </tr>
        `).join('');
    };

    const run = async (endpoint, { enablePostOnSuccess }) => {
        const body = buildBody();
        if (!body.alias || !body.json_text.trim()) {
            showToast('Alias and JSON are required.', 'danger');
            return;
        }
        dryRunBtn.disabled = true;
        postBtn.disabled = true;
        try {
            const result = await apiRequest(endpoint, 'POST', body);
            renderResult(result);
            if (result.success) {
                showToast(result.dry_run ? 'Dry-run complete.' : 'Notes posted.', 'success');
                if (enablePostOnSuccess) {
                    dryRunOk = true;
                    postBtn.disabled = false;
                } else {
                    dryRunOk = false;
                }
            } else {
                dryRunOk = false;
                showToast(result.error || 'Request failed.', 'danger');
            }
        } catch (err) {
            dryRunOk = false;
            showToast(err.message || 'Request failed.', 'danger');
        } finally {
            dryRunBtn.disabled = false;
            if (dryRunOk) postBtn.disabled = false;
        }
    };

    dryRunBtn.addEventListener('click', () => {
        run('/api/team/sfmc-lognotes/dry-run', { enablePostOnSuccess: true });
    });

    postBtn.addEventListener('click', () => {
        if (!dryRunOk) {
            showToast('Run a successful dry-run first.', 'danger');
            return;
        }
        if (!window.confirm('Post notes to the Slocum deployment? This writes to the database.')) {
            return;
        }
        run('/api/team/sfmc-lognotes/post', { enablePostOnSuccess: false });
    });
});
