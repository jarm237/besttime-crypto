"""MC9-E/F — P7 reactivation authorization tests.

Tests the authorization artifact (MC9-E) and dry validation logic (MC9-F).
"""
import hashlib
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
AUTH_PATH = ROOT / "model_coverage_mc9_p7_authorization.json"
AUTH_SHA_PATH = ROOT / "model_coverage_mc9_p7_authorization.json.sha256"
IDENTITY_PATH = ROOT / "model_coverage_mc9_release_identity.json"

SOURCE_COMMIT = "94407d3483bb01eccf0e86882cef258dcbb646e9"
EXPECTED_RELEASE_ID = "model-coverage-v1"
V1_MANIFEST_COMMIT = "56231dc093445280b6b4e73ae7d453b5e6409a16"
V1_IDENTITY_COMMIT = "9909463519405fb05307f987f10cbe878b3e0b00"
V1_ARMED_AUTH_COMMIT = "ba2a2ec5d0dc4a7e04b762ad39e21c8ab2e2fe33"
EXPECTED_SYMBOLS = ["BNB", "BTC", "DOGE", "ETH", "IOTA", "NEAR", "SOL", "TRX", "ZEC"]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def git_artifact_bytes(commit: str, path: str) -> bytes:
    """Read an immutable historical artifact directly from its sealing commit."""
    return subprocess.check_output(
        ["git", "show", f"{commit}:{path}"],
        cwd=ROOT,
    )


def validate_auth(auth: dict, identity_sha: str, manifest_sha: str) -> tuple[bool, str]:
    """Shared validation logic (mirrors mc9_verify_p7_authorization.py)."""
    if auth.get("authorization_state") != "ARMED":
        return False, f"state={auth.get('authorization_state')!r}"
    if auth.get("authorization_consumed") is not False:
        return False, "authorization_consumed != false"
    if auth.get("runtime_activation_performed") is not False:
        return False, "runtime_activation_performed != false"
    if auth.get("release_id") != EXPECTED_RELEASE_ID:
        return False, f"release_id mismatch"
    if auth.get("release_identity_sha256") != identity_sha:
        return False, "release_identity_sha256 mismatch"
    if auth.get("release_manifest_sha256") != manifest_sha:
        return False, "release_manifest_sha256 mismatch"
    if auth.get("source_commit") != SOURCE_COMMIT:
        return False, "source_commit mismatch"
    syms = auth.get("effective_runtime_symbols", [])
    if sorted(syms) != sorted(EXPECTED_SYMBOLS):
        return False, "symbols mismatch"
    if "SOL" not in syms:
        return False, "SOL missing"
    if auth.get("spawn_budget") != 1:
        return False, "spawn_budget != 1"
    if auth.get("restart_budget") != 0:
        return False, "restart_budget != 0"
    return True, "VALID"


@pytest.fixture(scope="module")
def auth():
    assert AUTH_PATH.exists(), f"Missing: {AUTH_PATH}"
    return json.loads(AUTH_PATH.read_bytes())


@pytest.fixture(scope="module")
def identity():
    assert IDENTITY_PATH.exists(), f"Missing: {IDENTITY_PATH}"
    return json.loads(IDENTITY_PATH.read_bytes())


@pytest.fixture(scope="module")
def armed_auth():
    return json.loads(
        git_artifact_bytes(V1_ARMED_AUTH_COMMIT, "model_coverage_mc9_p7_authorization.json")
    )


@pytest.fixture(scope="module")
def v1_manifest_sha():
    return hashlib.sha256(
        git_artifact_bytes(V1_MANIFEST_COMMIT, "model_coverage_mc8_release_manifest.json")
    ).hexdigest()


@pytest.fixture(scope="module")
def v1_identity_sha():
    return hashlib.sha256(
        git_artifact_bytes(V1_IDENTITY_COMMIT, "model_coverage_mc9_release_identity.json")
    ).hexdigest()


