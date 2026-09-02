"""Script for Phase S14: Epoch Governance Decision.

Invalidates p8-readiness-r1-20260902-01 and provisions fresh epoch p8-readiness-r2-20260902-01
bound to sealed release commit 34d646113e76ea5ee155b449a45bdc3291e02147.
"""

from datetime import datetime, timezone
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, ".")

from btc_scraper.core.config import analysis_universe_hash, parse_runtime_symbols
from btc_scraper.ml_engine.evidence_epoch import EvidenceEpoch
from btc_scraper.ml_engine.runtime_evidence_store import RuntimeEvidenceStore


def provision_r2_epoch():
    canonical_store_path = Path("runtime/worktrees/timestamp-remediation-20260901-01/runtime/paper/paper-canary-win-tsfix-20260901-01/logs/runtime_evidence.sqlite")
    deployment_id = "paper-canary-win-tsfix-20260901-01"
    universe_str = "BNB,BTC,DOGE,ETH,IOTA,NEAR,SOL,TRX,ZEC"
    release_sha = "34d646113e76ea5ee155b449a45bdc3291e02147"
    artifact_sha = "8781aeee0b4ed4b84b18332600572bc9deaf5fdab896f945923d948df6c48b26"
    metadata_sha = "c87dda729b71f140d739d414ee5714834c6f0e8b468f957e48493efb36967739"
    registry_sha = "977e643ba1df0ce22d1d489f1c7a05377b9198dbd375f7f5d8f2a78cebff0f1a"
    
    os.environ["BTC_DEPLOYMENT_ID"] = deployment_id
    os.environ["BTC_PAPER_RUN_ID"] = deployment_id
    os.environ["BTC_ANALYSIS_UNIVERSE"] = universe_str
    os.environ["AUTO_TRADE_COINS"] = universe_str
    os.environ["BTC_EVIDENCE_ELIGIBLE"] = "true"

    store = RuntimeEvidenceStore(canonical_store_path)

    # 1. Invalidate r1 epoch if active
    r1_epoch_id = "p8-readiness-r1-20260902-01"
    r1_epoch = store.get_evidence_epoch(r1_epoch_id)
    if r1_epoch and r1_epoch.status == "ACTIVE":
        print(f"Phase S14: Invalidating {r1_epoch_id}")
        store.invalidate_evidence_epoch(
            r1_epoch_id,
            reason_code="STARTUP_PROVENANCE_REMEDIATION",
            reason_detail="Previous epoch bound to release 043c56d2... superseded by startup remediation release 34d64611...",
            contributing_reasons=["STARTUP_PROVENANCE_UPDATE"],
        )
        print(f"Epoch {r1_epoch_id} invalidated successfully.")

    # 2. Provision r2 epoch
    fresh_epoch_id = "p8-readiness-r2-20260902-01"
    symbols = parse_runtime_symbols(universe_str, field_name="analysis_universe")
    
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
        print(f"Creating fresh evidence epoch: {fresh_epoch_id}")
        store.create_evidence_epoch(epoch_obj)

    print(f"Activating fresh evidence epoch: {fresh_epoch_id}")
    active_epoch = store.transition_evidence_epoch(fresh_epoch_id, "ACTIVE")
    
    print("\n--- Phase S14 Epoch Provisioning Read-Back ---")
    print(f"Store Path:     {canonical_store_path}")
    print(f"Active Epoch:   {active_epoch.epoch_id}")
    print(f"Status:         {active_epoch.status}")
    print(f"Release SHA:    {active_epoch.code_commit_sha}")
    print(f"Artifact SHA:   {active_epoch.artifact_sha256}")
    print("----------------------------------------------")


if __name__ == "__main__":
    provision_r2_epoch()
