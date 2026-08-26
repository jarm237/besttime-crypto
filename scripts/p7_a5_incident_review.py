#!/usr/bin/env python3
"""P7 Post-Activation — Phase O12: Incident Review Gate.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

HEALTH_REPORT = ROOT / "p7_sustained_health_report.json"
OUTPUT = ROOT / "p7_incident_summary.json"


def main() -> int:
    print("Executing Phase O12: Incident Review Gate...")
    print("=" * 60)

    if not HEALTH_REPORT.exists():
        print("FAIL: Sustained health report missing", file=sys.stderr)
        return 1

    health = json.loads(HEALTH_REPORT.read_bytes())
    
    # Track critical incidents
    unresolved_critical_incidents = health.get("fatal_runtime_errors", 0) + health.get("restart_count", 0)

    overall_pass = (unresolved_critical_incidents == 0)

    report = {
        "artifact": "p7_incident_summary",
        "generated_at": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "unresolved_critical_incidents": unresolved_critical_incidents,
        "incidents": [],
        "overall_verdict": "PASS" if overall_pass else "FAIL",
    }

    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    OUTPUT.write_text(payload, encoding="utf-8")
    digest = hashlib.sha256(payload.encode()).hexdigest()
    (ROOT / "p7_incident_summary.json.sha256").write_text(digest + "\n")

    print(json.dumps({
        "status": report["overall_verdict"],
        "unresolved_incidents": unresolved_critical_incidents,
        "output": str(OUTPUT),
        "sha256": digest,
    }, indent=2))
    return 0 if overall_pass else 1


if __name__ == "__main__":
    sys.exit(main())
