"""P7 Attempt #4 — A4-G0 Resume Contract Tests.

Verifies all 7 gates of the resume contract artifact plus negative cases.
"""
import hashlib
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

CONTRACT_PATH = ROOT / "p7_attempt4_resume_contract.json"

SOURCE_COMMIT     = "94407d3483bb01eccf0e86882cef258dcbb646e9"
V1_MANIFEST_COMMIT = "56231dc093445280b6b4e73ae7d453b5e6409a16"
V1_IDENTITY_COMMIT = "9909463519405fb05307f987f10cbe878b3e0b00"
V1_ARMED_AUTH_COMMIT = "ba2a2ec5d0dc4a7e04b762ad39e21c8ab2e2fe33"
ATTEMPT_ID        = "p7-attempt-4"
HISTORICAL_IDS    = {"p7-attempt-1", "p7-attempt-2", "p7-attempt-3"}
EXPECTED_SYMBOLS  = sorted(["BNB", "BTC", "DOGE", "ETH", "IOTA", "NEAR", "SOL", "TRX", "ZEC"])


def sha256_file(path: Path) -> str:
    d = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            d.update(block)
    return d.hexdigest()


def git_artifact_bytes(commit: str, path: str) -> bytes:
    """Read a generation-specific artifact from its immutable sealing commit."""
    return subprocess.check_output(
        ["git", "show", f"{commit}:{path}"],
        cwd=ROOT,
    )


@pytest.fixture(scope="module")
def contract():
    assert CONTRACT_PATH.exists(), f"Missing: {CONTRACT_PATH}"
    return json.loads(CONTRACT_PATH.read_bytes())


# ── T1  SHA256 sidecar valid ──────────────────────────────────────────────────
def test_a4_g0_t1_sidecar_valid():
    sidecar = Path(str(CONTRACT_PATH) + ".sha256")
    assert sidecar.exists()
    assert sha256_file(CONTRACT_PATH) == sidecar.read_text().strip()


# ── T2  all gates PASS ────────────────────────────────────────────────────────
def test_a4_g0_t2_all_gates_pass(contract):
    assert contract["overall_verdict"] == "PASS"
    for gate_id, gate in contract["gates"].items():
        assert gate["result"] == "PASS", f"Gate {gate_id} failed: {gate}"


# ── T3  attempt_id unique (not historical) ────────────────────────────────────
def test_a4_g0_t3_attempt_id_unique(contract):
    assert contract["attempt_id"] == ATTEMPT_ID
    assert ATTEMPT_ID not in HISTORICAL_IDS
    assert ATTEMPT_ID not in contract.get("historical_attempt_ids", [])


# ── T4  authorization hash matches expected ARMED authorization SHA ───────────
def test_a4_g0_t4_authorization_sha_matches_disk(contract):
    historical_auth = git_artifact_bytes(
        V1_ARMED_AUTH_COMMIT,
        "model_coverage_mc9_p7_authorization.json",
    )
    assert contract["authorization_sha256"] == hashlib.sha256(historical_auth).hexdigest()


# ── T5  release manifest hash matches bound v1 manifest and authorization record ───────────
def test_a4_g0_t5_manifest_sha_matches(contract):
    historical_manifest = git_artifact_bytes(
        V1_MANIFEST_COMMIT,
        "model_coverage_mc8_release_manifest.json",
    )
    historical_auth = git_artifact_bytes(
        V1_ARMED_AUTH_COMMIT,
        "model_coverage_mc9_p7_authorization.json",
    )
    assert contract["release_manifest_sha256"] == hashlib.sha256(historical_manifest).hexdigest()
    auth = json.loads(historical_auth)
    assert contract["release_manifest_sha256"] == auth["release_manifest_sha256"]


# ── T6  source commit exact ───────────────────────────────────────────────────
def test_a4_g0_t6_source_commit_exact(contract):
    assert contract["source_commit"] == SOURCE_COMMIT


# ── T7  authorization_state ARMED, not consumed ───────────────────────────────
def test_a4_g0_t7_armed_not_consumed(contract):
    assert contract["authorization_state"] == "ARMED"
    assert contract["authorization_consumed"] is False
    assert contract["runtime_activation"] == "NOT_PERFORMED"


# ── T8  SOL explicitly in effective symbols ───────────────────────────────────
def test_a4_g0_t8_sol_explicit(contract):
    assert "SOL" in contract["effective_runtime_symbols"]
    assert contract["sol_explicit"] is True


# ── T9  effective symbols exact 9 ─────────────────────────────────────────────
def test_a4_g0_t9_symbols_exact(contract):
    assert sorted(contract["effective_runtime_symbols"]) == EXPECTED_SYMBOLS
    assert contract["effective_runtime_count"] == 9


# ── T10  budgets unchanged ────────────────────────────────────────────────────
def test_a4_g0_t10_budgets(contract):
    assert contract["spawn_budget"] == 1
    assert contract["restart_budget"] == 0


# ── T11  release identity sha matches disk ────────────────────────────────────
def test_a4_g0_t11_identity_sha_matches_disk(contract):
    historical_identity = git_artifact_bytes(
        V1_IDENTITY_COMMIT,
        "model_coverage_mc9_release_identity.json",
    )
    assert contract["release_identity_sha256"] == hashlib.sha256(historical_identity).hexdigest()


# ── NEGATIVE: historical attempt id in contract would fail ────────────────────
@pytest.mark.parametrize("historical_id", sorted(HISTORICAL_IDS))
def test_a4_g0_neg_historical_id_not_reused(historical_id, contract):
    """Attempt id must not match any historical attempt."""
    assert contract["attempt_id"] != historical_id
