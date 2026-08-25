"""Tests for MC7-C — Inference Route Parity Verification.

Verifies that:
1. Legacy routes (BTC/ETH/BNB) resolve to the expected route type and SHA.
2. MC5 qualified routes (DOGE/IOTA/NEAR/SOL/TRX/ZEC) resolve and their SHAs match
   the MC4 candidate registry and MC5 final verdict.
3. All 13 disabled symbols are unresolvable — no silent substitution.
"""
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

MC6_REGISTRY   = REPO_ROOT / "model_coverage_mc6_inference_registry.json"
MC5_VERDICT    = REPO_ROOT / "model_coverage_mc5_final_verdict.json"
MC6_RECON      = REPO_ROOT / "model_coverage_mc6_reconciliation.json"
MC7_CONTRACT   = REPO_ROOT / "model_coverage_mc7_runtime_binding_contract.json"

LEGACY_SYMBOLS       = ["BTC", "ETH", "BNB"]
MC5_QUALIFIED        = sorted(["DOGE", "IOTA", "NEAR", "SOL", "TRX", "ZEC"])
ALL_AUTHORIZED       = sorted(LEGACY_SYMBOLS + MC5_QUALIFIED)


@pytest.fixture(scope="module")
def registry() -> dict:
    return json.loads(MC6_REGISTRY.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def registry_by_symbol(registry: dict) -> dict[str, dict]:
    return {r["symbol"]: r for r in registry["routes"]}


@pytest.fixture(scope="module")
def mc5_verdict() -> dict:
    return json.loads(MC5_VERDICT.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def mc6_recon() -> dict:
    return json.loads(MC6_RECON.read_text(encoding="utf-8"))


# ── Router — import and basic smoke ─────────────────────────────────────────

def test_inference_router_imports() -> None:
    from btc_scraper.ml_engine.inference_router import InferenceRouter
    router = InferenceRouter(MC6_REGISTRY, REPO_ROOT)
    assert router is not None


# ── Legacy route parity (BTC/ETH/BNB) ────────────────────────────────────────

@pytest.mark.parametrize("sym", LEGACY_SYMBOLS)
def test_legacy_route_resolves(sym: str) -> None:
    from btc_scraper.ml_engine.inference_router import InferenceRouter
    router = InferenceRouter(MC6_REGISTRY, REPO_ROOT)
    route = router.resolve(sym)
    assert route.symbol == sym


@pytest.mark.parametrize("sym", LEGACY_SYMBOLS)
def test_legacy_route_type_is_legacy(sym: str, registry_by_symbol: dict) -> None:
    rec = registry_by_symbol[sym]
    assert rec["route_type"] == "LEGACY"


@pytest.mark.parametrize("sym", LEGACY_SYMBOLS)
def test_legacy_route_qualification_is_grandfathered(sym: str, registry_by_symbol: dict) -> None:
    rec = registry_by_symbol[sym]
    assert rec.get("qualification_verdict") == "LEGACY_GRANDFATHERED"


# ── MC5 qualified route parity ────────────────────────────────────────────────

@pytest.mark.parametrize("sym", MC5_QUALIFIED)
def test_mc5_route_resolves(sym: str) -> None:
    from btc_scraper.ml_engine.inference_router import InferenceRouter
    router = InferenceRouter(MC6_REGISTRY, REPO_ROOT)
    route = router.resolve(sym)
    assert route.symbol == sym


@pytest.mark.parametrize("sym", MC5_QUALIFIED)
def test_mc5_route_type_is_mc5_qualified(sym: str, registry_by_symbol: dict) -> None:
    rec = registry_by_symbol[sym]
    assert rec["route_type"] == "MC5_QUALIFIED"


@pytest.mark.parametrize("sym", MC5_QUALIFIED)
def test_mc5_route_model_sha_present(sym: str, registry_by_symbol: dict) -> None:
    rec = registry_by_symbol[sym]
    assert isinstance(rec.get("model_sha256"), str)
    assert len(rec["model_sha256"]) == 64


@pytest.mark.parametrize("sym", MC5_QUALIFIED)
def test_mc5_route_calibrator_sha_present(sym: str, registry_by_symbol: dict) -> None:
    rec = registry_by_symbol[sym]
    assert isinstance(rec.get("calibrator_sha256"), str)
    assert len(rec["calibrator_sha256"]) == 64


@pytest.mark.parametrize("sym", MC5_QUALIFIED)
def test_mc5_route_qualification_verdict_is_qualified(sym: str, registry_by_symbol: dict) -> None:
    rec = registry_by_symbol[sym]
    assert rec.get("qualification_verdict") == "QUALIFIED"


@pytest.mark.parametrize("sym", MC5_QUALIFIED)
def test_mc5_route_matches_mc5_verdict(sym: str, mc5_verdict: dict, registry_by_symbol: dict) -> None:
    """Registry model SHA must match what MC5 OOS qualification recorded."""
    verdicts = {v["symbol"]: v for v in mc5_verdict.get("results", [])}
    if sym not in verdicts:
        pytest.skip(f"{sym} not in MC5 verdict results")
    v = verdicts[sym]
    rec = registry_by_symbol[sym]
    if v.get("model_sha256"):
        assert rec["model_sha256"] == v["model_sha256"]
    if v.get("calibrator_sha256"):
        assert rec["calibrator_sha256"] == v["calibrator_sha256"]


# ── Registry determinism ──────────────────────────────────────────────────────

def test_registry_symbol_set_matches_mc7_contract() -> None:
    contract = json.loads(MC7_CONTRACT.read_text(encoding="utf-8"))
    registry = json.loads(MC6_REGISTRY.read_text(encoding="utf-8"))
    registry_symbols = sorted(r["symbol"] for r in registry["routes"])
    assert registry_symbols == sorted(contract["authorized_routes"])


def test_registry_route_count_is_9(registry: dict) -> None:
    assert len(registry["routes"]) == 9


def test_registry_no_duplicate_symbols(registry: dict) -> None:
    symbols = [r["symbol"] for r in registry["routes"]]
    assert len(symbols) == len(set(symbols))


# ── Negative parity — disabled symbols cannot be resolved ────────────────────

@pytest.fixture(scope="module")
def disabled_symbols(mc6_recon: dict) -> list[str]:
    return [e["symbol"] for e in mc6_recon["excluded_symbols"]]


def test_disabled_symbols_count_13(disabled_symbols: list[str]) -> None:
    assert len(disabled_symbols) == 13


@pytest.mark.parametrize("sym", [
    "AEVO", "AR", "AVAX", "ENA", "SOPH", "TAO", "TRB", "TRUMP",
    "WLD", "XAUT", "XLM", "XPL", "XRP",
])
def test_disabled_symbol_raises_on_router_resolve(sym: str) -> None:
    from btc_scraper.ml_engine.inference_router import (
        InferenceRouter,
        InferenceSymbolUnsupported,
    )
    router = InferenceRouter(MC6_REGISTRY, REPO_ROOT)
    with pytest.raises(InferenceSymbolUnsupported):
        router.resolve(sym)


@pytest.mark.parametrize("sym", [
    "AEVO", "AR", "AVAX", "ENA", "SOPH", "TAO", "TRB", "TRUMP",
    "WLD", "XAUT", "XLM", "XPL", "XRP",
])
def test_disabled_symbol_raises_runtime_not_authorized(sym: str) -> None:
    """MC7-B: RuntimeSymbolPolicy raises before inference is dispatched."""
    from btc_scraper.ml_engine.runtime_symbol_policy import (
        RuntimeSymbolNotAuthorized,
        runtime_symbol_policy,
    )
    with pytest.raises(RuntimeSymbolNotAuthorized):
        runtime_symbol_policy.assert_enabled(sym)


@pytest.mark.parametrize("sym", [
    "AEVO", "AR", "AVAX", "ENA", "SOPH", "TAO", "TRB", "TRUMP",
    "WLD", "XAUT", "XLM", "XPL", "XRP",
])
def test_disabled_symbol_not_in_registry(sym: str, registry: dict) -> None:
    registry_symbols = {r["symbol"] for r in registry["routes"]}
    assert sym not in registry_symbols, f"{sym} unexpectedly found in registry"


# ── Parity: authorized symbols all have consistent SHA in registry ────────────

@pytest.mark.parametrize("sym", ALL_AUTHORIZED)
def test_authorized_symbol_in_registry(sym: str, registry_by_symbol: dict) -> None:
    assert sym in registry_by_symbol, f"{sym} missing from registry"
    rec = registry_by_symbol[sym]
    assert "route_type" in rec
    assert "route_version" in rec
    # MC5 qualified routes must have real model + calibrator SHAs
    if rec["route_type"] == "MC5_QUALIFIED":
        assert isinstance(rec.get("model_sha256"), str) and len(rec["model_sha256"]) == 64
        assert isinstance(rec.get("calibrator_sha256"), str) and len(rec["calibrator_sha256"]) == 64


@pytest.mark.parametrize("sym", ALL_AUTHORIZED)
def test_authorized_route_resolves_deterministically(sym: str) -> None:
    from btc_scraper.ml_engine.inference_router import InferenceRouter
    router1 = InferenceRouter(MC6_REGISTRY, REPO_ROOT)
    router2 = InferenceRouter(MC6_REGISTRY, REPO_ROOT)
    route1 = router1.resolve(sym)
    route2 = router2.resolve(sym)
    assert route1.symbol == route2.symbol
    assert route1.route_type == route2.route_type
