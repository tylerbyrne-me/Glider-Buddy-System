# Glider Buddy production monitoring and capacity

Infrastructure-only rollout for a **16 GB RAM / 1 TB disk** host running gunicorn **`-w 2`**. Application code is unchanged; observability uses Prometheus, node_exporter, process-exporter, blackbox_exporter, Grafana, journald log markers, and optional systemd memory accounting.

**Rollout order:** staging baseline → monitoring stack → load/soak validation → systemd guardrails → phased production.

| Doc | Purpose |
|-----|---------|
| [RUNBOOK.md](./RUNBOOK.md) | Day-2 ops: alerts, rollback, cache purge |
| [BASELINE.md](./BASELINE.md) | Pre-change inventory and 7-day baseline |
| [STAGING_VALIDATION.md](./STAGING_VALIDATION.md) | Load/soak pass gates |
| [PRODUCTION_ROLLOUT.md](./PRODUCTION_ROLLOUT.md) | Phased prod deployment |

## Quick install (staging or prod)

Adjust paths in `config/*.yml` and env vars in unit files before use.

```bash
# 1. Copy configs to the host (example paths)
sudo mkdir -p /etc/gliderbuddy-monitoring
sudo cp -r ops/monitoring/config/* /etc/gliderbuddy-monitoring/
sudo cp ops/monitoring/scripts/gbs_textfile_metrics.sh /usr/local/bin/
sudo chmod +x /usr/local/bin/gbs_textfile_metrics.sh

# 2. Install exporters + Prometheus + Grafana (distro packages or upstream binaries)
# See RUNBOOK.md § Install

# 3. Enable textfile timer + accounting drop-in (Phase A)
sudo cp ops/monitoring/systemd/gliderbuddy-monitoring-textfile.timer /etc/systemd/system/
sudo cp ops/monitoring/systemd/gliderbuddy-monitoring-textfile.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now gliderbuddy-monitoring-textfile.timer

# 4. Phase A accounting only (no hard memory cap)
sudo cp ops/monitoring/systemd/gliderbuddy-accounting.conf \
  /etc/systemd/system/gliderbuddy.service.d/accounting.conf
sudo systemctl daemon-reload
sudo systemctl restart gliderbuddy.service
```

## Directory layout

```
ops/monitoring/
├── README.md
├── RUNBOOK.md
├── BASELINE.md
├── STAGING_VALIDATION.md
├── PRODUCTION_ROLLOUT.md
├── config/
│   ├── prometheus.yml
│   ├── alert_rules.yml
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

## Threshold summary (16 GB host)

| Signal | Warning | Critical |
|--------|---------|----------|
| MemAvailable | < 4 GB (10m) | < 2 GB |
| Gunicorn RSS sum | > 8 GB (10m) | > 10 GB |
| Filesystem used | > 70% | > 85% |
| `data_store` size | > 100 GB or +10 GB/day | — |
| `/healthz` probe | p95 > 3 s | down > 2m |
| Journal | SLOWREQ > 10/h sustained | any WORKER TIMEOUT / OOM |

Full alert definitions: [config/alert_rules.yml](./config/alert_rules.yml).
