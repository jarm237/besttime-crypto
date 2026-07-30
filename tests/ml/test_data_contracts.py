import pytest

from btc_scraper.ml_engine.data_contracts import (
    ContractRejectReason,
    DEFAULT_RUNTIME_CONTRACTS,
    validate_runtime_event,
)
from btc_scraper.ml_engine.prediction_logger import append_prediction


def _position_closed_event(**overrides):
    event = {
        "event_type": "position_closed",
        "schema_version": "position-closed-v1",
        "event_id": "evt-1",
        "event_time": "2026-07-16T00:00:00+00:00",
        "ingest_time": "2026-07-16T00:00:01+00:00",
        "producer": "position_tracker",
        "position_id": "pos-1",
        "closed_at": "2026-07-16T00:00:00+00:00",
        "net_pnl_pct": 1.25,
        "outcome_revision": 1,
    }
    event.update(overrides)
    return event


def test_default_contract_registry_is_versioned():
    payload = DEFAULT_RUNTIME_CONTRACTS.to_dict()
    assert payload["registry_version"] == "runtime-contracts-v1"
    assert payload["contracts"]["position_closed"]["schema_version"] == "position-closed-v1"
    assert payload["contracts"]["calibration_sample_created"]["schema_version"] == "calibration-sample-v1"


def test_position_closed_contract_accepts_required_runtime_fields():
    result = validate_runtime_event(_position_closed_event())
    assert result.ok
    assert result.errors == ()


def test_unknown_event_type_rejects_fail_closed():
    result = validate_runtime_event(_position_closed_event(event_type="mystery_event"))
    assert not result.ok
    assert result.errors[0].reason == ContractRejectReason.UNKNOWN_EVENT_TYPE


def test_schema_drift_rejects_fail_closed():
    result = validate_runtime_event(_position_closed_event(schema_version="position-closed-v2"))
    assert not result.ok
    assert result.errors[0].reason == ContractRejectReason.SCHEMA_VERSION_MISMATCH


def test_missing_required_field_and_scope_are_reported():
    result = validate_runtime_event(_position_closed_event(position_id="", outcome_revision=None))
    reasons = {error.reason for error in result.errors}
    assert ContractRejectReason.MISSING_REQUIRED_FIELD in reasons
    assert ContractRejectReason.EMPTY_BUSINESS_KEY in reasons
    assert ContractRejectReason.EMPTY_IDEMPOTENCY_SCOPE in reasons


def test_prediction_logger_emits_contract_valid_event(tmp_path):
    entry = append_prediction(
        model_name="meta_model",
        model_version="v1",
        artifact_sha256="abc",
        feature_schema_version="schema",
        raw_prediction=.7,
        calibrated_prediction=.7,
        features=[1, 2],
        decision_context="entry",
        symbol="BTC",
        timeframe="15m",
        side="BUY",
        signal_id="sig-contract-1",
        caller_context="contract_test",
        log_dir=tmp_path,
    )
    assert validate_runtime_event(entry).ok
    assert entry["event_type"] == "prediction_created"
    assert entry["schema_version"] == "prediction-created-v1"
    assert entry["feature_snapshot_id"]
    assert entry["valid_until"]
    assert entry["raw_probability"] == .7
    assert entry["calibrated_probability"] == .7


def test_prediction_contract_rejects_missing_production_lineage():
    event = {
        "event_type": "prediction_created",
        "schema_version": "prediction-created-v1",
        "event_id": "evt-1",
        "event_time": "2026-07-16T00:00:00+00:00",
        "ingest_time": "2026-07-16T00:00:01+00:00",
        "producer": "prediction_logger",
        "prediction_id": "pred-1",
        "timestamp": "2026-07-16T00:00:00+00:00",
        "predicted_at": "2026-07-16T00:00:00+00:00",
        "model_name": "meta_model",
        "model_version": "v1",
        "feature_schema_version": "schema",
        "feature_hash": "hash",
        "raw_probability": .7,
        "calibrated_probability": .7,
        "decision_context": "entry",
    }
    result = validate_runtime_event(event)
    fields = {error.field for error in result.errors}
    assert not result.ok
    assert {
        "artifact_sha256",
        "feature_snapshot_id",
        "symbol",
        "timeframe",
        "side",
        "valid_until",
        "signal_id",
        "caller_context",
        "deployment_id",
    }.issubset(fields)


def test_prediction_logger_rejects_schema_override(tmp_path):
    with pytest.raises(ValueError, match="event contract validation failed"):
        append_prediction(
            model_name="meta_model",
            model_version="v1",
            artifact_sha256="abc",
            feature_schema_version="schema",
            raw_prediction=.7,
            calibrated_prediction=.7,
            features=[1, 2],
            decision_context="entry",
            symbol="BTC",
            timeframe="15m",
            side="BUY",
            signal_id="sig-schema-override",
            caller_context="contract_test",
            extra={"schema_version": "prediction-created-v2"},
            log_dir=tmp_path,
        )


def test_prediction_logger_rejects_missing_artifact_hash(tmp_path):
    with pytest.raises(ValueError, match="event contract validation failed"):
        append_prediction(
            model_name="meta_model",
            model_version="v1",
            artifact_sha256=None,
            feature_schema_version="schema",
            raw_prediction=.7,
            calibrated_prediction=.7,
            features=[1, 2],
            decision_context="entry",
            symbol="BTC",
            timeframe="15m",
            side="BUY",
            signal_id="sig-missing-hash",
            caller_context="contract_test",
            log_dir=tmp_path,
        )
