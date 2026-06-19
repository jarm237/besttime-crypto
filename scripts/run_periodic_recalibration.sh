#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKDIR="${WORKDIR:-$ROOT_DIR}"
LOGFILE="${LOGFILE:-$WORKDIR/logs/periodic_recalibration_cron.log}"
KEEP_LOGS="${KEEP_LOGS:-7}"
MAX_LOG_SIZE_MB="${MAX_LOG_SIZE_MB:-10}"
AUTO_COMMIT="${AUTO_COMMIT:-0}"
CLEANUP_ENABLED="${CLEANUP_ENABLED:-1}"
KEEP_REPORTS="${KEEP_REPORTS:-3}"
KEEP_MODELS="${KEEP_MODELS:-3}"

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

should_rotate_logs() {
    local log_size_bytes max_size_bytes

    if [[ ! -f "$LOGFILE" ]]; then
        return 1
    fi

    if [[ ! "$MAX_LOG_SIZE_MB" =~ ^[0-9]+$ ]] || (( MAX_LOG_SIZE_MB <= 0 )); then
        return 1
    fi

    log_size_bytes=$(stat -c%s "$LOGFILE")
    max_size_bytes=$((MAX_LOG_SIZE_MB * 1024 * 1024))
    (( log_size_bytes >= max_size_bytes ))
}

rotate_logs() {
    local index
    if [[ "$KEEP_LOGS" =~ ^[0-9]+$ ]] && (( KEEP_LOGS > 0 )); then
        for (( index=KEEP_LOGS-1; index>=1; index-- )); do
            if [[ -f "$LOGFILE.$index" ]]; then
                mv "$LOGFILE.$index" "$LOGFILE.$((index + 1))"
            fi
        done
        if [[ -f "$LOGFILE" ]]; then
            mv "$LOGFILE" "$LOGFILE.1"
        fi
        rm -f "$LOGFILE.$((KEEP_LOGS + 1))"
    fi
}

if should_rotate_logs; then
    rotate_logs
fi

cd "$WORKDIR"
AUTO_COMMIT="$AUTO_COMMIT" "$PYTHON_BIN" scripts/periodic_recalibration.py >> "$LOGFILE" 2>&1

if [[ "$CLEANUP_ENABLED" == "1" ]]; then
    CLEANUP_SCRIPT="$WORKDIR/scripts/cleanup_recalibration_artifacts.sh"
    if [[ -f "$CLEANUP_SCRIPT" ]]; then
        LOG_DIR="$WORKDIR/logs" KEEP_REPORTS="$KEEP_REPORTS" KEEP_MODELS="$KEEP_MODELS" bash "$CLEANUP_SCRIPT" >> "$LOGFILE" 2>&1 || \
            echo "Cleanup step failed; continuing without blocking recalibration job." >> "$LOGFILE"
    fi
fi