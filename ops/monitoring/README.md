# Glider Buddy production monitoring and capacity

Infrastructure rollout for hosts running gunicorn **`-w 2`**. Application code is unchanged; observability uses Prometheus, node_exporter, process-exporter, blackbox_exporter, Grafana, optional journal textfile metrics, and optional systemd memory accounting.

**Production (glider-dev.cove):** Phase A monitoring deployed 2026-09-24 — see [HOST_PROFILES.md](./HOST_PROFILES.md) for thresholds, ports, and Grafana access.

**Rollout order (new hosts):** baseline → monitoring stack → [STAGING_VALIDATION.md](./STAGING_VALIDATION.md) → phased [PRODUCTION_ROLLOUT.md](./PRODUCTION_ROLLOUT.md).

| Doc | Purpose |
|-----|---------|
| [RUNBOOK.md](./RUNBOOK.md) | Day-2 ops: install, alerts, rollback, cache purge |
| [HOST_PROFILES.md](./HOST_PROFILES.md) | 16 GiB vs ~10 GiB thresholds; glider-dev specifics |
| [BASELINE.md](./BASELINE.md) | Pre-change inventory and 7-day baseline |
| [STAGING_VALIDATION.md](./STAGING_VALIDATION.md) | Load/soak pass gates |
| [PRODUCTION_ROLLOUT.md](./PRODUCTION_ROLLOUT.md) | Phased prod deployment |

## Quick install (staging or prod)

Adjust paths, `instance` labels, and **alert rule file** (`alert_rules.yml` vs `alert_rules_10gb.yml`) before use.

```bash
# 1. Copy configs (example: central Prometheus paths on Rocky)
sudo mkdir -p /etc/prometheus /var/lib/node_exporter/textfile_collector
sudo cp ops/monitoring/config/prometheus.yml /etc/prometheus/
sudo cp ops/monitoring/config/alert_rules_10gb.yml /etc/prometheus/alert_rules.yml  # or alert_rules.yml on 16 GiB
sudo cp ops/monitoring/config/blackbox.yml /etc/blackbox-exporter/
sudo cp ops/monitoring/config/process-exporter.yml /etc/process-exporter/
sudo cp ops/monitoring/scripts/gbs_textfile_metrics.sh /usr/local/bin/
sudo chmod +x /usr/local/bin/gbs_textfile_metrics.sh

# 2. Install exporters + Prometheus + Grafana — see RUNBOOK.md § Install (Rocky 8 + upstream binaries)

# 3. Enable textfile timer + accounting drop-in (Phase A)
sudo cp ops/monitoring/systemd/gliderbuddy-monitoring-textfile.timer /etc/systemd/system/
sudo cp ops/monitoring/systemd/gliderbuddy-monitoring-textfile.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now gliderbuddy-monitoring-textfile.timer

# 4. Phase A accounting only (no hard memory cap)
sudo mkdir -p /etc/systemd/system/gliderbuddy.service.d
sudo cp ops/monitoring/systemd/gliderbuddy-accounting.conf \
  /etc/systemd/system/gliderbuddy.service.d/accounting.conf
sudo systemctl daemon-reload
sudo systemctl restart gliderbuddy.service
```

## Directory layout

```
ops/monitoring/
├── README.md
├── HOST_PROFILES.md
├── RUNBOOK.md
├── BASELINE.md
├── STAGING_VALIDATION.md
├── PRODUCTION_ROLLOUT.md
├── config/
│   ├── prometheus.yml
│   ├── alert_rules.yml          # 16 GiB
│   ├── alert_rules_10gb.yml     # ~10 GiB (glider-dev)
│   ├── blackbox.yml
│   └── process-exporter.yml
├── grafana/
│   └── gliderbuddy-overview.json
├── scripts/
│   ├── gbs_baseline_snapshot.sh
│   ├── gbs_textfile_metrics.sh
│   └── gbs_journal_log_counts.sh
└── systemd/
    ├── gliderbuddy-accounting.conf
    ├── gliderbuddy-memory-soft.conf
    ├── gliderbuddy-memory-hard.conf
    ├── gliderbuddy-monitoring-textfile.service
    └── gliderbuddy-monitoring-textfile.timer
```

## Threshold summary

| Profile | MemAvailable warn/crit | Gunicorn RSS warn/crit |
|---------|------------------------|-------------------------|
| 16 GiB ([alert_rules.yml](./config/alert_rules.yml)) | 4 GB / 2 GB | 8 GB / 10 GB |
| ~10 GiB ([alert_rules_10gb.yml](./config/alert_rules_10gb.yml)) | 2.5 GiB / 1.5 GiB | 6 GiB / 7.5 GiB |

Shared signals: `data_store` > 100 GB or +10 GB/day; `/healthz` p95 > 3 s; journal **SLOWREQ** / **WORKER TIMEOUT** when journal textfile script is enabled.

Full alert definitions: [config/alert_rules.yml](./config/alert_rules.yml) and [config/alert_rules_10gb.yml](./config/alert_rules_10gb.yml).
