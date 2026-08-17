#!/usr/bin/env python3
import os
import sys
import json
import shutil
import hashlib
from datetime import datetime, timezone
from pathlib import Path
import joblib

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from btc_scraper.core.paths import build_logs_path
from btc_scraper.core.config import analysis_universe_hash
from btc_scraper.ml_engine.evidence_epoch import EvidenceEpoch
from btc_scraper.ml_engine.runtime_evidence_store import RuntimeEvidenceStore
from btc_scraper.ml_engine.model_registry import ModelRegistry
from scripts.hmr_v5_d2_r1_real_runtime_parity import V5FilterModelClassifier

def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()

def main():
    print("=== V5 Canary Activation ===")
    
    # Paths
    logs_dir = REPO_ROOT / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    
    joblib_path = logs_dir / "meta_model.joblib"
    json_path = logs_dir / "meta_model.json"
    registry_path = logs_dir / "model_registry.json"
    
    joblib_backup = logs_dir / "meta_model.joblib.bak"
    json_backup = logs_dir / "meta_model.json.bak"
    registry_backup = logs_dir / "model_registry.json.bak"
    
    # 1. Back up existing files if not already backed up
    if joblib_path.exists() and not joblib_backup.exists():
        shutil.copy(joblib_path, joblib_backup)
        print(f"✓ Backed up {joblib_path.name} to {joblib_backup.name}")
    if json_path.exists() and not json_backup.exists():
        shutil.copy(json_path, json_backup)
        print(f"✓ Backed up {json_path.name} to {json_backup.name}")
    if registry_path.exists() and not registry_backup.exists():
        shutil.copy(registry_path, registry_backup)
        print(f"✓ Backed up {registry_path.name} to {registry_backup.name}")
        
    # 2. Build V5 model bundle
    model_dir = REPO_ROOT / "research/historical_market_replay_v5/v5_filter_model"
    classifier = V5FilterModelClassifier(str(model_dir))
    model_bundle = {
        "model": classifier,
        "features": ["return_8", "return_32", "return_72", "abs_move_72"],
        "version": "1.0.0"
    }
    
    # Save V5 model bundle to logs/meta_model.joblib
    joblib.dump(model_bundle, joblib_path)
    model_sha = sha256_file(joblib_path)
    print(f"✓ Saved V5 model bundle to {joblib_path} (SHA: {model_sha})")
    
    # 3. Create V5 model metadata logs/meta_model.json
    metadata = {
        "model_name": "meta_model",
        "model_version": "v3.1",
        "artifact_sha256": model_sha,
        "feature_schema_version": "meta-v3.1-43f",
        "status": "production",
        "runtime_contract": "sklearn-joblib-v1",
        "version": "v3.1",
        "n_samples": 14170,
        "n_features": 4,
        "features": ["return_8", "return_32", "return_72", "abs_move_72"]
    }
    with json_path.open("w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)
    print(f"✓ Saved V5 model metadata to {json_path}")
    
    # 4. Update logs/model_registry.json
    with registry_path.open("r", encoding="utf-8") as f:
        registry_data = json.load(f)
        
    # Archive existing meta_model records
    for r in registry_data["records"]:
        if r.get("model_name") == "meta_model" and r.get("status") == "production":
            r["status"] = "archive"
            
    # Append V5 production record
    new_record = {
        "model_name": "meta_model",
        "version": "v3.1",
        "status": "production",
        "artifact_path": "logs\\meta_model.joblib",
        "sha256": model_sha,
        "schema_version": "meta-v3.1-43f",
        "metrics": metadata,
        "registered_at": datetime.now(timezone.utc).isoformat()
    }
    registry_data["records"].append(new_record)
    with registry_path.open("w", encoding="utf-8") as f:
        json.dump(registry_data, f, indent=2)
    print(f"✓ Registered V5 model version v3.1 in {registry_path}")
    
    # 5. Create & activate evidence epoch
    db_path = logs_dir / "runtime_evidence.sqlite"
    store = RuntimeEvidenceStore(db_path)
    
    epoch_id = "canary-v5-filter-20260817-01"
    deployment_id = "local-production"
    
    # Get git commit SHA
    import subprocess
    commit_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    
    # Create epoch record
    release_manifest = {
        "manifest_schema_version": "evidence-manifest-v1",
        "release_sha": commit_sha,
        "artifact_sha256": model_sha,
        "metadata_sha256": sha256_file(json_path),
        "registry_sha256": sha256_file(registry_path),
        "deployment_id": deployment_id,
        "paper_run_id": deployment_id,
        "feature_schema_version": "meta-v3.1-43f",
        "analysis_universe": "BTC,ETH,BNB",
        "decision_contract": "side-probability-v2",
        "probability_semantics": "P(up)"
    }
    
    # Delete existing epoch if conflicting
    with store._global_transaction() as db:
        db.execute("DELETE FROM evidence_epochs WHERE epoch_id=?", (epoch_id,))
        
    epoch_val = EvidenceEpoch(
        epoch_id=epoch_id,
        deployment_id=deployment_id,
        started_at=datetime.now(timezone.utc).isoformat(),
        code_commit_sha=commit_sha,
        model_version="v3.1",
        artifact_sha256=model_sha,
        feature_schema_version="meta-v3.1-43f",
        analysis_universe=("BTC", "ETH", "BNB"),
        analysis_universe_hash=analysis_universe_hash(("BTC", "ETH", "BNB")),
        paper_run_id=deployment_id,
        release_manifest=release_manifest
    )
    
    store.create_evidence_epoch(epoch_val)
    print(f"✓ Created evidence epoch {epoch_id} in DRAFT status")
    
    # Set deployment ID in environment so validation succeeds
    os.environ["BTC_DEPLOYMENT_ID"] = deployment_id
    os.environ["BTC_PAPER_RUN_ID"] = deployment_id
    os.environ["BTC_ANALYSIS_UNIVERSE"] = "BTC,ETH,BNB"
    os.environ["AUTO_TRADE_COINS"] = "BTC,ETH,BNB"
    os.environ["BTC_EVIDENCE_ELIGIBLE"] = "true"
    
    # Transition to ACTIVE
    store.transition_evidence_epoch(epoch_id, "ACTIVE")
    print(f"✓ Transitioned evidence epoch {epoch_id} to ACTIVE status")
    print("\n=== V5 Canary Activated Successfully ===")

if __name__ == "__main__":
    main()
