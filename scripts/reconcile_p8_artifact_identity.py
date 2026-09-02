"""Script for Phases S4-S8: Artifact Identity Inventory, Audit, Selection & Compatibility Repair.

Performs byte-level verification, updates compatibility manifest for canonical
model artifact 8781aeee..., updates compatibility_hash, and enforces ARTIFACT_IDENTITY_CARDINALITY = 1.
"""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, ".")

from btc_scraper.ml_engine.artifact_compatibility import compute_compatibility_hash


def reconcile_artifact_identity():
    repo_root = Path(".").resolve()
    worktree_path = repo_root / "runtime" / "worktrees" / "timestamp-remediation-20260901-01"
    
    # 1. Byte-level sha256 hash of active model artifact
    joblib_path = worktree_path / "logs" / "meta_model.joblib"
    assert joblib_path.exists(), f"Joblib file not found at {joblib_path}"
    
    digest = hashlib.sha256()
    with joblib_path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(block)
    actual_sha = digest.hexdigest()
    
    canonical_sha = "8781aeee0b4ed4b84b18332600572bc9deaf5fdab896f945923d948df6c48b26"
    assert actual_sha == canonical_sha, f"Actual sha256 {actual_sha} != expected {canonical_sha}"
    
    print(f"Phase S5 Byte Verification: PASS. {joblib_path.name} sha256: {actual_sha}")
    
    # 2. Phase S7 Decision: Case A - 8781aeee... is canonical artifact.
    # Read existing compatibility manifest, update artifact sha256 AND recompute compatibility_hash
    root_compat_path = repo_root / "config" / "artifact_compatibility" / "meta_model.compatibility.json"
    wt_compat_path = worktree_path / "config" / "artifact_compatibility" / "meta_model.compatibility.json"
    
    with root_compat_path.open("r", encoding="utf-8") as f:
        compat_manifest = json.load(f)
        
    compat_manifest["artifact"]["sha256"] = canonical_sha
    compat_manifest["compatibility_hash"] = compute_compatibility_hash(compat_manifest)
    
    root_compat_path.parent.mkdir(parents=True, exist_ok=True)
    wt_compat_path.parent.mkdir(parents=True, exist_ok=True)
    
    with root_compat_path.open("w", encoding="utf-8") as f:
        json.dump(compat_manifest, f, indent=2)
    with wt_compat_path.open("w", encoding="utf-8") as f:
        json.dump(compat_manifest, f, indent=2)
        
    print(f"Phase S8 Repair: Updated compatibility manifest sha256={canonical_sha} and hash={compat_manifest['compatibility_hash']}")

    # 3. Update logs/meta_model.json in root repo to match worktree canonical artifact
    meta_json_path = repo_root / "logs" / "meta_model.json"
    meta_json_path.parent.mkdir(parents=True, exist_ok=True)
    meta_record = {
      "artifact_sha256": canonical_sha,
      "assembly_kind": "FROZEN_WEIGHTS_RUNTIME_WRAPPER",
      "feature_schema_version": "meta-v3.1-43f",
      "features": ["return_8", "return_32", "return_72", "abs_move_72"],
      "model_name": "meta_model",
      "model_version": "windows-v5-filter-1.0.0",
      "n_features": 4,
      "runtime_contract": "sklearn-joblib-v1",
      "source_model": "research/historical_market_replay_v5/v5_filter_model",
      "status": "production",
      "version": "windows-v5-filter-1.0.0"
    }
    with meta_json_path.open("w", encoding="utf-8") as f:
        json.dump(meta_record, f, indent=2)
        
    # Copy joblib file to root repo logs/meta_model.joblib for complete alignment
    root_joblib = repo_root / "logs" / "meta_model.joblib"
    root_joblib.parent.mkdir(parents=True, exist_ok=True)
    root_joblib.write_bytes(joblib_path.read_bytes())
    print("Synchronized logs/meta_model.joblib and logs/meta_model.json in root repo.")

    # 4. Inventory Record
    inventory_record = {
        "audit": "PHASES_S4_S8_ARTIFACT_IDENTITY_RECONCILIATION",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "canonical_decision": "CASE_A_RECONCILE_COMPATIBILITY_MANIFEST",
        "canonical_artifact_sha256": canonical_sha,
        "artifact_bytes_sha256": canonical_sha,
        "compatibility_manifest_sha256": compat_manifest["artifact"]["sha256"],
        "compatibility_hash": compat_manifest["compatibility_hash"],
        "metadata_sidecar_sha256": canonical_sha,
        "artifact_identity_cardinality": 1,
        "status": "PASS_RECONCILED",
    }
    
    out_path = repo_root / "research" / "p8_readiness_remediation" / "p8_s8_artifact_reconciliation.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(inventory_record, f, indent=2)
        
    print(f"Saved artifact reconciliation record to {out_path}")
    print("ARTIFACT_IDENTITY_CARDINALITY = 1 enforced successfully!")


if __name__ == "__main__":
    reconcile_artifact_identity()