# ── T1  SHA256 sidecar matches disk ─────────────────────────────────────────
def test_mc9_e_t1_sha256_sidecar():
    assert AUTH_SHA_PATH.exists()
    assert sha256_file(AUTH_PATH) == AUTH_SHA_PATH.read_text().strip().split()[0]


# ── T2  authorization_state == CONSUMED ────────────────────────────────────────
def test_mc9_e_t2_state_consumed(auth):
    assert auth["authorization_state"] == "CONSUMED"


# ── T3  authorization_consumed == true ───────────────────────────────────────
def test_mc9_e_t3_is_consumed(auth):
    assert auth["authorization_consumed"] is True


# ── T4  runtime_activation_performed == false ────────────────────────────────
def test_mc9_e_t4_no_activation(auth):
    assert auth["runtime_activation_performed"] is False


# ── T5  spawn_budget == 1, restart_budget == 0 ────────────────────────────────
def test_mc9_e_t5_budgets(auth):
    assert auth["spawn_budget"] == 1
    assert auth["restart_budget"] == 0


# ── T6  source commit exact ───────────────────────────────────────────────────
def test_mc9_e_t6_source_commit(auth):
    assert auth["source_commit"] == SOURCE_COMMIT


# ── T7  release_id and manifest sha correct ───────────────────────────────────
def test_mc9_e_t7_release_binding(auth, v1_manifest_sha):
    assert auth["release_id"] == EXPECTED_RELEASE_ID
    assert auth["release_manifest_sha256"] == v1_manifest_sha


# ── T8  release identity sha matches bound v1 identity ────────────────────────
def test_mc9_e_t8_identity_sha(auth, v1_identity_sha):
    assert auth["release_identity_sha256"] == v1_identity_sha


# ── T9  SOL is explicitly in effective_runtime_symbols ───────────────────────
def test_mc9_e_t9_sol_explicit(auth):
    assert "SOL" in auth["effective_runtime_symbols"]


# ── T10  effective symbols == exactly 9 expected ─────────────────────────────
def test_mc9_e_t10_symbols_exact(auth):
    assert sorted(auth["effective_runtime_symbols"]) == sorted(EXPECTED_SYMBOLS)
    assert auth["effective_runtime_count"] == 9


# ── T11  full positive validation passes for ARMED authorization ────────────
def test_mc9_e_t11_positive_validation(armed_auth, v1_identity_sha, v1_manifest_sha):
    ok, reason = validate_auth(armed_auth, v1_identity_sha, v1_manifest_sha)
    assert ok, f"Positive validation failed: {reason}"


# ── NEGATIVE CASES ─────────────────────────────────────────────────────────
@pytest.mark.parametrize("label,mutation", [
    ("state=CONSUMED", {"authorization_state": "CONSUMED"}),
    ("wrong_manifest_sha", {"release_manifest_sha256": "a" * 64}),
    ("wrong_source_commit", {"source_commit": "0" * 40}),
    ("extra_symbol_AEVO", {"effective_runtime_symbols": EXPECTED_SYMBOLS + ["AEVO"]}),
    ("missing_SOL", {"effective_runtime_symbols": [s for s in EXPECTED_SYMBOLS if s != "SOL"]}),
    ("spawn_budget_2", {"spawn_budget": 2}),
    ("restart_budget_1", {"restart_budget": 1}),
    ("consumed_true", {"authorization_consumed": True}),
    ("wrong_identity_sha", {"release_identity_sha256": "b" * 64}),
    ("wrong_release_id", {"release_id": "model-coverage-v0"}),
])
def test_mc9_f_negative(armed_auth, v1_identity_sha, v1_manifest_sha, label, mutation):
    """Every tampered authorization must be rejected (fail-closed)."""
    tampered = {**armed_auth, **mutation}
    ok, reason = validate_auth(tampered, v1_identity_sha, v1_manifest_sha)
    assert not ok, (
        f"Negative case '{label}' was NOT rejected (should have been): reason={reason!r}"
    )
