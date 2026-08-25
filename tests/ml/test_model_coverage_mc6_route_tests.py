"""Tests for MC6-D — Route Equivalence & Negative Tests.

Four groups:
  1. Legacy preservation (BTC/ETH/BNB unchanged)
  2. New MC5 coverage (DOGE, IOTA, NEAR, SOL, TRX, ZEC)
  3. Negative routing (unknown, missing, hash mismatch, schema, unqualified)
  4. Determinism (same registry => same route)
"""
import json
import hashlib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MC6_INF_REGISTRY   = REPO_ROOT / "model_coverage_mc6_inference_registry.json"
MC6_RECONCILIATION = REPO_ROOT / "model_coverage_mc6_reconciliation.json"
MC4_REGISTRY       = REPO_ROOT / "model_coverage_mc4_candidate_registry.json"
MC5_QUAL_REG       = REPO_ROOT / "model_coverage_mc5_qualification_registry.json"
MC5_CAL_RUNS       = REPO_ROOT / "model_coverage_mc5_calibration_runs.json"

from btc_scraper.ml_engine.inference_router import (
    InferenceRouter,
    InferenceSymbolUnsupported,
)


@pytest.fixture(scope="module")
def router() -> InferenceRouter:
    return InferenceRouter(MC6_INF_REGISTRY, REPO_ROOT)


# ═══════════════════════════════════════════════════════════════════════════
# GROUP 1: Legacy preservation
# ═══════════════════════════════════════════════════════════════════════════

class TestLegacyPreservation:

    def test_btc_route_resolves(self, router: InferenceRouter) -> None:
        route = router.resolve("BTC")
        assert route.route_type == "LEGACY"
        assert route.qualification_verdict == "LEGACY_GRANDFATHERED"

    def test_eth_route_resolves(self, router: InferenceRouter) -> None:
        route = router.resolve("ETH")
        assert route.route_type == "LEGACY"

    def test_bnb_route_resolves(self, router: InferenceRouter) -> None:
        route = router.resolve("BNB")
        assert route.route_type == "LEGACY"

    def test_legacy_routes_have_correct_schema(self, router: InferenceRouter) -> None:
        for sym in ["BTC", "ETH", "BNB"]:
            route = router.resolve(sym)
            assert route.feature_schema == ["return_8", "return_32", "return_72", "abs_move_72"]


# ═══════════════════════════════════════════════════════════════════════════
# GROUP 2: New MC5 coverage
# ═══════════════════════════════════════════════════════════════════════════

MC5_QUALIFIED = ["DOGE", "IOTA", "NEAR", "SOL", "TRX", "ZEC"]


class TestNewCoverage:

    @pytest.mark.parametrize("symbol", MC5_QUALIFIED)
    def test_mc5_symbol_resolves(self, router: InferenceRouter, symbol: str) -> None:
        route = router.resolve(symbol)
        assert route.route_type == "MC5_QUALIFIED"
        assert route.qualification_verdict == "QUALIFIED"

    @pytest.mark.parametrize("symbol", MC5_QUALIFIED)
    def test_mc5_artifacts_exist(self, router: InferenceRouter, symbol: str) -> None:
        route = router.resolve(symbol)
        assert route.model_artifact_path is not None
        assert route.model_artifact_path.exists()
        assert route.calibrator_artifact_path is not None
        assert route.calibrator_artifact_path.exists()

    @pytest.mark.parametrize("symbol", MC5_QUALIFIED)
    def test_mc5_model_sha_matches_mc4(self, router: InferenceRouter, symbol: str) -> None:
        route = router.resolve(symbol)
        mc4 = json.loads(MC4_REGISTRY.read_text(encoding="utf-8"))
        mc4_entry = next(e for e in mc4["candidates"] if e["symbol"] == symbol)
        assert route.model_sha256 == mc4_entry["artifact_sha256"]

    @pytest.mark.parametrize("symbol", MC5_QUALIFIED)
    def test_mc5_calibrator_sha_matches_runs(self, router: InferenceRouter, symbol: str) -> None:
        route = router.resolve(symbol)
        cal_runs = json.loads(MC5_CAL_RUNS.read_text(encoding="utf-8"))
        cal_entry = next(e for e in cal_runs["runs"] if e["symbol"] == symbol)
        assert route.calibrator_sha256 == cal_entry["calibrator_sha256"]


# ═══════════════════════════════════════════════════════════════════════════
# GROUP 3: Negative routing
# ═══════════════════════════════════════════════════════════════════════════

REJECTED_SYMBOLS = ["AEVO", "AR", "AVAX", "ENA", "TAO", "TRB", "WLD", "XLM", "XRP"]
NO_CANDIDATE     = ["SOPH", "TRUMP", "XPL"]
BLOCKED          = ["XAUT"]


class TestNegativeRouting:

    @pytest.mark.parametrize("symbol", ["FAKECOIN", "ABC123", ""])
    def test_unknown_symbol_rejected(self, router: InferenceRouter, symbol: str) -> None:
        with pytest.raises(InferenceSymbolUnsupported):
            router.resolve(symbol)

    @pytest.mark.parametrize("symbol", REJECTED_SYMBOLS)
    def test_mc5_rejected_symbol_raises(self, router: InferenceRouter, symbol: str) -> None:
        with pytest.raises(InferenceSymbolUnsupported):
            router.resolve(symbol)

    @pytest.mark.parametrize("symbol", NO_CANDIDATE)
    def test_mc4_skip_symbol_raises(self, router: InferenceRouter, symbol: str) -> None:
        with pytest.raises(InferenceSymbolUnsupported):
            router.resolve(symbol)

    @pytest.mark.parametrize("symbol", BLOCKED)
    def test_mc3_blocked_symbol_raises(self, router: InferenceRouter, symbol: str) -> None:
        with pytest.raises(InferenceSymbolUnsupported):
            router.resolve(symbol)

    def test_all_excluded_symbols_fail_closed(self, router: InferenceRouter) -> None:
        """Every excluded symbol from the reconciliation must raise."""
        recon = json.loads(MC6_RECONCILIATION.read_text(encoding="utf-8"))
        for entry in recon["excluded_symbols"]:
            with pytest.raises(InferenceSymbolUnsupported):
                router.resolve(entry["symbol"])


# ═══════════════════════════════════════════════════════════════════════════
# GROUP 4: Determinism
# ═══════════════════════════════════════════════════════════════════════════

class TestDeterminism:

    def test_same_registry_same_routes(self) -> None:
        """Two routers from the same registry file produce identical routes."""
        r1 = InferenceRouter(MC6_INF_REGISTRY, REPO_ROOT)
        r2 = InferenceRouter(MC6_INF_REGISTRY, REPO_ROOT)
        assert r1.routable_symbols == r2.routable_symbols
        for sym in r1.routable_symbols:
            route1 = r1.resolve(sym)
            route2 = r2.resolve(sym)
            assert route1 == route2

    def test_route_sha_deterministic(self) -> None:
        """Route SHA fields are deterministic across instantiations."""
        r1 = InferenceRouter(MC6_INF_REGISTRY, REPO_ROOT)
        r2 = InferenceRouter(MC6_INF_REGISTRY, REPO_ROOT)
        for sym in r1.routable_symbols:
            a = r1.resolve(sym)
            b = r2.resolve(sym)
            assert a.model_sha256 == b.model_sha256
            assert a.calibrator_sha256 == b.calibrator_sha256
