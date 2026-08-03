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

gitnexus_command() {
  if [[ -f ".gitnexus/run.cjs" ]]; then
    node .gitnexus/run.cjs "$@"
  elif command -v gitnexus >/dev/null 2>&1; then
    gitnexus "$@"
  else
    return 127
  fi
}

calculate_fingerprint() {
  {
    git rev-parse HEAD
    git status --porcelain=v1 --untracked-files=all -- "${SOURCE_PATHS[@]}"
    git diff -- "${SOURCE_PATHS[@]}"
    git diff --cached -- "${SOURCE_PATHS[@]}"

    # `git status` records only an untracked path, so include file contents to
    # detect later edits to an untracked source file as well.
    while IFS= read -r -d '' file; do
      printf 'untracked:%s\0' "$file"
      sha256sum -- "$file"
    done < <(git ls-files --others --exclude-standard -z -- "${SOURCE_PATHS[@]}")
  } | sha256sum | awk '{print $1}'
}

CURRENT="$(calculate_fingerprint)"
PREVIOUS=""

if [[ -f "$STATE_FILE" ]]; then
  PREVIOUS="$(<"$STATE_FILE")"
fi

if [[ "$CURRENT" == "$PREVIOUS" ]] && gitnexus_command status >/dev/null 2>&1; then
  echo "GitNexus index appears current."
  exit 0
fi

echo "Source state changed or the GitNexus index is unavailable."
echo "Refreshing GitNexus index..."

"$ROOT/scripts/gitnexus-refresh.sh"
