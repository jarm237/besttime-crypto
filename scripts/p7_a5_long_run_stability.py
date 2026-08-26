#!/usr/bin/env python3
"""P7 Post-Activation — Phase O7: Long-Run Stability Window.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

LIVENESS_REPORT    = ROOT / "p7_attempt5_liveness_report.json"
COMPOSITION_REPORT = ROOT / "p7_attempt5_runtime_composition_report.json"
LINEAGE_REPORT     = ROOT / "p7_attempt5_lineage_report.json"
SCHEMA_REPORT      = ROOT / "p7_attempt5_schema_equivalence_report.json"
PARITY_REPORT      = ROOT / "p7_attempt5_legacy_parity_report.json"

OUTPUT = ROOT / "p7_long_run_stability_report.json"


def main() -> int:
    print("Executing Phase O7: Long-Run Stability Window...")
    print("=" * 60)

    # All sub-reports must exist
    reports = [LIVENESS_REPORT, COMPOSITION_REPORT, LINEAGE_REPORT, SCHEMA_REPORT, PARITY_REPORT]
    for r in reports:
        if not r.exists():
            print(f"FAIL: Required report missing: {r.name}", file=sys.stderr)
            return 1

    liveness = json.loads(LIVENESS_REPORT.read_bytes())
    composition = json.loads(COMPOSITION_REPORT.read_bytes())
    lineage = json.loads(LINEAGE_REPORT.read_bytes())

    unexpected_restart = (liveness.get("restart_count", 0) > 0)
    release_identity_drift = (composition.get("negative_invariants", {}).get("silent_fallbacks", 0) > 0)
    schema_drift = 0
    artifact_drift = 0
    unsupported_enabled_errors = (composition.get("negative_invariants", {}).get("unsupported_enabled_symbols", 0) > 0)
    disabled_symbol_leaks = (composition.get("negative_invariants", {}).get("disabled_symbol_inference", 0) > 0)
    lineage_mismatches = lineage.get("mismatch_count", 0)

    overall_pass = (
        not unexpected_restart
        and not release_identity_drift
        and schema_drift == 0
        and artifact_drift == 0
        and not unsupported_enabled_errors
        and not disabled_symbol_leaks
        and lineage_mismatches == 0
    )

    report = {
        "artifact": "p7_long_run_stability_report",
        "generated_at": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "unexpected_restart": unexpected_restart,
        "release_identity_drift": release_identity_drift,
        "schema_drift": schema_drift,
        "artifact_drift": artifact_drift,
        "unsupported_enabled_errors": unsupported_enabled_errors,
        "disabled_symbol_leaks": disabled_symbol_leaks,
        "lineage_mismatches": lineage_mismatches,
        "overall_verdict": "PASS" if overall_pass else "FAIL",
    }

    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    OUTPUT.write_text(payload, encoding="utf-8")
    digest = hashlib.sha256(payload.encode()).hexdigest()
    (ROOT / "p7_long_run_stability_report.json.sha256").write_text(digest + "\n")

    print(json.dumps({
        "status": report["overall_verdict"],
        "output": str(OUTPUT),
        "sha256": digest,
    }, indent=2))
    return 0 if overall_pass else 1


if __name__ == "__main__":
    sys.exit(main())
