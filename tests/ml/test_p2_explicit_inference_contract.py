from __future__ import annotations

import asyncio
import hashlib
import json
import random
from pathlib import Path

import numpy as np
import pytest

from btc_scraper.ml_engine.decision_engine import MetaDecisionEngine
from btc_scraper.ml_engine.inference_contract import (
    INFERENCE_CONTRACT_VERSION,
    InferenceArtifact,
    InferenceContractError,
    artifact_set_hash,
    feature_schema_hash,
    normalize_inference_symbol,
    predict,
)
from btc_scraper.ml_engine.meta_model import predict_meta_confidence
from scripts.hmr_v5_d2_parity_replay import RuntimeInferenceEngine
from scripts.hmr_v5_d2_r1_real_runtime_parity import V5FilterModelClassifier


FEATURE_NAMES = ("return_8", "return_32", "return_72", "abs_move_72")
PREDICTIONS = {"BTC": 0.71, "ETH": 0.84, "BNB": 0.77}


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _artifact(symbol: str) -> InferenceArtifact:
    normalized = normalize_inference_symbol(symbol)

    def predictor(explicit_symbol: str, features: tuple[float, ...]) -> float:
        assert explicit_symbol == normalized
        assert len(features) == len(FEATURE_NAMES)
        return PREDICTIONS[normalized]

    return InferenceArtifact(
        model_family=f"fixture-{normalized.lower()}",
        artifact_version=f"{normalized.lower()}-v1",
        artifact_hash=_sha(f"artifact:{normalized}"),
        feature_schema_hash=feature_schema_hash(FEATURE_NAMES),
        feature_names=FEATURE_NAMES,
        predictor=predictor,
        feature_schema_version="fixture-4f/v1",
        artifact_metadata_consistent=True,
        supported_symbols=frozenset({normalized}),
    )


@pytest.mark.parametrize(
    ("raw", "error"),
    [
        (None, "must_be_string"),
        ("", "missing"),
        (" ", "missing"),
        ("UNKNOWN", "unsupported"),
        ("SOL", "unsupported"),
        (123, "must_be_string"),
    ],
)
def test_missing_and_invalid_symbols_fail_closed(raw, error):
    with pytest.raises(InferenceContractError, match=error):
        predict(
            symbol=raw,
            features=(1.0, 2.0, 3.0, 4.0),
            artifact=_artifact("BTC"),
        )


def test_symbol_normalization_is_explicit_and_deterministic():
    result = predict(
        symbol="btcUSDT",
        features=(1.0, 2.0, 3.0, 4.0),
        artifact=_artifact("BTC"),
    )
    assert result.symbol == "BTC"
    assert result.prediction == PREDICTIONS["BTC"]
    assert result.inference_contract_version == INFERENCE_CONTRACT_VERSION


def test_result_carries_the_six_required_identity_fields():
    artifact = _artifact("ETH")
    result = predict(
        symbol="ETH",
        features=(1.0, 2.0, 3.0, 4.0),
        artifact=artifact,
    )
    assert {
        "symbol": result.symbol,
        "artifact_version": result.artifact_version,
        "artifact_hash": result.artifact_hash,
        "feature_schema_hash": result.feature_schema_hash,
        "model_family": result.model_family,
        "prediction": result.prediction,
    } == {
        "symbol": "ETH",
        "artifact_version": artifact.artifact_version,
        "artifact_hash": artifact.artifact_hash,
        "feature_schema_hash": artifact.feature_schema_hash,
        "model_family": artifact.model_family,
        "prediction": PREDICTIONS["ETH"],
    }


def test_feature_schema_identity_is_order_sensitive_and_fail_closed():
    names = ("a", "b")
    with pytest.raises(InferenceContractError, match="feature_schema_hash_mismatch"):
        InferenceArtifact(
            model_family="fixture",
            artifact_version="v1",
            artifact_hash=_sha("artifact"),
            feature_schema_hash=feature_schema_hash(reversed(names)),
            feature_names=names,
            predictor=lambda symbol, values: 0.5,
        )


