from tests.recovery.helpers import make_coordinator, seed_prediction


def test_prediction_persisted_decision_missing_recovers_once_with_lineage(recovery_paths):
    first = make_coordinator(recovery_paths)
    prediction = seed_prediction(first.evidence_store, "pred-p1-6-s1")

    result = first.recover_final_decision(
        prediction["prediction_id"],
        lambda pred: {"action": "BUY", "status": "eligible", "signal_id": pred["signal_id"]},
    )
    assert result.status == "recovered"

    restarted = make_coordinator(recovery_paths)
    replay = restarted.recover_final_decision(
        prediction["prediction_id"],
        lambda pred: {"action": "SELL", "status": "eligible", "signal_id": pred["signal_id"]},
    )
    assert replay.status == "already_recovered"
    assert restarted.evidence_store.count_rows("predictions") == 1
    assert restarted.evidence_store.count_rows("feature_snapshots") == 1
    assert restarted.evidence_store.count_rows("final_decisions") == 1

    decision = restarted.evidence_store.get_final_decision_for_prediction(prediction["prediction_id"])
    assert decision["prediction_id"] == prediction["prediction_id"]
    assert decision["model_version"] == prediction["model_version"]
    assert decision["artifact_sha256"] == prediction["artifact_sha256"]
    assert decision["feature_schema_version"] == prediction["feature_schema_version"]
