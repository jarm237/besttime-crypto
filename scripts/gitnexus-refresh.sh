#!/usr/bin/env bash

set -Eeuo pipefail

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"

if [[ -z "$ROOT" ]]; then
  echo "ERROR: current directory is not inside a Git repository." >&2
  exit 1
fi

cd "$ROOT"

STATE_DIR="$(git rev-parse --git-dir)/gitnexus-local"
STATE_FILE="$STATE_DIR/source-fingerprint"
mkdir -p "$STATE_DIR"

SOURCE_PATHS=(
  '*.py' '*.pyi' '*.js' '*.jsx' '*.mjs' '*.cjs' '*.ts' '*.tsx'
  '*.java' '*.go' '*.rs' '*.cs' '*.php' '*.rb' '*.vue' '*.svelte'
  '*.sh' '*.sql' '*.html' '*.css' '*.scss' '*.yaml' '*.yml' '*.toml'
)

calculate_fingerprint() {
  {
    git rev-parse HEAD
    git status --porcelain=v1 --untracked-files=all -- "${SOURCE_PATHS[@]}"
    git diff -- "${SOURCE_PATHS[@]}"
    git diff --cached -- "${SOURCE_PATHS[@]}"

    while IFS= read -r -d '' file; do
      printf 'untracked:%s\0' "$file"
      sha256sum -- "$file"
    done < <(git ls-files --others --exclude-standard -z -- "${SOURCE_PATHS[@]}")
  } | sha256sum | awk '{print $1}'
}

if [[ -f ".gitnexus/run.cjs" ]]; then
  GITNEXUS=(node .gitnexus/run.cjs)
elif command -v gitnexus >/dev/null 2>&1; then
  GITNEXUS=(gitnexus)
else
  echo "ERROR: GitNexus is unavailable and .gitnexus/run.cjs is missing." >&2
  echo "Bootstrap it with: npx gitnexus analyze" >&2
  exit 1
fi

echo "Repository: $ROOT"
echo "GitNexus:   ${GITNEXUS[*]}"

# Serialize writers to the repository index. Concurrent analyze processes can
# corrupt or leave the graph in an inconsistent state.
if command -v flock >/dev/null 2>&1; then
  exec 9>"$STATE_DIR/analyze.lock"
  if ! flock -w 120 9; then
    echo "ERROR: timed out waiting for another GitNexus refresh." >&2
    exit 1
  fi
fi

# Prevent GitNexus from mutating tracked repository files such as AGENTS.md and CLAUDE.md
"${GITNEXUS[@]}" analyze --skip-agents-md --skip-skills
"${GITNEXUS[@]}" status
calculate_fingerprint > "$STATE_FILE"

echo
echo "GitNexus index refreshed successfully."
echo "GitNexus source fingerprint updated."
echo "Restart the Codex/MCP session if graph queries still show stale data."
