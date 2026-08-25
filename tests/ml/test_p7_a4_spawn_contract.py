"""P7 Attempt #4 — A4-G2/G3/G4 Phase C: Authorization Consumption & Supervised Spawn Tests.

Verifies the consumption record, spawn record, and authorization state update.
"""
import hashlib
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

CONSUMPTION_PATH = ROOT / "p7_attempt4_authorization_consumption.json"
SPAWN_PATH       = ROOT / "p7_attempt4_spawn_record.json"
AUTH_PATH        = ROOT / "model_coverage_mc9_p7_authorization.json"

ATTEMPT_ID = "p7-attempt-4"
EPOCH_ID = "canary-mc9-v1-a4-20260825-01"


def sha256_file(path: Path) -> str:
    d = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            d.update(block)
    return d.hexdigest()


@pytest.fixture(scope="module")
def consumption():
    assert CONSUMPTION_PATH.exists(), f"Missing: {CONSUMPTION_PATH}"
    return json.loads(CONSUMPTION_PATH.read_bytes())


@pytest.fixture(scope="module")
def spawn():
    assert SPAWN_PATH.exists(), f"Missing: {SPAWN_PATH}"
    return json.loads(SPAWN_PATH.read_bytes())


@pytest.fixture(scope="module")
def auth():
    assert AUTH_PATH.exists(), f"Missing: {AUTH_PATH}"
    return json.loads(AUTH_PATH.read_bytes())


# ── T1  SHA256 sidecars valid ─────────────────────────────────────────────────
def test_a4_g2_t1_sidecars_valid():
    for p in (CONSUMPTION_PATH, SPAWN_PATH):
        sidecar = Path(str(p) + ".sha256")
        assert sidecar.exists()
        assert sha256_file(p) == sidecar.read_text().strip()


# ── T2  authorization state updated to CONSUMED ───────────────────────────────
def test_a4_g2_t2_auth_state_consumed(auth):
    assert auth["authorization_state"] == "CONSUMED"
    assert auth["authorization_consumed"] is True
    assert auth["consumed_by_attempt"] == ATTEMPT_ID


# ── T3  consumption artifact properties ───────────────────────────────────────
def test_a4_g2_t3_consumption_properties(consumption):
    assert consumption["overall_verdict"] == "PASS"
    assert consumption["status"] == "CONSUMED"
    assert consumption["attempt_id"] == ATTEMPT_ID
    assert consumption["epoch_id"] == EPOCH_ID
    assert "consumed_at" in consumption


# ── T4  spawn record properties ───────────────────────────────────────────────
def test_a4_g2_t4_spawn_properties(spawn):
    assert spawn["contract"] == "p7-supervised-child/v1"
    assert spawn["status"] == "STILL_RUNNING"
    assert spawn["child_pid"] is not None
    assert spawn["spawn_attempt_count"] == 1
    assert spawn["restart_attempt_count"] == 0
    assert spawn["request"]["spawn_budget"] == 1
    assert spawn["request"]["restart_budget"] == 0
