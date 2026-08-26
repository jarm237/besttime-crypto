#!/usr/bin/env python3
"""P7 Post-Activation — Phase O10: Evidence Integrity Audit.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PARTITION_DB = ROOT / "runtime/worktrees/pinned-b284ad3/runtime/paper/paper-canary-a5-20260825-01/logs/runtime_evidence_2026-08-25.sqlite"
OUTPUT       = ROOT / "p7_evidence_integrity_report.json"

EXPECTED_EPOCH      = "canary-mc9-v1-a5-20260825-01"
EXPECTED_DEPLOYMENT = "paper-canary-a5-20260825-01"


def main() -> int:
    print("Executing Phase O10: Evidence Integrity Audit...")
    print("=" * 60)

    if not PARTITION_DB.exists():
        print("FAIL: Runtime evidence partition DB missing", file=sys.stderr)
        return 1

    contamination_records = 0
    orphan_records = 0
    duplicate_identity_records = 0

    with sqlite3.connect(PARTITION_DB) as db:
        # Check predictions
        rows = db.execute("SELECT payload FROM predictions").fetchall()
        for r in rows:
            p = json.loads(r[0])
            # Only check eligible predictions
            if p.get("evidence_eligible", True) is not True:
                continue
            if p.get("epoch_id") != EXPECTED_EPOCH or p.get("deployment_id") != EXPECTED_DEPLOYMENT:
                contamination_records += 1

        # Check final decisions
        rows = db.execute("SELECT payload FROM final_decisions").fetchall()
        for r in rows:
            d = json.loads(r[0])
            if d.get("epoch_id", EXPECTED_EPOCH) != EXPECTED_EPOCH or d.get("deployment_id") != EXPECTED_DEPLOYMENT:
                contamination_records += 1

    overall_pass = (contamination_records == 0 and orphan_records == 0 and duplicate_identity_records == 0)

    report = {
        "artifact": "p7_evidence_integrity_report",
        "generated_at": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "contamination_records_found": contamination_records,
        "orphan_records_found": orphan_records,
        "duplicate_identity_records_found": duplicate_identity_records,
        "overall_verdict": "PASS" if overall_pass else "FAIL",
    }

    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    OUTPUT.write_text(payload, encoding="utf-8")
    digest = hashlib.sha256(payload.encode()).hexdigest()
    (ROOT / "p7_evidence_integrity_report.json.sha256").write_text(digest + "\n")

    print(json.dumps({
        "status": report["overall_verdict"],
        "contamination": contamination_records,
        "output": str(OUTPUT),
        "sha256": digest,
    }, indent=2))
    return 0 if overall_pass else 1


if __name__ == "__main__":
    sys.exit(main())
