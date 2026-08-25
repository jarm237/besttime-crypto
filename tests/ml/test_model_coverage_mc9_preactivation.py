"""MC9-D — P7 pre-activation preflight tests."""
import hashlib
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
REPORT_PATH = ROOT / "model_coverage_mc9_p7_preactivation_report.json"
REPORT_SHA_PATH = ROOT / "model_coverage_mc9_p7_preactivation_report.json.sha256"

EXPECTED_LAUNCHER_CONTRACT = "paper-canary-launcher/v1"
EXPECTED_SUPERVISED_CONTRACT = "p7-supervised-child/v1"
EXPECTED_EVIDENCE_SCHEMA = 6


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


@pytest.fixture(scope="module")
def report():
    assert REPORT_PATH.exists(), f"Missing: {REPORT_PATH}"
    return json.loads(REPORT_PATH.read_bytes())


# ── T1  SHA256 sidecar matches disk ─────────────────────────────────────────
def test_mc9_d_t1_sha256_sidecar():
    assert REPORT_SHA_PATH.exists()
    recorded = REPORT_SHA_PATH.read_text().strip()
    actual = sha256_file(REPORT_PATH)
    assert actual == recorded


# ── T2  all 7 gates PASS ─────────────────────────────────────────────────────
def test_mc9_d_t2_all_gates_pass(report):
    gates = report.get("gates", {})
    assert len(gates) == 7, f"Expected 7 gates, got {len(gates)}: {list(gates)}"
    failures = {k: v for k, v in gates.items() if v.get("result") != "PASS"}
    assert not failures, f"Gates not PASS: {failures}"


# ── T3  pinned worktree HEAD exact ────────────────────────────────────────────
def test_mc9_d_t3_pinned_worktree_head(report):
    assert report["pinned_worktree_head"] == "94407d3483bb01eccf0e86882cef258dcbb646e9"
    assert report["pinned_worktree_clean"] is True


# ── T4  inference coverage: 9 routes, 0 failures ─────────────────────────────
def test_mc9_d_t4_inference_coverage(report):
    cov = report["inference_coverage"]
    assert cov["routes_resolved"] == 9
    assert cov["model_load_failures"] == 0
    assert cov["hash_failures"] == 0


# ── T5  launcher contract version correct ────────────────────────────────────
def test_mc9_d_t5_launcher_contract(report):
    tooling = report["supervised_launcher_tooling"]
    assert tooling["launcher_contract_version"] == EXPECTED_LAUNCHER_CONTRACT
    assert tooling["supervised_contract_version"] == EXPECTED_SUPERVISED_CONTRACT


# ── T6  evidence schema version correct ──────────────────────────────────────
def test_mc9_d_t6_evidence_schema(report):
    infra = report.get("evidence_infrastructure", {})
    assert infra.get("runtime_evidence_schema") == EXPECTED_EVIDENCE_SCHEMA
    assert infra.get("evidence_eligible") is False


# ── T7  spawn controls: LaunchRequest and LauncherContractError present ───────
def test_mc9_d_t7_spawn_controls(report):
    spawn = report.get("spawn_controls", {})
    assert spawn.get("LaunchRequest_exists") is True
    assert spawn.get("LauncherContractError_exists") is True
    assert spawn.get("LAUNCHER_CONTRACT_VERSION") == EXPECTED_LAUNCHER_CONTRACT


# ── T8  no ACTIVE epochs ──────────────────────────────────────────────────────
def test_mc9_d_t8_no_active_epochs(report):
    assert report["no_active_epochs"] is True
    assert report["active_epochs_found"] == []


# ── T9  fresh epoch required, no activation performed ────────────────────────
def test_mc9_d_t9_no_activation_performed(report):
    assert report["fresh_evidence_epoch_required"] is True
    assert report["runtime_activation_performed"] is False


# ── T10  overall_verdict PASS ────────────────────────────────────────────────
def test_mc9_d_t10_overall_pass(report):
    assert report["overall_verdict"] == "PASS"
