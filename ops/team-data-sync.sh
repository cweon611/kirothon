#!/usr/bin/env bash
# Team data refresh on the server (tourism places / festivals / support programs).
# Run by the kirothon-tourism-sync / kirothon-festival-sync systemd units, or by hand for the first setup:
#   ops/team-data-sync.sh full        # all tourism steps + support programs + readiness report
#   ops/team-data-sync.sh festivals   # codes + festivals only (daily)
#   ops/team-data-sync.sh status      # readiness report only (no external calls)
# Keys come from the environment (systemd EnvironmentFile); nothing is printed or written to the repo.
# Existing rows are never deleted: a failed source keeps its previous data and the failure is recorded
# in tourism_sync_run / benefit_sync_run.
set -euo pipefail
MODE="${1:-full}"
PROJECT="${KIROTHON_PROJECT:-/home/ubuntu/kirothon}"
export KIROTHON_DB_PATH="${KIROTHON_DB_PATH:-/home/ubuntu/kirothon-data/records.sqlite3}"
LOCK="$(dirname "$KIROTHON_DB_PATH")/.team-data-sync.lock"
PY="$PROJECT/backend/.venv/bin/python"
cd "$PROJECT/backend"
mkdir -p "$(dirname "$KIROTHON_DB_PATH")"
# One collection at a time across timers and manual runs (the DB run marker is a second guard).
exec 9>"$LOCK"
if ! flock -n 9; then
  echo "another team data sync is running; skipped" >&2
  exit 0
fi
status=0
case "$MODE" in
  full)
    "$PY" -m app.team.sync_tourism || status=1
    "$PY" -m app.team.benefits.cli sync || status=1
    ;;
  festivals)
    "$PY" -m app.team.sync_tourism --steps codes,festivals || status=1
    ;;
  status) ;;
  *) echo "usage: $0 full|festivals|status" >&2; exit 2 ;;
esac
"$PY" -m app.team.data_readiness || status=1
exit "$status"
