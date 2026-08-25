#!/usr/bin/env python3
"""P7 Attempt #5 — A5-G8-A: Process Identity read-back.

Verifies process metadata from the spawn record.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SPAWN_PATH      = ROOT / "p7_attempt5_spawn_record.json"
RESUME_CONTRACT = ROOT / "p7_attempt5_resume_contract.json"
OUTPUT          = ROOT / "p7_attempt5_identity_readback.json"

PINNED_PATH = "/home/tran-huynh/Workspaces/Personal/besttime-crypto/runtime/worktrees/pinned-97a9704"


def fail(msg: str) -> None:
    print(f"FAIL: {msg}", file=sys.stderr)
    sys.exit(1)


def main() -> int:
    print("P7-A5-G8-A: Process Identity Read-back")
    print("=" * 50)

    if not SPAWN_PATH.exists() or not RESUME_CONTRACT.exists():
        fail("Required spawn or resume contract artifacts are missing")

    spawn = json.loads(SPAWN_PATH.read_bytes())

    gates: dict[str, dict[str, Any]] = {}

    # G8-A-1: Spawn budget and restart budget are correct
    req = spawn.get("request", {})
    g8a_1_pass = (
        req.get("spawn_budget") == 1 and
        req.get("restart_budget") == 0
    )
    gates["A5-G8-A-1"] = {
        "gate": "correct_budgets",
        "spawn_budget": req.get("spawn_budget"),
        "restart_budget": req.get("restart_budget"),
        "result": "PASS" if g8a_1_pass else "FAIL",
    }
    if not g8a_1_pass:
        fail("Incorrect spawn/restart budgets")

    # G8-A-2: Cwd matches pinned worktree
    cwd = req.get("cwd")
    g8a_2_pass = (cwd == PINNED_PATH)
    gates["A5-G8-A-2"] = {
        "gate": "cwd_matches_pinned",
        "cwd": cwd,
        "pinned": PINNED_PATH,
        "result": "PASS" if g8a_2_pass else "FAIL",
    }
    if not g8a_2_pass:
        fail(f"Cwd mismatch: {cwd} != {PINNED_PATH}")

    # G8-A-3: Env vars set correctly
    env = req.get("env", {})
    g8a_3_pass = (
        env.get("LIVE_TRADING_ENABLED") == "false" and
        env.get("PYTHONPATH") == PINNED_PATH and
        env.get("BTC_RUNTIME_ENVIRONMENT") == "paper"
    )
    gates["A5-G8-A-3"] = {
        "gate": "env_variables_correct",
        "live_trading": env.get("LIVE_TRADING_ENABLED"),
        "pythonpath": env.get("PYTHONPATH"),
        "result": "PASS" if g8a_3_pass else "FAIL",
    }
    if not g8a_3_pass:
        fail("Environment variables mismatch in spawn request")

    overall = "PASS" if all(g["result"] == "PASS" for g in gates.values()) else "FAIL"

    report = {
        "artifact": "p7_attempt5_identity_readback",
        "generated_at": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "gates": gates,
        "overall_verdict": overall,
    }

    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    OUTPUT.write_text(payload, encoding="utf-8")
    digest = hashlib.sha256(payload.encode()).hexdigest()
    (ROOT / "p7_attempt5_identity_readback.json.sha256").write_text(digest + "\n")

    print(json.dumps({
        "status": "PASS",
        "output": str(OUTPUT),
        "sha256": digest,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