def test_artifact_hash_changes_when_actual_bytes_change(tmp_path):
    path = tmp_path / "model.bin"
    path.write_bytes(b"artifact-a")
    first = hashlib.sha256(path.read_bytes()).hexdigest()
    path.write_bytes(b"artifact-b")
    second = hashlib.sha256(path.read_bytes()).hexdigest()
    assert first != second


def test_caller_name_and_stack_shape_cannot_change_routing():
    artifact = _artifact("ETH")

    def direct():
        return predict(
            symbol="ETH",
            features=(1.0, 2.0, 3.0, 4.0),
            artifact=artifact,
        )

    def extra_wrapper(callback):
        market_symbol = "ETH"
        return callback() if market_symbol else None

    assert direct() == extra_wrapper(direct)


def test_concurrent_btc_eth_bnb_requests_never_cross_route():
    async def run() -> None:
        rng = random.Random(20260821)

        async def infer(symbol: str, delay: float):
            await asyncio.sleep(delay)
            return await asyncio.to_thread(
                predict,
                symbol=symbol,
                features=(1.0, 2.0, 3.0, 4.0),
                artifact=_artifact(symbol),
            )

        for _ in range(30):
            symbols = ["BTC", "ETH", "BNB"]
            rng.shuffle(symbols)
            results = await asyncio.gather(
                *(infer(symbol, rng.random() / 1000.0) for symbol in symbols)
            )
            by_symbol = {result.symbol: result for result in results}
            assert set(by_symbol) == {"BTC", "ETH", "BNB"}
            for symbol, result in by_symbol.items():
                assert result.prediction == PREDICTIONS[symbol]
                assert result.artifact_hash == _artifact(symbol).artifact_hash

    asyncio.run(run())


