#!/usr/bin/env python3
"""P7 Attempt #5 — A5-G8-B: Running Release Identity Read-Back.

Reads back active epoch values again to prove the running process release identity
matches the authorization.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PINNED          = ROOT / "runtime" / "worktrees" / "pinned-97a9704"
RESUME_CONTRACT = ROOT / "p7_attempt5_resume_contract.json"
OUTPUT          = ROOT / "p7_attempt5_release_readback.json"

EPOCH_ID = "canary-mc9-v1-a5-20260825-01"


def fail(msg: str) -> None:
    print(f"FAIL: {msg}", file=sys.stderr)
    sys.exit(1)


def import_pinned_modules(pinned_root: Path) -> dict[str, Any]:
    pinned = str(pinned_root)
    if pinned in sys.path:
        sys.path.remove(pinned)
    sys.path.insert(0, pinned)
    from btc_scraper.ml_engine.runtime_evidence_store import RuntimeEvidenceStore
    return {"RuntimeEvidenceStore": RuntimeEvidenceStore}


def main() -> int:
    print("P7-A5-G8-B: Running Release Identity Read-Back")
    print("=" * 50)

    if not RESUME_CONTRACT.exists():
        fail("Resume contract missing")

    modules = import_pinned_modules(PINNED)
    store = modules["RuntimeEvidenceStore"]()
    evidence_db = store.global_index_path
    if not evidence_db.exists():
        fail("Global index database missing")

    with sqlite3.connect(evidence_db) as db:
        row = db.execute(
            "SELECT epoch_id, deployment_id, status, code_commit_sha, release_manifest_sha256 "
            "FROM evidence_epochs WHERE epoch_id=?", (EPOCH_ID,)
        ).fetchone()

    if row is None:
        fail("Epoch row not found in database during G8-B")

    gates: dict[str, dict[str, Any]] = {}
    db_epoch_id, db_deploy_id, db_status, db_commit, db_manifest_sha = row

    g8b_1_pass = (
        db_epoch_id == EPOCH_ID and
        db_status == "ACTIVE" and
        db_commit == "1b4d2965d0a374660278a61b80dea8443f61382f" and
        db_manifest_sha == "86f83986d4f7a2ac8f5a077abad24ceb47b0e0a4e4f3f061738b5b12cc13f583"
    )

    gates["A5-G8-B-1"] = {
        "gate": "running_release_matches_authorization",
        "epoch_id": db_epoch_id,
        "status": db_status,
        "code_commit_sha": db_commit,
        "release_manifest_sha256": db_manifest_sha,
        "result": "PASS" if g8b_1_pass else "FAIL",
    }
    if not g8b_1_pass:
        fail("Running process release mismatch")

    overall = "PASS" if all(g["result"] == "PASS" for g in gates.values()) else "FAIL"

    report = {
        "artifact": "p7_attempt5_release_readback",
        "generated_at": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "gates": gates,
        "overall_verdict": overall,
    }
    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    OUTPUT.write_text(payload, encoding="utf-8")
    digest = hashlib.sha256(payload.encode()).hexdigest()
    (ROOT / "p7_attempt5_release_readback.json.sha256").write_text(digest + "\n")

    print(json.dumps({
        "status": "PASS",
        "output": str(OUTPUT),
        "sha256": digest,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
