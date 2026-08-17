#!/usr/bin/env bash
# ==============================================================================
# V5 Canary Manual Foreground Runner
# ==============================================================================
# Runs the V5 canary directly in the foreground. No background tasks or daemons.
# Press Ctrl+C to stop the runner cleanly.
#
# Usage:
#   ./scripts/run_v5_canary_manual.sh          (Runs continuously)
#   ./scripts/run_v5_canary_manual.sh --once   (Runs exactly once and exits)
# ==============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"

# Verify virtual environment
PYTHON_BIN="${REPO_ROOT}/.venv/bin/python"
if [[ ! -x "${PYTHON_BIN}" ]]; then
  echo "Error: Python virtual environment not found at ${PYTHON_BIN}" >&2
  exit 1
fi

# Verify active epoch exists in database
EVIDENCE_DB="${REPO_ROOT}/logs/runtime_evidence.sqlite"
if [[ ! -f "${EVIDENCE_DB}" ]]; then
  echo "Error: Evidence database not found at ${EVIDENCE_DB}" >&2
  exit 1
fi

# Configure environment variables for V5 local-production Canary
export BTC_LOG_DIR="logs"
export BTC_DEPLOYMENT_ID="local-production"
export BTC_PAPER_RUN_ID="local-production"
export BTC_ANALYSIS_UNIVERSE="BTC,ETH,BNB"
export BTC_EVIDENCE_ELIGIBLE="true"

# Clean any stale locks before starting
LOCK_FILE="${REPO_ROOT}/runtime/production/local-production/state/runtime.lock"
if [[ -f "${LOCK_FILE}" ]]; then
  echo "Removing stale lock file: ${LOCK_FILE}"
  rm -f "${LOCK_FILE}"
fi

echo "Starting V5 Canary in foreground (Deployment: local-production, Epoch: canary-v5-filter-20260817-01)..."
echo "Press Ctrl+C to stop."
echo "--------------------------------------------------------------------------------"

cd "${REPO_ROOT}"
exec "${PYTHON_BIN}" -m dotenv -f ".env" run -- \
  "${PYTHON_BIN}" main.py "$@"
