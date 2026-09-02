"""Script to inspect and verify Phase R21, R22, and R23 for the first natural cycle."""

from datetime import datetime, timezone
from pathlib import Path
import json
import sqlite3
import sys

sys.path.insert(0, ".")

def inspect_latest_natural_cycle():
    logs_dir = Path("runtime/worktrees/timestamp-remediation-20260901-01/runtime/paper/paper-canary-win-tsfix-20260901-01/logs")
    r19_path = Path("research/p8_readiness_remediation/p8_r19_runner_start.json")
    
    if not r19_path.exists():
        print("R19 runner start record not found.")
        return
        
    with r19_path.open("r", encoding="utf-8") as f:
        r19_data = json.load(f)
        
    spawn_time = r19_data["spawn_timestamp"]
    active_epoch_id = r19_data["epoch_id"]
    sealed_release = r19_data["release_sha"]
    sealed_artifact = r19_data["artifact_sha256"]
    
    print(f"R19 Spawn Time:  {spawn_time}")
    print(f"Active Epoch:    {active_epoch_id}")
    print(f"Sealed Release:  {sealed_release}")
    
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    daily_db_path = logs_dir / f"runtime_evidence_{today_str}.sqlite"
    
    if not daily_db_path.exists():
        print(f"Daily DB path {daily_db_path} does not exist yet.")
        return

    conn = sqlite3.connect(daily_db_path)
    cursor = conn.cursor()

    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in cursor.fetchall()]
    
    if "predictions" not in tables:
        print("No predictions table in daily DB.")
        conn.close()
        return

    cursor.execute("SELECT prediction_id, payload, written_at FROM predictions ORDER BY written_at DESC LIMIT 5")
    rows = cursor.fetchall()
    
    print(f"\nFound {len(rows)} recent prediction entries in {daily_db_path.name}:")
    matching_natural_cycles = []
    
    for pred_id, payload_str, written_at in rows:
        payload = json.loads(payload_str)
        rec_epoch = payload.get("epoch_id") or payload.get("evidence_epoch_id")
        created_at = payload.get("created_at") or written_at
        
        print(f"\n--- Prediction: {pred_id} | Epoch: {rec_epoch} | Written At: {written_at} ---")
        
        # Check if record belongs to active fresh epoch
        if rec_epoch == active_epoch_id:
            matching_natural_cycles.append({
                "prediction_id": pred_id,
                "written_at": written_at,
                "epoch_id": rec_epoch,
                "payload": payload,
            })
            
    conn.close()
    
    # Also inspect final decisions
    conn = sqlite3.connect(daily_db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT decision_id, payload, written_at FROM final_decisions ORDER BY written_at DESC LIMIT 5")
    dec_rows = cursor.fetchall()
    
    print(f"\nFound {len(dec_rows)} recent final decision entries in {daily_db_path.name}:")
    for dec_id, payload_str, written_at in dec_rows:
        payload = json.loads(payload_str)
        rec_epoch = payload.get("epoch_id") or payload.get("evidence_epoch_id")
        print(f"\n--- Final Decision: {dec_id} | Epoch: {rec_epoch} | Written At: {written_at} ---")

    conn.close()
    return matching_natural_cycles

if __name__ == "__main__":
    inspect_latest_natural_cycle()
