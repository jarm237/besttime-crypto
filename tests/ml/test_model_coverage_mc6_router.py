"""Tests for MC6-C — InferenceRouter unit tests."""
import json
import hashlib
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MC6_INF_REGISTRY = REPO_ROOT / "model_coverage_mc6_inference_registry.json"

from btc_scraper.ml_engine.inference_router import (
    InferenceRouter,
    InferenceSymbolUnsupported,
    InferenceRouteIntegrityError,
    InferenceRoute,
)


@pytest.fixture(scope="module")
def router() -> InferenceRouter:
    return InferenceRouter(MC6_INF_REGISTRY, REPO_ROOT)


# ── Resolve all routable symbols ─────────────────────────────────────────────

def test_resolve_all_routable(router: InferenceRouter) -> None:
    registry = json.loads(MC6_INF_REGISTRY.read_text(encoding="utf-8"))
    for entry in registry["routes"]:
        route = router.resolve(entry["symbol"])
        assert isinstance(route, InferenceRoute)
        assert route.symbol == entry["symbol"]


# ── Unknown symbol raises ────────────────────────────────────────────────────

def test_unknown_symbol_raises(router: InferenceRouter) -> None:
    with pytest.raises(InferenceSymbolUnsupported) as exc_info:
        router.resolve("FAKECOIN")
    assert "FAKECOIN" in str(exc_info.value)
    assert exc_info.value.reason == "no_registry_entry"


# ── Excluded symbol raises ──────────────────────────────────────────────────

def test_excluded_symbol_raises(router: InferenceRouter) -> None:
    """AEVO was MC5-rejected and should not be in the registry."""
    with pytest.raises(InferenceSymbolUnsupported):
        router.resolve("AEVO")


def test_mc4_no_candidate_raises(router: InferenceRouter) -> None:
    with pytest.raises(InferenceSymbolUnsupported):
        router.resolve("SOPH")


def test_mc3_blocked_raises(router: InferenceRouter) -> None:
    with pytest.raises(InferenceSymbolUnsupported):
        router.resolve("XAUT")


# ── Validate route integrity for MC5 symbols ────────────────────────────────

def test_validate_mc5_routes(router: InferenceRouter) -> None:
    registry = json.loads(MC6_INF_REGISTRY.read_text(encoding="utf-8"))
    for entry in registry["routes"]:
        if entry["route_type"] == "MC5_QUALIFIED":
            route = router.resolve(entry["symbol"])
            router.validate_route(route)  # should not raise


# ── Validate schema ─────────────────────────────────────────────────────────

def test_validate_schema_pass(router: InferenceRouter) -> None:
    route = router.resolve("DOGE")
    router.validate_schema(route)  # should not raise


def test_validate_schema_mismatch(router: InferenceRouter) -> None:
    route = router.resolve("DOGE")
    with pytest.raises(InferenceRouteIntegrityError) as exc_info:
        router.validate_schema(route, expected_features=["wrong_feature"])
    assert "schema_mismatch" in str(exc_info.value)


# ── Routable symbols list ───────────────────────────────────────────────────

def test_routable_symbols(router: InferenceRouter) -> None:
    expected = {"BTC", "ETH", "BNB", "DOGE", "IOTA", "NEAR", "SOL", "TRX", "ZEC"}
    assert set(router.routable_symbols) == expected


# ── Contains operator ────────────────────────────────────────────────────────

def test_contains(router: InferenceRouter) -> None:
    assert "DOGE" in router
    assert "FAKECOIN" not in router
    assert "AEVO" not in router
