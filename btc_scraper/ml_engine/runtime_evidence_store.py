"""Transactional, append-only SQLite evidence store for ML runtime lineage."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping

from .artifact_resolver import ROOT
from btc_scraper.core.paths import (
    get_runtime_paths,
    runtime_environment,
    runtime_evidence_eligible,
    runtime_paper_run_id,
)

RUNTIME_EVIDENCE_SCHEMA_VERSION = 2


def _canonical(payload: Mapping[str, Any]) -> str:
    return json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def payload_sha256(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


class RuntimeEvidenceStore:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path is not None else get_runtime_paths().runtime_evidence_path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        last_error: sqlite3.OperationalError | None = None
        for attempt in range(8):
            connection = sqlite3.connect(self.path, timeout=30.0)
            try:
                connection.execute("PRAGMA foreign_keys=ON")
                connection.execute("PRAGMA busy_timeout=30000")
                connection.execute("PRAGMA journal_mode=WAL")
                return connection
            except sqlite3.OperationalError as exc:
                connection.close()
                if "locked" not in str(exc).lower():
                    raise
                last_error = exc
                time.sleep(0.05 * (attempt + 1))
        assert last_error is not None
        raise last_error

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
                CREATE TABLE IF NOT EXISTS evidence_incidents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, incident_type TEXT NOT NULL,
                    record_id TEXT, details TEXT NOT NULL, detected_at TEXT NOT NULL,
                    resolved_at TEXT
                );
                CREATE UNIQUE INDEX IF NOT EXISTS uq_final_decision_prediction
                    ON final_decisions(prediction_id) WHERE prediction_id IS NOT NULL;
                CREATE UNIQUE INDEX IF NOT EXISTS uq_outcome_position_revision
                    ON outcome_links(
                        json_extract(payload, '$.position_id'),
                        CAST(json_extract(payload, '$.outcome_revision') AS INTEGER)
                    )
                    WHERE json_extract(payload, '$.position_id') IS NOT NULL;
            """)
            db.execute(f"PRAGMA user_version={RUNTIME_EVIDENCE_SCHEMA_VERSION}")

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
        prediction = self._with_runtime_metadata(prediction)
        snapshot = self._with_runtime_metadata(snapshot)
        prediction_id = str(prediction["prediction_id"])
        if str(snapshot.get("prediction_id")) != prediction_id:
            raise ValueError("prediction/snapshot identity mismatch")
        pred_json, snap_json = _canonical(prediction), _canonical(snapshot)
        written_at = datetime.now(timezone.utc).isoformat()
        try:
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
        except ValueError as exc:
            if "non-idempotent" in str(exc):
                self._record_incident("duplicate_conflicting_payload", "predictions", prediction_id, str(exc))
            raise

    def append_final_decision(self, decision: Mapping[str, Any]) -> None:
        decision = self._with_runtime_metadata(decision)
        decision_id = str(decision["decision_id"])
        prediction_id = str(decision.get("prediction_id") or "")
        if not prediction_id:
            raise ValueError("final decision must reference exactly one prediction")
        payload = _canonical(decision)
        try:
            with self.transaction() as db:
                if db.execute("SELECT 1 FROM predictions WHERE prediction_id=?", (prediction_id,)).fetchone() is None:
                    raise ValueError("final decision references unknown prediction")
                digest = payload_sha256(decision)
                existing = db.execute("SELECT payload_sha256 FROM final_decisions WHERE decision_id=?", (decision_id,)).fetchone()
                if existing and existing[0] != digest:
                    raise ValueError("non-idempotent duplicate final decision")
                other = db.execute(
                    "SELECT decision_id FROM final_decisions WHERE prediction_id=? AND decision_id<>?",
                    (prediction_id, decision_id),
                ).fetchone()
                if other:
                    raise ValueError("prediction already has a final decision")
                db.execute(
                    "INSERT OR IGNORE INTO final_decisions VALUES (?, ?, ?, ?, ?)",
                    (decision_id, prediction_id, payload, digest, datetime.now(timezone.utc).isoformat()),
                )
        except ValueError as exc:
            if "non-idempotent" in str(exc) or "already has" in str(exc):
                self._record_incident("duplicate_conflicting_payload", "final_decisions", decision_id, str(exc))
            raise

    def append_audit_event(self, event: Mapping[str, Any]) -> None:
        event = self._with_runtime_metadata(event)
        payload = _canonical(event)
        with self.transaction() as db:
            db.execute(
                "INSERT INTO audit_events(event_type,payload,payload_sha256,written_at) VALUES (?,?,?,?)",
                (str(event.get("event_type", "unknown")), payload, payload_sha256(event), datetime.now(timezone.utc).isoformat()),
            )

    def append_outcome_link(self, outcome: Mapping[str, Any]) -> None:
        outcome = self._with_runtime_metadata(outcome)
        outcome_id = str(outcome["outcome_id"])
        prediction_id = str(outcome["prediction_id"])
        position_id = str(outcome.get("position_id") or "")
        try:
            outcome_revision = int(outcome.get("outcome_revision"))
        except (TypeError, ValueError):
            outcome_revision = 0
        payload = _canonical(outcome)
        try:
            with self.transaction() as db:
                if db.execute("SELECT 1 FROM predictions WHERE prediction_id=?", (prediction_id,)).fetchone() is None:
                    raise ValueError("outcome references unknown prediction")
                if not position_id or outcome_revision < 1:
                    raise ValueError("outcome requires position_id and positive outcome_revision")
                digest = payload_sha256(outcome)
                existing = db.execute("SELECT payload_sha256 FROM outcome_links WHERE outcome_id=?", (outcome_id,)).fetchone()
                if existing and existing[0] != digest:
                    raise ValueError("non-idempotent duplicate outcome link")
                latest_revision = db.execute(
                    "SELECT MAX(CAST(json_extract(payload, '$.outcome_revision') AS INTEGER)) "
                    "FROM outcome_links WHERE json_extract(payload, '$.position_id')=?",
                    (position_id,),
                ).fetchone()[0]
                if latest_revision is not None and int(latest_revision) > outcome_revision:
                    raise ValueError("stale lower outcome revision")
                logical_duplicate = db.execute(
                    "SELECT outcome_id, payload_sha256 FROM outcome_links "
                    "WHERE json_extract(payload, '$.position_id')=? "
                    "AND CAST(json_extract(payload, '$.outcome_revision') AS INTEGER)=?",
                    (position_id, outcome_revision),
                ).fetchone()
                if logical_duplicate and logical_duplicate[0] != outcome_id:
                    raise ValueError("conflicting outcome amendment revision")
                db.execute(
                    "INSERT OR IGNORE INTO outcome_links VALUES (?, ?, ?, ?, ?)",
                    (outcome_id, prediction_id, payload, digest, datetime.now(timezone.utc).isoformat()),
                )
        except ValueError as exc:
            if "non-idempotent" in str(exc) or "conflicting outcome" in str(exc) or "stale lower" in str(exc):
                self._record_incident("duplicate_conflicting_payload", "outcome_links", outcome_id, str(exc))
            raise

    def get_prediction(self, prediction_id: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute("SELECT payload FROM predictions WHERE prediction_id=?", (prediction_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def get_feature_snapshot(self, prediction_id: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute("SELECT payload FROM feature_snapshots WHERE prediction_id=?", (prediction_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def get_final_decision_for_prediction(self, prediction_id: str) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute("SELECT payload FROM final_decisions WHERE prediction_id=?", (prediction_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def count_rows(self, table_name: str) -> int:
        if table_name not in {"predictions", "feature_snapshots", "final_decisions", "outcome_links", "audit_events", "evidence_quarantine"}:
            raise ValueError(f"unsupported table: {table_name}")
        with self._connect() as db:
            return int(db.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0])

    def quarantine_record(self, table_name: str, record_id: str, reason: str) -> None:
        self._record_incident(reason, table_name, record_id, reason)

    def _record_incident(self, incident_type: str, table_name: str, record_id: str, details: str) -> None:
        with self.transaction() as db:
            db.execute(
                "INSERT INTO evidence_incidents(incident_type,record_id,details,detected_at) VALUES (?,?,?,?)",
                (incident_type, record_id, details, datetime.now(timezone.utc).isoformat()),
            )
            db.execute(
                "INSERT OR IGNORE INTO evidence_quarantine VALUES (?,?,?,?)",
                (table_name, record_id, incident_type, datetime.now(timezone.utc).isoformat()),
            )

    @staticmethod
    def _with_runtime_metadata(payload: Mapping[str, Any]) -> dict[str, Any]:
        result = dict(payload)
        result.setdefault("environment", runtime_environment())
        result.setdefault("evidence_eligible", runtime_evidence_eligible())
        result.setdefault("paper_run_id", runtime_paper_run_id())
        return result

    def latest_outcomes(self) -> list[dict[str, Any]]:
        """Return only the highest valid amendment revision for each position."""
        latest: dict[str, tuple[int, dict[str, Any]]] = {}
        with self._connect() as db:
            rows = db.execute("SELECT payload FROM outcome_links ORDER BY written_at, outcome_id").fetchall()
        for (raw_payload,) in rows:
            payload = json.loads(raw_payload)
            position_id = str(payload.get("position_id") or "")
            revision = int(payload.get("outcome_revision") or 0)
            current = latest.get(position_id)
            if position_id and revision > 0 and (current is None or revision > current[0]):
                latest[position_id] = (revision, payload)
        return [row for _, row in latest.values()]

    def shadow_evidence_rows(self) -> dict[str, list[dict[str, Any]]]:
        """Read canonical JSON payloads used by the derived shadow gate."""
        result: dict[str, list[dict[str, Any]]] = {}
        with self._connect() as db:
            for table in ("predictions", "final_decisions", "audit_events"):
                result[table] = [json.loads(row[0]) for row in db.execute(f"SELECT payload FROM {table}")]
        result["outcomes"] = self.latest_outcomes()
        return result

    def health(self) -> dict[str, Any]:
        corrupt_payloads = self.verify_and_quarantine()
        with self._connect() as db:
            orphan_snapshots = db.execute(
                "SELECT COUNT(*) FROM feature_snapshots s LEFT JOIN predictions p USING(prediction_id) WHERE p.prediction_id IS NULL"
            ).fetchone()[0]
            missing_snapshots = db.execute(
                "SELECT COUNT(*) FROM predictions p LEFT JOIN feature_snapshots s USING(prediction_id) WHERE s.prediction_id IS NULL"
            ).fetchone()[0]
            orphan_decisions = db.execute(
                "SELECT COUNT(*) FROM final_decisions d LEFT JOIN predictions p USING(prediction_id) "
                "WHERE d.prediction_id IS NOT NULL AND p.prediction_id IS NULL"
            ).fetchone()[0]
            decisions_without_prediction = db.execute(
                "SELECT COUNT(*) FROM final_decisions WHERE prediction_id IS NULL OR prediction_id=''"
            ).fetchone()[0]
            duplicate_decision_predictions = db.execute(
                "SELECT COUNT(*) FROM (SELECT prediction_id FROM final_decisions "
                "WHERE prediction_id IS NOT NULL GROUP BY prediction_id HAVING COUNT(*)<>1)"
            ).fetchone()[0]
            orphan_outcomes = db.execute(
                "SELECT COUNT(*) FROM outcome_links o LEFT JOIN predictions p USING(prediction_id) "
                "WHERE p.prediction_id IS NULL"
            ).fetchone()[0]
            foreign_key_violations = len(db.execute("PRAGMA foreign_key_check").fetchall())
            unresolved_incidents = db.execute(
                "SELECT COUNT(*) FROM evidence_incidents WHERE resolved_at IS NULL"
            ).fetchone()[0]
            quarantined_records = db.execute("SELECT COUNT(*) FROM evidence_quarantine").fetchone()[0]
            integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
        healthy = (
            integrity == "ok"
            and orphan_snapshots == 0 and missing_snapshots == 0
            and orphan_decisions == 0 and orphan_outcomes == 0
            and decisions_without_prediction == 0 and duplicate_decision_predictions == 0
            and foreign_key_violations == 0 and corrupt_payloads == 0
            and unresolved_incidents == 0 and quarantined_records == 0
        )
        return {
            "status": "healthy" if healthy else "degraded",
            "integrity": integrity, "orphan_snapshots": orphan_snapshots, "missing_snapshots": missing_snapshots,
            "orphan_decisions": orphan_decisions, "orphan_outcomes": orphan_outcomes,
            "decisions_without_prediction": decisions_without_prediction,
            "duplicate_decision_predictions": duplicate_decision_predictions,
            "foreign_key_violations": foreign_key_violations,
            "unresolved_incidents": unresolved_incidents,
            "quarantined_records": quarantined_records,
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
