import { apiRequest, showToast } from '/static/js/api.js';

document.addEventListener('DOMContentLoaded', () => {
    const generateBtn = document.getElementById('generateBtn');
    const resultCard = document.getElementById('resultCard');
    const hexbinSummary = document.getElementById('hexbinSummary');
    const hexbinImageWrap = document.getElementById('hexbinImageWrap');
    const hexbinImage = document.getElementById('hexbinImage');
    const hexbinDownload = document.getElementById('hexbinDownload');

    const parseBbox = (raw) => {
        const text = (raw || '').trim();
        if (!text) return null;
        const parts = text.split(/[,\s]+/).filter(Boolean);
        if (parts.length !== 4) {
            throw new Error('BBox must be lon_min,lon_max,lat_min,lat_max');
        }
        return parts.map((p) => Number(p));
    };

    generateBtn.addEventListener('click', async () => {
        let bbox = null;
        try {
            bbox = parseBbox(document.getElementById('bboxInput').value);
        } catch (err) {
            showToast(err.message, 'danger');
            return;
        }

        const body = {
            center_lat: Number(document.getElementById('centerLat').value),
            center_lon: Number(document.getElementById('centerLon').value),
            size_km: Number(document.getElementById('sizeKm').value),
            gridsize: Number(document.getElementById('gridsize').value),
            missions: (document.getElementById('missionsInput').value || '').trim() || null,
            refresh: !!document.getElementById('refreshCache').checked,
            include_bathymetry: !!document.getElementById('includeBathy').checked,
            max_missions: Number(document.getElementById('maxMissions').value) || 40,
        };
        if (bbox) {
            body.lon_min = bbox[0];
            body.lon_max = bbox[1];
            body.lat_min = bbox[2];
            body.lat_max = bbox[3];
        }

        generateBtn.disabled = true;
        generateBtn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Generating…';
        resultCard.style.display = 'block';
        hexbinImageWrap.style.display = 'none';
        hexbinSummary.textContent = 'Running… this can take a few minutes.';

        try {
            const result = await apiRequest('/api/team/telemetry-hexbin/generate', 'POST', body);
            hexbinSummary.textContent = result.summary || result.error || '';
            if (result.success && result.output_url) {
                const token = localStorage.getItem('accessToken');
                const headers = {};
                if (token) headers.Authorization = `Bearer ${token}`;
                const resp = await fetch(result.output_url, { headers, credentials: 'include' });
                if (!resp.ok) throw new Error(`Failed to load PNG (${resp.status})`);
                const blob = await resp.blob();
                const objectUrl = URL.createObjectURL(blob);
                hexbinImage.src = objectUrl;
                hexbinDownload.href = objectUrl;
                hexbinDownload.download = result.filename || 'telemetry_hexbin.png';
                hexbinImageWrap.style.display = 'block';
                showToast('Hexbin generated.', 'success');
            } else {
                showToast(result.error || 'Generation failed.', 'danger');
            }
        } catch (err) {
            hexbinSummary.textContent = err.message || String(err);
            showToast(err.message || 'Generation failed.', 'danger');
        } finally {
            generateBtn.disabled = false;
            generateBtn.textContent = 'Generate';
        }
    });
});
