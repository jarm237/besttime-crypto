#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
PYTHON_BIN="${REPO_ROOT}/.venv/bin/python"

if [[ ! -x "${PYTHON_BIN}" ]]; then
  echo "Python virtual environment not found: ${PYTHON_BIN}" >&2
  exit 1
fi

cd "${REPO_ROOT}"

exec "${PYTHON_BIN}" "${REPO_ROOT}/scripts/run_canary_until_seal_ready.py" \
  --epoch-id "canary-lineage-risk-v1-20260801-10-r1" \
  --deployment-id "paper-canary-20260801-10-r1" \
  --evidence-path "${REPO_ROOT}/runtime/production/paper-canary-20260801-10-r1/logs/runtime_evidence.sqlite" \
  "$@"
