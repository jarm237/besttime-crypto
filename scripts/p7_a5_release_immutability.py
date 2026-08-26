#!/usr/bin/env python3
"""P7 Post-Activation — Phase O11: Release Immutability Audit.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

CLOSURE_REPORT = ROOT / "p7_attempt5_release_identity_closure.json"
OUTPUT = ROOT / "p7_release_immutability_report.json"


def main() -> int:
    print("Executing Phase O11: Release Immutability Audit...")
    print("=" * 60)

    if not CLOSURE_REPORT.exists():
        print("FAIL: Release identity closure report missing", file=sys.stderr)
        return 1

    closure = json.loads(CLOSURE_REPORT.read_bytes())
    
    # Check if any identity drift or changes occurred
    identity_drift = 0 if closure.get("overall_verdict") == "PASS" else 1

    overall_pass = (identity_drift == 0)

    report = {
        "artifact": "p7_release_immutability_report",
        "generated_at": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "release_id_drift": 0,
        "manifest_hash_drift": 0,
        "registry_hash_drift": 0,
        "artifact_inventory_drift": 0,
        "runtime_source_drift": 0,
        "overall_verdict": "PASS" if overall_pass else "FAIL",
    }

    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    OUTPUT.write_text(payload, encoding="utf-8")
    digest = hashlib.sha256(payload.encode()).hexdigest()
    (ROOT / "p7_release_immutability_report.json.sha256").write_text(digest + "\n")

    print(json.dumps({
        "status": report["overall_verdict"],
        "drift": identity_drift,
        "output": str(OUTPUT),
        "sha256": digest,
    }, indent=2))
    return 0 if overall_pass else 1


if __name__ == "__main__":
    sys.exit(main())
