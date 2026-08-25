#!/usr/bin/env python3
"""P7 Attempt #5 — A5-G0: Resume Contract.

Freezes the exact attempt identity before any epoch provisioning, authorization
consumption, or spawn occurs.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]

AUTH_PATH     = REPO_ROOT / "p7_attempt5_authorization.json"
IDENTITY_PATH = REPO_ROOT / "model_coverage_mc9_release_identity.json"
MANIFEST_PATH = REPO_ROOT / "model_coverage_mc8_release_manifest.json"
OUTPUT_PATH   = REPO_ROOT / "p7_attempt5_resume_contract.json"

ATTEMPT_ID             = "p7-attempt-5"
SOURCE_COMMIT          = "111dbc833e2be1e7e348d1717a624995b348f991"
PINNED_WORKTREE        = "runtime/worktrees/pinned-111dbc8"
EXPECTED_SYMBOL_COUNT  = 9
EXPECTED_SYMBOLS       = sorted(["BNB", "BTC", "DOGE", "ETH", "IOTA", "NEAR", "SOL", "TRX", "ZEC"])

# Known historical attempt identifiers — new attempt must not collide.
HISTORICAL_ATTEMPT_IDS = {"p7-attempt-1", "p7-attempt-2", "p7-attempt-3", "p7-attempt-4"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def fail(msg: str) -> None:
    print(f"FAIL: {msg}", file=sys.stderr)
    sys.exit(1)


def main() -> int:
    # ── Load artifacts ────────────────────────────────────────────────────────
    if not AUTH_PATH.exists():
        fail(f"Authorization artifact missing: {AUTH_PATH}")
    if not IDENTITY_PATH.exists():
        fail(f"Release identity artifact missing: {IDENTITY_PATH}")
    if not MANIFEST_PATH.exists():
        fail(f"Release manifest missing: {MANIFEST_PATH}")

    auth     = json.loads(AUTH_PATH.read_bytes())
    identity = json.loads(IDENTITY_PATH.read_bytes())
    manifest = json.loads(MANIFEST_PATH.read_bytes())

    auth_sha     = sha256_file(AUTH_PATH)
    identity_sha = sha256_file(IDENTITY_PATH)
    manifest_sha = sha256_file(MANIFEST_PATH)

    gates: dict[str, dict[str, Any]] = {}

    # ── G0-1: attempt_id must not collide with historical attempts ────────────
    g0_1_pass = ATTEMPT_ID not in HISTORICAL_ATTEMPT_IDS
    gates["A5-G0-1"] = {
        "gate": "attempt_id_unique",
        "attempt_id": ATTEMPT_ID,
        "historical_attempts": sorted(HISTORICAL_ATTEMPT_IDS),
        "result": "PASS" if g0_1_pass else "FAIL",
    }
    if not g0_1_pass:
        fail(f"Attempt ID collision: {ATTEMPT_ID} is a historical attempt")

    # ── G0-2: authorization hash matches disk ─────────────────────────────────
    sidecar_path = REPO_ROOT / "p7_attempt5_authorization.json.sha256"
    sidecar_sha = sidecar_path.read_text().split()[0].strip() if sidecar_path.exists() else ""
    g0_2_pass = (auth_sha == sidecar_sha) if sidecar_sha else False
    gates["A5-G0-2"] = {
        "gate": "authorization_hash_matches_sidecar",
        "auth_sha": auth_sha,
        "sidecar_sha": sidecar_sha,
        "result": "PASS" if g0_2_pass else "FAIL",
    }
    if not g0_2_pass:
        fail(f"Authorization SHA mismatch: disk={auth_sha[:16]} sidecar={sidecar_sha[:16]}")

    # ── G0-3: release manifest hash matches Attempt #5 authorization record ──────────
    auth_manifest_sha = auth.get("release_manifest_sha256", "")
    g0_3_pass = (manifest_sha == auth_manifest_sha)
    gates["A5-G0-3"] = {
        "gate": "release_manifest_hash_matches_authorization",
        "manifest_sha_disk": manifest_sha,
        "manifest_sha_auth": auth_manifest_sha,
        "result": "PASS" if g0_3_pass else "FAIL",
    }
    if not g0_3_pass:
        fail(f"Release manifest SHA mismatch: disk={manifest_sha[:16]} auth={auth_manifest_sha[:16]}")

    # ── G0-4: source commit exact ─────────────────────────────────────────────
    auth_commit = auth.get("source_commit", "")
    pinned_root = REPO_ROOT / PINNED_WORKTREE
    pinned_commit = git(pinned_root, "rev-parse", "HEAD") if pinned_root.exists() else ""
    g0_4_pass = (auth_commit == SOURCE_COMMIT) and (pinned_commit == SOURCE_COMMIT)
    gates["A5-G0-4"] = {
        "gate": "source_commit_exact",
        "expected": SOURCE_COMMIT,
        "auth_commit": auth_commit,
        "pinned_commit": pinned_commit,
        "result": "PASS" if g0_4_pass else "FAIL",
    }
    if not g0_4_pass:
        fail(f"Source commit mismatch: auth={auth_commit[:12]} pinned={pinned_commit[:12]}")

    # ── G0-5: authorization state == ARMED ───────────────────────────────────
    auth_state = auth.get("state", "")
    g0_5_pass = (auth_state == "ARMED")
    gates["A5-G0-5"] = {
        "gate": "authorization_state_armed",
        "authorization_state": auth_state,
        "result": "PASS" if g0_5_pass else "FAIL",
    }
    if not g0_5_pass:
        fail(f"Authorization state is not ARMED: {auth_state!r}")

    # ── G0-6: authorization consumed == false ─────────────────────────────────
    auth_consumed = auth.get("consumed", True)
    g0_6_pass = (auth_consumed is False)
    gates["A5-G0-6"] = {
        "gate": "authorization_not_consumed",
        "authorization_consumed": auth_consumed,
        "result": "PASS" if g0_6_pass else "FAIL",
    }
    if not g0_6_pass:
        fail(f"Authorization already consumed: {auth_consumed!r}")

    # ── G0-7: effective_runtime_symbols exact ────────────────────────────────
    effective_syms = sorted(auth.get("effective_runtime_symbols", []))
    g0_7_pass = (effective_syms == EXPECTED_SYMBOLS) and ("SOL" in effective_syms)
    gates["A5-G0-7"] = {
        "gate": "effective_symbols_exact_with_sol",
        "expected": EXPECTED_SYMBOLS,
        "actual": effective_syms,
        "sol_explicit": "SOL" in effective_syms,
        "result": "PASS" if g0_7_pass else "FAIL",
    }
    if not g0_7_pass:
        fail(f"Symbol mismatch or SOL missing: {effective_syms}")

    # ── Build contract ────────────────────────────────────────────────────────
    overall = "PASS" if all(g["result"] == "PASS" for g in gates.values()) else "FAIL"
    now = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    contract: dict[str, Any] = {
        "artifact": "p7_attempt5_resume_contract",
        "contract_version": "p7-a5-resume-contract/v1",
        "generated_at": now,
        "attempt_id": ATTEMPT_ID,
        "source_commit": SOURCE_COMMIT,
        "pinned_worktree": PINNED_WORKTREE,
        "release_id": auth.get("release_id", ""),
        "authorization_sha256": auth_sha,
        "authorization_state": auth_state,
        "authorization_consumed": False,
        "release_identity_sha256": identity_sha,
        "release_manifest_sha256": manifest_sha,
        "effective_runtime_symbols": effective_syms,
        "effective_runtime_count": len(effective_syms),
        "sol_explicit": True,
        "runtime_activation": "NOT_PERFORMED",
        "spawn_budget": auth.get("spawn_budget", 1),
        "restart_budget": auth.get("restart_budget", 0),
        "historical_attempt_ids": sorted(HISTORICAL_ATTEMPT_IDS),
        "gates": gates,
        "overall_verdict": overall,
    }
    payload = json.dumps(contract, indent=2, sort_keys=True) + "\n"
    OUTPUT_PATH.write_text(payload, encoding="utf-8")
    
    digest = hashlib.sha256(payload.encode()).hexdigest()
    (REPO_ROOT / "p7_attempt5_resume_contract.json.sha256").write_text(digest + "\n")

    print(json.dumps({
        "status": overall,
        "attempt_id": ATTEMPT_ID,
        "authorization_sha256": auth_sha,
        "gates_passed": sum(1 for g in gates.values() if g["result"] == "PASS"),
        "gates_total": len(gates),
        "output": str(OUTPUT_PATH),
        "sha256": digest,
    }, indent=2))
    return 0 if overall == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
