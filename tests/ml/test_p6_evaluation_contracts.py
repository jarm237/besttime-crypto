from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from btc_scraper.ml_engine.common_evaluator import CanonicalCandle
from btc_scraper.ml_engine.evaluation_contracts import (
    ArtifactContract,
    CANONICAL_MODEL_READINESS_DEPENDENCIES,
    CANONICAL_ENTRY_INTERVAL_SECONDS,
    EvaluationContractError,
    EvaluationProvenance,
    FieldContract,
    ReadinessState,
    SchemaContract,
    WarmupContract,
    canonical_hash,
    canonical_entry_readiness_contract,
    canonical_readiness_minimum_observations,
)


NOW = datetime(2026, 8, 21, 12, 0, tzinfo=timezone.utc)
H = {key: key * 64 for key in "abcdef"}


def artifact(**updates):
    values = {
        "artifact_id": "meta:v1", "artifact_type": "model",
        "artifact_version": "v1", "sha256": H["a"],
        "schema_version": "schema-v1", "feature_schema_hash": H["b"],
        "feature_order_hash": H["c"], "training_contract_hash": H["d"],
        "calibration_contract_hash": H["e"],
        "compatible_evaluator_version": "common-evaluator/v1",
    }
    values.update(updates)
    return ArtifactContract(**values)


def candle(index: int, *, closed=True):
    opened = NOW + timedelta(minutes=15 * index)
    return CanonicalCandle(opened, opened, 1.0, 1.0, 1.0, 1.0, 0.0, closed)


def test_artifact_identity_is_complete_pinned_and_deterministic():
    assert len(artifact().identity_hash) == 64
    assert artifact().identity_hash == artifact().identity_hash


@pytest.mark.parametrize("field", [
    "sha256", "feature_schema_hash", "feature_order_hash",
    "training_contract_hash", "calibration_contract_hash",
])
def test_artifact_missing_or_invalid_hash_fails_closed(field):
    with pytest.raises(EvaluationContractError, match=f"{field}_invalid"):
        artifact(**{field: "unavailable"})


def test_artifact_compatibility_and_feature_order_fail_closed():
    with pytest.raises(EvaluationContractError, match="feature_order_mismatch"):
        artifact().assert_compatible(
            evaluator_version="common-evaluator/v1",
            feature_schema_hash=H["b"], feature_order_hash=H["f"],
        )
    with pytest.raises(EvaluationContractError, match="incompatible_evaluator"):
        artifact().assert_compatible(
            evaluator_version="common-evaluator/v2",
            feature_schema_hash=H["b"], feature_order_hash=H["c"],
        )


def test_schema_fingerprint_locks_order_dtype_and_nullability():
    first = SchemaContract("features", "v1", (
        FieldContract("ema", "float"), FieldContract("regime", "str", True),
    ))
    reordered = SchemaContract("features", "v1", tuple(reversed(first.fields)))
    assert first.fingerprint != reordered.fingerprint
    assert first.order_hash != reordered.order_hash
    first.validate({"ema": 1.0, "regime": None})


@pytest.mark.parametrize("payload,signature", [
    ({"ema": 1.0}, "required_fields_missing"),
    ({"ema": 1.0, "regime": "x", "extra": 1}, "extra_fields_forbidden"),
    ({"ema": 1, "regime": "x"}, "dtype_mismatch"),
    ({"ema": float("nan"), "regime": "x"}, "non_finite"),
])
def test_schema_negative_boundaries_fail_closed(payload, signature):
    schema = SchemaContract("features", "v1", (
        FieldContract("ema", "float"), FieldContract("regime", "str"),
    ))
    with pytest.raises(EvaluationContractError, match=signature):
        schema.validate(payload)


def test_warmup_boundaries_are_explicit_and_not_hold():
    contract = WarmupContract({"ema": 3, "atr": 2}, 900)
    assert contract.evaluate([candle(0), candle(1)], NOW + timedelta(hours=1)) is ReadinessState.WARMING_UP
    assert contract.evaluate([candle(0), candle(1), candle(2)], NOW + timedelta(hours=1)) is ReadinessState.READY
    assert "HOLD" not in {item.value for item in ReadinessState}


def test_gap_partial_future_and_restart_are_deterministic():
    contract = WarmupContract({"resolved": 3}, 900)
    gap = [candle(0), candle(1), candle(3)]
    assert contract.evaluate(gap, NOW + timedelta(hours=1)) is ReadinessState.INVALID_INPUT
    partial = [candle(0), candle(1), candle(2, closed=False)]
    assert contract.evaluate(partial, NOW + timedelta(hours=1)) is ReadinessState.INVALID_INPUT
    ready = [candle(0), candle(1), candle(2)]
    before = contract.evaluate(ready, NOW + timedelta(hours=1))
    after_restart = WarmupContract({"resolved": 3}, 900).evaluate(tuple(ready), NOW + timedelta(hours=1))
    assert before is after_restart is ReadinessState.READY


