"""Tests for MC8-H — Negative Release Behavior.

Asserts that corrupting or misconfiguring the release bundle results in a clean,
fail-closed startup/preflight block with NO silent fallbacks.
"""
import hashlib
import json
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
RELEASE_DIR = REPO_ROOT / "runtime" / "releases" / "model-coverage-v1"
RELEASE_REGISTRY = RELEASE_DIR / "model_coverage_mc6_inference_registry.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ── Missing Model ─────────────────────────────────────────────────────────────

def test_missing_model_raises_integrity_error() -> None:
    from btc_scraper.ml_engine.inference_router import (
        InferenceRouter,
        InferenceRouteIntegrityError,
    )

    # Corrupt registry to point to non-existent model path
    data = json.loads(RELEASE_REGISTRY.read_text(encoding="utf-8"))
    for route in data["routes"]:
        if route["route_type"] == "MC5_QUALIFIED":
            route["model_artifact_path"] = "nonexistent_model.joblib"
            break

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_registry = Path(tmp_dir) / "corrupt_registry.json"
        tmp_registry.write_text(json.dumps(data), encoding="utf-8")

        router = InferenceRouter(tmp_registry, RELEASE_DIR)
        for route_entry in data["routes"]:
            if route_entry["route_type"] == "MC5_QUALIFIED":
                route_obj = router.resolve(route_entry["symbol"])
                with pytest.raises(InferenceRouteIntegrityError, match="model_artifact_missing"):
                    router.validate_route(route_obj)
                break


# ── Modified Model Byte ────────────────────────────────────────────────────────

def test_corrupted_model_hash_raises_integrity_error() -> None:
    from btc_scraper.ml_engine.inference_router import (
        InferenceRouter,
        InferenceRouteIntegrityError,
    )

    data = json.loads(RELEASE_REGISTRY.read_text(encoding="utf-8"))
    target_sym = None
    for route in data["routes"]:
        if route["route_type"] == "MC5_QUALIFIED":
            target_sym = route["symbol"]
            # Change the model hash in registry records
            route["model_sha256"] = "a" * 64
            break

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_registry = Path(tmp_dir) / "corrupt_registry.json"
        tmp_registry.write_text(json.dumps(data), encoding="utf-8")

        router = InferenceRouter(tmp_registry, RELEASE_DIR)
        route_obj = router.resolve(target_sym)
        with pytest.raises(InferenceRouteIntegrityError, match="model_sha_mismatch"):
            router.validate_route(route_obj)


# ── Missing Calibrator ────────────────────────────────────────────────────────

def test_missing_calibrator_raises_integrity_error() -> None:
    from btc_scraper.ml_engine.inference_router import (
        InferenceRouter,
        InferenceRouteIntegrityError,
    )

    data = json.loads(RELEASE_REGISTRY.read_text(encoding="utf-8"))
    for route in data["routes"]:
        if route["route_type"] == "MC5_QUALIFIED":
            route["calibrator_artifact_path"] = "nonexistent_calibrator.joblib"
            break

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_registry = Path(tmp_dir) / "corrupt_registry.json"
        tmp_registry.write_text(json.dumps(data), encoding="utf-8")

        router = InferenceRouter(tmp_registry, RELEASE_DIR)
        for route_entry in data["routes"]:
            if route_entry["route_type"] == "MC5_QUALIFIED":
                route_obj = router.resolve(route_entry["symbol"])
                with pytest.raises(InferenceRouteIntegrityError, match="calibrator_missing"):
                    router.validate_route(route_obj)
                break


# ── Wrong Schema ──────────────────────────────────────────────────────────────

def test_wrong_schema_raises_integrity_error() -> None:
    from btc_scraper.ml_engine.inference_router import (
        InferenceRouter,
        InferenceRouteIntegrityError,
    )

    router = InferenceRouter(RELEASE_REGISTRY, RELEASE_DIR)
    route_obj = router.resolve("SOL")
    with pytest.raises(InferenceRouteIntegrityError, match="schema_mismatch"):
        router.validate_schema(route_obj, expected_features=["wrong_feature"])


# ── Enabled Disabled-Symbol / Unknown Symbol ──────────────────────────────────

def test_unknown_symbol_resolves_error() -> None:
    from btc_scraper.ml_engine.inference_router import (
        InferenceRouter,
        InferenceSymbolUnsupported,
    )

    router = InferenceRouter(RELEASE_REGISTRY, RELEASE_DIR)
    with pytest.raises(InferenceSymbolUnsupported, match="no_registry_entry"):
        router.resolve("FAKECOIN")


def test_disabled_symbol_resolves_error() -> None:
    from btc_scraper.ml_engine.inference_router import (
        InferenceRouter,
        InferenceSymbolUnsupported,
    )

    router = InferenceRouter(RELEASE_REGISTRY, RELEASE_DIR)
    with pytest.raises(InferenceSymbolUnsupported):
        router.resolve("XRP")
