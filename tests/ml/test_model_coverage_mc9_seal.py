"""MC9 — Seal Tests: Release Seal & P7 Reactivation Authorization.

Verifies the complete MC9 governance chain before marking MC9 CLOSED.
11 invariants covering all canonical artifacts, authorization state,
universe accounting, and upstream SHA256 consistency.
"""
import hashlib
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

IDENTITY_PATH = ROOT / "model_coverage_mc9_release_identity.json"
READBACK_PATH = ROOT / "model_coverage_mc9_release_readback.json"
CLOSURE_PATH = ROOT / "model_coverage_mc9_p7_failure_closure.json"
PREACTIVATION_PATH = ROOT / "model_coverage_mc9_p7_preactivation_report.json"
AUTH_PATH = ROOT / "model_coverage_mc9_p7_authorization.json"

MC8_MANIFEST = ROOT / "model_coverage_mc8_release_manifest.json"
MC8_VERDICT = ROOT / "model_coverage_mc8_final_verdict.json"

SOURCE_COMMIT = "94407d3483bb01eccf0e86882cef258dcbb646e9"
EXPECTED_AUTHORIZED = ["BNB", "BTC", "DOGE", "ETH", "IOTA", "NEAR", "SOL", "TRX", "ZEC"]
EXPECTED_DISABLED = ["AEVO", "AR", "AVAX", "ENA", "SOPH", "TAO", "TRB", "TRUMP",
                     "WLD", "XAUT", "XLM", "XPL", "XRP"]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


@pytest.fixture(scope="module")
def auth():
    assert AUTH_PATH.exists()
    return json.loads(AUTH_PATH.read_bytes())


@pytest.fixture(scope="module")
def identity():
    assert IDENTITY_PATH.exists()
    return json.loads(IDENTITY_PATH.read_bytes())


@pytest.fixture(scope="module")
def readback():
    assert READBACK_PATH.exists()
    return json.loads(READBACK_PATH.read_bytes())


@pytest.fixture(scope="module")
def closure():
    assert CLOSURE_PATH.exists()
    return json.loads(CLOSURE_PATH.read_bytes())


@pytest.fixture(scope="module")
def preactivation():
    assert PREACTIVATION_PATH.exists()
    return json.loads(PREACTIVATION_PATH.read_bytes())


# ── SEAL-1  all MC9 canonical artifacts exist with sha256 sidecars ───────────
def test_mc9_seal_1_all_artifacts_exist():
    artifacts = [
        IDENTITY_PATH, READBACK_PATH, CLOSURE_PATH, PREACTIVATION_PATH, AUTH_PATH,
    ]
    for p in artifacts:
        assert p.exists(), f"Missing artifact: {p.name}"
        sha_path = p.parent / (p.name + ".sha256")
        assert sha_path.exists(), f"Missing sidecar: {sha_path.name}"
        assert sha256_file(p) == sha_path.read_text().strip().split()[0], f"SHA mismatch: {p.name}"


# ── SEAL-2  authorization state is CONSUMED and consumed ──────────────────────
def test_mc9_seal_2_authorization_consumed(auth):
    assert auth["authorization_state"] == "CONSUMED"
    assert auth["authorization_consumed"] is True
    assert auth["runtime_activation_performed"] is False


# ── SEAL-3  spawn_budget==1 restart_budget==0 ─────────────────────────────────
def test_mc9_seal_3_budgets(auth):
    assert auth["spawn_budget"] == 1
    assert auth["restart_budget"] == 0


# ── SEAL-4  authorization source_commit exact ────────────────────────────────
def test_mc9_seal_4_auth_source_commit(auth):
    assert auth["source_commit"] == SOURCE_COMMIT


# ── SEAL-5  SOL explicitly in authorization symbols ───────────────────────────
def test_mc9_seal_5_sol_in_authorization(auth):
    assert "SOL" in auth["effective_runtime_symbols"], "SOL missing from authorization symbols"


# ── SEAL-6  universe accounting: 9 + 13 == 22 ────────────────────────────────
def test_mc9_seal_6_universe_accounting(identity):
    auth_syms = identity["authorized_symbols"]
    dis_syms = identity["disabled_symbols"]
    assert len(auth_syms) == 9
    assert len(dis_syms) == 13
    assert len(auth_syms) + len(dis_syms) == 22


# ── SEAL-7  authorized and disabled lists exact ───────────────────────────────
def test_mc9_seal_7_symbol_lists_exact(identity):
    assert sorted(identity["authorized_symbols"]) == sorted(EXPECTED_AUTHORIZED)
    assert sorted(identity["disabled_symbols"]) == sorted(EXPECTED_DISABLED)


# ── SEAL-8  P7 R4 failure class CLOSED ───────────────────────────────────────
def test_mc9_seal_8_p7_r4_closed(closure):
    assert closure["p7_r4_failure_class"] == "CLOSED"
    inv = closure["coverage_closure_invariant"]
    assert inv["gap"] == []
    assert inv["verdict"] == "CLOSED"


# ── SEAL-9  SOL readback explicit PASS ───────────────────────────────────────
def test_mc9_seal_9_sol_readback_explicit(readback):
    sol = readback["sol_explicit"]
    assert sol["overall"] == "PASS"
    assert sol["runtime_enabled"] is True


# ── SEAL-10  no runtime activation performed (preactivation report) ───────────
def test_mc9_seal_10_no_activation(preactivation):
    assert preactivation["runtime_activation_performed"] is False
    assert preactivation["no_active_epochs"] is True
    assert preactivation["fresh_evidence_epoch_required"] is True


# ── SEAL-11  upstream MC8 manifest sha unchanged ──────────────────────────────
def test_mc9_seal_11_mc8_manifest_unchanged(identity):
    identity_recorded_sha = identity["release_manifest"]["sha256"]
    actual_sha = sha256_file(MC8_MANIFEST)
    assert actual_sha == identity_recorded_sha, (
        f"MC8 manifest sha changed! disk={actual_sha[:16]} identity={identity_recorded_sha[:16]}"
    )