def test_canonical_readiness_minimum_is_derived_from_declared_dependencies():
    dependencies = {item.name: item for item in CANONICAL_MODEL_READINESS_DEPENDENCIES}
    assert set(dependencies) == {"return_8", "return_32", "return_72", "abs_move_72"}
    assert dependencies["return_8"].minimum_observations == 9
    assert dependencies["return_32"].minimum_observations == 33
    assert dependencies["return_72"].minimum_observations == 73
    assert dependencies["abs_move_72"].minimum_observations == 73
    assert canonical_readiness_minimum_observations() == 73


@pytest.mark.parametrize("count", [0, 1, 71, 72])
def test_canonical_readiness_short_history_is_warming_up_not_invalid(count):
    contract = canonical_entry_readiness_contract()
    diagnosis = contract.diagnose(
        [candle(index) for index in range(count)],
        NOW + timedelta(days=2),
    )
    assert diagnosis.status is ReadinessState.WARMING_UP
    assert diagnosis.reason_code == "INSUFFICIENT_CANONICAL_HISTORY"
    assert diagnosis.required_observations == 73
    assert diagnosis.available_observations == count
    assert diagnosis.first_valid_timestamp is None
    assert diagnosis.blocking_dependency == "abs_move_72"


@pytest.mark.parametrize("count", [73, 74])
def test_canonical_readiness_ready_boundary_and_first_valid_timestamp(count):
    contract = canonical_entry_readiness_contract()
    candles = [candle(index) for index in range(count)]
    diagnosis = contract.diagnose(candles, NOW + timedelta(days=2))
    assert diagnosis.status is ReadinessState.READY
    assert diagnosis.reason_code == "READY"
    assert diagnosis.required_observations == 73
    assert diagnosis.available_observations == count
    assert diagnosis.first_valid_timestamp == candles[72].close_time.isoformat()


def test_canonical_readiness_rejects_count_only_windows_with_gaps():
    contract = canonical_entry_readiness_contract()
    gap = [
        *[candle(index) for index in range(40)],
        *[candle(index) for index in range(41, 74)],
    ]
    diagnosis = contract.diagnose(gap, NOW + timedelta(days=2))
    assert diagnosis.status is ReadinessState.INVALID_INPUT
    assert diagnosis.reason_code == "NON_CONTIGUOUS_CANONICAL_HISTORY"
    assert CANONICAL_ENTRY_INTERVAL_SECONDS == 900


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (lambda items: [*items[:3], candle(2), *items[4:]], "DUPLICATE_OBSERVATION"),
        (lambda items: [*items[:3], candle(1), *items[4:]], "OUT_OF_ORDER_OBSERVATION"),
        (lambda items: [*items[:-1], candle(72, closed=False)], "PARTIAL_CANDLE"),
        (lambda items: items, "FUTURE_OBSERVATION"),
    ],
)
def test_canonical_readiness_invalid_inputs_are_not_warmup(mutate, reason):
    contract = canonical_entry_readiness_contract()
    candles = mutate([candle(index) for index in range(73)])
    evaluation_time = (
        NOW + timedelta(minutes=30)
        if reason == "FUTURE_OBSERVATION"
        else NOW + timedelta(days=2)
    )
    diagnosis = contract.diagnose(candles, evaluation_time)
    assert diagnosis.status is ReadinessState.INVALID_INPUT
    assert diagnosis.reason_code == reason


def test_canonical_readiness_restart_reconstruction_parity():
    contract = canonical_entry_readiness_contract()
    left = [candle(index) for index in range(73)]
    reconstructed = tuple([*left[:36], *left[36:]])
    assert contract.diagnose(left, NOW + timedelta(days=2)) == contract.diagnose(
        reconstructed,
        NOW + timedelta(days=2),
    )


def test_provenance_round_trip_and_unknown_schema_fail_closed():
    item = EvaluationProvenance(
        NOW.isoformat(), H["a"], H["b"], H["c"], H["d"], H["e"],
        "common-evaluator/v1", H["f"],
    )
    assert EvaluationProvenance.from_dict(item.to_dict()) == item
    assert canonical_hash(item.to_dict()) == canonical_hash(item.to_dict())
    with pytest.raises(EvaluationContractError, match="provenance_schema_mismatch"):
        EvaluationProvenance.from_dict({**item.to_dict(), "unknown": "field"})
