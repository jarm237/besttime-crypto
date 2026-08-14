#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"

PYTHON_BIN="${PYTHON_BIN:-${REPO_ROOT}/.venv/bin/python}"
PINNED_COMMIT="35f28fbf4608e19b7688aade53a85a422bb640d0"
PINNED_ARTIFACT_SHA256="4f7bc98a6c18d04d7853a180c4f68763298580128a206bf159f4d16c956cf1e1"
PINNED_REGISTRY_SHA256="37fc84b62168b32acbb024d68fa17e9531d7e1b064349ced930f124d86825e2f"
PINNED_RL_EXIT_SHA256="ae894e5835b0e145d3bffc164e5d29500bea245d225b70aeef437de06cb3a489"
PINNED_RL_EXIT_METADATA_SHA256="8440d3c4fccfc595c720ad474c7344dbe7d925a86889097c873ef30a2b64b595"
DEPLOYMENT_ID="paper-canary-20260813-01"
EPOCH_ID="canary-lineage-risk-v1-20260813-01"
PINNED_WORKTREE="${REPO_ROOT}/runtime/worktrees/${DEPLOYMENT_ID}"
RUNTIME_ROOT="${REPO_ROOT}/runtime/production/${DEPLOYMENT_ID}"
EVIDENCE_PATH="${RUNTIME_ROOT}/logs/runtime_evidence_2026-08-13.sqlite"
ENV_FILE="${ENV_FILE:-${REPO_ROOT}/.env}"
CHILD_START_BUDGET="${CANARY_CHILD_START_BUDGET:-1}"

if [[ ! -x "${PYTHON_BIN}" ]]; then
  echo "Python virtual environment not found: ${PYTHON_BIN}" >&2
  exit 1
fi

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Environment file not found: ${ENV_FILE}" >&2
  exit 1
fi

if [[ ! -f "${EVIDENCE_PATH}" ]]; then
  echo "Evidence database not found: ${EVIDENCE_PATH}" >&2
  exit 1
fi

PROVISIONER="${REPO_ROOT}/scripts/provision_pinned_runtime_artifacts.py"
if [[ ! -f "${PROVISIONER}" ]]; then
  echo "Pinned artifact provisioner not found: ${PROVISIONER}" >&2
  exit 1
fi

copy_pinned_file() {
  local source_path="$1"
  local target_path="$2"
  local expected_sha="$3"
  local source_sha
  source_sha="$(sha256sum "${source_path}" | awk '{print $1}')"
  if [[ "${source_sha}" != "${expected_sha}" ]]; then
    echo "Pinned source SHA mismatch: ${source_path}" >&2
    echo "expected=${expected_sha} actual=${source_sha}" >&2
    exit 1
  fi
  mkdir -p "$(dirname -- "${target_path}")"
  if [[ -f "${target_path}" ]]; then
    local target_sha
    target_sha="$(sha256sum "${target_path}" | awk '{print $1}')"
    if [[ "${target_sha}" != "${expected_sha}" ]]; then
      echo "Refusing to overwrite conflicting pinned file: ${target_path}" >&2
      echo "expected=${expected_sha} actual=${target_sha}" >&2
      exit 1
    fi
    return
  fi
  install -m 0644 "${source_path}" "${target_path}"
}

resolved_commit="$(git -C "${REPO_ROOT}" rev-parse --verify "${PINNED_COMMIT}^{commit}")"
if [[ "${resolved_commit}" != "${PINNED_COMMIT}" ]]; then
  echo "Pinned canary commit did not resolve exactly: ${PINNED_COMMIT}" >&2
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

"${PYTHON_BIN}" "${PROVISIONER}" \
  --source-root "${REPO_ROOT}" \
  --target-worktree "${PINNED_WORKTREE}" \
  --expected-sha256 "${PINNED_ARTIFACT_SHA256}" \
  --expected-registry-sha256 "${PINNED_REGISTRY_SHA256}" \
  --release-sha "${PINNED_COMMIT}" >/dev/null

copy_pinned_file \
  "${REPO_ROOT}/logs/rl_models/production/rl_exit_ppo.zip" \
  "${PINNED_WORKTREE}/logs/rl_models/production/rl_exit_ppo.zip" \
  "${PINNED_RL_EXIT_SHA256}"
copy_pinned_file \
  "${REPO_ROOT}/logs/rl_models/production/metadata.json" \
  "${PINNED_WORKTREE}/logs/rl_models/production/metadata.json" \
  "${PINNED_RL_EXIT_METADATA_SHA256}"

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

echo "Running ${DEPLOYMENT_ID} manually on ${PINNED_COMMIT}."
echo "Foreground mode: press Ctrl+C to stop the supervisor and child cleanly."

cd "${PINNED_WORKTREE}"

exec "${PYTHON_BIN}" -m dotenv -f "${ENV_FILE}" run -- \
  "${PYTHON_BIN}" "${PINNED_RUNNER}" \
  --epoch-id "${EPOCH_ID}" \
  --deployment-id "${DEPLOYMENT_ID}" \
  --evidence-path "${EVIDENCE_PATH}" \
  --mongo-timeout-ms 15000 \
  --child-start-budget "${CHILD_START_BUDGET}" \
  "$@"
