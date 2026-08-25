"""P7 Attempt #4 — A4 Phase E G9/G10/Final Verdict Tests.

Verifies the outputs of Phase E reports.
"""
import hashlib
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

CYCLE_PATH   = ROOT / "p7_attempt4_first_cycle_report.json"
LINEAGE_PATH = ROOT / "p7_attempt4_lineage_report.json"
VERDICT_PATH = ROOT / "p7_attempt4_final_activation_verdict.json"


def sha256_file(path: Path) -> str:
    d = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            d.update(block)
    return d.hexdigest()


@pytest.fixture(scope="module")
def cycle():
    assert CYCLE_PATH.exists()
    return json.loads(CYCLE_PATH.read_bytes())


@pytest.fixture(scope="module")
def lineage():
    assert LINEAGE_PATH.exists()
    return json.loads(LINEAGE_PATH.read_bytes())


@pytest.fixture(scope="module")
def verdict():
    assert VERDICT_PATH.exists()
    return json.loads(VERDICT_PATH.read_bytes())


# ── T1  SHA256 sidecars valid ─────────────────────────────────────────────────
def test_a4_e_t1_sidecars_valid():
    for p in (CYCLE_PATH, LINEAGE_PATH, VERDICT_PATH):
        sidecar = Path(str(p) + ".sha256")
        assert sidecar.exists()
        assert sha256_file(p) == sidecar.read_text().strip()


# ── T2  first cycle report properties ─────────────────────────────────────────
def test_a4_e_t2_cycle_properties(cycle):
    assert cycle["overall_verdict"] == "FAIL"
    assert cycle["first_cycle_completed"] is False
    assert cycle["error_observed"] == "inference_symbol_unsupported:DOGE"


# ── T3  lineage report properties ─────────────────────────────────────────────
def test_a4_e_t3_lineage_properties(lineage):
    assert lineage["overall_verdict"] == "FAIL"
    assert lineage["lineage_records_found"] == 0
    assert lineage["mismatches_found"] is False


# ── T4  final verdict properties ──────────────────────────────────────────────
def test_a4_e_t4_final_verdict(verdict):
    assert verdict["P7_ATTEMPT"] == 4
    assert verdict["AUTHORIZATION"] == "CONSUMED"
    assert verdict["SPAWN_COUNT"] == 1
    assert verdict["RESTART_COUNT"] == 0
    assert verdict["FRESH_EVIDENCE_EPOCH"] == "PASS"
    assert verdict["PROCESS_IDENTITY"] == "PASS"
    assert verdict["RUNNING_RELEASE_IDENTITY"] == "PASS"
    assert verdict["SUSTAINED_LIVENESS"] == "FAIL"
    assert verdict["FIRST_RUNTIME_CYCLE"] == "FAIL"
    assert verdict["ENABLED_SYMBOLS"] == 9
    assert verdict["UNSUPPORTED_ENABLED"] == 6
    assert verdict["DISABLED_SYMBOL_LEAKS"] == 0
    assert verdict["P7_ACTIVATION"] == "FAIL"
    assert verdict["EVIDENCE_ACCUMULATION"] == "INACTIVE"
