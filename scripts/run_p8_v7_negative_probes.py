#!/usr/bin/env python3
"""Run P8 Governance V7 negative failure-mode probes (G5-G7)."""
import sys
import os
import json
import sqlite3
import tempfile
import hashlib
from pathlib import Path

# Add project root to sys.path
root_dir = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root_dir))

from btc_scraper.ml_engine.p8_governance import (
    check_runtime_lock_owner,
    _load_raw_partition_records,
    P8AttestationPolicy,
    GovernanceError,
    SEALED_COMMIT_SHA,
    SEALED_ARTIFACT_SHA,
)
from scripts.p8_economic_report import determine_verdict

def run_probes() -> dict:
    results = {}

    # Probe 1: Live Runtime Lock (G5)
    with tempfile.TemporaryDirectory() as tmpdir:
        tmppath = Path(tmpdir)
        logs_dir = tmppath / "logs"
        logs_dir.mkdir(parents=True)
        state_dir = tmppath / "state"
        state_dir.mkdir(parents=True)
        lock_file = state_dir / "runtime.lock"
        current_pid = os.getpid()
        lock_file.write_text(json.dumps({"pid": current_pid, "mode": "governed"}))

        try:
            status = check_runtime_lock_owner(logs_dir)
            results["probe_1_live_runtime_lock"] = {
                "status": "FAIL",
                "output": f"Expected error, got status {status}",
            }
        except GovernanceError as e:
            if "LIVE_RUNNER_ACTIVE_CONFLICT" in str(e):
                results["probe_1_live_runtime_lock"] = {
                    "status": "PASS",
                    "error_code": "LIVE_RUNNER_ACTIVE_CONFLICT",
                    "pid": current_pid,
                    "message": str(e),
                }
            else:
                results["probe_1_live_runtime_lock"] = {
                    "status": "FAIL",
                    "output": f"Unexpected GovernanceError: {e}",
                }

    # Probe 2: Corrupted Stored Payload SHA256 (G6)
    with tempfile.TemporaryDirectory() as tmpdir:
        tmppath = Path(tmpdir)
        db_path = tmppath / "runtime_evidence_2026-09-01.sqlite"
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "CREATE TABLE predictions (prediction_id TEXT PRIMARY KEY, payload TEXT, payload_sha256 TEXT, updated_at TEXT)"
        )
        conn.execute(
            "INSERT INTO predictions VALUES ('rec1', '{\"trade\": 1}', '0000000000000000000000000000000000000000000000000000000000000000', '2026-09-01T00:00:00Z')"
        )
        conn.commit()
        conn.close()

        try:
            _load_raw_partition_records(tmppath)
            results["probe_2_corrupted_payload_sha256"] = {
                "status": "FAIL",
                "output": "Expected payload_corruption error, but loaded successfully",
            }
        except GovernanceError as e:
            if "payload_corruption" in str(e):
                results["probe_2_corrupted_payload_sha256"] = {
                    "status": "PASS",
                    "error_code": "payload_corruption",
                    "message": str(e),
                }
            else:
                results["probe_2_corrupted_payload_sha256"] = {
                    "status": "FAIL",
                    "output": f"Unexpected GovernanceError: {e}",
                }

    # Probe 3: Same ID / Different Canonical Payload Hash (G6)
    with tempfile.TemporaryDirectory() as tmpdir:
        tmppath = Path(tmpdir)
        db1 = tmppath / "runtime_evidence_2026-09-01.sqlite"
        db2 = tmppath / "runtime_evidence_2026-09-02.sqlite"
        for p, text in [(db1, '{"trade": 1, "price": 100}'), (db2, '{"trade": 1, "price": 200}')]:
            conn = sqlite3.connect(str(p))
            conn.execute(
                "CREATE TABLE predictions (prediction_id TEXT PRIMARY KEY, payload TEXT, payload_sha256 TEXT, updated_at TEXT)"
            )
            h = hashlib.sha256(text.encode("utf-8")).hexdigest()
            conn.execute(
                "INSERT INTO predictions VALUES ('rec_dup', ?, ?, '2026-09-01T00:00:00Z')",
                (text, h),
            )
            conn.commit()
            conn.close()

        try:
            _load_raw_partition_records(tmppath)
            results["probe_3_duplicate_id_different_hash"] = {
                "status": "FAIL",
                "output": "Expected duplicate_conflict error, but loaded successfully",
            }
        except GovernanceError as e:
            if "duplicate_conflict" in str(e):
                results["probe_3_duplicate_id_different_hash"] = {
                    "status": "PASS",
                    "error_code": "duplicate_conflict",
                    "message": str(e),
                }
            else:
                results["probe_3_duplicate_id_different_hash"] = {
                    "status": "FAIL",
                    "output": f"Unexpected GovernanceError: {e}",
                }

    # Probe 4: Non-Eligible Economic Population Verdict (G7)
    metrics = {"mean_net_return_bps": 15.0, "win_rate": 0.55}
    v_class, v_reason = determine_verdict(120, metrics, {}, {}, allow_non_eligible=False)
    if v_class == "DIAGNOSTIC" and v_reason == "UNAUTHORIZED_POPULATION_VERDICT_NOT_PERMITTED":
        results["probe_4_unauthorized_population_verdict"] = {
            "status": "PASS",
            "verdict_class": v_class,
            "verdict_reason": v_reason,
        }
    else:
        results["probe_4_unauthorized_population_verdict"] = {
            "status": "FAIL",
            "output": f"Got {v_class}, {v_reason}",
        }

    # Probe 5: Missing Mandatory Attestation Field (G8)
    with tempfile.TemporaryDirectory() as tmpdir:
        tmppath = Path(tmpdir).resolve()
        policy = P8AttestationPolicy(sealed_root=tmppath)
        db_path = policy.canonical_evidence_log
        global_index = policy.canonical_global_index
        db_path.parent.mkdir(parents=True, exist_ok=True)
        db_path.touch()

        conn = sqlite3.connect(str(global_index))
        conn.execute(
            "CREATE TABLE evidence_epochs (epoch_id TEXT, status TEXT, code_commit_sha TEXT, artifact_sha256 TEXT, deployment_id TEXT, paper_run_id TEXT, analysis_universe_hash TEXT)"
        )
        conn.execute(
            "INSERT INTO evidence_epochs VALUES ('ep1', 'ACTIVE', ?, ?, 'deploy-v5-canary-01', 'run1', 'hash1')",
            (SEALED_COMMIT_SHA, SEALED_ARTIFACT_SHA)
        )
        conn.commit()
        conn.close()

        att = policy.attest_store(db_path)
        if not att.is_valid and any("missing or empty" in err for err in att.attestation_errors):
            results["probe_5_missing_mandatory_field"] = {
                "status": "PASS",
                "is_valid": att.is_valid,
                "errors": att.attestation_errors,
            }
        else:
            results["probe_5_missing_mandatory_field"] = {
                "status": "FAIL",
                "output": f"Unexpected attestation result: {att}",
            }

    # Probe 6: Missing Sealed Artifact File (G8/G9)
    with tempfile.TemporaryDirectory() as tmpdir:
        tmppath = Path(tmpdir).resolve()
        policy = P8AttestationPolicy(sealed_root=tmppath)
        db_path = policy.canonical_evidence_log
        global_index = policy.canonical_global_index
        db_path.parent.mkdir(parents=True, exist_ok=True)
        db_path.touch()

        conn = sqlite3.connect(str(global_index))
        conn.execute(
            "CREATE TABLE evidence_epochs (epoch_id TEXT, status TEXT, code_commit_sha TEXT, model_version TEXT, feature_schema_version TEXT, evidence_policy_version TEXT, risk_policy_version TEXT, runtime_schema_version TEXT, release_manifest_sha256 TEXT, artifact_sha256 TEXT, deployment_id TEXT, paper_run_id TEXT, analysis_universe_hash TEXT)"
        )
        conn.execute(
            "INSERT INTO evidence_epochs VALUES ('ep1', 'ACTIVE', ?, 'm1', 'f1', 'e1', 'r1', 'rt1', 'rel1', ?, 'deploy-v5-canary-01', 'run1', 'hash1')",
            (SEALED_COMMIT_SHA, SEALED_ARTIFACT_SHA)
        )
        conn.commit()
        conn.close()

        att = policy.attest_store(db_path)
        if not att.is_valid and any("Sealed artifact file not found" in err for err in att.attestation_errors):
            results["probe_6_missing_artifact_file"] = {
                "status": "PASS",
                "is_valid": att.is_valid,
                "errors": att.attestation_errors,
            }
        else:
            results["probe_6_missing_artifact_file"] = {
                "status": "FAIL",
                "output": f"Unexpected attestation result: {att}",
            }

    return results

if __name__ == "__main__":
    res = run_probes()
    print(json.dumps(res, indent=2))
