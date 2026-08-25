#!/usr/bin/env python3
"""P7 Attempt #5 — A5-G2: Exact Activation Preflight.

Runs final verification of all pre-spawn preconditions immediately before
authorization consumption and spawn occurs.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

AUTH_PATH            = REPO_ROOT / "p7_attempt5_authorization.json"
IDENTITY_PATH        = REPO_ROOT / "model_coverage_mc9_release_identity.json"
EPOCH_PROVISION_PATH = REPO_ROOT / "p7_attempt5_epoch_provision.json"
EPOCH_READBACK_PATH  = REPO_ROOT / "p7_attempt5_epoch_readback.json"
RESUME_CONTRACT_PATH = REPO_ROOT / "p7_attempt5_resume_contract.json"
OUTPUT_PATH          = REPO_ROOT / "p7_attempt5_prespawn_preflight.json"

EXPECTED_SYMBOLS     = sorted(["BNB", "BTC", "DOGE", "ETH", "IOTA", "NEAR", "SOL", "TRX", "ZEC"])
ATTEMPT_ID           = "p7-attempt-5"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def fail(msg: str) -> None:
    print(f"FAIL: {msg}", file=sys.stderr)
    sys.exit(1)


def main() -> int:
    print("Executing Phase A5-D: G2 Prespawn Activation Preflight...")
    print("=" * 60)

    # 1. Check artifact existence
    for p in (AUTH_PATH, IDENTITY_PATH, EPOCH_PROVISION_PATH, EPOCH_READBACK_PATH, RESUME_CONTRACT_PATH):
        if not p.exists():
            fail(f"Required artifact missing: {p.name}")

    auth = json.loads(AUTH_PATH.read_text(encoding="utf-8"))
    identity = json.loads(IDENTITY_PATH.read_text(encoding="utf-8"))
    readback = json.loads(EPOCH_READBACK_PATH.read_text(encoding="utf-8"))
    resume = json.loads(RESUME_CONTRACT_PATH.read_text(encoding="utf-8"))

    gates = {}

    # Check G2-1: fresh epoch active
    g2_1_pass = readback["overall_verdict"] == "PASS" and readback["db_record"]["status"] == "ACTIVE"
    gates["A5-G2-1"] = {
        "gate": "fresh_epoch_active",
        "epoch_id": readback["epoch_id"],
        "status": readback["db_record"]["status"],
        "result": "PASS" if g2_1_pass else "FAIL",
    }

    # Check G2-2: authorization is ARMED
    g2_2_pass = auth["state"] == "ARMED" and auth["consumed"] is False
    gates["A5-G2-2"] = {
        "gate": "authorization_armed",
        "state": auth["state"],
        "consumed": auth["consumed"],
        "result": "PASS" if g2_2_pass else "FAIL",
    }

    # Check G2-3: release ID and commit exact
    g2_3_pass = (
        auth["release_id"] == "model-coverage-v1-r1"
        and auth["source_commit"] == "1b4d2965d0a374660278a61b80dea8443f61382f"
    )
    gates["A5-G2-3"] = {
        "gate": "release_and_commit_exact",
        "release_id": auth["release_id"],
        "source_commit": auth["source_commit"],
        "result": "PASS" if g2_3_pass else "FAIL",
    }

    # Check G2-4: effective symbols exact
    g2_4_pass = sorted(auth["effective_runtime_symbols"]) == EXPECTED_SYMBOLS
    gates["A5-G2-4"] = {
        "gate": "effective_symbols_exact",
        "symbols": sorted(auth["effective_runtime_symbols"]),
        "result": "PASS" if g2_4_pass else "FAIL",
    }

    # Check G2-5: route-class contract check PASS
    route_class_report = REPO_ROOT / "p7_r6_v1r1_route_class_report.json"
    g2_5_pass = route_class_report.exists()
    if g2_5_pass:
        records = json.loads(route_class_report.read_text(encoding="utf-8"))
        g2_5_pass = all(r["status"] == "PASS" for r in records)
    gates["A5-G2-5"] = {
        "gate": "route_class_report_pass",
        "result": "PASS" if g2_5_pass else "FAIL",
    }

    # Check G2-6: runtime lock file is not active
    lock_file = REPO_ROOT / "runtime/paper/paper-canary-a5-20260825-01/state/runtime.lock"
    g2_6_pass = not lock_file.exists()
    gates["A5-G2-6"] = {
        "gate": "runtime_lock_absent",
        "lock_file": str(lock_file),
        "result": "PASS" if g2_6_pass else "FAIL",
    }

    overall = "PASS" if all(v["result"] == "PASS" for v in gates.values()) else "FAIL"

    report = {
        "attempt_id": ATTEMPT_ID,
        "gates": gates,
        "overall_verdict": overall,
    }

    content = json.dumps(report, indent=2, sort_keys=True)
    OUTPUT_PATH.write_text(content, encoding="utf-8")
    
    digest = _sha256_text(content)
    (REPO_ROOT / "p7_attempt5_prespawn_preflight.json.sha256").write_text(
        f"{digest}  p7_attempt5_prespawn_preflight.json\n", encoding="utf-8"
    )

    print("Generated p7_attempt5_prespawn_preflight.json")
    for k, v in gates.items():
        print(f"  {k:<35} {v['result']}")
    print(f"Overall Preactivation Preflight: {overall}")

    return 0 if overall == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
