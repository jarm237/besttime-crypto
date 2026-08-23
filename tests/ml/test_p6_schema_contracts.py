from __future__ import annotations

from datetime import datetime, timezone, timedelta

import numpy as np
import pytest

from btc_scraper.ml_engine.evaluation_contracts import EvaluationContractError
from btc_scraper.ml_engine.inference_contract import InferenceArtifact, feature_schema_hash
from btc_scraper.ml_engine.meta_model import predict_meta_confidence
from btc_scraper.ml_engine.schema_contracts import (
    CANONICAL_MODEL_FEATURES,
    MODEL_FEATURE_VECTOR_SCHEMA,
    RuntimeSchema,
    SchemaField,
    build_model_feature_vector,
    canonical_timestamp,
    classify_persisted_schema_identity,
)


def _artifact(call_counter: dict[str, int] | None = None) -> InferenceArtifact:
    def predictor(_symbol: str, _features: tuple[float, ...]) -> float:
        if call_counter is not None:
            call_counter["calls"] += 1
        return 0.71

    return InferenceArtifact(
        model_family="fixture",
        artifact_version="schema-v1",
        artifact_hash="a" * 64,
        feature_schema_hash=feature_schema_hash(CANONICAL_MODEL_FEATURES),
        feature_names=CANONICAL_MODEL_FEATURES,
        predictor=predictor,
        feature_schema_version="meta-v3.1-43f",
        artifact_metadata_consistent=True,
        supported_symbols=frozenset({"BTC"}),
    )


def _features(**updates):
    values = {
        "return_8": 0.01,
        "return_32": 0.02,
        "return_72": -0.03,
        "abs_move_72": 0.04,
    }
    values.update(updates)
    return values


def test_schema_fingerprint_is_deterministic_and_order_sensitive():
    first = RuntimeSchema(
        "fixture",
        "v1",
        (SchemaField("a", "float"), SchemaField("b", "float")),
        allow_extra=True,
    )
    same = RuntimeSchema(
        "fixture",
        "v1",
        (SchemaField("a", "float"), SchemaField("b", "float")),
        allow_extra=True,
    )
    reordered = RuntimeSchema(
        "fixture",
        "v1",
        (SchemaField("b", "float"), SchemaField("a", "float")),
        allow_extra=True,
    )
    dtype_changed = RuntimeSchema(
        "fixture",
        "v1",
        (SchemaField("a", "int"), SchemaField("b", "float")),
        allow_extra=True,
    )
    nullable_changed = RuntimeSchema(
        "fixture",
        "v1",
        (SchemaField("a", "float", nullable=True), SchemaField("b", "float")),
        allow_extra=True,
    )

    assert first.fingerprint == same.fingerprint
    assert first.fingerprint != reordered.fingerprint
    assert first.order_hash != reordered.order_hash
    assert first.fingerprint != dtype_changed.fingerprint
    assert first.fingerprint != nullable_changed.fingerprint


def test_model_feature_vector_locks_order_and_canonical_numeric_types():
    vector = build_model_feature_vector(
        {
            "return_8": 1,
            "return_32": np.float64(2.0),
            "return_72": 3.0,
            "abs_move_72": np.float32(4.0),
            "extra": 999,
        }
    )

    assert vector.schema == MODEL_FEATURE_VECTOR_SCHEMA
    assert vector.values == pytest.approx((1.0, 2.0, 3.0, 4.0))
    assert len(vector.semantic_hash) == 64


@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        ({"return_72": None}, "NULL_NOT_ALLOWED:return_72"),
        ({"return_72": float("nan")}, "NON_FINITE_VALUE:return_72"),
        ({"return_72": float("inf")}, "NON_FINITE_VALUE:return_72"),
        ({"return_72": "0.1"}, "DTYPE_MISMATCH:return_72:float"),
        ({"return_72": True}, "DTYPE_MISMATCH:return_72:float"),
    ],
)
def test_negative_numeric_matrix_fails_closed(payload, reason):
    values = _features(**payload)
    with pytest.raises(EvaluationContractError, match=reason):
        build_model_feature_vector(values)


def test_missing_and_wrong_feature_order_fail_closed():
    missing = _features()
    del missing["return_72"]
    with pytest.raises(EvaluationContractError, match="MISSING_REQUIRED_FIELD:return_72"):
        build_model_feature_vector(missing)
    with pytest.raises(EvaluationContractError, match="FEATURE_ORDER_MISMATCH"):
        build_model_feature_vector(
            _features(),
            feature_names=("return_8", "return_72", "return_32", "abs_move_72"),
        )


def test_source_map_blocks_legacy_default_fill_before_inference():
    with pytest.raises(EvaluationContractError, match="MISSING_REQUIRED_FIELD:return_72"):
        build_model_feature_vector(
            _features(return_72=0.0),
            source_map={
                "return_8": 0.01,
                "return_32": 0.02,
                "abs_move_72": 0.04,
            },
        )


def test_invalid_schema_does_not_invoke_model_inference():
    calls = {"calls": 0}
    result = predict_meta_confidence(
        {
            "coin": "BTC",
            "symbol": "BTCUSDT",
            "cycle_id": "cycle-g3",
            "signal_id": "sig-g3",
            "return_8": 0.01,
            "return_32": 0.02,
            "abs_move_72": 0.04,
        },
        symbol="BTC",
        artifact=_artifact(calls),
    )

    assert result["probability"] is None
    assert "MISSING_REQUIRED_FIELD:return_72" in result["error"]
    assert calls["calls"] == 0
    assert result.get("action") is None


def test_valid_schema_preserves_inference_behavior():
    calls = {"calls": 0}
    result = predict_meta_confidence(
        {
            "coin": "BTC",
            "symbol": "BTCUSDT",
            "cycle_id": "cycle-g3",
            "signal_id": "sig-g3",
            **_features(),
        },
        symbol="BTC",
        artifact=_artifact(calls),
    )

    assert result["probability"] == pytest.approx(0.71)
    assert calls["calls"] == 1


def test_timestamp_canonicalization_and_legacy_persistence_policy():
    utc = datetime(2026, 8, 23, 10, 0, tzinfo=timezone.utc)
    offset = datetime(2026, 8, 23, 17, 0, tzinfo=timezone(timedelta(hours=7)))

    assert canonical_timestamp(utc) == canonical_timestamp(offset)
    with pytest.raises(EvaluationContractError, match="TIMESTAMP_NAIVE"):
        canonical_timestamp(datetime(2026, 8, 23, 10, 0))
    with pytest.raises(EvaluationContractError, match="TIMESTAMP_INVALID"):
        canonical_timestamp("not-a-date")
    assert classify_persisted_schema_identity({
        "feature_schema_hash": "h",
        "feature_schema_version": "v",
    }) == "CURRENT_SCHEMA_IDENTIFIED"
    assert classify_persisted_schema_identity({}) == "LEGACY_UNVERIFIED_SCHEMA"
