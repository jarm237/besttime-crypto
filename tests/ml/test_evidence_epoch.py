from datetime import datetime, timezone

import pytest

from btc_scraper.ml_engine.evidence_epoch import EvidenceEpoch
from btc_scraper.ml_engine.runtime_evidence_store import RuntimeEvidenceStore


def _epoch(epoch_id="epoch-canary-1", **overrides):
    values = {
        "epoch_id": epoch_id,
        "deployment_id": "paper-shadow-20260730-01",
        "started_at": datetime(2026, 7, 30, tzinfo=timezone.utc).isoformat(),
        "code_commit_sha": "c42b802",
        "model_version": "meta-v3",
        "artifact_sha256": "artifact-v3",
        "feature_schema_version": "schema-v3",
    }
    values.update(overrides)
    return EvidenceEpoch(**values)


def _eligible_prediction(prediction_id="p-epoch", **overrides):
    prediction = {
        "event_type": "prediction_created",
        "prediction_id": prediction_id,
        "idempotency_key": f"key-{prediction_id}",
        "signal_id": f"signal-{prediction_id}",
        "deployment_id": "paper-shadow-20260730-01",
        "symbol": "BTCUSDT",
        "decision_context": "entry",
        "caller_context": "agent_orchestrator",
        "model_version": "meta-v3",
        "artifact_sha256": "artifact-v3",
        "feature_schema_version": "schema-v3",
        "feature_hash": f"hash-{prediction_id}",
        "git_commit": "c42b802",
        "evidence_eligible": True,
    }
    prediction.update(overrides)
    snapshot = {
        "prediction_id": prediction_id,
        "feature_hash": prediction["feature_hash"],
        "features": [1.0, 2.0],
    }
    return prediction, snapshot


def test_eligible_prediction_requires_active_epoch(tmp_path):
    store = RuntimeEvidenceStore(tmp_path / "runtime_evidence.sqlite")
    with pytest.raises(RuntimeError, match="ACTIVE epoch"):
        store.write_prediction_evidence(*_eligible_prediction())
    assert store.count_rows("predictions") == 0


def test_active_epoch_is_persisted_and_attached_to_evidence(tmp_path):
    path = tmp_path / "runtime_evidence.sqlite"
    store = RuntimeEvidenceStore(path)
    store.create_evidence_epoch(_epoch())
    store.transition_evidence_epoch("epoch-canary-1", "ACTIVE")

    prediction = store.write_prediction_evidence(*_eligible_prediction())
    assert prediction["epoch_id"] == "epoch-canary-1"
    assert store.get_feature_snapshot("p-epoch")["epoch_id"] == "epoch-canary-1"

    restarted = RuntimeEvidenceStore(path)
    assert restarted.get_active_evidence_epoch().epoch_id == "epoch-canary-1"


@pytest.mark.parametrize("field,value", [
    ("deployment_id", "other-deployment"),
    ("model_version", "other-model"),
    ("artifact_sha256", "other-artifact"),
    ("feature_schema_version", "other-schema"),
    ("git_commit", "other-commit"),
    ("epoch_id", "other-epoch"),
])
def test_active_epoch_rejects_mixed_lineage(tmp_path, field, value):
    store = RuntimeEvidenceStore(tmp_path / "runtime_evidence.sqlite")
    store.create_evidence_epoch(_epoch())
    store.transition_evidence_epoch("epoch-canary-1", "ACTIVE")
    prediction, snapshot = _eligible_prediction(**{field: value})
    with pytest.raises(RuntimeError, match="active evidence epoch mismatch"):
        store.write_prediction_evidence(prediction, snapshot)
    assert store.count_rows("predictions") == 0


def test_sealed_epoch_cannot_receive_new_evidence(tmp_path):
    store = RuntimeEvidenceStore(tmp_path / "runtime_evidence.sqlite")
    store.create_evidence_epoch(_epoch())
    store.transition_evidence_epoch("epoch-canary-1", "ACTIVE")
    store.transition_evidence_epoch("epoch-canary-1", "SEALED")

    with pytest.raises(RuntimeError, match="ACTIVE epoch"):
        store.write_prediction_evidence(*_eligible_prediction())


def test_epoch_state_machine_and_single_active_epoch(tmp_path):
    store = RuntimeEvidenceStore(tmp_path / "runtime_evidence.sqlite")
    store.create_evidence_epoch(_epoch("epoch-a"))
    store.create_evidence_epoch(_epoch("epoch-b"))
    store.transition_evidence_epoch("epoch-a", "ACTIVE")
    with pytest.raises(Exception):
        store.transition_evidence_epoch("epoch-b", "ACTIVE")
    with pytest.raises(ValueError, match="invalid evidence epoch transition"):
        store.transition_evidence_epoch("epoch-a", "DRAFT")
    assert store.transition_evidence_epoch("epoch-a", "SEALED").status == "SEALED"
    assert store.transition_evidence_epoch("epoch-b", "ACTIVE").status == "ACTIVE"


def test_epoch_policy_versions_fail_closed(tmp_path):
    store = RuntimeEvidenceStore(tmp_path / "runtime_evidence.sqlite")
    with pytest.raises(ValueError, match="evidence policy"):
        store.create_evidence_epoch(_epoch(
            evidence_policy_version="legacy-policy",
        ))
    with pytest.raises(ValueError, match="risk policy"):
        store.create_evidence_epoch(_epoch(
            risk_policy_version="legacy-risk",
        ))
