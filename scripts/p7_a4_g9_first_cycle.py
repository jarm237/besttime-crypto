#!/usr/bin/env python3
"""P7 Attempt #4 — A4-G9: First Cycle verification.

Records whether the first runtime cycle completed. Since the process prematurely
exited on symbol mismatch, this gate records a FAIL.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OUTPUT = ROOT / "p7_attempt4_first_cycle_report.json"
STDERR_PATH = ROOT / "runtime/paper/paper-canary-a4-20260825-01/logs/supervised_child.stderr.log"


def main() -> int:
    print("P7-A4-G9: First Cycle verification")
    print("=" * 50)

    # Search child stderr for exceptions or unsupported symbol errors
    error_found = None
    if STDERR_PATH.exists():
        stderr_content = STDERR_PATH.read_text()
        if "inference_symbol_unsupported" in stderr_content:
            error_found = "inference_symbol_unsupported:DOGE"
        elif "RuntimeError" in stderr_content:
            error_found = "RuntimeError"

    g9_pass = False
    report = {
        "artifact": "p7_attempt4_first_cycle_report",
        "generated_at": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "first_cycle_completed": False,
        "error_observed": error_found,
        "overall_verdict": "FAIL",
    }
    print(f"  First cycle completed: {report['first_cycle_completed']}")
    print(f"  Error observed: {report['error_observed']}")

    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    OUTPUT.write_text(payload, encoding="utf-8")
    digest = hashlib.sha256(payload.encode()).hexdigest()
    (ROOT / "p7_attempt4_first_cycle_report.json.sha256").write_text(digest + "\n")

    print(json.dumps({
        "status": "FAIL",
        "output": str(OUTPUT),
        "sha256": digest,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
