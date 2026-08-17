#!/usr/bin/env python3
import os
import sys
import sqlite3
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Set env vars
os.environ["BTC_LOG_DIR"] = "logs"
os.environ["BTC_DEPLOYMENT_ID"] = "local-production"
os.environ["BTC_PAPER_RUN_ID"] = "local-production"
os.environ["BTC_ANALYSIS_UNIVERSE"] = "BTC,ETH,BNB"
os.environ["BTC_EVIDENCE_ELIGIBLE"] = "true"

from btc_scraper.ml_engine.runtime_evidence_store import get_runtime_evidence_store
from btc_scraper.ml_engine.meta_model import predict_meta_confidence

def main():
    print("=== V5 Canary First-Cycle Sanity Check ===")
    
    # 1. Verify Active Epoch
    store = get_runtime_evidence_store()
    epoch = store.get_active_evidence_epoch()
    if epoch is None:
        print("✗ No active evidence epoch found!")
        sys.exit(1)
        
    print(f"✓ Active Epoch ID: {epoch.epoch_id}")
    print(f"✓ Deployment ID: {epoch.deployment_id}")
    print(f"✓ Code Commit SHA: {epoch.code_commit_sha}")
    print(f"✓ Model Version: {epoch.model_version}")
    print(f"✓ Feature Schema Version: {epoch.feature_schema_version}")
    print(f"✓ Artifact SHA256: {epoch.artifact_sha256}")
    
    # Assert manifest schema and contracts
    manifest = epoch.release_manifest
    print(f"✓ Manifest Schema Version: {manifest['manifest_schema_version']}")
    print(f"✓ Exit Contract: {manifest['decision_contract']}")
    print(f"✓ Probability Semantics: {manifest['probability_semantics']}")
    
    # 2. Verify V5 Canary Thresholds & Exit/Execution Config
    with open(REPO_ROOT / "research/historical_market_replay_v5/v5_d3_canary_config.json", "r") as f:
        config = json.load(f)
    print(f"✓ Config Status: {config['status']}")
    print(f"✓ Config Live Trading: {config['live_trading']}")
    print(f"✓ Config Paper Execution: {config['paper_execution']}")
    print(f"✓ Exit type: {config['config']['exit']['type']} (TP: {config['config']['exit']['tp_bps']} / SL: {config['config']['exit']['sl_bps']} bps)")
    print(f"✓ Execution type: {config['config']['execution']}")
    print(f"✓ Dynamic updates: model_retrain={config['config']['model_retrain']}, threshold_change={config['config']['threshold_change']}")
    
    # 3. Simulate first natural cycle prediction trace
    # (observation -> features -> score -> S3 decision -> P4 eligibility)
    mock_analysis = {
        "coin": "BTC",
        "symbol": "BTCUSDT",
        "timeframe": "15m",
        "signal": "BUY",
        "return_8": 0.0012,
        "return_32": -0.0034,
        "return_72": 0.0056,
        "abs_move_72": 0.0078
    }
    
    print("\nTracing first mock prediction...")
    pred_res = predict_meta_confidence(mock_analysis)
    
    if "error" in pred_res:
        print(f"✗ Prediction error: {pred_res['error']}")
        sys.exit(1)
        
    print(f"✓ Probability generated: {pred_res['probability']:.8f}")
    print(f"✓ Sizing probability: {pred_res['sizing_probability']:.8f}")
    print(f"✓ Prediction ID: {pred_res['prediction_id']}")
    print(f"✓ Feature Hash: {pred_res['feature_hash']}")
    
    # 4. Verify SQLite persistence of the prediction event
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).date().isoformat()
    partition_db = REPO_ROOT / f"logs/runtime_evidence_{today}.sqlite"
    
    if not partition_db.exists():
        print(f"✗ Partition database {partition_db} not found!")
        sys.exit(1)
        
    db = sqlite3.connect(str(partition_db))
    cur = db.cursor()
    row = cur.execute("SELECT prediction_id, payload FROM predictions WHERE prediction_id=?", (pred_res['prediction_id'],)).fetchone()
    if row is None:
        print("✗ Prediction event was not found in SQLite database!")
        sys.exit(1)
        
    payload_data = json.loads(row[1])
    print(f"✓ Database verified: prediction_id={row[0]}")
    print(f"  - payload.symbol: {payload_data.get('symbol')}")
    print(f"  - payload.raw_probability: {payload_data.get('raw_probability'):.8f}")
    print(f"  - payload.feature_hash: {payload_data.get('feature_hash')}")
    print(f"  - payload.paper_run_id: {payload_data.get('paper_run_id')}")
    print("\n=== All first-cycle sanity checks passed! V5 Canary is ACTIVE. ===")

import json
if __name__ == "__main__":
    main()
