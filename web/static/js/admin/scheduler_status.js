import { apiRequest, showToast } from '/static/js/api.js';

document.addEventListener('DOMContentLoaded', () => {
    const jobsTableBody = document.getElementById('jobsTableBody');
    const refreshBtn = document.getElementById('refreshJobsBtn');
    const platformFilter = document.getElementById('platformFilter');
    let allJobs = [];

    const PLATFORM_LABELS = {
        ...(typeof window !== 'undefined' && window.APP_PLATFORM_LABELS ? window.APP_PLATFORM_LABELS : {
            wave_glider: 'Wave Glider',
            slocum: 'Slocum',
        }),
        system: 'System',
    };

    const STATUS_META = {
        ok: {
            className: 'bg-success',
            title: 'Last run succeeded or was intentionally skipped, and the job is not overdue.',
        },
        warning: {
            className: 'bg-warning text-dark',
            title: 'Last run completed with partial failures.',
        },
        failed: {
            className: 'bg-danger',
            title: 'Last run failed or raised an error.',
        },
        overdue: {
            className: 'bg-danger',
            title: 'Next run time is in the past. The job may have missed its schedule.',
        },
        never_run: {
            className: 'bg-secondary',
            title: 'No run outcome has been recorded yet.',
        },
    };

    const deriveJobPlatform = (job) => {
        if (job && job.platform && PLATFORM_LABELS[job.platform]) {
            return job.platform;
        }
        const jobId = String((job && job.id) || '');
        if (jobId.startsWith('system_')) return 'system';
        if (jobId.startsWith('slocum_')) return 'slocum';
        if (jobId.startsWith('wave_glider_')) return 'wave_glider';
        return 'system';
    };

    const formatUtc = (value) => {
        if (!value) return 'N/A';
        return new Date(value).toLocaleString('en-CA', { timeZone: 'UTC' }).replace(',', '') + ' UTC';
    };

    const escapeHtml = (value) => String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');

    const renderJobs = (jobs) => {
        if (jobs.length === 0) {
            jobsTableBody.innerHTML = '<tr><td colspan="10" class="text-center text-muted">No scheduled jobs found.</td></tr>';
            return;
        }

        jobsTableBody.innerHTML = jobs.map(job => {
            const statusKey = String(job.status || 'never_run').toLowerCase();
            const statusMeta = STATUS_META[statusKey] || STATUS_META.never_run;
            const platform = deriveJobPlatform(job);
            const platformLabel = PLATFORM_LABELS[platform] || 'System';
            const lastOutcome = job.last_outcome ? String(job.last_outcome) : '—';
            const lastMessage = job.last_message ? String(job.last_message) : '';
            const lastResultTitle = lastMessage || (job.last_outcome ? `Outcome: ${job.last_outcome}` : 'No result recorded');

            return `
                <tr>
                    <td>
                        <span class="badge ${statusMeta.className}" title="${escapeHtml(statusMeta.title)}">${escapeHtml(statusKey.toUpperCase())}</span>
                    </td>
                    <td><span class="badge bg-secondary">${escapeHtml(platformLabel)}</span></td>
                    <td><code>${escapeHtml(job.id)}</code></td>
                    <td>${escapeHtml(job.name)}</td>
                    <td><code>${escapeHtml(job.func_ref)}</code></td>
                    <td><span class="badge bg-secondary">${escapeHtml(job.trigger.type)}</span></td>
                    <td>${escapeHtml(job.trigger.details)}</td>
                    <td>${escapeHtml(formatUtc(job.next_run_time))}</td>
                    <td>${escapeHtml(formatUtc(job.last_run_time))}</td>
                    <td>
                        <span title="${escapeHtml(lastResultTitle)}">
                            <code>${escapeHtml(lastOutcome)}</code>
                            ${lastMessage ? `<div class="small text-muted text-truncate" style="max-width: 18rem;">${escapeHtml(lastMessage)}</div>` : ''}
                        </span>
                    </td>
                </tr>
            `;
        }).join('');
    };

    const applyFilter = () => {
        const selected = platformFilter ? platformFilter.value : 'all';
        if (selected === 'all') {
            renderJobs(allJobs);
            return;
        }
        renderJobs(allJobs.filter(job => deriveJobPlatform(job) === selected));
    };

    const loadJobs = async () => {
        jobsTableBody.innerHTML = `
            <tr>
                <td colspan="10" class="text-center">
                    <div class="spinner-border" role="status"><span class="visually-hidden">Loading...</span></div>
                </td>
            </tr>`;

        try {
            allJobs = await apiRequest('/api/admin/scheduler/jobs', 'GET');
            applyFilter();
        } catch (error) {
            jobsTableBody.innerHTML = '<tr><td colspan="10" class="text-center text-danger">Failed to load job status. You may not have permission to view this page.</td></tr>';
        }
    };

    if (platformFilter) {
        const urlPlatform = new URLSearchParams(window.location.search).get('platform');
        if (urlPlatform && PLATFORM_LABELS[urlPlatform]) {
            platformFilter.value = urlPlatform;
        }
        platformFilter.addEventListener('change', applyFilter);
    }

    refreshBtn.addEventListener('click', () => {
        showToast('Refreshing job list...', 'info');
        loadJobs();
    });

    loadJobs();
});
