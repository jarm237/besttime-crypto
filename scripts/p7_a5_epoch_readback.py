#!/usr/bin/env python3
"""P7 Attempt #5 — A5-G1 Phase C: Fresh Evidence Epoch Read-Back.

Reads back the created evidence epoch from the global database index.
Verifies all 6 gates:
  - A5-G1-1: epoch exists in global index
  - A5-G1-2: epoch status is ACTIVE
  - A5-G1-3: epoch identity matches A5 resume contract
  - A5-G1-4: epoch deployment identity matches manifest
  - A5-G1-5: epoch release identity matches Attempt #5 authorization
  - A5-G1-6 (SOL): SOL is explicitly in the analysis universe
"""
from __future__ import annotations

import datetime
import hashlib
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PINNED          = ROOT / "runtime" / "worktrees" / "pinned-1b4d296"
RESUME_CONTRACT = ROOT / "p7_attempt5_resume_contract.json"
AUTH_PATH       = ROOT / "p7_attempt5_authorization.json"
A5_MANIFEST     = ROOT / "p7_a5_manifest.json"
OUTPUT          = ROOT / "p7_attempt5_epoch_readback.json"

ATTEMPT_ID     = "p7-attempt-5"
DEPLOYMENT_ID  = "paper-canary-a5-20260825-01"
PAPER_RUN_ID   = "paper-canary-a5-20260825-01"
EPOCH_ID       = "canary-mc9-v1-a5-20260825-01"
SOURCE_COMMIT  = "1b4d2965d0a374660278a61b80dea8443f61382f"


def fail(msg: str) -> None:
    print(f"FAIL: {msg}", file=sys.stderr)
    sys.exit(1)


def sha256_file(path: Path) -> str:
    d = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            d.update(block)
    return d.hexdigest()


def import_pinned_modules(pinned_root: Path) -> dict[str, Any]:
    pinned = str(pinned_root)
    if pinned in sys.path:
        sys.path.remove(pinned)
    sys.path.insert(0, pinned)
    from btc_scraper.ml_engine.runtime_evidence_store import RuntimeEvidenceStore
    return {"RuntimeEvidenceStore": RuntimeEvidenceStore}


