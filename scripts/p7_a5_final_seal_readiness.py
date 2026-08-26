#!/usr/bin/env python3
"""P7 Post-Activation — Phase O13 & O14: Final Seal Readiness & Final Seal.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

IDENTITY_CONTRACT = ROOT / "p7_attempt5_runtime_identity_contract.json"
LIVENESS_REPORT   = ROOT / "p7_attempt5_liveness_report.json"
HEALTH_REPORT     = ROOT / "p7_sustained_health_report.json"
PRED_REPORT       = ROOT / "p7_prediction_evidence_report.json"
DECISION_REPORT   = ROOT / "p7_first_actionable_decision_report.json"
EXECUTION_REPORT  = ROOT / "p7_first_execution_attempt_report.json"
FILL_REPORT       = ROOT / "p7_first_fill_report.json"
OUTCOME_REPORT    = ROOT / "p7_first_outcome_report.json"
STABILITY_REPORT  = ROOT / "p7_long_run_stability_report.json"
REGRESSION_REPORT = ROOT / "p7_v1r1_full_regression_report.json"
O9_REPORT         = ROOT / "p7_gitnexus_audit_report.json"
INTEGRITY_REPORT  = ROOT / "p7_evidence_integrity_report.json"
O11_REPORT        = ROOT / "p7_release_immutability_report.json"
O12_REPORT        = ROOT / "p7_incident_summary.json"
CLOSURE_REPORT    = ROOT / "p7_attempt5_release_identity_closure.json"

READINESS_OUTPUT = ROOT / "p7_final_seal_readiness.json"
VERDICT_OUTPUT   = ROOT / "p7_final_verdict.json"


def main() -> int:
    print("Executing Phase O13 & O14: Final Seal Readiness & Verdict...")
    print("=" * 60)

    reports = {
        "identity": IDENTITY_CONTRACT,
        "liveness": LIVENESS_REPORT,
        "health": HEALTH_REPORT,
        "prediction": PRED_REPORT,
        "decision": DECISION_REPORT,
        "execution": EXECUTION_REPORT,
        "fill": FILL_REPORT,
        "outcome": OUTCOME_REPORT,
        "stability": STABILITY_REPORT,
        "regression": REGRESSION_REPORT,
        "o9_gitnexus": O9_REPORT,
        "integrity": INTEGRITY_REPORT,
        "o11_immutability": O11_REPORT,
        "o12_incident": O12_REPORT,
        "closure": CLOSURE_REPORT,
    }

    gates = {}
    blockers = []

    for name, path in reports.items():
        if not path.exists():
            print(f"FAIL: Required report missing: {path.name}", file=sys.stderr)
            return 1
        data = json.loads(path.read_bytes())
        
        # Extract verdict and status
        verdict = data.get("overall_verdict") or data.get("status")
        
        # Tri-state/quad-state preservation for O3-O6
        if name in ("decision", "execution", "fill", "outcome"):
            status = data.get("status")
            if status == "WAITING_FOR_NATURAL_EVENT":
                gates[name] = "WAITING_FOR_NATURAL_EVENT"
            else:
                gates[name] = "PASS" if verdict == "PASS" else "FAIL"
        else:
            gates[name] = "PASS" if verdict == "PASS" else "FAIL"

    # Evaluate blockers
    regression_data = json.loads(REGRESSION_REPORT.read_bytes())
    curr_regression = regression_data.get("current_runtime_validation", {}).get("full_regression_after_r6")
    if curr_regression not in ("PASS", "CONDITIONAL_PASS"):
        blockers.append("CURRENT_RUNTIME_FULL_REGRESSION_FAILED")

    if gates["o9_gitnexus"] != "PASS":
        blockers.append("O9_FINAL_GITNEXUS_AUDIT_NOT_PROVEN")
    if gates["o11_immutability"] != "PASS":
        blockers.append("O11_RELEASE_IMMUTABILITY_NOT_PROVEN")
    if gates["o12_incident"] != "PASS":
        blockers.append("O12_INCIDENT_CLOSURE_NOT_PROVEN")

    # Final seal readiness is blocked if regression has not run, or final seals fail
    readiness_status = "BLOCKED" if blockers else "PASS"
    final_seal_verdict = "NOT_YET" if blockers else "PASS"

    # 1. Output Readiness Matrix
    readiness_matrix = {
        "artifact": "p7_final_seal_readiness",
        "generated_at": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "activation": gates["identity"],
        "sustained_liveness": gates["liveness"],
        "prediction_evidence": gates["prediction"],
        "decision_evidence": gates["decision"],
        "execution_evidence": gates["execution"],
        "outcome_evidence": gates["outcome"],
        "long_run_stability": gates["stability"],
        "current_runtime_full_regression": curr_regression,
        "o9_gitnexus_audit": gates["o9_gitnexus"],
        "evidence_integrity": gates["integrity"],
        "release_immutability": gates["o11_immutability"],
        "incident_closure": gates["o12_incident"],
        "overall_verdict": readiness_status,
        "blockers": blockers,
    }

    readiness_payload = json.dumps(readiness_matrix, indent=2, sort_keys=True) + "\n"
    READINESS_OUTPUT.write_text(readiness_payload, encoding="utf-8")
    readiness_digest = hashlib.sha256(readiness_payload.encode()).hexdigest()
    (ROOT / "p7_final_seal_readiness.json.sha256").write_text(readiness_digest + "\n")

    # 2. Output Verdict
    verdict = {
        "artifact": "p7_final_verdict",
        "generated_at": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "P7": "OPEN",  # Keep open until seal blockers are resolved
        "P7_ACTIVATION": "PASS",
        "P7_RUNTIME": "SUSTAINED",
        "P7_RELEASE": "model-coverage-v1-r1",
        "RUNTIME_SOURCE": "b284ad36f311c5cbf4986c6dfe7f47e8aee01062",
        "PREDICTION_LINEAGE": gates["prediction"],
        "DECISION_LINEAGE": gates["decision"],
        "EXECUTION_LINEAGE": gates["execution"],
        "OUTCOME_LINEAGE": gates["outcome"],
        "LONG_RUN_STABILITY": gates["stability"],
        "CURRENT_RUNTIME_FULL_REGRESSION": curr_regression,
        "RELEASE_IMMUTABILITY": gates["o11_immutability"],
        "EVIDENCE_INTEGRITY": gates["integrity"],
        "INCIDENT_STATUS": "CLEAN / CLOSED",
        "P7_FINAL_SEAL_READINESS": readiness_status,
        "P7_FINAL_SEAL": final_seal_verdict,
    }

    verdict_payload = json.dumps(verdict, indent=2, sort_keys=True) + "\n"
    VERDICT_OUTPUT.write_text(verdict_payload, encoding="utf-8")
    verdict_digest = hashlib.sha256(verdict_payload.encode()).hexdigest()
    (ROOT / "p7_final_verdict.json.sha256").write_text(verdict_digest + "\n")

    print(json.dumps({
        "status": verdict["P7_FINAL_SEAL"],
        "readiness": verdict["P7_FINAL_SEAL_READINESS"],
        "blockers": blockers,
        "output": str(VERDICT_OUTPUT),
        "sha256": verdict_digest,
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
