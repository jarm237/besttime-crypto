"""Tests for MC8-A — Release Construction Contract."""
import hashlib
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

MC8_CONTRACT = REPO_ROOT / "model_coverage_mc8_release_contract.json"
MC8_REPORT   = REPO_ROOT / "model_coverage_mc8_release_contract_report.json"
MC6_REGISTRY = REPO_ROOT / "model_coverage_mc6_inference_registry.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(scope="module")
def contract() -> dict:
    return json.loads(MC8_CONTRACT.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def report() -> dict:
    return json.loads(MC8_REPORT.read_text(encoding="utf-8"))


# ── SHA sidecar validity ─────────────────────────────────────────────────────

def test_mc8_contract_sha_sidecar_valid() -> None:
    sha_path = Path(str(MC8_CONTRACT) + ".sha256")
    assert sha_path.exists()
    digest, rel = sha_path.read_text().strip().split()
    assert _sha256(REPO_ROOT / rel) == digest


def test_mc8_report_sha_sidecar_valid() -> None:
    sha_path = Path(str(MC8_REPORT) + ".sha256")
    assert sha_path.exists()
    digest, rel = sha_path.read_text().strip().split()
    assert _sha256(REPO_ROOT / rel) == digest


# ── Contract Structure ────────────────────────────────────────────────────────

def test_mc8_contract_pinned_commits(contract: dict) -> None:
    assert contract["source_commit"] == "94407d3483bb01eccf0e86882cef258dcbb646e9"
    assert contract["mc6_registry_seal"] == "506ae19ba4d325dacf71cb535d616a82385938d3"


def test_mc8_contract_registry_sha(contract: dict) -> None:
    assert contract["mc6_registry_sha256"] == _sha256(MC6_REGISTRY)


def test_mc8_contract_universe_sizes(contract: dict) -> None:
    assert len(contract["authorized_symbols"]) == 9
    assert len(contract["disabled_symbols"]) == 13


def test_mc8_contract_all_routes_accounted(contract: dict) -> None:
    assert len(contract["model_fingerprints"]) == 9
    assert len(contract["calibrator_fingerprints"]) == 9


# ── Preflight Gates ───────────────────────────────────────────────────────────

def test_mc8_report_overall_pass(report: dict) -> None:
    assert report["overall_verdict"] == "PASS"


def test_mc8_report_all_gates_pass(report: dict) -> None:
    for gate_id, gate in report["gates"].items():
        assert gate["result"] == "PASS", f"Gate {gate_id} failed: {gate}"
