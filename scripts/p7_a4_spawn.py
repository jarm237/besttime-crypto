#!/usr/bin/env python3
"""P7 Attempt #4 — A4-G2/G3/G4 Phase C: Authorization Consumption & Supervised Spawn.

1. Re-verifies live authorization is ARMED.
2. Re-verifies evidence epoch is ACTIVE.
3. Overwrites model_coverage_mc9_p7_authorization.json to CONSUMED.
4. Spawns the child process under supervision of scripts/p7_r3a_supervised_child.py.
5. Saves p7_attempt4_authorization_consumption.json and p7_attempt4_spawn_record.json.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PINNED          = ROOT / "runtime" / "worktrees" / "pinned-94407d3"
AUTH_PATH       = ROOT / "model_coverage_mc9_p7_authorization.json"
AUTH_SHA_PATH   = ROOT / "model_coverage_mc9_p7_authorization.json.sha256"
MANIFEST_PATH   = ROOT / "model_coverage_mc8_release_manifest.json"
RESUME_CONTRACT = ROOT / "p7_attempt4_resume_contract.json"
A4_MANIFEST     = ROOT / "p7_a4_manifest.json"

CONSUMPTION_PATH = ROOT / "p7_attempt4_authorization_consumption.json"
SPAWN_PATH       = ROOT / "p7_attempt4_spawn_record.json"

ATTEMPT_ID     = "p7-attempt-4"
DEPLOYMENT_ID  = "paper-canary-a4-20260825-01"
PAPER_RUN_ID   = "paper-canary-a4-20260825-01"
EPOCH_ID       = "canary-mc9-v1-a4-20260825-01"
SOURCE_COMMIT  = "94407d3483bb01eccf0e86882cef258dcbb646e9"


def fail(msg: str) -> None:
    print(f"FAIL: {msg}", file=sys.stderr)
    sys.exit(1)


def sha256_file(path: Path) -> str:
    d = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            d.update(block)
    return d.hexdigest()


def import_pinned_modules(pinned_root: Path) -> dict[str, Any]:
    pinned = str(pinned_root)
    if pinned in sys.path:
        sys.path.remove(pinned)
    sys.path.insert(0, pinned)
    from btc_scraper.ml_engine.runtime_evidence_store import RuntimeEvidenceStore
    return {"RuntimeEvidenceStore": RuntimeEvidenceStore}


def main() -> int:
    print("P7-A4-G2/G3/G4: Authorization Consumption & Supervised Spawn")
    print("=" * 50)

    # ── 1. Re-verifications ──────────────────────────────────────────────────
    if not AUTH_PATH.exists() or not MANIFEST_PATH.exists() or not RESUME_CONTRACT.exists():
        fail("Required governance artifacts are missing")

    auth = json.loads(AUTH_PATH.read_bytes())
    if auth.get("authorization_state") != "ARMED" or auth.get("authorization_consumed") is not False:
        fail("Authorization is not ARMED or is already consumed")

    # Verify active epoch is ACTIVE
    modules = import_pinned_modules(PINNED)
    store = modules["RuntimeEvidenceStore"]()
    evidence_db = store.global_index_path
    if not evidence_db.exists():
        fail("Global index database missing")

    with sqlite3.connect(evidence_db) as db:
        row = db.execute(
            "SELECT status FROM evidence_epochs WHERE epoch_id=?", (EPOCH_ID,)
        ).fetchone()
    if row is None or row[0] != "ACTIVE":
        fail(f"Epoch {EPOCH_ID} is not ACTIVE in database (status={row[0] if row else 'None'})")

    print("  Preconditions: VALID")

    # ── 2. Atomically Consume Authorization ────────────────────────────────────
    now_str = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    original_auth_sha = sha256_file(AUTH_PATH)

    # Overwrite authorization file to CONSUMED
    auth["authorization_state"] = "CONSUMED"
    auth["authorization_consumed"] = True
    auth["consumed_at"] = now_str
    auth["consumed_by_attempt"] = ATTEMPT_ID

    auth_payload = json.dumps(auth, indent=2, sort_keys=True) + "\n"
    AUTH_PATH.write_text(auth_payload, encoding="utf-8")
    new_auth_sha = hashlib.sha256(auth_payload.encode()).hexdigest()
    AUTH_SHA_PATH.write_text(new_auth_sha + "\n")

    # Write consumption report
    consumption_report = {
        "artifact": "p7_attempt4_authorization_consumption",
        "generated_at": now_str,
        "attempt_id": ATTEMPT_ID,
        "epoch_id": EPOCH_ID,
        "consumed_at": now_str,
        "original_authorization_sha256": original_auth_sha,
        "consumed_authorization_sha256": new_auth_sha,
        "status": "CONSUMED",
        "overall_verdict": "PASS",
    }
    consumption_payload = json.dumps(consumption_report, indent=2, sort_keys=True) + "\n"
    CONSUMPTION_PATH.write_text(consumption_payload, encoding="utf-8")
    consumption_digest = hashlib.sha256(consumption_payload.encode()).hexdigest()
    CONSUMPTION_PATH.with_suffix(".json.sha256").write_text(consumption_digest + "\n")

    print(f"  Authorization consumed: ARMED -> CONSUMED (sha={new_auth_sha[:16]})")

    # ── 3. Spawn child under supervision ──────────────────────────────────────
    from scripts.p7_r3a_supervised_child import SupervisedChildRequest, supervise_child

    # Command parameters
    argv = (sys.executable, str(PINNED / "main.py"))

    # Environment variables
    child_env = {
        **os.environ,
        "PYTHONPATH": str(PINNED),
        "PYTHONNOUSERSITE": "1",
        "BTC_RUNTIME_ENVIRONMENT": "paper",
        "BTC_DEPLOYMENT_ID": DEPLOYMENT_ID,
        "BTC_PAPER_RUN_ID": PAPER_RUN_ID,
        "BTC_EVIDENCE_ELIGIBLE": "true",
        "AUTO_TRADE_DRY_RUN": "true",
        "AUTO_TRADE_BINANCE_TESTNET": "true",
        "LIVE_TRADING_ENABLED": "false",
        "P7_MANIFEST_PATH": str(A4_MANIFEST.resolve()),
        "P7_MANIFEST_SHA256": sha256_file(A4_MANIFEST),
        "P7_RELEASE_COMMIT_SHA": SOURCE_COMMIT,
        "P7_RELEASE_TREE_SHA": "fb816e7194dcd2af35f69d77e155bbf24de04347",
        "P7_ARTIFACT_SHA256": "dbf0a08241dae01241539ef3f48c6a0b13da9b13a5b128de259aac06d267241c",
        "P7_LAUNCHER_CONTRACT": "paper-canary-launcher/v1",
        "P7_A4_AUTHORIZATION_SHA256": new_auth_sha,
    }

    # Stdout/Stderr logs go to the deployment directory
    logs_dir = ROOT / "runtime" / "paper" / DEPLOYMENT_ID / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    stdout_path = logs_dir / "supervised_child.stdout.log"
    stderr_path = logs_dir / "supervised_child.stderr.log"

    request = SupervisedChildRequest(
        argv=argv,
        cwd=PINNED.resolve(),
        env=child_env,
        stdout_path=stdout_path.resolve(),
        stderr_path=stderr_path.resolve(),
        lifecycle_path=SPAWN_PATH.resolve(),
        authorization_sha256=new_auth_sha,
        spawn_budget=1,
        restart_budget=0,
        automatic_retry=False,
    )

    print("  Spawning child process...")
    # Monitor child for 10.0 seconds to confirm liveness
    result = supervise_child(request, observation_timeout_seconds=10.0)

    # Check spawn status
    status = result.get("status", "")
    child_pid = result.get("child_pid")
    print(f"  Spawn status: {status} (PID={child_pid})")

    # Generate sha256 sidecar for spawn record
    spawn_payload = SPAWN_PATH.read_bytes()
    spawn_digest = hashlib.sha256(spawn_payload).hexdigest()
    SPAWN_PATH.with_suffix(".json.sha256").write_text(spawn_digest + "\n")

    if status not in ("STILL_RUNNING", "EXITED"):
        fail(f"Supervised spawn failed: status={status!r}")

    print(json.dumps({
        "status": "PASS",
        "child_status": status,
        "child_pid": child_pid,
        "consumption_sha256": consumption_digest,
        "spawn_sha256": spawn_digest,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
