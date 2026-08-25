"""Tests for MC6-B — Immutable Inference Registry."""
import json
import hashlib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

MC6_INF_REGISTRY   = REPO_ROOT / "model_coverage_mc6_inference_registry.json"
MC6_RECONCILIATION = REPO_ROOT / "model_coverage_mc6_reconciliation.json"
MC4_REGISTRY       = REPO_ROOT / "model_coverage_mc4_candidate_registry.json"

LEGACY = {"BTC", "ETH", "BNB"}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@pytest.fixture(scope="module")
def registry() -> dict:
    return json.loads(MC6_INF_REGISTRY.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def recon() -> dict:
    return json.loads(MC6_RECONCILIATION.read_text(encoding="utf-8"))


# ── SHA sidecar validity ────────────────────────────────────────────────────

def test_sha_sidecar_valid() -> None:
    sha_path = Path(str(MC6_INF_REGISTRY) + ".sha256")
    assert sha_path.exists()
    digest, rel = sha_path.read_text().strip().split()
    assert _sha256(REPO_ROOT / rel) == digest


# ── Every routable symbol has a route ────────────────────────────────────────

def test_every_routable_has_route(registry: dict, recon: dict) -> None:
    route_symbols = {r["symbol"] for r in registry["routes"]}
    routable = set(recon["routable_symbols"])
    assert route_symbols == routable


# ── No excluded symbols in registry ──────────────────────────────────────────

def test_no_excluded_in_registry(registry: dict, recon: dict) -> None:
    route_symbols = {r["symbol"] for r in registry["routes"]}
    excluded = {e["symbol"] for e in recon["excluded_symbols"]}
    assert route_symbols.isdisjoint(excluded)


# ── No duplicate routes ──────────────────────────────────────────────────────

def test_no_duplicate_routes(registry: dict) -> None:
    symbols = [r["symbol"] for r in registry["routes"]]
    assert len(symbols) == len(set(symbols))


# ── MC5 routes have valid artifact paths ─────────────────────────────────────

def test_mc5_routes_artifacts_exist(registry: dict) -> None:
    for route in registry["routes"]:
        if route["route_type"] == "MC5_QUALIFIED":
            model_path = REPO_ROOT / route["model_artifact_path"]
            cal_path = REPO_ROOT / route["calibrator_artifact_path"]
            assert model_path.exists(), f"{route['symbol']}: model missing"
            assert cal_path.exists(), f"{route['symbol']}: calibrator missing"


# ── SHA matches on disk ──────────────────────────────────────────────────────

def test_mc5_routes_sha_match(registry: dict) -> None:
    for route in registry["routes"]:
        if route["route_type"] == "MC5_QUALIFIED":
            model_path = REPO_ROOT / route["model_artifact_path"]
            cal_path = REPO_ROOT / route["calibrator_artifact_path"]
            assert _sha256(model_path) == route["model_sha256"], \
                f"{route['symbol']}: model SHA mismatch"
            assert _sha256(cal_path) == route["calibrator_sha256"], \
                f"{route['symbol']}: calibrator SHA mismatch"


# ── MC4 provenance cross-check ───────────────────────────────────────────────

def test_mc5_routes_match_mc4_provenance(registry: dict) -> None:
    mc4 = json.loads(MC4_REGISTRY.read_text(encoding="utf-8"))
    mc4_map = {e["symbol"]: e for e in mc4["candidates"]}
    for route in registry["routes"]:
        if route["route_type"] == "MC5_QUALIFIED":
            mc4_entry = mc4_map.get(route["symbol"])
            assert mc4_entry is not None, f"{route['symbol']} not in MC4"
            assert route["model_sha256"] == mc4_entry["artifact_sha256"], \
                f"{route['symbol']}: registry model SHA ≠ MC4 artifact SHA"


# ── Feature schema consistent across routes ──────────────────────────────────

def test_feature_schema_consistent(registry: dict) -> None:
    expected = ["return_8", "return_32", "return_72", "abs_move_72"]
    for route in registry["routes"]:
        assert route["feature_schema"] == expected


# ── Legacy routes have correct type ──────────────────────────────────────────

def test_legacy_route_types(registry: dict) -> None:
    for route in registry["routes"]:
        if route["symbol"] in LEGACY:
            assert route["route_type"] == "LEGACY"
            assert route["qualification_verdict"] == "LEGACY_GRANDFATHERED"


# ── No integrity failures ───────────────────────────────────────────────────

def test_zero_integrity_failures(registry: dict) -> None:
    assert len(registry["integrity_failures"]) == 0


# ── Counts match ─────────────────────────────────────────────────────────────

def test_counts_match(registry: dict) -> None:
    assert registry["routable_count"] == len(registry["routes"])
    assert registry["legacy_count"] + registry["mc5_qualified_count"] == registry["routable_count"]
