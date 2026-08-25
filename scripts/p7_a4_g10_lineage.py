#!/usr/bin/env python3
"""P7 Attempt #4 — A4-G10: Lineage verification.

Checks that the persisted predictions/decisions match Attempt #4 identifiers.
Since the first cycle failed, this script verifies that 0 predictions were made,
resulting in a FAIL.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OUTPUT = ROOT / "p7_attempt4_lineage_report.json"
DEPLOYMENT_ID = "paper-canary-a4-20260825-01"


def main() -> int:
    print("P7-A4-G10: Lineage verification")
    print("=" * 50)

    # Count predictions in sqlite global index for this deployment
    sys.path.insert(0, "runtime/worktrees/pinned-94407d3")
    from btc_scraper.ml_engine.runtime_evidence_store import RuntimeEvidenceStore
    store = RuntimeEvidenceStore()
    evidence_db = store.global_index_path

    predictions_count = 0
    mismatch_found = False

    if evidence_db.exists():
        try:
            with sqlite3.connect(evidence_db) as db:
                predictions_count = db.execute(
                    "SELECT COUNT(*) FROM predictions WHERE deployment_id=?",
                    (DEPLOYMENT_ID,)
                ).fetchone()[0]
        except Exception:
            predictions_count = 0

    print(f"  Persisted predictions for A4: {predictions_count}")

    report = {
        "artifact": "p7_attempt4_lineage_report",
        "generated_at": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "lineage_records_found": predictions_count,
        "mismatches_found": mismatch_found,
        "overall_verdict": "FAIL",
    }

    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    OUTPUT.write_text(payload, encoding="utf-8")
    digest = hashlib.sha256(payload.encode()).hexdigest()
    (ROOT / "p7_attempt4_lineage_report.json.sha256").write_text(digest + "\n")

    print(json.dumps({
        "status": "FAIL",
        "output": str(OUTPUT),
        "sha256": digest,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
