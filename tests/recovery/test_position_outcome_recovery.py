from tests.recovery.helpers import make_coordinator, seed_prediction


def test_closed_position_creates_one_outcome_with_prediction_lineage(recovery_paths):
    coord = make_coordinator(recovery_paths)
    prediction = seed_prediction(coord.evidence_store, "pred-position-outcome")
    outcome = {
        "outcome_id": "out-position-outcome",
        "prediction_id": prediction["prediction_id"],
        "position_id": "pos-position-outcome",
        "outcome_revision": 1,
        "net_pnl_pct": 1.5,
        "model_version": prediction["model_version"],
        "artifact_sha256": prediction["artifact_sha256"],
        "feature_schema_version": prediction["feature_schema_version"],
    }

    assert coord.recover_outcome(outcome).status == "linked"
    assert make_coordinator(recovery_paths).recover_outcome(outcome).status == "linked"

    restarted = make_coordinator(recovery_paths)
    assert restarted.evidence_store.count_rows("outcome_links") == 1
    latest = restarted.evidence_store.latest_outcomes()
    assert latest[0]["prediction_id"] == prediction["prediction_id"]
    assert latest[0]["model_version"] == prediction["model_version"]
    assert latest[0]["artifact_sha256"] == prediction["artifact_sha256"]
