#!/usr/bin/env bash
# Production path cutover: Wave-Glider-Buddy-System → Glider-Buddy-System
# Run on the app host as a user with sudo during a maintenance window.
# Docs: docs/wiki/how-tos/PROD_PATH_RENAME.md
set -euo pipefail

OLD_PATH="/home/cove/Wave-Glider-Buddy-System"
NEW_PATH="/home/cove/Glider-Buddy-System"
SERVICE="gliderbuddy.service"

if [[ "${1:-}" == "--rollback" ]]; then
  echo "Rolling back path rename..."
  sudo systemctl stop "$SERVICE" || true
  if [[ -L "$OLD_PATH" ]]; then
    sudo rm "$OLD_PATH"
  fi
  if [[ -d "$NEW_PATH" && ! -e "$OLD_PATH" ]]; then
    sudo mv "$NEW_PATH" "$OLD_PATH"
  fi
  echo "Restore WorkingDirectory and .env paths to $OLD_PATH, then:"
  echo "  sudo systemctl daemon-reload && sudo systemctl start $SERVICE"
  exit 0
fi

if [[ "${1:-}" != "--execute" ]]; then
  cat <<EOF
Usage:
  $0 --execute     Stop service, mv tree, symlink soak, print unit/.env reminders
  $0 --rollback    Undo mv/symlink (does not edit unit/.env for you)

Current:
EOF
  ls -ld "$OLD_PATH" "$NEW_PATH" 2>/dev/null || true
  systemctl is-active "$SERVICE" 2>/dev/null || true
  exit 1
fi

if [[ ! -d "$OLD_PATH" ]]; then
  echo "ERROR: $OLD_PATH not found (already cut over?)"
  ls -ld "$NEW_PATH" 2>/dev/null || true
  exit 1
fi
if [[ -e "$NEW_PATH" ]]; then
  echo "ERROR: $NEW_PATH already exists; aborting"
  exit 1
fi

echo "Stopping $SERVICE..."
sudo systemctl stop "$SERVICE"

echo "Moving $OLD_PATH -> $NEW_PATH"
sudo mv "$OLD_PATH" "$NEW_PATH"

echo "Creating soak symlink $OLD_PATH -> $NEW_PATH"
sudo ln -s "$NEW_PATH" "$OLD_PATH"

cat <<EOF

Next (manual):
  1. sudo systemctl edit --full $SERVICE
     set WorkingDirectory=$NEW_PATH
     (and ExecStart python path if it embeds the old tree)
  2. Update .env absolute paths (LOCAL_DATA_BASE_PATH, LOG_FILE_PATH, …)
  3. sudo systemctl daemon-reload
  4. sudo systemctl start $SERVICE
  5. sudo systemctl status $SERVICE
  6. ps aux | grep '[g]unicorn'
  7. sudo journalctl -u gliderbuddy --since "5 min ago" | grep -E 'STARTUP:|APScheduler|startup leader|WORKER TIMEOUT'

After soak (days/weeks), remove symlink only:
  sudo rm $OLD_PATH   # only if it is the symlink

Rollback helper: $0 --rollback
EOF
