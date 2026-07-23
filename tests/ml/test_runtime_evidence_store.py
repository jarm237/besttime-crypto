from concurrent.futures import ThreadPoolExecutor

import pytest

from btc_scraper.ml_engine.runtime_evidence_store import RuntimeEvidenceStore


def _payload(index):
    prediction = {"prediction_id": f"p-{index}", "probability": .6, "feature_hash": f"h-{index}"}
    snapshot = {"prediction_id": f"p-{index}", "features": [index], "feature_hash": f"h-{index}"}
    return prediction, snapshot


def test_prediction_and_snapshot_are_atomic_and_idempotent(tmp_path):
    store = RuntimeEvidenceStore(tmp_path / "evidence.sqlite")
    prediction, snapshot = _payload(1)
    store.write_prediction_evidence(prediction, snapshot)
    store.write_prediction_evidence(prediction, snapshot)
    assert store.health()["status"] == "healthy"


def test_non_idempotent_duplicate_is_rejected(tmp_path):
    store = RuntimeEvidenceStore(tmp_path / "evidence.sqlite")
    prediction, snapshot = _payload(1)
    store.write_prediction_evidence(prediction, snapshot)
    with pytest.raises(ValueError, match="non-idempotent"):
        store.write_prediction_evidence({**prediction, "probability": .9}, snapshot)


def test_concurrent_evidence_writes_preserve_all_rows(tmp_path):
    store = RuntimeEvidenceStore(tmp_path / "evidence.sqlite")
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda i: store.write_prediction_evidence(*_payload(i)), range(30)))
    with store._connect() as db:
        assert db.execute("SELECT COUNT(*) FROM predictions").fetchone()[0] == 30
        assert db.execute("SELECT COUNT(*) FROM feature_snapshots").fetchone()[0] == 30


def test_failed_atomic_write_leaves_no_partial_prediction(tmp_path):
    store = RuntimeEvidenceStore(tmp_path / "evidence.sqlite")
    prediction, snapshot = _payload(1)
    with pytest.raises(ValueError, match="identity mismatch"):
        store.write_prediction_evidence(prediction, {**snapshot, "prediction_id": "other"})
    with store._connect() as db:
        assert db.execute("SELECT COUNT(*) FROM predictions").fetchone()[0] == 0


def test_outcome_must_reference_existing_prediction(tmp_path):
    store = RuntimeEvidenceStore(tmp_path / "evidence.sqlite")
    with pytest.raises(ValueError, match="unknown prediction"):
        store.append_outcome_link({"outcome_id": "o-1", "prediction_id": "missing"})


def test_corrupt_payload_is_quarantined_and_health_degrades(tmp_path):
    store = RuntimeEvidenceStore(tmp_path / "evidence.sqlite")
    store.write_prediction_evidence(*_payload(1))
    with store._connect() as db:
        db.execute("UPDATE predictions SET payload='tampered' WHERE prediction_id='p-1'")
    health = store.health()
    assert health["status"] == "degraded"
    assert health["quarantined_corrupt_payloads"] == 1
