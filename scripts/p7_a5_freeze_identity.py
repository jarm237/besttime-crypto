#!/usr/bin/env python3
"""P7 Attempt #5 — Phase A: Freeze exact identities into contract.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SPAWN_PATH      = ROOT / "p7_attempt5_spawn_record.json"
AUTH_PATH       = ROOT / "p7_attempt5_authorization.json"
RESUME_CONTRACT = ROOT / "p7_attempt5_resume_contract.json"
OUTPUT          = ROOT / "p7_attempt5_runtime_identity_contract.json"


def main() -> int:
    print("Executing Phase A: Freeze Attempt #5 exact identities...")
    print("=" * 60)

    if not SPAWN_PATH.exists() or not AUTH_PATH.exists() or not RESUME_CONTRACT.exists():
        print("FAIL: Required governance artifacts are missing", file=sys.stderr)
        return 1

    spawn = json.loads(SPAWN_PATH.read_bytes())
    auth = json.loads(AUTH_PATH.read_bytes())

    # Pin exactly:
    attempt_id = 5
    epoch_id = "canary-mc9-v1-a5-20260825-01"
    deployment_id = "paper-canary-a5-20260825-01"
    paper_run_id = "paper-canary-a5-20260825-01"

    release_id = "model-coverage-v1-r1"
    release_identity_sha256 = "d8dcafb2aef0010926acfa19114eb2c2b827517bae8f45be2a7e849b6643c14a"
    release_manifest_sha256 = "6f79cd6b52bfb4083c1af2b258cbc7ef465ed07ebb383d4729e4d923500cd64b"
    runtime_source_commit = "b284ad36f311c5cbf4986c6dfe7f47e8aee01062"
    authorization_sha256 = "f892bb91cb5a85ea34a220e5386bde6a19dd726462df059f0040eab9c105a42c"

    child_pid = spawn.get("child_pid")
    if not child_pid or child_pid != 770821:
        print(f"FAIL: child PID mismatch, expected 770821, got {child_pid}", file=sys.stderr)
        return 1

    authorized_symbols = [
        "BNB",
        "BTC",
        "DOGE",
        "ETH",
        "IOTA",
        "NEAR",
        "SOL",
        "TRX",
        "ZEC"
    ]
    disabled_symbols = [
        "AEVO",
        "AR",
        "AVAX",
        "ENA",
        "SOPH",
        "TAO",
        "TRB",
        "TRUMP",
        "WLD",
        "XAUT",
        "XLM",
        "XPL",
        "XRP"
    ]
    feature_schema_version = "meta-v3.1-43f"

    # Assert no drift
    assert auth["attempt"] == attempt_id, "attempt mismatch"
    assert auth["release_id"] == release_id, "release_id mismatch"
    assert auth["source_commit"] == runtime_source_commit, "source_commit mismatch"
    assert auth["release_manifest_sha256"] == release_manifest_sha256, "manifest sha mismatch"
    assert auth["release_identity_sha256"] == release_identity_sha256, "identity sha mismatch"
    assert auth["consumed"] is True, "authorization must be CONSUMED"

    contract = {
        "artifact": "p7_attempt5_runtime_identity_contract",
        "generated_at": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "attempt_id": attempt_id,
        "epoch_id": epoch_id,
        "deployment_id": deployment_id,
        "paper_run_id": paper_run_id,
        "release_id": release_id,
        "release_identity_sha256": release_identity_sha256,
        "release_manifest_sha256": release_manifest_sha256,
        "runtime_source_commit": runtime_source_commit,
        "authorization_sha256": authorization_sha256,
        "child_pid": child_pid,
        "authorized_symbols": authorized_symbols,
        "disabled_symbols": disabled_symbols,
        "feature_schema_version": feature_schema_version,
        "overall_verdict": "PASS"
    }

    payload = json.dumps(contract, indent=2, sort_keys=True) + "\n"
    OUTPUT.write_text(payload, encoding="utf-8")
    digest = hashlib.sha256(payload.encode()).hexdigest()
    (ROOT / "p7_attempt5_runtime_identity_contract.json.sha256").write_text(digest + "\n")

    print(json.dumps({
        "status": "PASS",
        "output": str(OUTPUT),
        "sha256": digest,
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
