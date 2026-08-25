"""P7 Attempt #4 — A4-G1 Fresh Evidence Epoch Provision and Readback Tests.

Verifies the provision and read-back reports for the Attempt #4 evidence epoch.
"""
import hashlib
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

PROVISION_PATH = ROOT / "p7_attempt4_epoch_provision.json"
READBACK_PATH  = ROOT / "p7_attempt4_epoch_readback.json"
RESUME_PATH    = ROOT / "p7_attempt4_resume_contract.json"

EXPECTED_SYMBOLS = sorted(["BNB", "BTC", "DOGE", "ETH", "IOTA", "NEAR", "SOL", "TRX", "ZEC"])
EPOCH_ID = "canary-mc9-v1-a4-20260825-01"
DEPLOYMENT_ID = "paper-canary-a4-20260825-01"


def sha256_file(path: Path) -> str:
    d = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            d.update(block)
    return d.hexdigest()


@pytest.fixture(scope="module")
def provision_report():
    assert PROVISION_PATH.exists(), f"Missing: {PROVISION_PATH}"
    return json.loads(PROVISION_PATH.read_bytes())


@pytest.fixture(scope="module")
def readback_report():
    assert READBACK_PATH.exists(), f"Missing: {READBACK_PATH}"
    return json.loads(READBACK_PATH.read_bytes())


# ── T1  SHA256 sidecars valid ─────────────────────────────────────────────────
def test_a4_g1_t1_sidecars_valid():
    for p in (PROVISION_PATH, READBACK_PATH):
        sidecar = Path(str(p) + ".sha256")
        assert sidecar.exists()
        assert sha256_file(p) == sidecar.read_text().strip()


# ── T2  provision overall PASS and active epoch count 1 ───────────────────────
def test_a4_g1_t2_provision_pass(provision_report):
    assert provision_report["overall_verdict"] == "PASS"
    assert provision_report["provision_status"] == "PASS_OPERATIONAL_STATE_PROVISIONED"
    assert provision_report["active_epoch_count"] == 1


# ── T3  readback overall PASS and status ACTIVE ──────────────────────────────
def test_a4_g1_t3_readback_pass(readback_report):
    assert readback_report["overall_verdict"] == "PASS"
    assert readback_report["db_record"]["status"] == "ACTIVE"


# ── T4  all 6 readback gates PASS ─────────────────────────────────────────────
def test_a4_g1_t4_all_readback_gates_pass(readback_report):
    for gate_id, gate in readback_report["gates"].items():
        assert gate["result"] == "PASS", f"Gate {gate_id} failed: {gate}"


# ── T5  epoch & deployment ID identity matching ───────────────────────────────
def test_a4_g1_t5_identities(provision_report, readback_report):
    assert provision_report["epoch_id"] == EPOCH_ID
    assert provision_report["deployment_id"] == DEPLOYMENT_ID
    assert readback_report["epoch_id"] == EPOCH_ID
    assert readback_report["deployment_id"] == DEPLOYMENT_ID


# ── T6  SOL explicitly present in analysis universe ──────────────────────────
def test_a4_g1_t6_sol_explicit(readback_report):
    assert "SOL" in readback_report["db_record"]["analysis_universe"]
    assert sorted(readback_report["db_record"]["analysis_universe"]) == EXPECTED_SYMBOLS


# ── T7  immutable hashes in database match manifest ──────────────────────────
def test_a4_g1_t7_release_manifest_details(readback_report):
    db_manifest = readback_report["db_record"]["release_manifest_sha256"]
    assert db_manifest == "213aff3cfc6edfa8339dc0ccec31f2bab99aba3e2c400bebac6a36b67d60538a"
