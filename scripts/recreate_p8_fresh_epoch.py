"""Script to invalidate defective epoch and create & activate fresh P8 evidence epoch."""

from datetime import datetime, timezone
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, ".")

from btc_scraper.core.config import analysis_universe_hash, parse_runtime_symbols
from btc_scraper.ml_engine.evidence_epoch import EvidenceEpoch
from btc_scraper.ml_engine.runtime_evidence_store import RuntimeEvidenceStore


def recreate_epoch():
    store = RuntimeEvidenceStore()
    
    # 1. First invalidate defective epoch if it exists in store
    defective_id = "P8_DEFECTIVE_EPOCH_INITIAL"
    try:
        if store.get_evidence_epoch(defective_id):
            print(f"Invalidating defective epoch: {defective_id}")
            store.invalidate_evidence_epoch(
                defective_id,
                reason_code="RUNTIME_CANONICAL_HISTORY_TRUNCATION",
                reason_detail="Truncation of analysis history to 8 candles prevented evaluator from receiving required 73 observations.",
                contributing_reasons=["INSUFFICIENT_CANONICAL_HISTORY"],
            )
    except Exception as err:
        print(f"Note on defective epoch invalidation: {err}")

    # 2. Provision fresh epoch
    fresh_epoch_id = "p8-readiness-r1-20260902-01"
    deployment_id = "paper-canary-readiness-r1-20260902-01"
    universe_str = "BTC,ETH,SOL"
    symbols = parse_runtime_symbols(universe_str, field_name="analysis_universe")
    
    release_manifest = {
        "manifest_schema_version": "evidence-manifest-v1",
        "deployment_id": deployment_id,
        "paper_run_id": deployment_id,
        "release_sha": "1d4da42",
        "artifact_sha256": "dbf0a08241dae01241539ef3f48c6a0b13da9b13a5b128de259aac06d267241c",
        "metadata_sha256": "6d1bba532b090af90e3e2761e3b85633b0e0b82e6bf9544b43daf8fe4e070591",
        "registry_sha256": "445a38a625d0a56aa416192d46cae417e4ff62ffcf7ea249a7ee1b376829346a",
        "feature_schema_version": "meta-v3.1-43f",
        "decision_contract": "side-probability-v2",
        "probability_semantics": "P(up)",
        "analysis_universe": universe_str,
    }
    
    epoch_obj = EvidenceEpoch(
        epoch_id=fresh_epoch_id,
        deployment_id=deployment_id,
        started_at=datetime.now(timezone.utc).isoformat(),
        code_commit_sha="1d4da42",
        model_version="v3.1",
        artifact_sha256="dbf0a08241dae01241539ef3f48c6a0b13da9b13a5b128de259aac06d267241c",
        feature_schema_version="meta-v3.1-43f",
        analysis_universe=symbols,
        analysis_universe_hash=analysis_universe_hash(symbols),
        paper_run_id=deployment_id,
        release_manifest=release_manifest,
    )
    
    existing = store.get_evidence_epoch(fresh_epoch_id)
    if existing is None:
        print(f"Creating fresh evidence epoch: {fresh_epoch_id}")
        store.create_evidence_epoch(epoch_obj)
    
    os.environ["BTC_DEPLOYMENT_ID"] = deployment_id
    os.environ["BTC_PAPER_RUN_ID"] = deployment_id
    os.environ["BTC_ANALYSIS_UNIVERSE"] = universe_str
    os.environ["AUTO_TRADE_COINS"] = universe_str
    os.environ["BTC_EVIDENCE_ELIGIBLE"] = "true"

    print(f"Activating evidence epoch: {fresh_epoch_id}")
    active_epoch = store.transition_evidence_epoch(fresh_epoch_id, "ACTIVE")
    
    # Save epoch creation manifest to research directory
    manifest_record = {
        "epoch_id": active_epoch.epoch_id,
        "deployment_id": active_epoch.deployment_id,
        "status": active_epoch.status,
        "started_at": active_epoch.started_at,
        "artifact_sha256": active_epoch.artifact_sha256,
        "analysis_universe": list(active_epoch.analysis_universe),
        "code_commit_sha": active_epoch.code_commit_sha,
        "release_manifest": active_epoch.release_manifest,
    }
    
    out_path = Path("research/p8_readiness_remediation/p8_fresh_epoch_manifest.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(manifest_record, f, indent=2)
        
    print(f"Fresh Epoch Manifest saved to: {out_path}")
    print("\nFresh epoch recreated and activated successfully!")
    print(f"Epoch ID:    {active_epoch.epoch_id}")
    print(f"Deployment:  {active_epoch.deployment_id}")
    print(f"Status:      {active_epoch.status}")


if __name__ == "__main__":
    recreate_epoch()
