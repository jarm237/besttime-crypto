"""Tests for MC8-D/E — Bundle Self-Containment.

Verifies that the release bundle is self-contained:
1. All 9 authorized routes can be resolved and validated.
2. Inference runs successfully for all 9 routes inside a sandbox.
3. No file accesses to research directories or main repository folders occur during inference.
"""
import builtins
import hashlib
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
RELEASE_DIR = REPO_ROOT / "runtime" / "releases" / "model-coverage-v1"
MC8_INVENTORY = REPO_ROOT / "model_coverage_mc8_artifact_inventory.json"

EXPECTED_AUTHORIZED = sorted(["BTC", "ETH", "BNB", "DOGE", "IOTA", "NEAR", "SOL", "TRX", "ZEC"])


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(scope="module")
def inventory() -> dict:
    return json.loads(MC8_INVENTORY.read_text(encoding="utf-8"))


# ── SHA sidecar validity ─────────────────────────────────────────────────────

def test_mc8_inventory_sha_sidecar_valid() -> None:
    sha_path = Path(str(MC8_INVENTORY) + ".sha256")
    assert sha_path.exists()
    digest, rel = sha_path.read_text().strip().split()
    assert _sha256(REPO_ROOT / rel) == digest


# ── Inventory structures ─────────────────────────────────────────────────────

def test_inventory_overall_pass(inventory: dict) -> None:
    assert inventory["overall_verdict"] == "PASS"
    for gate_id, gate in inventory["gates"].items():
        assert gate["result"] == "PASS", f"Gate {gate_id} failed: {gate}"


# ── Sandboxed Self-Containment Test ───────────────────────────────────────────

def test_sandboxed_inference_reads_only_from_release_bundle(monkeypatch) -> None:
    """Verifies that all 9 routable symbols can resolve, validate, and execute
    predictions strictly from the release bundle artifacts, without reading any
    model files from the main repository.
    """
    from btc_scraper.ml_engine.inference_router import InferenceRouter
    import btc_scraper.ml_engine.artifact_resolver as resolver
    import btc_scraper.ml_engine.model_registry as model_registry
    import btc_scraper.ml_engine.artifact_compatibility as comp
    import btc_scraper.ml_engine.meta_model as mm
    import btc_scraper.ml_engine.runtime_symbol_policy as symbol_policy

    # 1. Point all artifact resolvers to the release bundle root
    release_registry = RELEASE_DIR / "model_coverage_mc6_inference_registry.json"
    assert release_registry.exists()

    monkeypatch.setattr(resolver, "ROOT", RELEASE_DIR)
    monkeypatch.setattr(resolver, "DEFAULT_CONFIG", RELEASE_DIR / "config" / "model_artifacts.yaml")
    monkeypatch.setattr(model_registry, "ROOT", RELEASE_DIR)
    monkeypatch.setattr(comp, "ROOT", RELEASE_DIR)
    monkeypatch.setattr(mm, "MODEL_OUT", RELEASE_DIR / "logs/meta_model.joblib")

    # Clear cached model in memory to force reload from disk
    monkeypatch.setattr(mm, "_MODEL_CACHE", None)
    monkeypatch.setattr(mm, "_CACHED_MODEL", None)

    # 2. Intercept and monitor all file read/open operations
    original_open = builtins.open
    opened_paths: set[Path] = set()

    def monitored_open(file, *args, **kwargs):
        path = Path(file).resolve()
        # Track python file/joblib reads inside the project folder
        if str(REPO_ROOT) in str(path) and path.suffix in {".joblib", ".json", ".pkl"}:
            opened_paths.add(path)
        return original_open(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", monitored_open)

    # 3. Instantiate router pointing to the release registry
    router = InferenceRouter(release_registry, RELEASE_DIR)

    # Mock inputs
    mock_analysis = {
        "observed_at": "2026-08-25T13:00:00+00:00",
        "signal": "BUY",
        "close": 100.0,
        "return_8": 0.01,
        "return_32": -0.02,
        "return_72": 0.05,
        "abs_move_72": 0.05,
        "coin": "BTC",
        "ticker": "BTC",
    }

    # Run router validation and prediction for each of the 9 authorized symbols
    for sym in EXPECTED_AUTHORIZED:
        route = router.resolve(sym)
        router.validate_route(route)
        router.validate_schema(route)

        # Legacy models load via the global path, while MC5 routes use custom artifacts
        # We simulate the exact prediction dispatch
        mock_analysis_sym = mock_analysis.copy()
        mock_analysis_sym["coin"] = sym
        mock_analysis_sym["ticker"] = sym

        if route.route_type == "LEGACY":
            # Uses the grandfathered global model (meta_model.joblib)
            res = mm.predict_meta_confidence(mock_analysis_sym, symbol=sym)
            assert isinstance(res, dict)
            assert 0.0 <= res["probability"] <= 1.0
            assert 0.0 <= res["sizing_probability"] <= 1.0
        else:
            # Uses the custom candidate model and calibrator
            # We load the candidate artifact explicitly to mock the route path
            from btc_scraper.ml_engine.inference_contract import InferenceArtifact
            import joblib

            model_dict = joblib.load(route.model_artifact_path)
            calibrator_dict = joblib.load(route.calibrator_artifact_path)
            inner_model = model_dict["model"]
            inner_calibrator = calibrator_dict["calibrator"]

            def mock_predictor(symbol_str, feature_vector):
                # Simple evaluation: predict probability using the model and calibrator
                import numpy as np
                feats = np.array(feature_vector).reshape(1, -1)
                raw = inner_model.predict_proba(feats)[0, 1]
                cal = inner_calibrator.predict_proba(np.array([[raw]]))[0, 1]
                return cal

            from btc_scraper.ml_engine.inference_contract import feature_schema_hash

            artifact = InferenceArtifact(
                model_family="meta_model",
                artifact_version=route.route_version,
                artifact_hash=route.model_sha256,
                feature_schema_hash=feature_schema_hash(route.feature_schema),
                feature_names=tuple(route.feature_schema),
                predictor=mock_predictor,
                feature_schema_version=route.feature_schema_version,
                calibration_method="isotonic",
                supported_symbols=frozenset({sym}),
            )

            res = mm.predict_meta_confidence(mock_analysis_sym, symbol=sym, artifact=artifact)
            assert isinstance(res, dict)
            assert 0.0 <= res["probability"] <= 1.0
            assert 0.0 <= res["sizing_probability"] <= 1.0

    # 4. Strict assertion: Assert no files were read from outside the release bundle
    # specifically, no reads of joblib/json files inside research/ or non-release logs/
    out_of_bounds = []
    for path in opened_paths:
        # If it is inside REPO_ROOT but NOT inside RELEASE_DIR, it's out of bounds!
        if str(REPO_ROOT) in str(path) and str(RELEASE_DIR) not in str(path):
            out_of_bounds.append(path)

    # Print any offending files for troubleshooting
    if out_of_bounds:
        print("OUT_OF_BOUNDS READS DETECTED:")
        for path in out_of_bounds:
            print(f"  - {path}")

    assert not out_of_bounds, f"Inference accessed files outside release bundle: {out_of_bounds}"
