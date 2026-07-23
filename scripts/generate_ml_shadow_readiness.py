#!/usr/bin/env python3
"""Generate a point-in-time shadow-readiness report from canonical evidence."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from btc_scraper.ml_engine.shadow_validation import evaluate_shadow_validation


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        default="evaluations/ml_engine_remediation_20260723/shadow_validation_status.json",
    )
    args = parser.parse_args()
    report = evaluate_shadow_validation()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({
        "passed": report["passed"],
        "failed_checks": report["failed_checks"],
        "output": str(output),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
