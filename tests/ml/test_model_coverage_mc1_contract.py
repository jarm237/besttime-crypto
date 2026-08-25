import json
from pathlib import Path

import pytest

from btc_scraper.core.config import DEFAULT_ANALYSIS_UNIVERSE


REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = REPO_ROOT / "model_coverage_mc1_contract.json"
REGISTRY_PATH = REPO_ROOT / "model_coverage_mc1_symbol_registry.json"


@pytest.fixture(scope="module")
def contract() -> dict:
    return json.loads(CONTRACT_PATH.read_text())


@pytest.fixture(scope="module")
def registry() -> dict:
    return json.loads(REGISTRY_PATH.read_text())


def test_mc1_canonical_list_is_frozen_and_deterministic(contract: dict) -> None:
    symbols = contract["canonical_symbols"]

    assert contract["contract"] == "model-coverage/v1"
    assert contract["canonical_symbol_count"] == 22
    assert symbols == list(DEFAULT_ANALYSIS_UNIVERSE)
    assert len(symbols) == len(set(symbols))


def test_mc1_support_definition_requires_more_than_metadata(contract: dict) -> None:
    required = set(contract["supported_symbol_definition"]["required_predicates"])

    assert contract["supported_symbol_definition"]["metadata_only_support"] is False
    assert contract["supported_symbol_definition"]["schema_compatibility_only_support"] is False
    assert {
        "symbol_in_canonical_symbols",
        "explicit_route_exists",
        "artifact_identity_resolves",
        "feature_schema_identity_resolves",
        "preprocessing_identity_resolves",
        "training_data_provenance_known",
        "calibration_semantics_explicit",
        "bounded_inference_smoke_passes",
    }.issubset(required)


def test_mc1_fail_closed_and_forbidden_semantics_are_frozen(contract: dict) -> None:
    forbidden = contract["forbidden_semantics"]

    assert contract["fail_closed_policy"]["unknown_symbol"] == "inference_symbol_unsupported:<symbol>"
    assert contract["fail_closed_policy"]["unsupported_canonical_symbol"] == "explicit_coverage_failure"
    assert contract["fail_closed_policy"]["pre_semantic_failure"] is True
    assert forbidden["implicit_fallback"] == "FORBIDDEN"
    assert forbidden["silent_skip"] == "FORBIDDEN"
    assert forbidden["universe_reduction"] == "FORBIDDEN"
    assert forbidden["metadata_only_support"] == "FORBIDDEN"
    assert forbidden["paper_activation"] == "FORBIDDEN"
    assert forbidden["authorization_4"] == "FORBIDDEN"
    assert forbidden["attempt_4"] == "FORBIDDEN"


def test_mc1_shared_artifact_policy_rejects_schema_only_support(contract: dict) -> None:
    policy = contract["shared_artifact_policy"]

    assert policy["allowed"] is True
    assert "training evidence covers each symbol in the shared set" in policy["conditions"]
    assert "validation evidence covers each symbol in the shared set" in policy["conditions"]
    assert policy["forbidden_claim"] == "A shared feature schema implies shared model coverage."


def test_mc1_symbol_registry_is_complete(registry: dict) -> None:
    entries = registry["symbols"]
    symbols = [entry["symbol"] for entry in entries]

    assert registry["contract"] == "model-coverage/v1"
    assert symbols == list(DEFAULT_ANALYSIS_UNIVERSE)
    assert len(entries) == 22
    assert len(symbols) == len(set(symbols))
    assert all(entry["canonical"] for entry in entries)
    assert all(entry["runtime_enabled"] for entry in entries)
    assert all(entry["artifact_declared"] for entry in entries)


def test_mc1_existing_routes_are_recognized(registry: dict) -> None:
    by_symbol = {entry["symbol"]: entry for entry in registry["symbols"]}

    assert {
        symbol for symbol, entry in by_symbol.items() if entry["actual_route_exists"]
    } == {"BTC", "ETH", "BNB"}
    for symbol in ("BTC", "ETH", "BNB"):
        entry = by_symbol[symbol]
        assert entry["coverage_state"] == "EXISTING_ROUTE"
        assert entry["route_identity"] == f"V5FilterModelClassifier.model_params.{symbol}"
        assert entry["artifact_identity"]


def test_mc1_metadata_only_symbols_are_not_supported(registry: dict) -> None:
    metadata_only = [
        entry for entry in registry["symbols"]
        if entry["artifact_declared"] and not entry["actual_route_exists"]
    ]

    assert len(metadata_only) == 19
    assert {entry["coverage_state"] for entry in metadata_only} == {"MISSING_ROUTE"}
    assert all(entry["route_identity"] is None for entry in metadata_only)
    assert all(entry["artifact_identity"] is None for entry in metadata_only)


def test_mc1_registry_summary_matches_route_gap(registry: dict) -> None:
    summary = registry["summary"]

    assert summary["canonical_count"] == 22
    assert summary["runtime_enabled_count"] == 22
    assert summary["artifact_declared_count"] == 22
    assert summary["actual_route_count"] == 3
    assert summary["missing_route_count"] == 19
    assert summary["metadata_only_count"] == 19
    assert registry["verdict"] == "MC1_SYMBOL_REGISTRY_COMPLETE_ROUTE_GAP_RECORDED"


def test_mc1_exit_gate_closes_without_runtime_work(contract: dict) -> None:
    gate = contract["mc1_exit_gate"]

    assert gate["MC1-C1_CANONICAL_UNIVERSE_FROZEN"] == "PASS"
    assert gate["MC1-C2_SUPPORT_DEFINITION_FROZEN"] == "PASS"
    assert gate["MC1-C3_FAIL_CLOSED_POLICY"] == "PASS"
    assert gate["MC1-C4_SHARED_ARTIFACT_POLICY"] == "PASS"
    assert gate["MC1-C5_SYMBOL_REGISTRY_COMPLETE"] == "PASS"
    assert gate["MC1"] == "CLOSED"
    assert gate["MC2"] == "READY_TO_START"
    assert contract["training"] == "NOT_STARTED"
    assert contract["artifact_build"] == "NOT_STARTED"
    assert contract["routing_changes"] == "NOT_STARTED"
    assert contract["runtime_changes"] == "NONE"
