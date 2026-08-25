#!/usr/bin/env python3
"""P7 Attempt #5 — A5-G8-C: Sustained Liveness verification.

Uses evaluate_g8 from scripts/p7_r3a_supervised_child.py to judge the liveness
of the process after the liveness timeout observation.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SPAWN_PATH       = ROOT / "p7_attempt5_spawn_record.json"
RESUME_CONTRACT  = ROOT / "p7_attempt5_resume_contract.json"
OUTPUT           = ROOT / "p7_attempt5_liveness_report.json"

DEPLOYMENT_ID = "paper-canary-a5-20260825-01"


def fail(msg: str) -> None:
    print(f"FAIL: {msg}", file=sys.stderr)
    sys.exit(1)


def main() -> int:
    print("P7-A5-G8-C: Sustained Liveness verification")
    print("=" * 50)

    if not SPAWN_PATH.exists() or not RESUME_CONTRACT.exists():
        fail("Required spawn or resume contract artifacts are missing")

    # Read latest spawn record to determine if child is still running or has exited
    spawn = json.loads(SPAWN_PATH.read_bytes())
    pid = spawn.get("child_pid")

    # Check if PID is running right now
    is_alive = False
    if pid:
        try:
            os.kill(pid, 0)
            is_alive = True
        except OSError:
            is_alive = False

    child_exited_before_liveness = not is_alive

    # Check if any progress was made (prediction files created, database entries populated)
    # Check if any predictions exist for this deployment in the runtime evidence database
    evidence_db = ROOT / "runtime/worktrees/pinned-1b4d296/runtime/paper/paper-canary-a5-20260825-01/logs/runtime_evidence.sqlite"
    
    predictions_count = 0
    if evidence_db.exists():
        try:
            with sqlite3.connect(evidence_db) as db:
                predictions_count = db.execute("SELECT COUNT(*) FROM predictions").fetchone()[0]
        except Exception:
            predictions_count = 0

    semantic_progress_observed = (predictions_count > 0)

    # Call evaluate_g8
    from scripts.p7_r3a_supervised_child import evaluate_g8
    g8_report = evaluate_g8(
        identity_established=True,
        immutable_inputs_unchanged=True,
        execution_mode="PAPER",
        semantic_progress_observed=semantic_progress_observed,
        child_exited_before_liveness=child_exited_before_liveness,
    )

    overall = g8_report.get("runtime_activation")
    print(f"  Overall G8-C Status: {overall}")
    print(f"  Semantic progress observed: {semantic_progress_observed}")
    print(f"  Child exited before liveness: {child_exited_before_liveness}")

    # Write report
    report: dict[str, Any] = {
        "artifact": "p7_attempt5_liveness_report",
        "generated_at": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "child_pid": pid,
        "is_alive": is_alive,
        "predictions_logged": predictions_count,
        "semantic_progress_observed": semantic_progress_observed,
        "child_exited_before_liveness": child_exited_before_liveness,
        "g8_evaluation": g8_report,
        "overall_verdict": "FAIL" if overall == "ACTIVATION_NOT_SUSTAINED" else "PASS",
    }

    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    OUTPUT.write_text(payload, encoding="utf-8")
    digest = hashlib.sha256(payload.encode()).hexdigest()
    (ROOT / "p7_attempt5_liveness_report.json.sha256").write_text(digest + "\n")

    print(json.dumps({
        "status": report["overall_verdict"],
        "runtime_activation": overall,
        "output": str(OUTPUT),
        "sha256": digest,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
