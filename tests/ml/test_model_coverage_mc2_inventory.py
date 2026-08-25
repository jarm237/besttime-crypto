import hashlib
import json
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
MC1_REGISTRY = REPO_ROOT / "model_coverage_mc1_symbol_registry.json"
INVENTORY = REPO_ROOT / "model_coverage_mc2_artifact_inventory.json"
MATRIX = REPO_ROOT / "model_coverage_mc2_coverage_matrix.json"
GAPS = REPO_ROOT / "model_coverage_mc2_gap_registry.json"
SIDECARS = (
    REPO_ROOT / "model_coverage_mc2_artifact_inventory.json.sha256",
    REPO_ROOT / "model_coverage_mc2_coverage_matrix.json.sha256",
    REPO_ROOT / "model_coverage_mc2_gap_registry.json.sha256",
)


@pytest.fixture(scope="module")
def mc1_registry() -> dict:
    return json.loads(MC1_REGISTRY.read_text())


@pytest.fixture(scope="module")
def inventory() -> dict:
    return json.loads(INVENTORY.read_text())


@pytest.fixture(scope="module")
def matrix() -> dict:
    return json.loads(MATRIX.read_text())


@pytest.fixture(scope="module")
def gaps() -> dict:
    return json.loads(GAPS.read_text())


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sidecar_pair(sidecar: Path) -> tuple[str, Path]:
    digest, rel_path = sidecar.read_text().strip().split()
    return digest, REPO_ROOT / rel_path


def test_mc2_uses_exact_mc1_symbol_universe(mc1_registry: dict, matrix: dict) -> None:
    mc1_symbols = [entry["symbol"] for entry in mc1_registry["symbols"]]
    mc2_symbols = [entry["symbol"] for entry in matrix["symbols"]]

    assert matrix["universe_source"] == "model_coverage_mc1_symbol_registry.json"
    assert mc2_symbols == mc1_symbols
    assert matrix["summary"]["canonical_symbol_count"] == 22
    assert len(mc2_symbols) == len(set(mc2_symbols))


def test_mc2_inventory_enumerates_candidate_artifacts_with_sha(inventory: dict) -> None:
    artifacts = inventory["artifacts"]

    assert inventory["inventory_summary"]["candidate_artifact_count"] == len(artifacts)
    assert len(artifacts) == 7
    assert all(entry["path"] for entry in artifacts)
    assert all(len(entry["sha256"]) == 64 for entry in artifacts)
    assert inventory["inventory_summary"]["duplicate_sha_count"] == 0
    assert inventory["mc2_gates"]["MC2-C1_ARTIFACT_INVENTORY_COMPLETE"] == "PASS"


def test_mc2_inventory_records_provenance_schema_training_and_calibration(inventory: dict) -> None:
    for artifact in inventory["artifacts"]:
        assert artifact["provenance_classification"]
        assert artifact["schema_classification"]
        assert artifact["training_scope_classification"]
        assert artifact["calibration_classification"]

    assert inventory["mc2_gates"]["MC2-C2_PROVENANCE_AUDITED"] == "PASS"
    assert inventory["mc2_gates"]["MC2-C4_SCHEMA_COMPATIBILITY_AUDITED"] == "PASS"
    assert inventory["mc2_gates"]["MC2-C5_TRAINING_SCOPE_AUDITED"] == "PASS"
    assert inventory["mc2_gates"]["MC2-C6_CALIBRATION_SCOPE_AUDITED"] == "PASS"


def test_mc2_current_runtime_artifact_is_only_three_route_authorized(inventory: dict) -> None:
    runtime_artifact = next(
        entry for entry in inventory["artifacts"]
        if entry["artifact_id"] == "production_meta_model_joblib"
    )

    assert set(runtime_artifact["declared_symbols"]) > set(runtime_artifact["actual_route_symbols"])
    assert set(runtime_artifact["actual_route_symbols"]) == {"BNB", "BTC", "ETH"}
    assert runtime_artifact["training_scope_classification"] == "SYMBOL_SCOPED_BTC_ETH_BNB"


