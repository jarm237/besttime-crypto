#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKDIR="${WORKDIR:-$ROOT_DIR}"
LOGFILE="${LOGFILE:-$WORKDIR/logs/periodic_recalibration_cron.log}"
SCHEDULE="${SCHEDULE:-0 2 * * *}"
AUTO_COMMIT="${AUTO_COMMIT:-0}"
KEEP_LOGS="${KEEP_LOGS:-7}"
MAX_LOG_SIZE_MB="${MAX_LOG_SIZE_MB:-10}"
ACTION="${1:-install}"

if [[ -x "$WORKDIR/.venv/bin/python" ]]; then
	PYTHON_BIN="$WORKDIR/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
	PYTHON_BIN="$(command -v python3)"
elif command -v python >/dev/null 2>&1; then
	PYTHON_BIN="$(command -v python)"
else
	echo "Python interpreter not found. Install python3 or create .venv first." >&2
	exit 1
fi

mkdir -p "$(dirname "$LOGFILE")"

RUNNER="$WORKDIR/scripts/run_periodic_recalibration.sh"

if [[ ! -f "$RUNNER" ]]; then
	echo "Missing runner script: $RUNNER" >&2
	exit 1
fi

COMMAND="cd \"$WORKDIR\" && LOGFILE=\"$LOGFILE\" KEEP_LOGS=$KEEP_LOGS MAX_LOG_SIZE_MB=$MAX_LOG_SIZE_MB AUTO_COMMIT=$AUTO_COMMIT bash \"$RUNNER\""
CRON_LINE="$SCHEDULE $COMMAND"
MATCH_TOKEN="$RUNNER"

install_cron() {
	(crontab -l 2>/dev/null | grep -v -F "$MATCH_TOKEN" || true; echo "$CRON_LINE") | crontab -
	echo "Installed cron entry:"
	echo "$CRON_LINE"
}

remove_cron() {
	(crontab -l 2>/dev/null | grep -v -F "$MATCH_TOKEN" || true) | crontab -
	echo "Removed cron entries for $MATCH_TOKEN"
}

case "$ACTION" in
	install)
		install_cron
		;;
	remove)
		remove_cron
		;;
	print)
		echo "$CRON_LINE"
		;;
	*)
		echo "Usage: $0 [install|remove|print]" >&2
		exit 1
		;;
esac
