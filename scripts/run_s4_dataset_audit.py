#!/usr/bin/env python3
"""Run the bounded, read-only S4-P1A dataset audit."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from btc_scraper.research.s4_dataset_audit import render_markdown, run_dataset_audit


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REPO_ROOT / "research/s4_forecast_information_screening",
    )
    args = parser.parse_args()
    result = run_dataset_audit(REPO_ROOT)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / "s4_stage1_dataset_audit.json"
    report_path = args.output_dir / "s4_stage1_dataset_audit.md"
    json_path.write_text(json.dumps(result, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    report_path.write_text(render_markdown(result), encoding="utf-8")
    print(f"verdict={result['verdict']}")
    print(f"next_step={result['next_step']} (not executed)")
    print(f"json={json_path}")
    print(f"report={report_path}")
    return 0 if result["verdict"] == "DATASET_READY" else 2


if __name__ == "__main__":
    raise SystemExit(main())

