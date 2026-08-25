"""Tests for MC7-D — Runtime Startup Compatibility Preflight."""
import hashlib
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

MC7_STARTUP  = REPO_ROOT / "model_coverage_mc7_startup_preflight.json"
MC6_REGISTRY = REPO_ROOT / "model_coverage_mc6_inference_registry.json"

CANONICAL_FEATURES = ("return_8", "return_32", "return_72", "abs_move_72")
EXPECTED_AUTHORIZED = sorted(["BTC", "ETH", "BNB", "DOGE", "IOTA", "NEAR", "SOL", "TRX", "ZEC"])


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(scope="module")
def startup() -> dict:
    return json.loads(MC7_STARTUP.read_text(encoding="utf-8"))


# ── SHA sidecar ───────────────────────────────────────────────────────────────

def test_startup_preflight_sha_sidecar_valid() -> None:
    sha_path = Path(str(MC7_STARTUP) + ".sha256")
    assert sha_path.exists()
    digest, rel = sha_path.read_text().strip().split()
    assert _sha256(REPO_ROOT / rel) == digest


# ── Overall verdict ───────────────────────────────────────────────────────────

def test_startup_preflight_overall_pass(startup: dict) -> None:
    assert startup["overall_verdict"] == "PASS"


def test_startup_preflight_all_gates_pass(startup: dict) -> None:
    for gate_id, gate in startup["gates"].items():
        assert gate["result"] == "PASS", f"Gate {gate_id} failed: {gate}"


# ── Specific gate assertions ──────────────────────────────────────────────────

def test_startup_preflight_authorized_count_9(startup: dict) -> None:
    assert startup["authorized_count"] == 9


def test_startup_preflight_authorized_symbols_exact(startup: dict) -> None:
    assert sorted(startup["authorized_symbols"]) == EXPECTED_AUTHORIZED


def test_startup_preflight_feature_schema_v5(startup: dict) -> None:
    assert tuple(startup["feature_schema"]) == CANONICAL_FEATURES


# ── Live startup simulation ───────────────────────────────────────────────────

def test_startup_get_analysis_universe_returns_9_authorized() -> None:
    import os
    env_backup = os.environ.pop("BTC_ANALYSIS_UNIVERSE", None)
    try:
        from btc_scraper.core.config import get_analysis_universe
        universe = get_analysis_universe()
        assert len(universe) == 9
        assert sorted(universe) == EXPECTED_AUTHORIZED
    finally:
        if env_backup is not None:
            os.environ["BTC_ANALYSIS_UNIVERSE"] = env_backup


def test_startup_registry_has_9_routes() -> None:
    registry = json.loads(MC6_REGISTRY.read_text(encoding="utf-8"))
    assert len(registry["routes"]) == 9


def test_startup_router_resolves_all_9_authorized() -> None:
    from btc_scraper.ml_engine.inference_router import InferenceRouter
    router = InferenceRouter(MC6_REGISTRY, REPO_ROOT)
    for sym in EXPECTED_AUTHORIZED:
        route = router.resolve(sym)
        assert route.symbol == sym


def test_startup_all_routes_have_v5_feature_schema() -> None:
    registry = json.loads(MC6_REGISTRY.read_text(encoding="utf-8"))
    for r in registry["routes"]:
        assert tuple(r.get("feature_schema", [])) == CANONICAL_FEATURES, (
            f"{r['symbol']} has wrong feature schema: {r.get('feature_schema')}"
        )


def test_startup_disabled_symbols_rejected_by_policy() -> None:
    """All 13 disabled symbols must be rejected by RuntimeSymbolPolicy at startup."""
    from btc_scraper.ml_engine.runtime_symbol_policy import (
        RuntimeSymbolNotAuthorized,
        runtime_symbol_policy,
    )
    disabled = [
        "AEVO", "AR", "AVAX", "ENA", "SOPH", "TAO", "TRB", "TRUMP",
        "WLD", "XAUT", "XLM", "XPL", "XRP",
    ]
    for sym in disabled:
        with pytest.raises(RuntimeSymbolNotAuthorized):
            runtime_symbol_policy.assert_enabled(sym)