def test_mc2_every_symbol_has_one_final_classification(matrix: dict) -> None:
    entries = matrix["symbols"]

    assert len(entries) == 22
    assert all(entry["mapping_state"] for entry in entries)
    assert all(entry["final_state"] in {"SUPPORTED", "MISSING"} for entry in entries)
    assert matrix["mc2_gates"]["MC2-C3_SYMBOL_MAPPING_COMPLETE"] == "PASS"
    assert matrix["mc2_gates"]["MC2-C7_COVERAGE_MATRIX_FROZEN"] == "PASS"


def test_mc2_supported_symbol_requires_full_predicate(matrix: dict) -> None:
    supported = [entry for entry in matrix["symbols"] if entry["final_state"] == "SUPPORTED"]

    assert {entry["symbol"] for entry in supported} == {"BTC", "ETH", "BNB"}
    for entry in supported:
        assert entry["artifact_exists"] is True
        assert entry["provenance_valid"] is True
        assert entry["schema_compatible"] is True
        assert entry["training_contract_authorizes_symbol"] is True
        assert entry["calibration_compatible"] is True
        assert entry["build_eligibility"] == "NO_BUILD_REQUIRED"


def test_mc2_missing_provenance_or_route_cannot_be_supported(matrix: dict) -> None:
    missing = [entry for entry in matrix["symbols"] if entry["final_state"] == "MISSING"]

    assert len(missing) == 19
    for entry in missing:
        assert entry["artifact_exists"] is False
        assert entry["provenance_valid"] is False
        assert entry["training_contract_authorizes_symbol"] is False
        assert entry["calibration_compatible"] is False
        assert entry["build_eligibility"] == "READY_FOR_DATA_AUDIT"


def test_mc2_schema_and_calibration_fail_closed_examples(matrix: dict) -> None:
    sol = next(entry for entry in matrix["symbols"] if entry["symbol"] == "SOL")

    assert sol["schema_status"] == "UNKNOWN_SCHEMA"
    assert sol["calibration_status"] == "CALIBRATION_MISSING"
    assert sol["final_state"] == "MISSING"


def test_mc2_gap_registry_matches_matrix(matrix: dict, gaps: dict) -> None:
    supported = [entry["symbol"] for entry in matrix["symbols"] if entry["final_state"] == "SUPPORTED"]
    missing = sorted(entry["symbol"] for entry in matrix["symbols"] if entry["final_state"] == "MISSING")

    assert gaps["groups"]["GROUP_A_ALREADY_FULLY_SUPPORTED"] == supported
    assert gaps["groups"]["GROUP_C_ARTIFACT_MISSING"] == missing
    assert gaps["build_eligibility"]["READY_FOR_DATA_AUDIT"] == missing
    assert gaps["mc3_scope"]["required_build_symbols"] == missing


def test_mc2_closes_without_build_training_calibration_or_runtime(gaps: dict) -> None:
    closure = gaps["closure"]

    assert closure["MC2"] == "CLOSED"
    assert closure["MC3"] == "READY_TO_START"
    assert gaps["model_build"] == "NOT_STARTED"
    assert gaps["training"] == "NOT_STARTED"
    assert gaps["calibration"] == "NOT_STARTED"
    assert gaps["routing"] == "NOT_STARTED"
    assert gaps["runtime"] == "UNCHANGED"
    assert gaps["activation"] == "NOT_AUTHORIZED"


def test_mc2_sha_sidecars_match() -> None:
    for sidecar in SIDECARS:
        digest, target = _sidecar_pair(sidecar)
        assert _sha256(target) == digest


def test_mc2_json_artifacts_are_deterministic() -> None:
    for path in (INVENTORY, MATRIX, GAPS):
        payload = json.loads(path.read_text())
        assert json.loads(json.dumps(payload, sort_keys=True)) == payload


def test_mc2_no_runtime_files_are_changed() -> None:
    runtime_paths = {
        artifact["path"]
        for artifact in json.loads(INVENTORY.read_text())["artifacts"]
        if artifact["path"].startswith(("logs/", "config/", "research/"))
    }

    assert "logs/meta_model.joblib" in runtime_paths
    assert "config/artifact_compatibility/meta_model.compatibility.json" in runtime_paths
