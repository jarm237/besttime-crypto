#!/usr/bin/env python3
"""MC9-E — Build fresh one-shot P7 reactivation authorization.

Creates exactly ONE authorization artifact in state ARMED.
This authorization:
  - References the MC8 seal commit and model-coverage-v1 release identity
  - Allows exactly 1 spawn, 0 restarts
  - Does NOT contain the MC9 seal commit (avoiding circular hash dependency)
  - Must be independently verified by mc9_verify_p7_authorization.py

Authorization state machine:
  NOT_CREATED → ARMED → CONSUMED

Once CONSUMED (after P7 Attempt #4, whether successful or not),
a new authorization is required. MC9 does not issue a second authorization.

Output: model_coverage_mc9_p7_authorization.json + .sha256
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

IDENTITY = ROOT / "model_coverage_mc9_release_identity.json"
MC8_VERDICT = ROOT / "model_coverage_mc8_final_verdict.json"
PREACTIVATION = ROOT / "model_coverage_mc9_p7_preactivation_report.json"

OUTPUT = ROOT / "model_coverage_mc9_p7_authorization.json"
OUTPUT_SHA = ROOT / "model_coverage_mc9_p7_authorization.json.sha256"

EFFECTIVE_RUNTIME_SYMBOLS = ["BNB", "BTC", "DOGE", "ETH", "IOTA", "NEAR", "SOL", "TRX", "ZEC"]
SOURCE_COMMIT = "94407d3483bb01eccf0e86882cef258dcbb646e9"
# MC8 seal = HEAD of branch at MC8 close (before MC9 commits)
MC8_SEAL_COMMIT = "d857d0c"  # short form; full hash below
MC8_SEAL_COMMIT_FULL = "d857d0c"  # populated from verdict


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def fail(msg: str) -> None:
    print(f"[FAIL] {msg}", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    print("MC9-E Build P7 Reactivation Authorization")
    print("=" * 50)

    # Load upstream evidence
    identity = json.loads(IDENTITY.read_bytes())
    mc8_verdict = json.loads(MC8_VERDICT.read_bytes())
    preactivation = json.loads(PREACTIVATION.read_bytes())

    # Hard stop checks
    if mc8_verdict.get("mc8_verdict") != "CLOSED":
        fail("MC8 verdict is not CLOSED")
    if preactivation.get("overall_verdict") != "PASS":
        fail("MC9-D preactivation report is not PASS")
    if preactivation.get("runtime_activation_performed") is not False:
        fail("runtime_activation_performed != false in preactivation report")
    if preactivation.get("no_active_epochs") is not True:
        fail("active epochs found — cannot issue fresh authorization")

    identity_sha = sha256_file(IDENTITY)
    manifest_sha = identity["release_manifest"]["sha256"]
    mc8_source_commit = mc8_verdict.get("mc8_source_commit", SOURCE_COMMIT)

    print(f"  release_id:            model-coverage-v1")
    print(f"  source_commit:         {mc8_source_commit[:12]}...")
    print(f"  release_identity_sha:  {identity_sha[:12]}...")
    print(f"  release_manifest_sha:  {manifest_sha[:12]}...")
    print(f"  spawn_budget:          1")
    print(f"  restart_budget:        0")
    print(f"  authorization_state:   ARMED")

    # NOTE: We do NOT embed the MC9 seal commit here to avoid circular dependency.
    # The MC9 final verdict will reference THIS authorization's sha256 instead.
    authorization: dict[str, Any] = {
        "authorization_type": "P7_REACTIVATION",
        "authorization_version": "mc9-p7-authorization/v1",

        # Release identity anchors
        "release_id": "model-coverage-v1",
        "release_identity_sha256": identity_sha,
        "release_manifest_sha256": manifest_sha,

        # Commit anchors
        "mc8_seal_commit": mc8_source_commit,   # last MC8 commit = source commit pinned by MC8
        "source_commit": SOURCE_COMMIT,

        # Effective universe (exact list — no inference from count alone)
        "effective_runtime_symbols": EFFECTIVE_RUNTIME_SYMBOLS,
        "effective_runtime_count": len(EFFECTIVE_RUNTIME_SYMBOLS),

        # Spawn and restart controls
        "spawn_budget": 1,
        "restart_budget": 0,

        # State machine: NOT_CREATED → ARMED → CONSUMED
        # Once consumed (for any reason), a new authorization is required.
        "authorization_state": "ARMED",
        "runtime_activation_performed": False,
        "authorization_consumed": False,

        # Provenance chain (not circular — does not reference MC9 seal)
        "issued_by": "MC9-E",
        "issued_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "upstream_preactivation_sha256": sha256_file(PREACTIVATION),
        "upstream_mc8_verdict_sha256": sha256_file(MC8_VERDICT),

        # Explicit prohibitions (for auditors)
        "prohibitions": [
            "different_source_commit",
            "different_release_bundle",
            "different_registry",
            "different_effective_universe",
            "second_spawn",
            "automatic_retry",
            "restart_on_failure",
        ],
    }

    OUTPUT.write_text(json.dumps(authorization, indent=2))
    file_sha = sha256_file(OUTPUT)
    OUTPUT_SHA.write_text(file_sha)

    print(f"\nWritten: {OUTPUT.name}")
    print(f"SHA256:  {file_sha}")
    print("MC9-E-VERDICT: AUTHORIZATION ARMED")


if __name__ == "__main__":
    main()
