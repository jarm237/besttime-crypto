"""Tests for MC7-I — Governance Seal.

Verifies that the final verdict artifact is consistent, all verdicts are PASS,
and cross-consistency with prior MC artifacts is maintained.
"""
import hashlib
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

MC7_VERDICT  = REPO_ROOT / "model_coverage_mc7_final_verdict.json"
MC7_CONTRACT = REPO_ROOT / "model_coverage_mc7_runtime_binding_contract.json"
MC7_STARTUP  = REPO_ROOT / "model_coverage_mc7_startup_preflight.json"
MC6_REGISTRY = REPO_ROOT / "model_coverage_mc6_inference_registry.json"
MC1_CONTRACT = REPO_ROOT / "model_coverage_mc1_contract.json"

EXPECTED_AUTHORIZED = sorted(["BTC", "ETH", "BNB", "DOGE", "IOTA", "NEAR", "SOL", "TRX", "ZEC"])
EXPECTED_DISABLED_COUNT = 13


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(scope="module")
def verdict() -> dict:
    return json.loads(MC7_VERDICT.read_text(encoding="utf-8"))


# ── SHA sidecar ───────────────────────────────────────────────────────────────

def test_mc7_verdict_sha_sidecar_valid() -> None:
    sha_path = Path(str(MC7_VERDICT) + ".sha256")
    assert sha_path.exists()
    digest, rel = sha_path.read_text().strip().split()
    assert _sha256(REPO_ROOT / rel) == digest


# ── Verdict = CLOSED ──────────────────────────────────────────────────────────

def test_mc7_verdict_is_closed(verdict: dict) -> None:
    assert verdict["mc7_verdict"] == "CLOSED"


def test_mc7_all_top_level_verdicts_pass(verdict: dict) -> None:
    verdicts_to_check = [
        "legacy_parity",
        "new_route_parity",
        "runtime_symbol_binding",
        "startup_compatibility",
        "disabled_symbol_protection",
        "artifact_integrity",
        "schema_compatibility",
        "runtime_path_audit",
        "regression",
    ]
    for field in verdicts_to_check:
        assert verdict[field] == "PASS", f"verdict['{field}'] is not PASS: {verdict.get(field)}"


def test_mc7_all_gate_sections_pass(verdict: dict) -> None:
    for gate_id, gate in verdict["gates"].items():
        assert gate["result"] == "PASS", f"Gate {gate_id} is not PASS: {gate}"


# ── Counts ────────────────────────────────────────────────────────────────────

def test_mc7_verdict_canonical_universe_22(verdict: dict) -> None:
    assert verdict["canonical_universe"] == 22


def test_mc7_verdict_authorized_routes_9(verdict: dict) -> None:
    assert verdict["authorized_routes"] == 9
    assert sorted(verdict["authorized_symbols"]) == EXPECTED_AUTHORIZED


def test_mc7_verdict_disabled_13(verdict: dict) -> None:
    assert verdict["inference_disabled"] == EXPECTED_DISABLED_COUNT
    assert len(verdict["disabled_symbols"]) == EXPECTED_DISABLED_COUNT


def test_mc7_verdict_effective_universe_9(verdict: dict) -> None:
    assert verdict["effective_runtime_universe"] == 9


def test_mc7_verdict_unsupported_enabled_zero(verdict: dict) -> None:
    assert verdict["unsupported_enabled_symbols"] == 0


def test_mc7_regression_gate_pass_count(verdict: dict) -> None:
    g = verdict["gates"]["MC7-G"]
    assert g["failures"] == 0
    assert g["regression_suite_passed"] >= 400
    assert g["mc7_specific_tests_passed"] == 18
    assert g["total_tests_passed"] == 422


# ── Cross-consistency with prior artifacts ────────────────────────────────────

def test_mc7_verdict_authorized_matches_mc7_contract(verdict: dict) -> None:
    contract = json.loads(MC7_CONTRACT.read_text(encoding="utf-8"))
    assert sorted(verdict["authorized_symbols"]) == sorted(contract["authorized_routes"])


def test_mc7_verdict_authorized_matches_mc6_registry(verdict: dict) -> None:
    registry = json.loads(MC6_REGISTRY.read_text(encoding="utf-8"))
    registry_symbols = sorted(r["symbol"] for r in registry["routes"])
    assert sorted(verdict["authorized_symbols"]) == registry_symbols


def test_mc7_verdict_canonical_matches_mc1(verdict: dict) -> None:
    mc1 = json.loads(MC1_CONTRACT.read_text(encoding="utf-8"))
    assert verdict["canonical_universe"] == mc1["canonical_symbol_count"]


def test_mc7_verdict_disabled_matches_contract(verdict: dict) -> None:
    contract = json.loads(MC7_CONTRACT.read_text(encoding="utf-8"))
    assert sorted(verdict["disabled_symbols"]) == sorted(contract["inference_disabled_symbols"])


def test_mc7_startup_preflight_passed(verdict: dict) -> None:
    startup = json.loads(MC7_STARTUP.read_text(encoding="utf-8"))
    assert startup["overall_verdict"] == "PASS"
    assert sorted(startup["authorized_symbols"]) == sorted(verdict["authorized_symbols"])


# ── Live system consistency ───────────────────────────────────────────────────

def test_live_get_analysis_universe_matches_verdict(verdict: dict) -> None:
    import os
    env_backup = os.environ.pop("BTC_ANALYSIS_UNIVERSE", None)
    try:
        from btc_scraper.core.config import get_analysis_universe
        universe = get_analysis_universe()
        assert sorted(universe) == sorted(verdict["authorized_symbols"])
    finally:
        if env_backup is not None:
            os.environ["BTC_ANALYSIS_UNIVERSE"] = env_backup


def test_live_runtime_symbol_policy_enabled_matches_verdict(verdict: dict) -> None:
    from btc_scraper.ml_engine.runtime_symbol_policy import runtime_symbol_policy
    enabled = runtime_symbol_policy.enabled_symbols()
    assert sorted(enabled) == sorted(verdict["authorized_symbols"])


def test_live_disabled_symbols_all_rejected(verdict: dict) -> None:
    from btc_scraper.ml_engine.runtime_symbol_policy import (
        RuntimeSymbolNotAuthorized,
        runtime_symbol_policy,
    )
    for sym in verdict["disabled_symbols"]:
        with pytest.raises(RuntimeSymbolNotAuthorized):
            runtime_symbol_policy.assert_enabled(sym)
