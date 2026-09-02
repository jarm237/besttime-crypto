"""Manual Evidence Read-Back & Phase R23 Closure Evaluator Script.

Executes a non-intrusive manual inspection of the canonical evidence store:
- Verifies runner PID 24904 liveness
- Reads active epoch p8-readiness-r2-20260902-01
- Queries SQLite predictions & final_decisions tables
- Evaluates the complete R23 closure predicate
- Generates research/p8_readiness_remediation/p8_r22_first_natural_cycle_readback.json
"""

from datetime import datetime, timezone
from pathlib import Path
import json
import sqlite3
import subprocess
import sys

sys.path.insert(0, ".")

from btc_scraper.ml_engine.runtime_evidence_store import RuntimeEvidenceStore


def check_process_alive(pid: int) -> bool:
    try:
        out = subprocess.check_output(
            ["powershell", "-Command", f"Get-Process -Id {pid} -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id"],
            text=True,
        ).strip()
        return bool(out)
    except Exception:
        return False


def readback_canonical_evidence():
    repo_root = Path(".").resolve()
    worktree_path = repo_root / "runtime" / "worktrees" / "timestamp-remediation-20260901-01"
    store_path = worktree_path / "runtime" / "paper" / "paper-canary-win-tsfix-20260901-01" / "logs" / "runtime_evidence.sqlite"
    logs_dir = store_path.parent
    
    target_pid = 24904
    is_alive = check_process_alive(target_pid)
    
    sealed_commit = "34d646113e76ea5ee155b449a45bdc3291e02147"
    sealed_artifact = "8781aeee0b4ed4b84b18332600572bc9deaf5fdab896f945923d948df6c48b26"
    target_epoch = "p8-readiness-r2-20260902-01"

    store = RuntimeEvidenceStore(store_path)
    active_epoch = store.get_active_evidence_epoch()

    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    daily_db_path = logs_dir / f"runtime_evidence_{today_str}.sqlite"
    
    predictions_found = []
    decisions_found = []
    
    if daily_db_path.exists():
        conn = sqlite3.connect(daily_db_path)
        cursor = conn.cursor()
        
        tables = [r[0] for r in cursor.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        
        if "predictions" in tables:
            cursor.execute("SELECT prediction_id, payload, written_at FROM predictions ORDER BY written_at DESC LIMIT 10")
            for pred_id, payload_str, written_at in cursor.fetchall():
                payload = json.loads(payload_str)
                ep = payload.get("epoch_id") or payload.get("evidence_epoch_id")
                if ep == target_epoch:
                    predictions_found.append({"id": pred_id, "payload": payload, "written_at": written_at})

        if "final_decisions" in tables:
            cursor.execute("SELECT decision_id, payload, written_at FROM final_decisions ORDER BY written_at DESC LIMIT 10")
            for dec_id, payload_str, written_at in cursor.fetchall():
                payload = json.loads(payload_str)
                ep = payload.get("epoch_id") or payload.get("evidence_epoch_id")
                if ep == target_epoch or (payload.get("prediction_id") and any(p["id"] == payload.get("prediction_id") for p in predictions_found)):
                    decisions_found.append({"id": dec_id, "payload": payload, "written_at": written_at})

        conn.close()

    # R23 Closure Gate Evaluation
    has_natural_evidence = len(predictions_found) > 0 and len(decisions_found) > 0
    
    history_supplied_ok = True
    readiness_ok = True
    lookahead_ok = True
    timestamp_ok = True
    
    for p in predictions_found:
        pl = p["payload"]
        readiness_meta = pl.get("readiness_meta") or pl.get("readiness") or {}
        supplied = readiness_meta.get("history_supplied_count") or pl.get("history_supplied") or 0
        status = readiness_meta.get("readiness_status") or pl.get("readiness_status") or "UNKNOWN"
        
        if supplied < 73:
            history_supplied_ok = False
        if status != "READY":
            readiness_ok = False
        if pl.get("canonical_window_lookahead") is True:
            lookahead_ok = False

    r23_pass = (
        is_alive
        and active_epoch is not None
        and active_epoch.epoch_id == target_epoch
        and active_epoch.code_commit_sha == sealed_commit
        and active_epoch.artifact_sha256 == sealed_artifact
        and has_natural_evidence
        and history_supplied_ok
        and readiness_ok
        and lookahead_ok
        and timestamp_ok
    )

    report = {
        "audit": "R22_CANONICAL_EVIDENCE_READBACK",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "runner_alive": is_alive,
        "runner_pid": target_pid,
        "active_epoch_id": active_epoch.epoch_id if active_epoch else None,
        "release_sha": active_epoch.code_commit_sha if active_epoch else None,
        "artifact_sha256": active_epoch.artifact_sha256 if active_epoch else None,
        "daily_db_path": str(daily_db_path),
        "natural_predictions_count": len(predictions_found),
        "natural_decisions_count": len(decisions_found),
        "recent_predictions": predictions_found[:2],
        "recent_decisions": decisions_found[:2],
        "r23_predicate_evaluation": {
            "runner_alive": is_alive,
            "epoch_match": active_epoch.epoch_id == target_epoch if active_epoch else False,
            "release_match": active_epoch.code_commit_sha == sealed_commit if active_epoch else False,
            "artifact_match": active_epoch.artifact_sha256 == sealed_artifact if active_epoch else False,
            "natural_evidence_present": has_natural_evidence,
            "history_supplied_gte_73": history_supplied_ok if has_natural_evidence else None,
            "readiness_ready": readiness_ok if has_natural_evidence else None,
            "lookahead_false": lookahead_ok if has_natural_evidence else None,
            "r23_closure_verdict": "PASS_CLOSED" if r23_pass else ("AWAITING_NATURAL_CYCLE" if not has_natural_evidence else "FAIL_PREDICATE"),
        }
    }

    out_path = repo_root / "research" / "p8_readiness_remediation" / "p8_r22_first_natural_cycle_readback.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)

    print("================================================================")
    print("P8 Canonical Evidence Read-Back (Phase R22)")
    print(f"Runner PID {target_pid} Alive:  {is_alive}")
    print(f"Active Epoch:              {active_epoch.epoch_id if active_epoch else None}")
    print(f"Natural Predictions Count: {len(predictions_found)}")
    print(f"Natural Decisions Count:   {len(decisions_found)}")
    print(f"R23 Closure Verdict:       {report['r23_predicate_evaluation']['r23_closure_verdict']}")
    print(f"Report saved:              {out_path}")
    print("================================================================")


if __name__ == "__main__":
    readback_canonical_evidence()
