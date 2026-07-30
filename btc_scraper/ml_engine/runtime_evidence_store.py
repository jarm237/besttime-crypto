"""Transactional, append-only, daily SQLite evidence store for ML runtime lineage."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping

from .artifact_resolver import ROOT
from btc_scraper.core.paths import (
    get_runtime_paths,
    runtime_deployment_id,
    runtime_environment,
    runtime_evidence_eligible,
    runtime_id,
    runtime_paper_run_id,
    runtime_owner_metadata,
)

RUNTIME_EVIDENCE_SCHEMA_VERSION = 2


def _canonical(payload: Mapping[str, Any]) -> str:
    return json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def payload_sha256(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


class RuntimeEvidenceStore:
    def __init__(
        self,
        path: Path | str | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        """Create a daily-partitioned evidence store.

        ``path`` is the logical/legacy path. New files are written beside it as
        ``<stem>_YYYY-MM-DD<suffix>``. The undated file remains readable for
        backward compatibility.
        """
        self.path = Path(path) if path is not None else get_runtime_paths().runtime_evidence_path
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize_path(self.current_path)

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @property
    def current_path(self) -> Path:
        return self.partition_path(self._now())

    def partition_path(self, value: datetime | str) -> Path:
        if isinstance(value, datetime):
            normalized = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
            day = normalized.date().isoformat()
        else:
            day = str(value)
        return self.path.with_name(f"{self.path.stem}_{day}{self.path.suffix}")

    def partition_paths(self) -> list[Path]:
        """Return every readable partition, including the legacy undated file."""
        pattern = f"{self.path.stem}_????-??-??{self.path.suffix}"
        paths = list(self.path.parent.glob(pattern))
        if self.path.exists():
            paths.append(self.path)
        return sorted(set(paths), key=lambda item: item.name, reverse=True)

    def _connect_path(self, path: Path) -> sqlite3.Connection:
        last_error: sqlite3.OperationalError | None = None
        for attempt in range(8):
            connection = sqlite3.connect(path, timeout=30.0)
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

    def _connect(self, path: Path | None = None) -> sqlite3.Connection:
        """Connect to a partition; defaults to today's partition.

        The optional path keeps low-level operational/test callers compatible
        while allowing the store itself to route reads across all partitions.
        """
        target = path or self.current_path
        self._initialize_path(target)
        return self._connect_path(target)

    def _initialize_path(self, path: Path) -> None:
        with self._connect_path(path) as db:
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
    def transaction(self, path: Path | None = None) -> Iterator[sqlite3.Connection]:
        db = self._connect(path)
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _find_partition(self, table: str, key: str, value: str) -> Path | None:
        for path in self.partition_paths():
            with self._connect(path) as db:
                if db.execute(f"SELECT 1 FROM {table} WHERE {key}=?", (value,)).fetchone():
                    return path
        return None

    def _all_rows(self, table: str, columns: str) -> Iterator[tuple[Any, ...]]:
        for path in self.partition_paths():
            with self._connect(path) as db:
                yield from db.execute(f"SELECT {columns} FROM {table}").fetchall()

    def write_prediction_evidence(self, prediction: Mapping[str, Any], snapshot: Mapping[str, Any]) -> None:
        prediction = self._with_runtime_metadata(prediction)
        snapshot = self._with_runtime_metadata(snapshot)
        prediction_id = str(prediction["prediction_id"])
        if str(snapshot.get("prediction_id")) != prediction_id:
            raise ValueError("prediction/snapshot identity mismatch")
        pred_json, snap_json = _canonical(prediction), _canonical(snapshot)
        written_at = self._now().isoformat()
        target_path = self._find_partition("predictions", "prediction_id", prediction_id) or self.current_path
        try:
            with self.transaction(target_path) as db:
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
        target_path = self._find_partition("predictions", "prediction_id", prediction_id)
        try:
            if target_path is None:
                raise ValueError("final decision references unknown prediction")
            digest = payload_sha256(decision)
            existing_path = self._find_partition("final_decisions", "decision_id", decision_id)
            existing = None
            if existing_path is not None:
                with self._connect(existing_path) as existing_db:
                    existing = existing_db.execute(
                        "SELECT payload_sha256 FROM final_decisions WHERE decision_id=?", (decision_id,)
                    ).fetchone()
            if existing and existing[0] != digest:
                raise ValueError("non-idempotent duplicate final decision")
            other = None
            for path in self.partition_paths():
                with self._connect(path) as candidate_db:
                    other = candidate_db.execute(
                        "SELECT decision_id FROM final_decisions WHERE prediction_id=? AND decision_id<>?",
                        (prediction_id, decision_id),
                    ).fetchone()
                if other:
                    break
            if other:
                raise ValueError("prediction already has a final decision")
            with self.transaction(target_path) as db:
                if db.execute("SELECT 1 FROM predictions WHERE prediction_id=?", (prediction_id,)).fetchone() is None:
                    raise ValueError("final decision references unknown prediction")
                db.execute(
                    "INSERT OR IGNORE INTO final_decisions VALUES (?, ?, ?, ?, ?)",
                    (decision_id, prediction_id, payload, digest, self._now().isoformat()),
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
                (str(event.get("event_type", "unknown")), payload, payload_sha256(event), self._now().isoformat()),
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
        target_path = self._find_partition("predictions", "prediction_id", prediction_id)
        try:
            if target_path is None:
                raise ValueError("outcome references unknown prediction")
            if not position_id or outcome_revision < 1:
                raise ValueError("outcome requires position_id and positive outcome_revision")
            digest = payload_sha256(outcome)
            existing_path = self._find_partition("outcome_links", "outcome_id", outcome_id)
            existing = None
            if existing_path is not None:
                with self._connect(existing_path) as existing_db:
                    existing = existing_db.execute(
                        "SELECT payload_sha256 FROM outcome_links WHERE outcome_id=?", (outcome_id,)
                    ).fetchone()
            if existing and existing[0] != digest:
                raise ValueError("non-idempotent duplicate outcome link")
            revisions: list[int] = []
            logical_duplicate = None
            for path in self.partition_paths():
                with self._connect(path) as candidate_db:
                    latest = candidate_db.execute(
                        "SELECT MAX(CAST(json_extract(payload, '$.outcome_revision') AS INTEGER)) "
                        "FROM outcome_links WHERE json_extract(payload, '$.position_id')=?",
                        (position_id,),
                    ).fetchone()[0]
                    if latest is not None:
                        revisions.append(int(latest))
                    logical_duplicate = candidate_db.execute(
                        "SELECT outcome_id, payload_sha256 FROM outcome_links "
                        "WHERE json_extract(payload, '$.position_id')=? "
                        "AND CAST(json_extract(payload, '$.outcome_revision') AS INTEGER)=?",
                        (position_id, outcome_revision),
                    ).fetchone()
                if logical_duplicate and logical_duplicate[0] != outcome_id:
                    break
            latest_revision = max(revisions) if revisions else None
            if latest_revision is not None and int(latest_revision) > outcome_revision:
                raise ValueError("stale lower outcome revision")
            if logical_duplicate and logical_duplicate[0] != outcome_id:
                raise ValueError("conflicting outcome amendment revision")
            with self.transaction(target_path) as db:
                if db.execute("SELECT 1 FROM predictions WHERE prediction_id=?", (prediction_id,)).fetchone() is None:
                    raise ValueError("outcome references unknown prediction")
                db.execute(
                    "INSERT OR IGNORE INTO outcome_links VALUES (?, ?, ?, ?, ?)",
                    (outcome_id, prediction_id, payload, digest, self._now().isoformat()),
                )
        except ValueError as exc:
            if "non-idempotent" in str(exc) or "conflicting outcome" in str(exc) or "stale lower" in str(exc):
                self._record_incident("duplicate_conflicting_payload", "outcome_links", outcome_id, str(exc))
            raise

    def get_prediction(self, prediction_id: str) -> dict[str, Any] | None:
        path = self._find_partition("predictions", "prediction_id", prediction_id)
        if path is None:
            return None
        with self._connect(path) as db:
            row = db.execute("SELECT payload FROM predictions WHERE prediction_id=?", (prediction_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def get_feature_snapshot(self, prediction_id: str) -> dict[str, Any] | None:
        path = self._find_partition("feature_snapshots", "prediction_id", prediction_id)
        if path is None:
            return None
        with self._connect(path) as db:
            row = db.execute("SELECT payload FROM feature_snapshots WHERE prediction_id=?", (prediction_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def get_final_decision_for_prediction(self, prediction_id: str) -> dict[str, Any] | None:
        path = self._find_partition("final_decisions", "prediction_id", prediction_id)
        if path is None:
            return None
        with self._connect(path) as db:
            row = db.execute("SELECT payload FROM final_decisions WHERE prediction_id=?", (prediction_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def count_rows(self, table_name: str) -> int:
        if table_name not in {"predictions", "feature_snapshots", "final_decisions", "outcome_links", "audit_events", "evidence_quarantine"}:
            raise ValueError(f"unsupported table: {table_name}")
        identity_columns = {
            "predictions": "prediction_id",
            "feature_snapshots": "prediction_id",
            "final_decisions": "decision_id",
            "outcome_links": "outcome_id",
            "audit_events": "event_type, payload_sha256, written_at",
            "evidence_quarantine": "table_name, record_id",
        }
        return len(set(self._all_rows(table_name, identity_columns[table_name])))

    def quarantine_record(self, table_name: str, record_id: str, reason: str) -> None:
        self._record_incident(reason, table_name, record_id, reason)

    def _record_incident(self, incident_type: str, table_name: str, record_id: str, details: str) -> None:
        with self.transaction() as db:
            db.execute(
                "INSERT INTO evidence_incidents(incident_type,record_id,details,detected_at) VALUES (?,?,?,?)",
                (incident_type, record_id, details, self._now().isoformat()),
            )
            db.execute(
                "INSERT OR IGNORE INTO evidence_quarantine VALUES (?,?,?,?)",
                (table_name, record_id, incident_type, self._now().isoformat()),
            )

    @staticmethod
    def _with_runtime_metadata(payload: Mapping[str, Any]) -> dict[str, Any]:
        result = dict(payload)
        result.setdefault("environment", runtime_environment())
        result.setdefault("deployment_id", runtime_deployment_id())
        result.setdefault("runtime_id", runtime_id())
        result.setdefault("evidence_eligible", runtime_evidence_eligible())
        result.setdefault("paper_run_id", runtime_paper_run_id())
        owner = runtime_owner_metadata()
        result.setdefault("process_id", owner["process_id"])
        result.setdefault("hostname", owner["hostname"])
        result.setdefault("started_at", owner["started_at"])
        return result

    def latest_outcomes(self) -> list[dict[str, Any]]:
        """Return only the highest valid amendment revision for each position."""
        latest: dict[str, tuple[int, dict[str, Any]]] = {}
        seen_outcome_ids: set[str] = set()
        rows = sorted(
            self._all_rows("outcome_links", "outcome_id, payload, written_at"),
            key=lambda row: (str(row[2]), str(row[0])),
        )
        for outcome_id, raw_payload, _ in rows:
            if str(outcome_id) in seen_outcome_ids:
                continue
            seen_outcome_ids.add(str(outcome_id))
            payload = json.loads(raw_payload)
            position_id = str(payload.get("position_id") or "")
            revision = int(payload.get("outcome_revision") or 0)
            current = latest.get(position_id)
            if position_id and revision > 0 and (current is None or revision > current[0]):
                latest[position_id] = (revision, payload)
        return [row for _, row in latest.values()]

    def get_latest_outcome_for_position(self, position_id: str) -> dict[str, Any] | None:
        latest: tuple[int, dict[str, Any]] | None = None
        seen_outcome_ids: set[str] = set()
        for outcome_id, raw_payload in self._all_rows(
            "outcome_links",
            "outcome_id, payload",
        ):
            if str(outcome_id) in seen_outcome_ids:
                continue
            seen_outcome_ids.add(str(outcome_id))
            payload = json.loads(raw_payload)
            if str(payload.get("position_id") or "") != str(position_id):
                continue
            revision = int(payload.get("outcome_revision") or 0)
            if latest is None or revision > latest[0]:
                latest = (revision, payload)
        return latest[1] if latest else None

    def shadow_evidence_rows(self) -> dict[str, list[dict[str, Any]]]:
        """Read canonical JSON payloads used by the derived shadow gate."""
        result: dict[str, list[dict[str, Any]]] = {}
        identity_columns = {
            "predictions": "prediction_id",
            "final_decisions": "decision_id",
            "audit_events": "event_type || ':' || payload_sha256 || ':' || written_at",
        }
        for table, identity in identity_columns.items():
            unique: dict[str, dict[str, Any]] = {}
            for record_id, payload in self._all_rows(table, f"{identity}, payload"):
                unique.setdefault(str(record_id), json.loads(payload))
            result[table] = list(unique.values())
        result["outcomes"] = self.latest_outcomes()
        return result

    def health(self) -> dict[str, Any]:
        corrupt_payloads = self.verify_and_quarantine()
        prediction_ids = {str(row[0]) for row in self._all_rows("predictions", "prediction_id")}
        snapshot_ids = {str(row[0]) for row in self._all_rows("feature_snapshots", "prediction_id")}
        decisions = {
            (str(decision_id), str(prediction_id or ""))
            for decision_id, prediction_id in self._all_rows("final_decisions", "decision_id, prediction_id")
        }
        outcomes = {
            (str(outcome_id), str(prediction_id or ""))
            for outcome_id, prediction_id in self._all_rows("outcome_links", "outcome_id, prediction_id")
        }
        orphan_snapshots = len(snapshot_ids - prediction_ids)
        missing_snapshots = len(prediction_ids - snapshot_ids)
        orphan_decisions = sum(bool(prediction_id) and prediction_id not in prediction_ids for _, prediction_id in decisions)
        decisions_without_prediction = sum(not prediction_id for _, prediction_id in decisions)
        decisions_by_prediction: dict[str, set[str]] = {}
        for decision_id, prediction_id in decisions:
            if prediction_id:
                decisions_by_prediction.setdefault(prediction_id, set()).add(decision_id)
        duplicate_decision_predictions = sum(
            len(decision_ids) > 1 for decision_ids in decisions_by_prediction.values()
        )
        orphan_outcomes = sum(prediction_id not in prediction_ids for _, prediction_id in outcomes)
        unresolved_incidents = len({
            (str(kind), str(record_id), str(details), str(detected_at))
            for kind, record_id, details, detected_at, resolved_at in self._all_rows(
                "evidence_incidents", "incident_type, record_id, details, detected_at, resolved_at"
            )
            if resolved_at is None
        })
        quarantined_records = len({
            (str(table), str(record_id))
            for table, record_id in self._all_rows("evidence_quarantine", "table_name, record_id")
        })
        foreign_key_violations = 0
        integrity_results: list[str] = []
        for path in self.partition_paths():
            with self._connect(path) as db:
                foreign_key_violations += len(db.execute("PRAGMA foreign_key_check").fetchall())
                integrity_results.append(str(db.execute("PRAGMA integrity_check").fetchone()[0]))
        integrity = "ok" if integrity_results and all(value == "ok" for value in integrity_results) else "; ".join(integrity_results)
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
        corrupt: set[tuple[str, str]] = set()
        table_keys = {
            "predictions": "prediction_id", "feature_snapshots": "prediction_id",
            "final_decisions": "decision_id", "outcome_links": "outcome_id",
        }
        for path in self.partition_paths():
            with self.transaction(path) as db:
                for table, key in table_keys.items():
                    for record_id, payload, digest in db.execute(f"SELECT {key}, payload, payload_sha256 FROM {table}"):
                        actual = hashlib.sha256(str(payload).encode("utf-8")).hexdigest()
                        if actual != digest:
                            corrupt.add((table, str(record_id)))
                            db.execute(
                                "INSERT OR IGNORE INTO evidence_quarantine VALUES (?, ?, ?, ?)",
                                (table, str(record_id), "payload_sha256_mismatch", self._now().isoformat()),
                            )
        return len(corrupt)


_STORE: RuntimeEvidenceStore | None = None


def get_runtime_evidence_store() -> RuntimeEvidenceStore:
    global _STORE
    if _STORE is None:
        _STORE = RuntimeEvidenceStore()
    return _STORE
