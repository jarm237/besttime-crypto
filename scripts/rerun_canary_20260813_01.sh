#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

export CANARY_CHILD_START_BUDGET="${CANARY_CHILD_START_BUDGET:-2}"

exec "${SCRIPT_DIR}/run_canary_20260813_01_manual.sh" "$@"