def main() -> int:
    print("P7-A5-G1: Fresh Evidence Epoch Read-Back")
    print("=" * 50)

    # Load contracts and manifest
    if not RESUME_CONTRACT.exists():
        fail("Resume contract missing — run p7_a5_resume_contract.py first")
    if not A5_MANIFEST.exists():
        fail("A5 manifest missing — run p7_a5_provision_epoch.py first")

    contract = json.loads(RESUME_CONTRACT.read_bytes())
    auth = json.loads(AUTH_PATH.read_bytes())
    manifest = json.loads(A5_MANIFEST.read_bytes())

    # Import pinned RuntimeEvidenceStore
    modules = import_pinned_modules(PINNED)
    store = modules["RuntimeEvidenceStore"]()
    evidence_db = store.global_index_path

    if not evidence_db.exists():
        fail(f"Global index database missing: {evidence_db}")

    # Query active epoch
    with sqlite3.connect(evidence_db) as db:
        row = db.execute(
            "SELECT epoch_id, deployment_id, status, paper_run_id, code_commit_sha, "
            "artifact_sha256, release_manifest_sha256, analysis_universe, release_manifest "
            "FROM evidence_epochs WHERE epoch_id=?",
            (EPOCH_ID,)
        ).fetchone()

    gates: dict[str, dict[str, Any]] = {}

    # G1-1: Epoch exists
    g1_1_pass = row is not None
    gates["A5-G1-1"] = {
        "gate": "epoch_exists",
        "epoch_id": EPOCH_ID,
        "result": "PASS" if g1_1_pass else "FAIL",
    }
    if not g1_1_pass:
        fail(f"Epoch {EPOCH_ID} not found in database")

    db_epoch_id, db_deploy_id, db_status, db_run_id, db_commit, db_artifact_sha, db_manifest_sha, db_universe_raw, db_manifest_raw = row

    # G1-2: Status is ACTIVE
    g1_2_pass = db_status == "ACTIVE"
    gates["A5-G1-2"] = {
        "gate": "status_active",
        "status": db_status,
        "result": "PASS" if g1_2_pass else "FAIL",
    }
    if not g1_2_pass:
        fail(f"Epoch status is not ACTIVE: {db_status}")

    # G1-3: Identity matches resume contract
    g1_3_pass = (
        db_epoch_id == EPOCH_ID and
        db_deploy_id == DEPLOYMENT_ID and
        db_run_id == PAPER_RUN_ID
    )
    gates["A5-G1-3"] = {
        "gate": "identity_matches_resume_contract",
        "epoch_id": db_epoch_id,
        "deployment_id": db_deploy_id,
        "paper_run_id": db_run_id,
        "result": "PASS" if g1_3_pass else "FAIL",
    }
    if not g1_3_pass:
        fail(f"Identity mismatch in database: epoch={db_epoch_id} deploy={db_deploy_id} run={db_run_id}")

    # G1-4: Deployment identity matches manifest
    g1_4_pass = (
        db_deploy_id == manifest["deployment_id"] and
        db_run_id == manifest["paper_run_id"] and
        db_commit == manifest["release"]["commit_sha"] and
        db_artifact_sha == manifest["artifact"]["sha256"]
    )
    gates["A5-G1-4"] = {
        "gate": "deployment_identity_matches_manifest",
        "manifest_deployment_id": manifest["deployment_id"],
        "manifest_artifact_sha": manifest["artifact"]["sha256"],
        "result": "PASS" if g1_4_pass else "FAIL",
    }
    if not g1_4_pass:
        fail("Deployment mismatch between database and manifest")

    # G1-5: Release identity matches Attempt #5 authorization / manifest
    expected_manifest_dict = {
        "analysis_universe": "BNB,BTC,DOGE,ETH,IOTA,NEAR,SOL,TRX,ZEC",
        "artifact_sha256": "dbf0a08241dae01241539ef3f48c6a0b13da9b13a5b128de259aac06d267241c",
        "decision_contract": "side-probability-v2",
        "deployment_id": DEPLOYMENT_ID,
        "feature_schema_version": "meta-v3.1-43f",
        "manifest_schema_version": "evidence-manifest-v1",
        "metadata_sha256": "6d1bba532b090af90e3e2761e3b85633b0e0b82e6bf9544b43daf8fe4e070591",
        "paper_run_id": PAPER_RUN_ID,
        "probability_semantics": "P(up)",
        "registry_sha256": "445a38a625d0a56aa416192d46cae417e4ff62ffcf7ea249a7ee1b376829346a",
        "release_sha": SOURCE_COMMIT,
    }
    expected_dynamic_manifest_payload = json.dumps(expected_manifest_dict, separators=(",", ":"), sort_keys=True)
    expected_dynamic_manifest_sha = hashlib.sha256(expected_dynamic_manifest_payload.encode()).hexdigest()
    try:
        release_manifest_dict = json.loads(db_manifest_raw) if isinstance(db_manifest_raw, str) else db_manifest_raw
    except Exception:
        release_manifest_dict = {}

    g1_5_pass = (
        db_manifest_sha == expected_dynamic_manifest_sha and
        db_commit == SOURCE_COMMIT and
        release_manifest_dict.get("release_sha") == SOURCE_COMMIT and
        release_manifest_dict.get("artifact_sha256") == "dbf0a08241dae01241539ef3f48c6a0b13da9b13a5b128de259aac06d267241c" and
        release_manifest_dict.get("metadata_sha256") == "6d1bba532b090af90e3e2761e3b85633b0e0b82e6bf9544b43daf8fe4e070591" and
        release_manifest_dict.get("registry_sha256") == "445a38a625d0a56aa416192d46cae417e4ff62ffcf7ea249a7ee1b376829346a"
    )
    gates["A5-G1-5"] = {
        "gate": "release_identity_matches_authorization",
        "db_manifest_sha256": db_manifest_sha,
        "expected_dynamic_manifest_sha256": expected_dynamic_manifest_sha,
        "db_code_commit_sha": db_commit,
        "release_sha": release_manifest_dict.get("release_sha"),
        "artifact_sha256": release_manifest_dict.get("artifact_sha256"),
        "metadata_sha256": release_manifest_dict.get("metadata_sha256"),
        "registry_sha256": release_manifest_dict.get("registry_sha256"),
        "result": "PASS" if g1_5_pass else "FAIL",
    }
    if not g1_5_pass:
        fail(f"Release manifest or commit mismatch: db_manifest_sha={db_manifest_sha} commit={db_commit}")

    # G1-6: SOL explicitly present in analysis universe
    try:
        universe_list = json.loads(db_universe_raw)
    except Exception:
        universe_list = db_universe_raw.split(",")
    universe_list = [sym.strip().upper() for sym in universe_list if sym.strip()]

    g1_6_pass = "SOL" in universe_list
    gates["A5-G1-6"] = {
        "gate": "sol_explicit_in_universe",
        "universe": universe_list,
        "sol_explicit": g1_6_pass,
        "result": "PASS" if g1_6_pass else "FAIL",
    }
    if not g1_6_pass:
        fail(f"SOL missing from epoch analysis universe: {universe_list}")

    overall = "PASS" if all(g["result"] == "PASS" for g in gates.values()) else "FAIL"

    # Write report
    report: dict[str, Any] = {
        "artifact": "p7_attempt5_epoch_readback",
        "generated_at": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "attempt_id": ATTEMPT_ID,
        "deployment_id": DEPLOYMENT_ID,
        "paper_run_id": PAPER_RUN_ID,
        "epoch_id": EPOCH_ID,
        "source_commit": SOURCE_COMMIT,
        "pinned_worktree": str(PINNED),
        "db_path": str(evidence_db),
        "db_record": {
            "epoch_id": db_epoch_id,
            "deployment_id": db_deploy_id,
            "status": db_status,
            "paper_run_id": db_run_id,
            "code_commit_sha": db_commit,
            "artifact_sha256": db_artifact_sha,
            "release_manifest_sha256": db_manifest_sha,
            "analysis_universe": universe_list,
        },
        "gates": gates,
        "overall_verdict": overall,
    }
    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    OUTPUT.write_text(payload, encoding="utf-8")
    
    digest = hashlib.sha256(payload.encode()).hexdigest()
    (ROOT / "p7_attempt5_epoch_readback.json.sha256").write_text(digest + "\n")

    print(json.dumps({
        "status": "PASS",
        "epoch_id": EPOCH_ID,
        "db_status": db_status,
        "sol_explicit": g1_6_pass,
        "output": str(OUTPUT),
        "sha256": digest,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
