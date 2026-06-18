#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="${LOG_DIR:-$ROOT_DIR/logs}"
KEEP_REPORTS="${KEEP_REPORTS:-3}"
KEEP_MODELS="${KEEP_MODELS:-3}"
DRY_RUN="${DRY_RUN:-0}"

delete_old_files() {
    local keep_count="$1"
    local file_glob="$2"
    local exclude_glob="${3:-}"
    local files=()
    local stale=()
    local index

    if [[ ! "$keep_count" =~ ^[0-9]+$ ]]; then
        echo "Invalid keep count: $keep_count" >&2
        return 1
    fi

    while IFS= read -r file_path; do
        [[ -n "$file_path" ]] && files+=("$file_path")
    done < <(
        if [[ -n "$exclude_glob" ]]; then
            find "$LOG_DIR" -maxdepth 1 -type f -name "$file_glob" ! -name "$exclude_glob" -printf '%T@ %p\n' | sort -nr | cut -d' ' -f2-
        else
            find "$LOG_DIR" -maxdepth 1 -type f -name "$file_glob" -printf '%T@ %p\n' | sort -nr | cut -d' ' -f2-
        fi
    )

    if (( ${#files[@]} <= keep_count )); then
        return 0
    fi

    for (( index=keep_count; index<${#files[@]}; index++ )); do
        stale+=("${files[$index]}")
    done

    for file_path in "${stale[@]}"; do
        if [[ "$DRY_RUN" == "1" ]]; then
            echo "Would remove $file_path"
        else
            rm -f "$file_path"
            echo "Removed $file_path"
        fi
    done
}

delete_old_files "$KEEP_REPORTS" 'recalibration_*.json' 'recalibration_latest.json'
delete_old_files "$KEEP_MODELS" 'meta_model_calibrated_periodic_*.joblib'