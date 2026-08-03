# Production path rename (GBS)

Canonical tree: **`/home/cove/Glider-Buddy-System`** (was `Wave-Glider-Buddy-System`).

Service unit name stays **`gliderbuddy.service`**.

## Cutover (maintenance window)

```bash
sudo systemctl stop gliderbuddy.service

# Move tree
sudo mv /home/cove/Wave-Glider-Buddy-System /home/cove/Glider-Buddy-System

# Symlink bridge for one release (anything still pointing at the old path)
sudo ln -s /home/cove/Glider-Buddy-System /home/cove/Wave-Glider-Buddy-System

# Update unit WorkingDirectory (and any drop-in override)
sudo systemctl edit --full gliderbuddy.service
# set: WorkingDirectory=/home/cove/Glider-Buddy-System

# Update .env absolute paths if present, e.g.:
# LOCAL_DATA_BASE_PATH=/home/cove/Glider-Buddy-System/data
# LOG_FILE_PATH=...

sudo systemctl daemon-reload
sudo systemctl start gliderbuddy.service
sudo systemctl status gliderbuddy.service
ps aux | grep '[g]unicorn'
sudo journalctl -u gliderbuddy --since "5 min ago" | grep -E 'STARTUP:|APScheduler|startup leader|WORKER TIMEOUT'
```

Expect one leader: single sync + single APScheduler start.

## After soak

Remove the symlink when nothing external depends on the old path:

```bash
sudo rm /home/cove/Wave-Glider-Buddy-System   # only if it is the symlink
```

## App defaults

[`app/config.py`](../../app/config.py) default `local_data_base_path` and [`AGENTS.md`](../../AGENTS.md) examples use `/home/cove/Glider-Buddy-System`. Override via `.env` until cutover is done.
