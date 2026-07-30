from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone
from multiprocessing import get_context
import sqlite3

import pytest

from btc_scraper.ml_engine.runtime_evidence_store import (
    RUNTIME_EVIDENCE_SCHEMA_VERSION,
    RuntimeEvidenceStore,
    idempotency_payload_sha256,
)


def _payload(index):
    prediction = {"prediction_id": f"p-{index}", "probability": .6, "feature_hash": f"h-{index}"}
    snapshot = {"prediction_id": f"p-{index}", "features": [index], "feature_hash": f"h-{index}"}
    return prediction, snapshot


def _idempotent_payload(prediction_id, *, feature_hash="shared-hash"):
    prediction = {
        "prediction_id": prediction_id,
        "idempotency_key": "shared-key",
        "probability": .6,
        "feature_hash": feature_hash,
    }
    snapshot = {
        "prediction_id": prediction_id,
        "features": [1, 2, 3],
        "feature_hash": feature_hash,
    }
    return prediction, snapshot


def _multiprocess_global_write(args):
    path, prediction_id = args
    store = RuntimeEvidenceStore(path)
    return store.write_prediction_evidence(
        *_idempotent_payload(prediction_id)
    )["prediction_id"]


def _multiprocess_global_recover(path):
    return RuntimeEvidenceStore(path).recover_global_reservations()


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


def test_global_idempotency_serializes_two_processes(tmp_path):
    path = tmp_path / "runtime_evidence.sqlite"
    with get_context("spawn").Pool(2) as pool:
        prediction_ids = pool.map(
            _multiprocess_global_write,
            [(path, "p-process-a"), (path, "p-process-b")],
        )

    store = RuntimeEvidenceStore(path)
    assert len(set(prediction_ids)) == 1
    assert store.count_rows("predictions") == 1
    assert store.health()["predictions_without_global_commit"] == 0


def test_global_idempotency_uses_first_canonical_utc_partition(tmp_path):
    current_a = datetime(2026, 7, 30, 23, 59, 59, tzinfo=timezone.utc)
    current_b = datetime(2026, 7, 31, 0, 0, 1, tzinfo=timezone.utc)
    path = tmp_path / "runtime_evidence.sqlite"
    store_a = RuntimeEvidenceStore(path, clock=lambda: current_a)
    store_b = RuntimeEvidenceStore(path, clock=lambda: current_b)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(
            lambda item: item[0].write_prediction_evidence(
                *_idempotent_payload(item[1])
            ),
            ((store_a, "p-day-a"), (store_b, "p-day-b")),
        ))

    assert len({row["prediction_id"] for row in results}) == 1
    with store_a._global_connect() as db:
        row = db.execute(
            "SELECT prediction_id,partition_date,state "
            "FROM prediction_global_idempotency WHERE idempotency_key='shared-key'"
        ).fetchone()
    assert row[1] in {"2026-07-30", "2026-07-31"}
    canonical_path = store_a.partition_path(row[1])
    with store_a._connect(canonical_path) as db:
        assert db.execute("SELECT COUNT(*) FROM predictions").fetchone()[0] == 1
    assert row[2] == "COMMITTED"


def test_stale_reservation_without_partition_write_is_aborted_and_replayable(tmp_path):
    current = [datetime(2026, 7, 30, tzinfo=timezone.utc)]
    store = RuntimeEvidenceStore(
        tmp_path / "runtime_evidence.sqlite",
        clock=lambda: current[0],
    )
    prediction, snapshot = _idempotent_payload("p-reserved")
    prediction_with_metadata = store._with_runtime_metadata(prediction)
    reservation = store._reserve_global_prediction(
        idempotency_key="shared-key",
        prediction_id="p-reserved",
        payload_hash=idempotency_payload_sha256(prediction_with_metadata),
    )
    assert reservation["state"] == "RESERVED"

    current[0] = datetime(2026, 7, 30, 0, 10, tzinfo=timezone.utc)
    assert store.recover_global_reservations(stale_after_seconds=60)["aborted"] == 1
    persisted = store.write_prediction_evidence(prediction, snapshot)
    assert persisted["prediction_id"] == "p-reserved"
    assert store._get_global_reservation("shared-key")["state"] == "COMMITTED"


