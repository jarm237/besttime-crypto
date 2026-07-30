from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import sqlite3

import pytest

from btc_scraper.ml_engine.runtime_evidence_store import RUNTIME_EVIDENCE_SCHEMA_VERSION, RuntimeEvidenceStore


def _payload(index):
    prediction = {"prediction_id": f"p-{index}", "probability": .6, "feature_hash": f"h-{index}"}
    snapshot = {"prediction_id": f"p-{index}", "features": [index], "feature_hash": f"h-{index}"}
    return prediction, snapshot


def test_database_schema_version_is_explicit(tmp_path):
    store = RuntimeEvidenceStore(tmp_path / "evidence.sqlite")
    with store._connect() as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == RUNTIME_EVIDENCE_SCHEMA_VERSION


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
    health = store.health()
    assert health["status"] == "degraded"
    assert health["unresolved_incidents"] == 1


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


def test_final_decision_requires_one_unique_known_prediction(tmp_path):
    store = RuntimeEvidenceStore(tmp_path / "evidence.sqlite")
    store.write_prediction_evidence(*_payload(1))
    with pytest.raises(ValueError, match="exactly one prediction"):
        store.append_final_decision({"decision_id": "d-missing"})
    store.append_final_decision({"decision_id": "d-1", "prediction_id": "p-1", "action": "HOLD"})
    with pytest.raises(ValueError, match="already has"):
        store.append_final_decision({"decision_id": "d-2", "prediction_id": "p-1", "action": "BUY"})
    health = store.health()
    assert health["status"] == "degraded"
    assert health["quarantined_records"] == 1


def test_latest_outcome_revision_is_canonical_and_conflicts_quarantine(tmp_path):
    store = RuntimeEvidenceStore(tmp_path / "evidence.sqlite")
    store.write_prediction_evidence(*_payload(1))
    base = {"prediction_id": "p-1", "position_id": "pos-1"}
    store.append_outcome_link({**base, "outcome_id": "o-1", "outcome_revision": 1, "net_pnl_pct": -1.0})
    store.append_outcome_link({**base, "outcome_id": "o-2", "outcome_revision": 2, "net_pnl_pct": 2.0})
    latest = store.latest_outcomes()
    assert len(latest) == 1
    assert {
        key: latest[0][key]
        for key in ("prediction_id", "position_id", "outcome_id", "outcome_revision", "net_pnl_pct")
    } == {**base, "outcome_id": "o-2", "outcome_revision": 2, "net_pnl_pct": 2.0}
    assert latest[0]["environment"] == "test"
    assert latest[0]["evidence_eligible"] is False
    with pytest.raises(ValueError, match="conflicting outcome amendment"):
        store.append_outcome_link({**base, "outcome_id": "o-other", "outcome_revision": 2, "net_pnl_pct": 9.0})
    assert store.health()["status"] == "degraded"


def test_corrupt_payload_is_quarantined_and_health_degrades(tmp_path):
    store = RuntimeEvidenceStore(tmp_path / "evidence.sqlite")
    store.write_prediction_evidence(*_payload(1))
    with store._connect() as db:
        db.execute("UPDATE predictions SET payload='tampered' WHERE prediction_id='p-1'")
    health = store.health()
    assert health["status"] == "degraded"
    assert health["quarantined_corrupt_payloads"] == 1


def test_invalid_production_lineage_is_quarantined_and_excluded_from_shadow(tmp_path):
    store = RuntimeEvidenceStore(tmp_path / "evidence.sqlite")
    prediction, snapshot = _payload(1)
    prediction.update({
        "event_type": "prediction_created",
        "signal_id": None,
        "deployment_id": "deployment-test",
        "caller_context": "agent_orchestrator",
        "decision_context": "entry",
        "model_version": "meta-test",
        "artifact_sha256": "artifact-test",
        "feature_schema_version": "schema-test",
        "symbol": "UNKNOWN",
    })
    store.write_prediction_evidence(prediction, snapshot)

    assert store.health()["status"] == "degraded"
    assert store.shadow_evidence_rows()["predictions"] == []


def test_health_exposes_required_evidence_rates(tmp_path):
    store = RuntimeEvidenceStore(tmp_path / "evidence.sqlite")
    prediction, snapshot = _payload(1)
    prediction.update({
        "event_type": "prediction_created",
        "signal_id": "signal-1",
        "deployment_id": "paper-shadow-v1",
        "caller_context": "agent_orchestrator",
        "decision_context": "entry",
        "model_version": "meta-v3",
        "artifact_sha256": "artifact-v3",
        "feature_schema_version": "schema-v3",
        "symbol": "BTCUSDT",
    })
    store.write_prediction_evidence(prediction, snapshot)

    health = store.health()
    assert health["severity"] == "HEALTHY"
    assert health["invalid_lineage_rate"] == 0.0
    assert health["duplicate_prediction_rate"] == 0.0
    assert health["orphan_decision_rate"] == 0.0
    assert health["missing_outcome_rate"] == 0.0
    assert health["unknown_symbol_rate"] == 0.0


