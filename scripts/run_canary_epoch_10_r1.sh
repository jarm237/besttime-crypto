#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
PYTHON_BIN="${REPO_ROOT}/.venv/bin/python"
PINNED_COMMIT="cc4d93b4ed937a7812140a24f4c0435a84574a77"
PINNED_WORKTREE="${REPO_ROOT}/runtime/worktrees/paper-canary-20260801-10-r1"
RUNTIME_ROOT="${REPO_ROOT}/runtime/production/paper-canary-20260801-10-r1"
EVIDENCE_PATH="${RUNTIME_ROOT}/logs/runtime_evidence.sqlite"
ENV_FILE="${REPO_ROOT}/.env"

if [[ ! -x "${PYTHON_BIN}" ]]; then
  echo "Python virtual environment not found: ${PYTHON_BIN}" >&2
  exit 1
fi

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Environment file not found: ${ENV_FILE}" >&2
  exit 1
fi

resolved_commit="$(git -C "${REPO_ROOT}" rev-parse --verify "${PINNED_COMMIT}^{commit}")"
if [[ "${resolved_commit}" != "${PINNED_COMMIT}" ]]; then
  echo "Pinned epoch commit did not resolve exactly: ${PINNED_COMMIT}" >&2
  exit 1
fi

if [[ ! -e "${PINNED_WORKTREE}" ]]; then
  mkdir -p "$(dirname -- "${PINNED_WORKTREE}")"
  git -C "${REPO_ROOT}" worktree add --detach "${PINNED_WORKTREE}" "${PINNED_COMMIT}"
elif [[ ! -d "${PINNED_WORKTREE}" ]]; then
  echo "Pinned worktree path is not a directory: ${PINNED_WORKTREE}" >&2
  exit 1
fi

worktree_root="$(git -C "${PINNED_WORKTREE}" rev-parse --show-toplevel 2>/dev/null || true)"
worktree_commit="$(git -C "${PINNED_WORKTREE}" rev-parse HEAD 2>/dev/null || true)"
if [[ "${worktree_root}" != "${PINNED_WORKTREE}" || "${worktree_commit}" != "${PINNED_COMMIT}" ]]; then
  echo "Pinned worktree is invalid or on the wrong commit: ${PINNED_WORKTREE}" >&2
  exit 1
fi

if ! git -C "${PINNED_WORKTREE}" diff --quiet --exit-code \
  || ! git -C "${PINNED_WORKTREE}" diff --cached --quiet --exit-code; then
  echo "Pinned worktree has tracked changes; refusing to contaminate epoch lineage." >&2
  exit 1
fi

PINNED_RUNNER="${PINNED_WORKTREE}/scripts/run_canary_until_seal_ready.py"
if [[ ! -f "${PINNED_RUNNER}" ]]; then
  echo "Canary runner not found in pinned worktree: ${PINNED_RUNNER}" >&2
  exit 1
fi

export BTC_RUNTIME_ROOT="${RUNTIME_ROOT}"
export BTC_RUNTIME_EVIDENCE_PATH="${EVIDENCE_PATH}"

cd "${PINNED_WORKTREE}"

exec "${PYTHON_BIN}" -m dotenv -f "${ENV_FILE}" run -- \
  "${PYTHON_BIN}" "${PINNED_RUNNER}" \
  --epoch-id "canary-lineage-risk-v1-20260801-10-r1" \
  --deployment-id "paper-canary-20260801-10-r1" \
  --evidence-path "${EVIDENCE_PATH}" \
  --mongo-timeout-ms 15000 \
  "$@"