def test_recovery_commits_partition_write_left_reserved_after_crash(
    tmp_path, monkeypatch,
):
    path = tmp_path / "runtime_evidence.sqlite"
    store = RuntimeEvidenceStore(path)
    original_mark = store._mark_global_committed
    monkeypatch.setattr(
        store,
        "_mark_global_committed",
        lambda _key: (_ for _ in ()).throw(RuntimeError("simulated crash")),
    )
    with pytest.raises(RuntimeError, match="simulated crash"):
        store.write_prediction_evidence(*_idempotent_payload("p-crash"))

    monkeypatch.setattr(store, "_mark_global_committed", original_mark)
    restarted = RuntimeEvidenceStore(path)
    assert restarted.recover_global_reservations()["recovered"] == 1
    assert restarted.get_prediction_by_idempotency_key("shared-key")["prediction_id"] == "p-crash"


def test_replay_after_restart_returns_canonical_prediction(tmp_path):
    path = tmp_path / "runtime_evidence.sqlite"
    first = RuntimeEvidenceStore(path)
    persisted = first.write_prediction_evidence(
        *_idempotent_payload("p-first")
    )
    restarted = RuntimeEvidenceStore(path)
    replay = restarted.write_prediction_evidence(
        *_idempotent_payload("p-replay")
    )
    assert replay["prediction_id"] == persisted["prediction_id"]
    assert restarted.count_rows("predictions") == 1


def test_same_global_key_with_different_feature_hash_conflicts(tmp_path):
    store = RuntimeEvidenceStore(tmp_path / "runtime_evidence.sqlite")
    store.write_prediction_evidence(
        *_idempotent_payload("p-first", feature_hash="hash-a")
    )
    with pytest.raises(ValueError, match="non-idempotent"):
        store.write_prediction_evidence(
            *_idempotent_payload("p-second", feature_hash="hash-b")
        )
    assert store.count_rows("predictions") == 1
    assert store._get_global_reservation("shared-key")["error_reason"] == "conflicting_payload_hash"


@pytest.mark.parametrize("failure", [
    sqlite3.DatabaseError("database disk image is malformed"),
    sqlite3.OperationalError("database is locked"),
])
def test_global_index_failure_is_fail_closed(tmp_path, monkeypatch, failure):
    store = RuntimeEvidenceStore(tmp_path / "runtime_evidence.sqlite")
    monkeypatch.setattr(
        store,
        "_global_connect",
        lambda: (_ for _ in ()).throw(failure),
    )
    with pytest.raises(type(failure)):
        store.write_prediction_evidence(
            *_idempotent_payload("p-global-failure")
        )
    assert store.count_rows("predictions") == 0


def test_corrupt_global_index_blocks_store_startup(tmp_path):
    global_path = tmp_path / "global_evidence_index.sqlite"
    global_path.write_bytes(b"not-a-sqlite-database")
    with pytest.raises(sqlite3.DatabaseError):
        RuntimeEvidenceStore(tmp_path / "runtime_evidence.sqlite")


def test_partition_write_failure_aborts_global_reservation(tmp_path, monkeypatch):
    store = RuntimeEvidenceStore(tmp_path / "runtime_evidence.sqlite")

    @contextmanager
    def broken_transaction(_path=None):
        raise OSError("partition unavailable")
        yield

    monkeypatch.setattr(store, "transaction", broken_transaction)
    with pytest.raises(OSError, match="partition unavailable"):
        store.write_prediction_evidence(
            *_idempotent_payload("p-partition-failure")
        )
    assert store._get_global_reservation("shared-key")["state"] == "ABORTED"


def test_concurrent_recovery_is_idempotent(tmp_path, monkeypatch):
    path = tmp_path / "runtime_evidence.sqlite"
    store = RuntimeEvidenceStore(path)
    original_mark = store._mark_global_committed
    monkeypatch.setattr(
        store,
        "_mark_global_committed",
        lambda _key: (_ for _ in ()).throw(RuntimeError("simulated crash")),
    )
    with pytest.raises(RuntimeError):
        store.write_prediction_evidence(*_idempotent_payload("p-recovery"))
    monkeypatch.setattr(store, "_mark_global_committed", original_mark)

    with get_context("spawn").Pool(2) as pool:
        pool.map(_multiprocess_global_recover, (path, path))
    assert store._get_global_reservation("shared-key")["state"] == "COMMITTED"
    assert store.count_rows("predictions") == 1


def test_schema_v3_partitions_are_backfilled_without_evidence_loss(tmp_path):
    path = tmp_path / "runtime_evidence.sqlite"
    old_store = RuntimeEvidenceStore(path)
    old_store.write_prediction_evidence(*_payload(42))
    old_store.global_index_path.unlink()

    migrated = RuntimeEvidenceStore(path)
    assert migrated.get_prediction("p-42")["prediction_id"] == "p-42"
    assert migrated._get_global_reservation("prediction_id:p-42")["state"] == "COMMITTED"
    assert migrated.health()["status"] == "healthy"
