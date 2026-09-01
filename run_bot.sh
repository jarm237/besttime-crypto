#!/bin/bash
# run_bot.sh: Bash helper script to execute the besttime-crypto trading bot.

set -e

# Resolve project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Ensure venv is available
if [ ! -d ".venv" ]; then
    echo "Error: .venv virtual environment not found in $SCRIPT_DIR"
    exit 1
fi

PYTHON_EXE=".venv/bin/python3"
if [ ! -f "$PYTHON_EXE" ]; then
    # Fallback to python
    PYTHON_EXE=".venv/bin/python"
fi

if [ ! -f "$PYTHON_EXE" ]; then
    echo "Error: python executable not found in .venv"
    exit 1
fi

echo "Starting Trading Bot..."
PYTHONPATH=. "$PYTHON_EXE" main.py "$@"
