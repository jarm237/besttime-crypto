"""P7 Attempt #4 — A4-G8 identity and liveness test cases.

Verifies the results of G8 identity readback, release readback, and liveness.
"""
import hashlib
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

IDENTITY_PATH = ROOT / "p7_attempt4_identity_readback.json"
RELEASE_PATH  = ROOT / "p7_attempt4_release_readback.json"
LIVENESS_PATH = ROOT / "p7_attempt4_liveness_report.json"


def sha256_file(path: Path) -> str:
    d = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            d.update(block)
    return d.hexdigest()


@pytest.fixture(scope="module")
def identity():
    assert IDENTITY_PATH.exists()
    return json.loads(IDENTITY_PATH.read_bytes())


@pytest.fixture(scope="module")
def release():
    assert RELEASE_PATH.exists()
    return json.loads(RELEASE_PATH.read_bytes())


@pytest.fixture(scope="module")
def liveness():
    assert LIVENESS_PATH.exists()
    return json.loads(LIVENESS_PATH.read_bytes())


# ── T1  SHA256 sidecars valid ─────────────────────────────────────────────────
def test_a4_g8_t1_sidecars_valid():
    for p in (IDENTITY_PATH, RELEASE_PATH, LIVENESS_PATH):
        sidecar = Path(str(p) + ".sha256")
        assert sidecar.exists()
        assert sha256_file(p) == sidecar.read_text().strip()


# ── T2  G8-A passes process identity properties ───────────────────────────────
def test_a4_g8_t2_identity_properties(identity):
    assert identity["overall_verdict"] == "PASS"
    for gate_id, gate in identity["gates"].items():
        assert gate["result"] == "PASS"


# ── T3  G8-B passes release readback properties ───────────────────────────────
def test_a4_g8_t3_release_properties(release):
    assert release["overall_verdict"] == "PASS"
    for gate_id, gate in release["gates"].items():
        assert gate["result"] == "PASS"


# ── T4  G8-C fails and has correct verdict ────────────────────────────────────
def test_a4_g8_t4_liveness_failure(liveness):
    assert liveness["overall_verdict"] == "FAIL"
    assert liveness["g8_evaluation"]["runtime_activation"] == "ACTIVATION_NOT_SUSTAINED"
    assert liveness["child_exited_before_liveness"] is True
    assert liveness["semantic_progress_observed"] is False
