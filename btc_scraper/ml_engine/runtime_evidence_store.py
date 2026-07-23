"""Transactional, append-only SQLite evidence store for ML runtime lineage."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping

from .artifact_resolver import ROOT


def _canonical(payload: Mapping[str, Any]) -> str:
    return json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def payload_sha256(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


class RuntimeEvidenceStore:
    def __init__(self, path: Path | str = ROOT / "logs" / "runtime_evidence.sqlite") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30.0)
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS predictions (
                    prediction_id TEXT PRIMARY KEY, payload TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL, written_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS feature_snapshots (
                    prediction_id TEXT PRIMARY KEY REFERENCES predictions(prediction_id),
                    payload TEXT NOT NULL, payload_sha256 TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS final_decisions (
                    decision_id TEXT PRIMARY KEY, prediction_id TEXT REFERENCES predictions(prediction_id),
                    payload TEXT NOT NULL, payload_sha256 TEXT NOT NULL, written_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS outcome_links (
                    outcome_id TEXT PRIMARY KEY, prediction_id TEXT REFERENCES predictions(prediction_id),
                    payload TEXT NOT NULL, payload_sha256 TEXT NOT NULL, written_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS audit_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, event_type TEXT NOT NULL,
                    payload TEXT NOT NULL, payload_sha256 TEXT NOT NULL, written_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS evidence_quarantine (
                    table_name TEXT NOT NULL, record_id TEXT NOT NULL, reason TEXT NOT NULL,
                    detected_at TEXT NOT NULL, PRIMARY KEY(table_name, record_id)
                );
            """)

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def write_prediction_evidence(self, prediction: Mapping[str, Any], snapshot: Mapping[str, Any]) -> None:
        prediction_id = str(prediction["prediction_id"])
        if str(snapshot.get("prediction_id")) != prediction_id:
            raise ValueError("prediction/snapshot identity mismatch")
        pred_json, snap_json = _canonical(prediction), _canonical(snapshot)
        written_at = datetime.now(timezone.utc).isoformat()
        with self.transaction() as db:
            existing = db.execute("SELECT payload_sha256 FROM predictions WHERE prediction_id=?", (prediction_id,)).fetchone()
            digest = payload_sha256(prediction)
            if existing and existing[0] != digest:
                raise ValueError("non-idempotent duplicate prediction")
            existing_snapshot = db.execute(
                "SELECT payload_sha256 FROM feature_snapshots WHERE prediction_id=?", (prediction_id,)
            ).fetchone()
            snapshot_digest = payload_sha256(snapshot)
            if existing_snapshot and existing_snapshot[0] != snapshot_digest:
                raise ValueError("non-idempotent duplicate feature snapshot")
            db.execute(
                "INSERT OR IGNORE INTO predictions VALUES (?, ?, ?, ?)",
                (prediction_id, pred_json, digest, written_at),
            )
            db.execute(
                "INSERT OR IGNORE INTO feature_snapshots VALUES (?, ?, ?)",
                (prediction_id, snap_json, snapshot_digest),
            )

    def append_final_decision(self, decision: Mapping[str, Any]) -> None:
        decision_id = str(decision["decision_id"])
        payload = _canonical(decision)
        with self.transaction() as db:
            digest = payload_sha256(decision)
            existing = db.execute("SELECT payload_sha256 FROM final_decisions WHERE decision_id=?", (decision_id,)).fetchone()
            if existing and existing[0] != digest:
                raise ValueError("non-idempotent duplicate final decision")
            db.execute(
                "INSERT OR IGNORE INTO final_decisions VALUES (?, ?, ?, ?, ?)",
                (decision_id, decision.get("prediction_id"), payload, digest, datetime.now(timezone.utc).isoformat()),
            )

    def append_audit_event(self, event: Mapping[str, Any]) -> None:
        payload = _canonical(event)
        with self.transaction() as db:
            db.execute(
                "INSERT INTO audit_events(event_type,payload,payload_sha256,written_at) VALUES (?,?,?,?)",
                (str(event.get("event_type", "unknown")), payload, payload_sha256(event), datetime.now(timezone.utc).isoformat()),
            )

    def append_outcome_link(self, outcome: Mapping[str, Any]) -> None:
        outcome_id = str(outcome["outcome_id"])
        prediction_id = str(outcome["prediction_id"])
        payload = _canonical(outcome)
        with self.transaction() as db:
            if db.execute("SELECT 1 FROM predictions WHERE prediction_id=?", (prediction_id,)).fetchone() is None:
                raise ValueError("outcome references unknown prediction")
            digest = payload_sha256(outcome)
            existing = db.execute("SELECT payload_sha256 FROM outcome_links WHERE outcome_id=?", (outcome_id,)).fetchone()
            if existing and existing[0] != digest:
                raise ValueError("non-idempotent duplicate outcome link")
            db.execute(
                "INSERT OR IGNORE INTO outcome_links VALUES (?, ?, ?, ?, ?)",
                (outcome_id, prediction_id, payload, digest, datetime.now(timezone.utc).isoformat()),
            )

    def health(self) -> dict[str, Any]:
        corrupt_payloads = self.verify_and_quarantine()
        with self._connect() as db:
            orphan_snapshots = db.execute(
                "SELECT COUNT(*) FROM feature_snapshots s LEFT JOIN predictions p USING(prediction_id) WHERE p.prediction_id IS NULL"
            ).fetchone()[0]
            missing_snapshots = db.execute(
                "SELECT COUNT(*) FROM predictions p LEFT JOIN feature_snapshots s USING(prediction_id) WHERE s.prediction_id IS NULL"
            ).fetchone()[0]
            integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
        return {
            "status": "healthy" if integrity == "ok" and orphan_snapshots == 0 and missing_snapshots == 0 and corrupt_payloads == 0 else "degraded",
            "integrity": integrity, "orphan_snapshots": orphan_snapshots, "missing_snapshots": missing_snapshots,
            "quarantined_corrupt_payloads": corrupt_payloads,
        }

    def verify_and_quarantine(self) -> int:
        corrupt: list[tuple[str, str]] = []
        table_keys = {
            "predictions": "prediction_id", "feature_snapshots": "prediction_id",
            "final_decisions": "decision_id", "outcome_links": "outcome_id",
        }
        with self.transaction() as db:
            for table, key in table_keys.items():
                for record_id, payload, digest in db.execute(f"SELECT {key}, payload, payload_sha256 FROM {table}"):
                    actual = hashlib.sha256(str(payload).encode("utf-8")).hexdigest()
                    if actual != digest:
                        corrupt.append((table, str(record_id)))
                        db.execute(
                            "INSERT OR IGNORE INTO evidence_quarantine VALUES (?, ?, ?, ?)",
                            (table, str(record_id), "payload_sha256_mismatch", datetime.now(timezone.utc).isoformat()),
                        )
        return len(corrupt)


_STORE: RuntimeEvidenceStore | None = None


def get_runtime_evidence_store() -> RuntimeEvidenceStore:
    global _STORE
    if _STORE is None:
        _STORE = RuntimeEvidenceStore()
    return _STORE
