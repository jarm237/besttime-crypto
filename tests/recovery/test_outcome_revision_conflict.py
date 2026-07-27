import pytest

from tests.recovery.helpers import make_coordinator, seed_prediction


def test_outcome_revision_replay_and_conflicts_are_idempotent_or_quarantined(recovery_paths):
    coord = make_coordinator(recovery_paths)
    prediction = seed_prediction(coord.evidence_store, "pred-outcome-revision")
    base = {
        "prediction_id": prediction["prediction_id"],
        "position_id": "pos-outcome-revision",
    }
    revision_1 = {**base, "outcome_id": "out-rev-1", "outcome_revision": 1, "net_pnl_pct": 1.0}
    revision_2 = {**base, "outcome_id": "out-rev-2", "outcome_revision": 2, "net_pnl_pct": 2.0}

    coord.recover_outcome(revision_1)
    coord.recover_outcome(revision_1)
    assert coord.evidence_store.count_rows("outcome_links") == 1

    coord.recover_outcome(revision_2)
    assert coord.evidence_store.latest_outcomes()[0]["outcome_revision"] == 2

    with pytest.raises(ValueError, match="conflicting outcome amendment|non-idempotent"):
        coord.recover_outcome({**base, "outcome_id": "out-rev-conflict", "outcome_revision": 2, "net_pnl_pct": 9.0})

    with pytest.raises(ValueError, match="stale lower outcome revision"):
        coord.recover_outcome({**base, "outcome_id": "out-rev-lower", "outcome_revision": 1, "net_pnl_pct": -1.0})

    assert coord.evidence_store.count_rows("evidence_quarantine") >= 2