def test_health_reports_foreign_key_violations_and_orphans(tmp_path):
    store = RuntimeEvidenceStore(tmp_path / "evidence.sqlite")
    with store._connect() as db:
        db.execute("PRAGMA foreign_keys=OFF")
        db.execute(
            "INSERT INTO outcome_links VALUES (?,?,?,?,?)",
            ("o-orphan", "p-missing", "{}", "bad-hash", "2026-01-01T00:00:00+00:00"),
        )
    health = store.health()
    assert health["status"] == "degraded"
    assert health["orphan_outcomes"] == 1
    assert health["foreign_key_violations"] == 1


def test_writes_roll_over_to_daily_utc_partitions_and_reads_across_them(tmp_path):
    current = [datetime(2026, 7, 29, 23, 59, tzinfo=timezone.utc)]
    base_path = tmp_path / "runtime_evidence.sqlite"
    store = RuntimeEvidenceStore(base_path, clock=lambda: current[0])

    store.write_prediction_evidence(*_payload(1))
    store.append_audit_event({"event_type": "day-one"})
    current[0] = datetime(2026, 7, 30, 0, 1, tzinfo=timezone.utc)
    store.write_prediction_evidence(*_payload(2))
    store.append_audit_event({"event_type": "day-two"})

    first_path = tmp_path / "runtime_evidence_2026-07-29.sqlite"
    second_path = tmp_path / "runtime_evidence_2026-07-30.sqlite"
    assert first_path.exists()
    assert second_path.exists()
    assert not base_path.exists()
    assert store.get_prediction("p-1")["prediction_id"] == "p-1"
    assert store.get_feature_snapshot("p-2")["prediction_id"] == "p-2"
    assert store.count_rows("predictions") == 2
    assert {row["event_type"] for row in store.shadow_evidence_rows()["audit_events"]} == {
        "day-one", "day-two",
    }


def test_decisions_and_outcomes_follow_prediction_partition_after_rollover(tmp_path):
    current = [datetime(2026, 7, 29, 23, 59, tzinfo=timezone.utc)]
    store = RuntimeEvidenceStore(tmp_path / "runtime_evidence.sqlite", clock=lambda: current[0])
    store.write_prediction_evidence(*_payload(1))
    prediction_path = store.current_path

    current[0] = datetime(2026, 7, 30, 0, 1, tzinfo=timezone.utc)
    store.append_final_decision({"decision_id": "d-1", "prediction_id": "p-1", "action": "HOLD"})
    store.append_outcome_link({
        "outcome_id": "o-1",
        "prediction_id": "p-1",
        "position_id": "pos-1",
        "outcome_revision": 1,
    })

    with store._connect(prediction_path) as db:
        assert db.execute("SELECT COUNT(*) FROM final_decisions").fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM outcome_links").fetchone()[0] == 1
    with store._connect() as db:
        assert db.execute("SELECT COUNT(*) FROM final_decisions").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM outcome_links").fetchone()[0] == 0
    assert store.get_final_decision_for_prediction("p-1")["decision_id"] == "d-1"
    assert store.latest_outcomes()[0]["outcome_id"] == "o-1"
    assert store.health()["status"] == "healthy"


def test_legacy_undated_database_remains_readable_with_new_partitions(tmp_path):
    day_one = datetime(2026, 7, 29, tzinfo=timezone.utc)
    base_path = tmp_path / "runtime_evidence.sqlite"
    old_store = RuntimeEvidenceStore(base_path, clock=lambda: day_one)
    old_store.write_prediction_evidence(*_payload(1))
    old_partition = old_store.current_path
    with old_store._connect() as source, sqlite3.connect(base_path) as destination:
        source.backup(destination)
    old_partition.unlink()

    day_two = datetime(2026, 7, 30, tzinfo=timezone.utc)
    store = RuntimeEvidenceStore(base_path, clock=lambda: day_two)
    store.write_prediction_evidence(*_payload(2))

    assert store.get_prediction("p-1")["prediction_id"] == "p-1"
    assert store.get_prediction("p-2")["prediction_id"] == "p-2"
    assert store.count_rows("predictions") == 2
    assert store.health()["status"] == "healthy"


def test_matching_legacy_and_partition_records_are_deduplicated(tmp_path):
    now = datetime(2026, 7, 30, tzinfo=timezone.utc)
    base_path = tmp_path / "runtime_evidence.sqlite"
    store = RuntimeEvidenceStore(base_path, clock=lambda: now)
    store.write_prediction_evidence(*_payload(1))
    with store._connect() as source, sqlite3.connect(base_path) as destination:
        source.backup(destination)

    assert store.count_rows("predictions") == 1
    assert len(store.shadow_evidence_rows()["predictions"]) == 1
    assert store.health()["status"] == "healthy"
