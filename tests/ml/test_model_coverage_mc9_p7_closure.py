"""MC9-C — P7 failure closure matrix tests."""
import hashlib
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CLOSURE_PATH = ROOT / "model_coverage_mc9_p7_failure_closure.json"
CLOSURE_SHA_PATH = ROOT / "model_coverage_mc9_p7_failure_closure.json.sha256"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


@pytest.fixture(scope="module")
def closure():
    assert CLOSURE_PATH.exists(), f"Missing: {CLOSURE_PATH}"
    return json.loads(CLOSURE_PATH.read_bytes())


# ── T1  SHA256 sidecar matches disk ─────────────────────────────────────────
def test_mc9_c_t1_sha256_sidecar():
    assert CLOSURE_SHA_PATH.exists()
    recorded = CLOSURE_SHA_PATH.read_text().strip()
    actual = sha256_file(CLOSURE_PATH)
    assert actual == recorded


# ── T2  P7 R4 failure class is CLOSED ────────────────────────────────────────
def test_mc9_c_t2_p7_r4_closed(closure):
    assert closure["p7_r4_failure_class"] == "CLOSED", (
        f"p7_r4_failure_class = {closure['p7_r4_failure_class']!r}"
    )


# ── T3  SOL coverage gap is CLOSED ───────────────────────────────────────────
def test_mc9_c_t3_sol_gap_closed(closure):
    matrix = closure["failure_matrix"]
    sol_entry = next(
        (e for e in matrix if e["failure_class"] == "INFERENCE_SYMBOL_UNSUPPORTED_SOL"), None
    )
    assert sol_entry is not None, "SOL failure class not documented in matrix"
    assert sol_entry["status"] == "CLOSED", f"SOL status: {sol_entry['status']}"
    assert sol_entry["closure_owner"] == "MC9"


# ── T4  coverage closure invariant: effective==authorized==resolvable==9 ─────
def test_mc9_c_t4_coverage_closure_invariant(closure):
    inv = closure["coverage_closure_invariant"]
    assert inv["effective_runtime_symbols"] == 9
    assert inv["authorized_routes"] == 9
    assert inv["resolvable_release_routes"] == 9
    assert inv["gap"] == []
    assert inv["verdict"] == "CLOSED"


# ── T5  no claim that ALL failure modes are impossible ───────────────────────
def test_mc9_c_t5_no_all_impossible_claim(closure):
    assert closure["all_p7_failure_modes_impossible"] is False


# ── T6  prerequisite classes documented ──────────────────────────────────────
def test_mc9_c_t6_prerequisites_documented(closure):
    prereqs = closure["summary"]["prerequisite_classes"]
    assert "NO_ACTIVE_EVIDENCE_EPOCH" in prereqs
    assert "LIVENESS_NOT_SUSTAINED" in prereqs


# ── T7  overall_verdict PASS ─────────────────────────────────────────────────
def test_mc9_c_t7_overall_pass(closure):
    assert closure["overall_verdict"] == "PASS"


# ── T8  failure matrix has entries for all 3 historical attempts ─────────────
def test_mc9_c_t8_all_attempts_documented(closure):
    matrix = closure["failure_matrix"]
    attempts = {e["attempt"] for e in matrix}
    assert "#1" in attempts, "Attempt #1 not documented"
    assert "#2" in attempts, "Attempt #2 not documented"
    assert "#3" in attempts, "Attempt #3 not documented"
