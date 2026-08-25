"""Tests for MC7-A — Runtime Universe Binding Contract."""
import hashlib
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

MC7_CONTRACT = REPO_ROOT / "model_coverage_mc7_runtime_binding_contract.json"
MC7_REPORT   = REPO_ROOT / "model_coverage_mc7_runtime_binding_report.json"
MC6_REGISTRY = REPO_ROOT / "model_coverage_mc6_inference_registry.json"
MC1_CONTRACT = REPO_ROOT / "model_coverage_mc1_contract.json"

EXPECTED_AUTHORIZED = sorted(["BTC", "ETH", "BNB", "DOGE", "IOTA", "NEAR", "SOL", "TRX", "ZEC"])
EXPECTED_DISABLED_COUNT = 13


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(scope="module")
def contract() -> dict:
    return json.loads(MC7_CONTRACT.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def report() -> dict:
    return json.loads(MC7_REPORT.read_text(encoding="utf-8"))


# ── SHA sidecar validity ─────────────────────────────────────────────────────

def test_mc7_contract_sha_sidecar_valid() -> None:
    sha_path = Path(str(MC7_CONTRACT) + ".sha256")
    assert sha_path.exists()
    digest, rel = sha_path.read_text().strip().split()
    assert _sha256(REPO_ROOT / rel) == digest


def test_mc7_report_sha_sidecar_valid() -> None:
    sha_path = Path(str(MC7_REPORT) + ".sha256")
    assert sha_path.exists()
    digest, rel = sha_path.read_text().strip().split()
    assert _sha256(REPO_ROOT / rel) == digest


# ── Contract structure ────────────────────────────────────────────────────────

def test_mc7_contract_canonical_universe_22(contract: dict) -> None:
    assert contract["canonical_universe_count"] == 22
    assert len(contract["canonical_universe"]) == 22


def test_mc7_contract_authorized_routes_9(contract: dict) -> None:
    assert contract["authorized_routes_count"] == 9
    assert sorted(contract["authorized_routes"]) == EXPECTED_AUTHORIZED


def test_mc7_contract_disabled_13(contract: dict) -> None:
    assert contract["inference_disabled_count"] == EXPECTED_DISABLED_COUNT


def test_mc7_contract_effective_equals_authorized(contract: dict) -> None:
    assert sorted(contract["effective_runtime_universe"]) == sorted(contract["authorized_routes"])
    assert contract["effective_runtime_universe_count"] == contract["authorized_routes_count"]


def test_mc7_contract_policies(contract: dict) -> None:
    assert contract["binding_policy"] == "AUTHORIZED_ROUTES_ONLY"
    assert contract["unknown_symbol_policy"] == "FAIL_CLOSED"
    assert contract["disabled_symbol_policy"] == "REJECT_BEFORE_DISPATCH"


def test_mc7_contract_sources_inventoried(contract: dict) -> None:
    sources = contract["runtime_symbol_sources"]
    assert len(sources) >= 8  # at least 8 runtime paths identified
    for src in sources:
        assert "path" in src
        assert "source_type" in src


def test_mc7_contract_authorized_disabled_disjoint(contract: dict) -> None:
    auth = set(contract["authorized_routes"])
    disabled = set(contract["inference_disabled_symbols"])
    assert auth & disabled == set()


def test_mc7_contract_union_equals_canonical(contract: dict) -> None:
    auth = set(contract["authorized_routes"])
    disabled = set(contract["inference_disabled_symbols"])
    canonical = set(contract["canonical_universe"])
    assert auth | disabled == canonical


# ── Report gates ─────────────────────────────────────────────────────────────

def test_mc7_report_overall_pass(report: dict) -> None:
    assert report["overall_verdict"] == "PASS"


def test_mc7_report_all_gates_pass(report: dict) -> None:
    for gate_id, gate in report["gates"].items():
        assert gate["result"] == "PASS", f"Gate {gate_id} failed: {gate}"


# ── Cross-consistency with MC6 registry ─────────────────────────────────────

def test_mc7_contract_matches_mc6_registry(contract: dict) -> None:
    registry = json.loads(MC6_REGISTRY.read_text(encoding="utf-8"))
    registry_symbols = sorted(r["symbol"] for r in registry["routes"])
    assert sorted(contract["authorized_routes"]) == registry_symbols


# ── Cross-consistency with MC1 canonical universe ────────────────────────────

def test_mc7_contract_canonical_matches_mc1(contract: dict) -> None:
    mc1 = json.loads(MC1_CONTRACT.read_text(encoding="utf-8"))
    assert contract["canonical_universe"] == mc1["canonical_symbols"]
    assert contract["canonical_universe_count"] == mc1["canonical_symbol_count"]