def _write_v5_fixture(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    manifest = {
        "model_id": "fixture-v5",
        "version": "1.0.0",
    }
    models = {
        "BTC": {"coefficients": [1.0, 0.0], "intercept": 0.1},
        "ETH": {"coefficients": [0.0, 1.0], "intercept": 0.2},
        "BNB": {"coefficients": [-1.0, 1.0], "intercept": 0.3},
    }
    preprocessing = {
        symbol: {"means": [0.0, 0.0], "scales": [1.0, 1.0]}
        for symbol in models
    }
    schema = {"feature_names": ["a", "b"]}
    for filename, payload in (
        ("manifest.json", manifest),
        ("model.json", models),
        ("preprocessing.json", preprocessing),
        ("feature_schema.json", schema),
    ):
        (path / filename).write_text(json.dumps(payload), encoding="utf-8")


def test_mutable_current_symbol_cannot_override_explicit_v5_route(tmp_path):
    _write_v5_fixture(tmp_path)
    classifier = V5FilterModelClassifier(str(tmp_path))
    row = np.asarray([[0.5, -0.25]])
    expected = classifier.predict_proba(row, symbol="ETH")
    for ambient in ("BTC", "BNB", "UNKNOWN"):
        classifier.current_symbol = ambient
        actual = classifier.predict_proba(row, symbol="ETH")
        np.testing.assert_array_equal(actual, expected)


def test_live_and_historical_adapters_share_explicit_identity_and_prediction(tmp_path):
    _write_v5_fixture(tmp_path)
    classifier = V5FilterModelClassifier(str(tmp_path))
    replay = RuntimeInferenceEngine(tmp_path)
    artifact_hash = artifact_set_hash((
        tmp_path / "manifest.json",
        tmp_path / "model.json",
        tmp_path / "preprocessing.json",
        tmp_path / "feature_schema.json",
    ))
    names = ("a", "b")
    live_artifact = InferenceArtifact(
        model_family="fixture-v5",
        artifact_version="1.0.0",
        artifact_hash=artifact_hash,
        feature_schema_hash=feature_schema_hash(names),
        feature_names=names,
        predictor=lambda symbol, values: float(
            classifier.predict_proba(
                np.asarray([values]),
                symbol=symbol,
            )[0, 1]
        ),
        feature_schema_version="hmr-v5-filter-schema/v1",
        supported_symbols=frozenset({"BTC", "ETH", "BNB"}),
    )
    for symbol in ("BTC", "ETH", "BNB"):
        features = [0.5, -0.25]
        live = predict(symbol=symbol, features=features, artifact=live_artifact)
        historical = replay.predict_inference(symbol=symbol, features=features)
        assert live == historical


def test_meta_prediction_identity_survives_final_decision(monkeypatch):
    names = FEATURE_NAMES
    artifact = InferenceArtifact(
        model_family="meta_model",
        artifact_version="fixture-meta-v1",
        artifact_hash=_sha("fixture-meta-model"),
        feature_schema_hash=feature_schema_hash(names),
        feature_names=names,
        predictor=lambda symbol, values: 0.75,
        feature_schema_version="meta-v3.1-43f",
        artifact_metadata_consistent=False,
        supported_symbols=frozenset({"BTC"}),
    )
    monkeypatch.setattr(
        "btc_scraper.ml_engine.prediction_logger.append_prediction",
        lambda **kwargs: {
            "prediction_id": "pred-p2",
            "feature_hash": _sha("features"),
            "deployment_id": "dep-p2",
            "paper_run_id": "paper-p2",
            "cycle_id": "cycle-p2",
            "signal_id": "sig-p2",
            "decision_context": "entry",
            "caller_context": "p2-test",
        },
    )
    analysis = {
        "coin": "BTC",
        "symbol": "BTCUSDT",
        "signal": "BUY",
        "action": "BUY",
        "entry": 100.0,
        "tp1": 101.0,
        "sl": 99.0,
        "cycle_id": "cycle-p2",
        "signal_id": "sig-p2",
        "decision_context": "entry",
        "caller_context": "p2-test",
    }
    prediction = predict_meta_confidence(
        analysis,
        symbol="BTC",
        artifact=artifact,
    )
    final_decision = MetaDecisionEngine(weights={"meta": 1.0}).decide(
        {**analysis, "_meta_prediction": prediction},
        persist_final=False,
    )
    for field in (
        "symbol",
        "artifact_version",
        "artifact_hash",
        "feature_schema_hash",
        "model_family",
        "prediction",
        "inference_contract_version",
        "artifact_metadata_consistent",
    ):
        assert final_decision[field] == prediction[field]


def test_analysis_symbol_cannot_disagree_with_explicit_request():
    result = predict_meta_confidence(
        {"coin": "BTC", "symbol": "BTCUSDT"},
        symbol="ETH",
        artifact=_artifact("ETH"),
    )
    assert result["probability"] is None
    assert "analysis_symbol_mismatch" in result["error"]


def test_inference_modules_contain_no_forbidden_ambient_routing_patterns():
    root = Path(__file__).resolve().parents[2]
    targets = (
        root / "btc_scraper/ml_engine/inference_contract.py",
        root / "btc_scraper/ml_engine/meta_model.py",
        root / "btc_scraper/ml_engine/inference_coordinator.py",
        root / "scripts/hmr_v5_d2_parity_replay.py",
        root / "scripts/hmr_v5_d2_r1_real_runtime_parity.py",
    )
    forbidden = (
        "inspect.stack",
        "inspect.currentframe",
        ".f_back",
        ".f_locals",
        "getattr(self, \"current_symbol\"",
        "self.current_symbol or",
    )
    findings = {
        str(path.relative_to(root)): [
            pattern for pattern in forbidden if pattern in path.read_text(encoding="utf-8")
        ]
        for path in targets
    }
    assert all(not matches for matches in findings.values()), findings
