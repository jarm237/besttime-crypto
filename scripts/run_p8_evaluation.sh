#!/bin/bash
# run_p8_evaluation.sh: Manual execution wrapper for P8 economic evaluation.

set -e

# Resolve script directory and project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_ROOT"

# Ensure venv is available
if [ ! -d ".venv" ]; then
    echo "Error: .venv virtual environment not found in $PROJECT_ROOT"
    exit 1
fi

echo "Running P8 Economic Effectiveness Evaluation..."
PYTHONPATH=. .venv/bin/python3 scripts/p8_economic_report.py \
    --evidence-db logs/runtime_evidence.sqlite \
    --reservation-db runtime/production/local-production/data/execution/reservations.db

echo "P8 Evaluation reports generated successfully!"
echo "- JSON: p8_economic_effectiveness_report.json"
echo "- Markdown: p8_economic_effectiveness_report.md"
