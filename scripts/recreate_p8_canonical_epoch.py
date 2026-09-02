"""Script to invalidate old defective epoch and provision/activate fresh P8 evidence epoch in CANONICAL evidence store."""

from datetime import datetime, timezone
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, ".")

from btc_scraper.core.config import analysis_universe_hash, parse_runtime_symbols
from btc_scraper.ml_engine.evidence_epoch import EvidenceEpoch
from btc_scraper.ml_engine.runtime_evidence_store import RuntimeEvidenceStore


def provision_canonical_epoch():
    # 1. Target the canonical paper deployment store
    canonical_store_path = Path("runtime/worktrees/timestamp-remediation-20260901-01/runtime/paper/paper-canary-win-tsfix-20260901-01/logs/runtime_evidence.sqlite")
    print(f"Targeting canonical evidence store: {canonical_store_path.resolve()}")
    
    deployment_id = "paper-canary-win-tsfix-20260901-01"
    universe_str = "BNB,BTC,DOGE,ETH,IOTA,NEAR,SOL,TRX,ZEC"
    
    os.environ["BTC_DEPLOYMENT_ID"] = deployment_id
    os.environ["BTC_PAPER_RUN_ID"] = deployment_id
    os.environ["BTC_ANALYSIS_UNIVERSE"] = universe_str
    os.environ["AUTO_TRADE_COINS"] = universe_str
    os.environ["BTC_EVIDENCE_ELIGIBLE"] = "true"

    store = RuntimeEvidenceStore(canonical_store_path)

    # 2. Invalidate old active epoch if present
    old_epoch_id = "canary-win-v5-tsfix-20260901-01"
    old_epoch = store.get_evidence_epoch(old_epoch_id)
    if old_epoch and old_epoch.status == "ACTIVE":
        print(f"Invalidating old defective epoch: {old_epoch_id}")
        store.invalidate_evidence_epoch(
            old_epoch_id,
            reason_code="RUNTIME_CANONICAL_HISTORY_TRUNCATION",
            reason_detail="Truncation of analysis history to 8 candles prevented evaluator from receiving required 73 observations.",
            contributing_reasons=["INSUFFICIENT_CANONICAL_HISTORY"],
        )
        print(f"Old epoch {old_epoch_id} invalidated successfully.")

    # 3. Create fresh epoch
    fresh_epoch_id = "p8-readiness-r1-20260902-01"
    symbols = parse_runtime_symbols(universe_str, field_name="analysis_universe")
    release_sha = "043c56d2a1296c18687d47ed05448c34812b71ab"
    artifact_sha = "8781aeee0b4ed4b84b18332600572bc9deaf5fdab896f945923d948df6c48b26"
    metadata_sha = "c87dda729b71f140d739d414ee5714834c6f0e8b468f957e48493efb36967739"
    registry_sha = "977e643ba1df0ce22d1d489f1c7a05377b9198dbd375f7f5d8f2a78cebff0f1a"
    
    release_manifest = {
        "manifest_schema_version": "evidence-manifest-v1",
        "deployment_id": deployment_id,
        "paper_run_id": deployment_id,
        "release_sha": release_sha,
        "artifact_sha256": artifact_sha,
        "metadata_sha256": metadata_sha,
        "registry_sha256": registry_sha,
        "feature_schema_version": "meta-v3.1-43f",
        "decision_contract": "side-probability-v2",
        "probability_semantics": "P(up)",
        "analysis_universe": universe_str,
    }
    
    epoch_obj = EvidenceEpoch(
        epoch_id=fresh_epoch_id,
        deployment_id=deployment_id,
        started_at=datetime.now(timezone.utc).isoformat(),
        code_commit_sha=release_sha,
        model_version="windows-v5-filter-1.0.0",
        artifact_sha256=artifact_sha,
        feature_schema_version="meta-v3.1-43f",
        analysis_universe=symbols,
        analysis_universe_hash=analysis_universe_hash(symbols),
        paper_run_id=deployment_id,
        release_manifest=release_manifest,
    )
    
    existing = store.get_evidence_epoch(fresh_epoch_id)
    if existing is None:
        print(f"Creating fresh evidence epoch in canonical store: {fresh_epoch_id}")
        store.create_evidence_epoch(epoch_obj)

    print(f"Activating fresh evidence epoch: {fresh_epoch_id}")
    active_epoch = store.transition_evidence_epoch(fresh_epoch_id, "ACTIVE")
    
    # 4. Verify DB state directly from SQLite
    active_in_store = store.get_active_evidence_epoch()
    print("\n--- Canonical Store Read-Back Verification ---")
    print(f"Store Path:     {canonical_store_path}")
    print(f"Active Epoch:   {active_in_store.epoch_id if active_in_store else None}")
    print(f"Status:         {active_in_store.status if active_in_store else None}")
    print(f"Artifact SHA:   {active_in_store.artifact_sha256 if active_in_store else None}")
    print(f"Release SHA:    {active_in_store.code_commit_sha if active_in_store else None}")
    print(f"Universe:       {','.join(active_in_store.analysis_universe) if active_in_store else None}")
    print("----------------------------------------------")

    manifest_record = {
        "canonical_store_path": str(canonical_store_path.resolve()),
        "epoch_id": active_in_store.epoch_id,
        "deployment_id": active_in_store.deployment_id,
        "status": active_in_store.status,
        "started_at": active_in_store.started_at,
        "artifact_sha256": active_in_store.artifact_sha256,
        "code_commit_sha": active_in_store.code_commit_sha,
        "analysis_universe": list(active_in_store.analysis_universe),
        "invalidated_epoch_id": old_epoch_id,
        "release_manifest": active_in_store.release_manifest,
    }
    
    out_path = Path("research/p8_readiness_remediation/p8_canonical_epoch_manifest.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(manifest_record, f, indent=2)
        
    print(f"Saved canonical epoch manifest to {out_path}")


if __name__ == "__main__":
    provision_canonical_epoch()
