import { apiRequest, showToast } from '/static/js/api.js';

document.addEventListener('DOMContentLoaded', () => {
    const galleryGrid = document.getElementById('galleryGrid');
    const galleryMeta = document.getElementById('galleryMeta');
    const galleryStatus = document.getElementById('galleryStatus');
    const rebuildAllBtn = document.getElementById('rebuildAllBtn');
    const reuseSnapshot = document.getElementById('reuseSnapshot');
    const chartDetail = document.getElementById('chartDetail');
    const detailTitle = document.getElementById('detailTitle');
    const detailCaption = document.getElementById('detailCaption');
    const detailMeta = document.getElementById('detailMeta');
    const detailImage = document.getElementById('detailImage');
    const detailEmpty = document.getElementById('detailEmpty');
    const detailRebuildBtn = document.getElementById('detailRebuildBtn');
    const detailDownload = document.getElementById('detailDownload');

    let chartsBySlug = {};
    let selectedSlug = null;

    const escapeHtml = (value) => {
        const div = document.createElement('div');
        div.textContent = value == null ? '' : String(value);
        return div.innerHTML;
    };

    const reuseBody = () => ({
        reuse_snapshot: Boolean(reuseSnapshot && reuseSnapshot.checked),
    });

    const setBusy = (isBusy, message) => {
        if (rebuildAllBtn) rebuildAllBtn.disabled = isBusy;
        if (detailRebuildBtn) detailRebuildBtn.disabled = isBusy;
        if (galleryStatus) {
            if (isBusy) {
                galleryStatus.style.display = 'block';
                galleryStatus.innerHTML = `<span class="spinner-border spinner-border-sm me-2" role="status"></span>${escapeHtml(message || 'Working…')}`;
            } else {
                galleryStatus.style.display = 'none';
                galleryStatus.textContent = '';
            }
        }
    };

    const imageUrlWithCacheBust = (url, generatedAt) => {
        if (!url) return null;
        const stamp = generatedAt || String(Date.now());
        const sep = url.includes('?') ? '&' : '?';
        return `${url}${sep}t=${encodeURIComponent(stamp)}`;
    };

    const showDetail = (slug) => {
        const chart = chartsBySlug[slug];
        if (!chart || !chartDetail) return;
        selectedSlug = slug;
        detailTitle.textContent = chart.title || slug;
        detailCaption.textContent = chart.caption || '';
        const bits = [];
        if (chart.generated_at) bits.push(`Generated ${chart.generated_at}`);
        if (chart.as_of) bits.push(`as-of ${chart.as_of}`);
        if (chart.truncated) bits.push('truncated');
        if (chart.error) bits.push(`error: ${chart.error}`);
        detailMeta.textContent = bits.join(' · ');
        detailRebuildBtn.dataset.slug = slug;
        if (chart.has_image && chart.image_url) {
            const src = imageUrlWithCacheBust(chart.image_url, chart.generated_at);
            detailImage.src = src;
            detailImage.style.display = 'block';
            detailEmpty.style.display = 'none';
            detailDownload.href = src;
            detailDownload.download = `${slug}.png`;
            detailDownload.classList.remove('disabled');
        } else {
            detailImage.removeAttribute('src');
            detailImage.style.display = 'none';
            detailEmpty.style.display = 'block';
            detailDownload.href = '#';
            detailDownload.classList.add('disabled');
        }
        chartDetail.style.display = 'block';
        chartDetail.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        if (window.location.hash !== `#${slug}`) {
            history.replaceState(null, '', `#${slug}`);
        }
    };

    const renderGallery = (payload) => {
        const charts = payload.charts || [];
        chartsBySlug = {};
        charts.forEach((c) => {
            chartsBySlug[c.slug] = c;
        });

        const snapBits = [];
        if (payload.snapshot_fetched_at) {
            snapBits.push(`Snapshot fetched ${payload.snapshot_fetched_at}`);
        }
        if (payload.snapshot_as_of) {
            snapBits.push(`as-of ${payload.snapshot_as_of}`);
        }
        if (payload.tracker_host) {
            snapBits.push(payload.tracker_host);
        }
        galleryMeta.textContent = snapBits.join(' · ');

        if (!charts.length) {
            galleryGrid.innerHTML = '<div class="col-12 text-muted">No charts registered.</div>';
            return;
        }

        galleryGrid.innerHTML = charts.map((chart) => {
            const thumb = chart.has_image && chart.image_url
                ? `<img src="${escapeHtml(imageUrlWithCacheBust(chart.image_url, chart.generated_at))}" alt="" class="card-img-top team-viz-thumb">`
                : `<div class="team-viz-placeholder text-muted d-flex align-items-center justify-content-center">Not generated yet</div>`;
            const when = chart.generated_at
                ? `<span class="small text-muted">${escapeHtml(chart.generated_at)}</span>`
                : '<span class="small text-muted">Never generated</span>';
            return `
                <div class="col-md-6 col-lg-4">
                    <div class="card gbs-card h-100 team-viz-card" data-slug="${escapeHtml(chart.slug)}" role="button" tabindex="0">
                        ${thumb}
                        <div class="card-body">
                            <h2 class="h6 card-title mb-1">${escapeHtml(chart.title)}</h2>
                            ${when}
                        </div>
                        <div class="card-footer bg-transparent border-0 pt-0">
                            <button type="button" class="btn btn-sm btn-outline-primary team-viz-rebuild" data-slug="${escapeHtml(chart.slug)}">Rebuild</button>
                        </div>
                    </div>
                </div>
            `;
        }).join('');
    };

    const loadGallery = async () => {
        const payload = await apiRequest('/api/team/visualizations', 'GET');
        renderGallery(payload);
        const hash = (window.location.hash || '').replace(/^#/, '');
        if (hash && chartsBySlug[hash]) {
            showDetail(hash);
        } else if (selectedSlug && chartsBySlug[selectedSlug]) {
            showDetail(selectedSlug);
        }
        return payload;
    };

    const rebuildOne = async (slug) => {
        setBusy(true, `Rebuilding ${slug}…`);
        try {
            await apiRequest(
                `/api/team/visualizations/${encodeURIComponent(slug)}/generate`,
                'POST',
                reuseBody(),
            );
            showToast('Chart rebuilt.', 'success');
            await loadGallery();
            showDetail(slug);
        } catch (err) {
            showToast(err.message || String(err), 'danger');
        } finally {
            setBusy(false);
        }
    };

    const rebuildAll = async () => {
        setBusy(true, 'Rebuilding all charts (Tracker walk may take a while)…');
        try {
            const result = await apiRequest(
                '/api/team/visualizations/generate-all',
                'POST',
                reuseBody(),
            );
            showToast(
                result.success ? 'All charts rebuilt.' : 'Rebuild finished with errors.',
                result.success ? 'success' : 'warning',
            );
            await loadGallery();
        } catch (err) {
            showToast(err.message || String(err), 'danger');
        } finally {
            setBusy(false);
        }
    };

    galleryGrid.addEventListener('click', (event) => {
        const rebuild = event.target.closest('.team-viz-rebuild');
        if (rebuild) {
            event.preventDefault();
            event.stopPropagation();
            const slug = rebuild.dataset.slug;
            if (slug) rebuildOne(slug);
            return;
        }
        const card = event.target.closest('.team-viz-card');
        if (card && card.dataset.slug) {
            showDetail(card.dataset.slug);
        }
    });

    galleryGrid.addEventListener('keydown', (event) => {
        if (event.key !== 'Enter' && event.key !== ' ') return;
        const card = event.target.closest('.team-viz-card');
        if (!card || !card.dataset.slug) return;
        event.preventDefault();
        showDetail(card.dataset.slug);
    });

    if (rebuildAllBtn) {
        rebuildAllBtn.addEventListener('click', () => rebuildAll());
    }
    if (detailRebuildBtn) {
        detailRebuildBtn.addEventListener('click', () => {
            const slug = detailRebuildBtn.dataset.slug || selectedSlug;
            if (slug) rebuildOne(slug);
        });
    }

    (async () => {
        try {
            await loadGallery();
        } catch (err) {
            galleryGrid.innerHTML = `<div class="col-12 text-danger">${escapeHtml(err.message || String(err))}</div>`;
            showToast(err.message || 'Failed to load gallery.', 'danger');
        }
    })();
});
