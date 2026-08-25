#!/usr/bin/env python3
"""MC9-F — Dry-validate the P7 reactivation authorization.

Verifies the authorization created by mc9_build_p7_authorization.py is
internally consistent and passes all required checks BEFORE any spawn attempt.

Also runs negative cases — all must fail-closed:
  - Tampered authorization (any field mutated)
  - Wrong release manifest hash
  - Wrong source commit
  - Extra symbol added (e.g. AEVO)
  - Missing SOL
  - spawn_budget > 1
  - restart_budget > 0
  - authorization_state = "CONSUMED"
  - old authorization cross-check (wrong identity sha)

Usage:
  python scripts/mc9_verify_p7_authorization.py
  Exits 0 on success, non-zero if any check fails.
"""
from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

AUTH_PATH = ROOT / "model_coverage_mc9_p7_authorization.json"
AUTH_SHA_PATH = ROOT / "model_coverage_mc9_p7_authorization.json.sha256"
IDENTITY_PATH = ROOT / "model_coverage_mc9_release_identity.json"

SOURCE_COMMIT = "94407d3483bb01eccf0e86882cef258dcbb646e9"
EXPECTED_RELEASE_ID = "model-coverage-v1"
EXPECTED_SYMBOLS = ["BNB", "BTC", "DOGE", "ETH", "IOTA", "NEAR", "SOL", "TRX", "ZEC"]
EXPECTED_SPAWN = 1
EXPECTED_RESTART = 0


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def check_authorization(auth: dict[str, Any], identity_sha: str, manifest_sha: str,
                        label: str = "positive") -> tuple[bool, str]:
    """Return (ok, reason). ok=True means the authorization is VALID."""
    # State
    if auth.get("authorization_state") != "ARMED":
        return False, f"authorization_state != ARMED: {auth.get('authorization_state')!r}"
    if auth.get("authorization_consumed") is not False:
        return False, "authorization_consumed != false"
    if auth.get("runtime_activation_performed") is not False:
        return False, "runtime_activation_performed != false"

    # Release identity binding
    if auth.get("release_id") != EXPECTED_RELEASE_ID:
        return False, f"release_id mismatch: {auth.get('release_id')!r}"
    if auth.get("release_identity_sha256") != identity_sha:
        return False, f"release_identity_sha256 mismatch"
    if auth.get("release_manifest_sha256") != manifest_sha:
        return False, f"release_manifest_sha256 mismatch"

    # Source commit
    if auth.get("source_commit") != SOURCE_COMMIT:
        return False, f"source_commit mismatch: {auth.get('source_commit')!r}"

    # Effective symbols (exact set, ordered)
    syms = auth.get("effective_runtime_symbols", [])
    if sorted(syms) != sorted(EXPECTED_SYMBOLS):
        return False, f"effective_runtime_symbols mismatch: {syms}"
    if "SOL" not in syms:
        return False, "SOL missing from effective_runtime_symbols"

    # Spawn/restart budgets
    if auth.get("spawn_budget") != EXPECTED_SPAWN:
        return False, f"spawn_budget != {EXPECTED_SPAWN}: {auth.get('spawn_budget')}"
    if auth.get("restart_budget") != EXPECTED_RESTART:
        return False, f"restart_budget != {EXPECTED_RESTART}: {auth.get('restart_budget')}"

    return True, "VALID"


def fail(msg: str) -> None:
    print(f"[FAIL] {msg}", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    print("MC9-F Authorization Dry Validation")
    print("=" * 50)

    auth = json.loads(AUTH_PATH.read_bytes())
    identity = json.loads(IDENTITY_PATH.read_bytes())
    identity_sha = sha256_file(IDENTITY_PATH)
    manifest_sha = identity["release_manifest"]["sha256"]

    # ── POSITIVE: SHA256 sidecar consistency ──────────────────────────────────
    recorded_sha = AUTH_SHA_PATH.read_text().strip()
    actual_sha = sha256_file(AUTH_PATH)
    if actual_sha != recorded_sha:
        fail(f"Authorization SHA256 sidecar mismatch: disk={actual_sha[:16]} sidecar={recorded_sha[:16]}")
    print("  [+] SHA256 sidecar consistent: PASS")

    # ── POSITIVE: Full positive validation ────────────────────────────────────
    ok, reason = check_authorization(auth, identity_sha, manifest_sha)
    if not ok:
        fail(f"Positive validation failed: {reason}")
    print("  [+] Positive validation: PASS")
    print(f"      state={auth['authorization_state']} spawn={auth['spawn_budget']} restart={auth['restart_budget']}")
    print(f"      SOL in symbols: {('SOL' in auth.get('effective_runtime_symbols', []))}")

    # ── NEGATIVE CASES: all must REJECT ──────────────────────────────────────
    print("\n  Negative cases (all must reject):")
    negative_results: list[dict[str, Any]] = []

    def neg(label: str, mutated_auth: dict[str, Any], expected_rejection: bool = True) -> None:
        ok_neg, reason_neg = check_authorization(mutated_auth, identity_sha, manifest_sha)
        rejected = not ok_neg
        status = "PASS" if (rejected == expected_rejection) else "FAIL"
        icon = "✓" if status == "PASS" else "✗"
        print(f"    [{icon}] {label}: {status} (rejected={rejected}, reason={reason_neg!r})")
        negative_results.append({"label": label, "rejected": rejected, "reason": reason_neg, "result": status})
        if status == "FAIL":
            fail(f"Negative case '{label}' did not fail-closed as expected")

    # Tamper: state = CONSUMED
    m = dict(auth); m["authorization_state"] = "CONSUMED"
    neg("state=CONSUMED", m)

    # Tamper: wrong manifest sha
    m = dict(auth); m["release_manifest_sha256"] = "a" * 64
    neg("wrong release_manifest_sha256", m)

    # Tamper: wrong source commit
    m = dict(auth); m["source_commit"] = "0" * 40
    neg("wrong source_commit", m)

    # Tamper: extra symbol AEVO
    m = dict(auth); m["effective_runtime_symbols"] = auth["effective_runtime_symbols"] + ["AEVO"]
    neg("extra symbol AEVO", m)

    # Tamper: remove SOL
    m = dict(auth); m["effective_runtime_symbols"] = [s for s in auth["effective_runtime_symbols"] if s != "SOL"]
    neg("missing SOL", m)

    # Tamper: spawn_budget > 1
    m = dict(auth); m["spawn_budget"] = 2
    neg("spawn_budget=2", m)

    # Tamper: restart_budget > 0
    m = dict(auth); m["restart_budget"] = 1
    neg("restart_budget=1", m)

    # Tamper: already consumed
    m = dict(auth); m["authorization_consumed"] = True
    neg("authorization_consumed=True", m)

    # Tamper: wrong release identity sha
    m = dict(auth); m["release_identity_sha256"] = "b" * 64
    neg("wrong release_identity_sha256", m)

    # Tamper: wrong release_id
    m = dict(auth); m["release_id"] = "model-coverage-v0"
    neg("wrong release_id", m)

    failed_neg = [r for r in negative_results if r["result"] == "FAIL"]
    if failed_neg:
        fail(f"Negative cases not all rejected: {[r['label'] for r in failed_neg]}")

    print(f"\n  All {len(negative_results)} negative cases rejected: PASS")
    print("\nMC9-F-VERDICT: PASS")


if __name__ == "__main__":
    main()
