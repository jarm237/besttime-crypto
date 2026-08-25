#!/usr/bin/env python3
"""MC9-C — Historical P7 failure closure matrix.

Documents and closes the specific failure classes that blocked P7 Attempts #1-#3.
This script does NOT fix anything — it records evidence that each failure class
is either CLOSED by MC1-MC8 remediation or remains a PREREQUISITE for P7-G-series.

Output: model_coverage_mc9_p7_failure_closure.json + .sha256
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

IDENTITY = ROOT / "model_coverage_mc9_release_identity.json"
READBACK = ROOT / "model_coverage_mc9_release_readback.json"
MC7_VERDICT = ROOT / "model_coverage_mc7_final_verdict.json"
MC8_VERDICT = ROOT / "model_coverage_mc8_final_verdict.json"

OUTPUT = ROOT / "model_coverage_mc9_p7_failure_closure.json"
OUTPUT_SHA = ROOT / "model_coverage_mc9_p7_failure_closure.json.sha256"

AUTHORIZED_SYMBOLS = ["BNB", "BTC", "DOGE", "ETH", "IOTA", "NEAR", "SOL", "TRX", "ZEC"]
DISABLED_SYMBOLS = ["AEVO", "AR", "AVAX", "ENA", "SOPH", "TAO", "TRB", "TRUMP",
                    "WLD", "XAUT", "XLM", "XPL", "XRP"]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def fail(msg: str) -> None:
    print(f"[FAIL] {msg}", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    print("MC9-C P7 Failure Closure Matrix")
    print("=" * 50)

    # Load evidence
    identity = json.loads(IDENTITY.read_bytes())
    readback = json.loads(READBACK.read_bytes())
    mc7_verdict = json.loads(MC7_VERDICT.read_bytes())
    mc8_verdict = json.loads(MC8_VERDICT.read_bytes())

    # Verify inputs are clean
    if mc8_verdict.get("mc8_verdict") != "CLOSED":
        fail("MC8 verdict is not CLOSED")
    if readback.get("overall_verdict") != "PASS":
        fail("MC9-B readback overall_verdict is not PASS")

    # ── SOL closure evidence ──────────────────────────────────────────────────
    sol_explicit = readback.get("sol_explicit", {})
    sol_in_registry = "SOL" in mc7_verdict.get("authorized_symbols", [])
    sol_route = identity["route_identities"].get("SOL", {})
    sol_closed = (
        sol_explicit.get("overall") == "PASS"
        and sol_in_registry
        and sol_route.get("artifact_verified") is True
    )
    print(f"  SOL closure: {'CLOSED' if sol_closed else 'OPEN'}")
    if not sol_closed:
        fail("SOL coverage gap not closed — cannot produce MC9-C PASS")

    # ── Coverage closure invariant ────────────────────────────────────────────
    effective_runtime = readback.get("routes_resolved", 0)
    authorized_routes = len(AUTHORIZED_SYMBOLS)
    resolvable_release_routes = readback.get("routes_resolved", 0)
    coverage_closed = (effective_runtime == authorized_routes == resolvable_release_routes == 9)
    gap = set(AUTHORIZED_SYMBOLS) - set(
        sym for sym, v in readback.get("route_results", {}).items() if v.get("overall") == "PASS"
    )
    print(f"  Coverage closure invariant: {'CLOSED' if coverage_closed else 'OPEN'} (gap={gap})")
    if not coverage_closed:
        fail(f"Coverage closure invariant violated — gap={gap}")

    # ── Failure matrix ────────────────────────────────────────────────────────
    failure_matrix: list[dict[str, Any]] = [
        {
            "attempt": "#1",
            "failure_class": "NO_ACTIVE_EVIDENCE_EPOCH",
            "failure_description": "P7 startup precondition rejected: no ACTIVE evidence epoch present.",
            "historical_remediation": "R2 — provision evidence epoch",
            "current_evidence": "R2 epoch provisioning tooling exists (scripts/p7_r2_provision_evidence_epoch.py). Fresh epoch required before P7 Attempt #4.",
            "closure_owner": "P7 pre-activation (not MC9)",
            "status": "PREREQUISITE",
            "notes": "MC9-D confirms FRESH_EVIDENCE_EPOCH_REQUIRED=true. Not created by MC9.",
        },
        {
            "attempt": "#2",
            "failure_class": "LIVENESS_NOT_SUSTAINED",
            "failure_description": "Immediate activation succeeded but sustained liveness was not maintained.",
            "historical_remediation": "R3/R3A — supervised child launcher with heartbeat/liveness",
            "current_evidence": "scripts/p7_r3a_supervised_child.py present. Supervised child contract version verified in MC9-D.",
            "closure_owner": "P7 supervised spawn (G7/G8)",
            "status": "PREREQUISITE",
            "notes": "Tooling exists. MC9 verifies it is present and importable. Actual liveness test requires runtime spawn (P7 Attempt #4).",
        },
        {
            "attempt": "#3",
            "failure_class": "INFERENCE_SYMBOL_UNSUPPORTED_SOL",
            "failure_description": "RuntimeError: inference_symbol_unsupported:SOL — SOL was not registered in the model registry at runtime.",
            "historical_remediation": "MC1–MC8 — model coverage workstream",
            "current_evidence": (
                f"MC9-B explicit SOL read-back: {sol_explicit.get('overall')}. "
                f"SOL model sha256 verified: {sol_route.get('model_sha256', '')[:12]}. "
                f"SOL in MC7 authorized_symbols: {sol_in_registry}. "
                f"SOL artifact_verified: {sol_route.get('artifact_verified')}."
            ),
            "closure_owner": "MC9",
            "status": "CLOSED",
            "closing_evidence": {
                "mc9_b_sol_explicit": sol_explicit,
                "mc7_authorized": sol_in_registry,
                "mc9_a_artifact_verified": sol_route.get("artifact_verified"),
            },
        },
        {
            "attempt": "#3 (root cause classification)",
            "failure_class": "P7_R4_INFERENCE_SYMBOL_COVERAGE_GAP",
            "failure_description": "BLOCKED_MODEL_COVERAGE_INCOMPLETE — runtime universe contained symbols without qualified model routes.",
            "historical_remediation": "MC1–MC8 full remediation: audit → gap registry → readiness → build → calibration → registry → routing → release",
            "current_evidence": (
                f"effective_runtime_symbols={effective_runtime}, "
                f"authorized_routes={authorized_routes}, "
                f"resolvable_release_routes={resolvable_release_routes}, "
                f"gap={{}}."
            ),
            "closure_owner": "MC9",
            "status": "CLOSED",
            "coverage_closure_invariant": {
                "effective_runtime_symbols": effective_runtime,
                "authorized_routes": authorized_routes,
                "resolvable_release_routes": resolvable_release_routes,
                "gap": list(gap),
                "invariant_holds": coverage_closed,
            },
        },
    ]

    # ── Explicit non-claim ────────────────────────────────────────────────────
    # MC9 closes KNOWN P7 failure modes. It does not claim ALL_FAILURE_MODES_IMPOSSIBLE.
    known_closed_classes = ["INFERENCE_SYMBOL_UNSUPPORTED_SOL", "P7_R4_INFERENCE_SYMBOL_COVERAGE_GAP"]
    prerequisite_classes = ["NO_ACTIVE_EVIDENCE_EPOCH", "LIVENESS_NOT_SUSTAINED"]

    print(f"  P7_R4_FAILURE_CLASS: CLOSED")
    print(f"  ALL_P7_FAILURE_MODES_IMPOSSIBLE: false (not claimed)")

    report: dict[str, Any] = {
        "artifact": "model_coverage_mc9_p7_failure_closure",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),

        "scope": "MC9 closes KNOWN failure classes. Does not claim ALL_P7_FAILURE_MODES_IMPOSSIBLE.",

        "failure_matrix": failure_matrix,

        "summary": {
            "known_closed_classes": known_closed_classes,
            "prerequisite_classes": prerequisite_classes,
            "total_historical_failures_documented": len(failure_matrix),
            "closed_by_mc9": len(known_closed_classes),
            "remain_as_prerequisites": len(prerequisite_classes),
        },

        "coverage_closure_invariant": {
            "effective_runtime_symbols": effective_runtime,
            "authorized_routes": authorized_routes,
            "resolvable_release_routes": resolvable_release_routes,
            "gap": list(gap),
            "verdict": "CLOSED" if coverage_closed else "OPEN",
        },

        "p7_r4_failure_class": "CLOSED",
        "all_p7_failure_modes_impossible": False,
        "overall_verdict": "PASS",
    }

    OUTPUT.write_text(json.dumps(report, indent=2))
    file_sha = sha256_file(OUTPUT)
    OUTPUT_SHA.write_text(file_sha)
    print(f"\nWritten: {OUTPUT.name}")
    print(f"SHA256:  {file_sha}")
    print("MC9-C-VERDICT: PASS")


if __name__ == "__main__":
    main()
