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
from dataclasses import replace

from .artifact_resolver import ROOT
from btc_scraper.core.config import analysis_universe_hash, get_runtime_universe
from .evidence_epoch import (
    EVIDENCE_POLICY_VERSION,
    RELEASE_MANIFEST_SCHEMA_VERSION,
    RISK_POLICY_VERSION,
    EvidenceEpoch,
)
from btc_scraper.core.paths import (
    get_runtime_paths,
    runtime_deployment_id,
    runtime_environment,
    runtime_evidence_eligible,
    runtime_id,
    runtime_paper_run_id,
    runtime_owner_metadata,
)

RUNTIME_EVIDENCE_SCHEMA_VERSION = 6
GLOBAL_EVIDENCE_INDEX_SCHEMA_VERSION = 6
GLOBAL_RESERVATION_STALE_SECONDS = 300.0
EPOCH_INVALIDATION_AUDIT_EVENT = "EPOCH_INVALIDATION_AUDIT_RECORDED"
EPOCH_ACTIVATION_AUDIT_EVENT = "EPOCH_ACTIVATION_RECORDED"
REQUIRED_PREDICTION_LINEAGE_FIELDS = (
    "signal_id",
    "prediction_id",
    "deployment_id",
    "symbol",
    "decision_context",
    "caller_context",
    "model_version",
    "artifact_sha256",
    "feature_schema_version",
    "feature_hash",
    "analysis_universe",
    "analysis_universe_hash",
)


def _canonical(payload: Mapping[str, Any]) -> str:
    return json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def payload_sha256(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def idempotency_payload_sha256(payload: Mapping[str, Any]) -> str:
    """Hash stable inference semantics, excluding per-process/write metadata."""
    volatile = {
        "prediction_id", "event_id", "event_time", "ingest_time", "timestamp",
        "predicted_at", "valid_until", "latency_ms", "process_id", "hostname",
        "started_at", "runtime_id",
    }
    return payload_sha256({
        key: value for key, value in payload.items() if key not in volatile
    })


class RuntimeEvidenceStore:
    def __init__(
        self,
        path: Path | str | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
        read_only: bool = False,
    ) -> None:
        """Create a daily-partitioned evidence store.

        ``path`` is the logical/legacy path. New files are written beside it as
        ``<stem>_YYYY-MM-DD<suffix>``. The undated file remains readable for
        backward compatibility.
        """
        self.path = Path(path) if path is not None else get_runtime_paths().runtime_evidence_path
        self.global_index_path = self.path.parent / "global_evidence_index.sqlite"
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self.read_only = read_only
        if not self.read_only:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._initialize_path(self.current_path)
            self._initialize_global_index()
            self._backfill_global_index()
            self._reconcile_global_index_locations()

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
        if getattr(self, "read_only", False):
            uri = f"file:{path.resolve().as_posix()}?mode=ro"
            connection = sqlite3.connect(uri, uri=True, timeout=30.0)
            return connection

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
        if not getattr(self, "read_only", False):
            self._initialize_path(target)
        return self._connect_path(target)

    def _global_connect(self) -> sqlite3.Connection:
        return self._connect_path(self.global_index_path)

    def _initialize_global_index(self) -> None:
        with self._global_connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS prediction_global_idempotency (
                    idempotency_key TEXT PRIMARY KEY,
                    prediction_id TEXT NOT NULL UNIQUE,
                    partition_date TEXT NOT NULL,
                    state TEXT NOT NULL CHECK(state IN ('RESERVED','COMMITTED','ABORTED')),
                    payload_hash TEXT NOT NULL,
                    reserved_at TEXT NOT NULL,
                    committed_at TEXT,
                    owner_id TEXT,
                    error_reason TEXT
                );
                CREATE TABLE IF NOT EXISTS global_index_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS evidence_epochs (
                    epoch_id TEXT PRIMARY KEY,
                    deployment_id TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    activated_at TEXT,
                    code_commit_sha TEXT NOT NULL,
                    model_version TEXT NOT NULL,
                    artifact_sha256 TEXT NOT NULL,
                    feature_schema_version TEXT NOT NULL,
                    analysis_universe TEXT NOT NULL,
                    analysis_universe_hash TEXT NOT NULL,
                    evidence_policy_version TEXT NOT NULL,
                    risk_policy_version TEXT NOT NULL,
                    runtime_schema_version INTEGER NOT NULL,
                    status TEXT NOT NULL CHECK(status IN (
                        'DRAFT','ACTIVE','SEAL_BLOCKED','SEAL_READY','SEALED',
                        'INVALIDATED','QUARANTINED'
                    )),
                    paper_run_id TEXT NOT NULL DEFAULT '',
                    release_manifest TEXT,
                    release_manifest_sha256 TEXT NOT NULL DEFAULT '',
                    runtime_pause_policy TEXT NOT NULL DEFAULT '{}',
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS audit_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL,
                    written_at TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS uq_one_active_evidence_epoch
                    ON evidence_epochs((1))
                    WHERE status IN ('ACTIVE','SEAL_BLOCKED','SEAL_READY');
            """)
            columns = {
                str(row[1])
                for row in db.execute("PRAGMA table_info(evidence_epochs)").fetchall()
            }
            if "analysis_universe" not in columns:
                db.execute(
                    "ALTER TABLE evidence_epochs ADD COLUMN analysis_universe "
                    "TEXT NOT NULL DEFAULT '[]'"
                )
            if "analysis_universe_hash" not in columns:
                db.execute(
                    "ALTER TABLE evidence_epochs ADD COLUMN analysis_universe_hash "
                    "TEXT NOT NULL DEFAULT ''"
                )
            if "activated_at" not in columns:
                db.execute(
                    "ALTER TABLE evidence_epochs ADD COLUMN activated_at TEXT"
                )
            if "runtime_pause_policy" not in columns:
                db.execute(
                    "ALTER TABLE evidence_epochs ADD COLUMN runtime_pause_policy "
                    "TEXT NOT NULL DEFAULT '{}'"
                )
            if "paper_run_id" not in columns:
                db.execute(
                    "ALTER TABLE evidence_epochs ADD COLUMN paper_run_id "
                    "TEXT NOT NULL DEFAULT ''"
                )
            if "release_manifest" not in columns:
                db.execute(
                    "ALTER TABLE evidence_epochs ADD COLUMN release_manifest TEXT"
                )
            if "release_manifest_sha256" not in columns:
                db.execute(
                    "ALTER TABLE evidence_epochs ADD COLUMN release_manifest_sha256 "
                    "TEXT NOT NULL DEFAULT ''"
                )
            table_sql = str(db.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='evidence_epochs'"
            ).fetchone()[0])
            if "SEAL_READY" not in table_sql or "QUARANTINED" not in table_sql:
                db.execute("DROP INDEX IF EXISTS uq_one_active_evidence_epoch")
                db.execute("ALTER TABLE evidence_epochs RENAME TO evidence_epochs_legacy")
                db.executescript("""
                    CREATE TABLE evidence_epochs (
                        epoch_id TEXT PRIMARY KEY,
                        deployment_id TEXT NOT NULL,
                        started_at TEXT NOT NULL,
                        activated_at TEXT,
                        code_commit_sha TEXT NOT NULL,
                        model_version TEXT NOT NULL,
                        artifact_sha256 TEXT NOT NULL,
                        feature_schema_version TEXT NOT NULL,
                        analysis_universe TEXT NOT NULL,
                        analysis_universe_hash TEXT NOT NULL,
                        evidence_policy_version TEXT NOT NULL,
                        risk_policy_version TEXT NOT NULL,
                        runtime_schema_version INTEGER NOT NULL,
                        status TEXT NOT NULL CHECK(status IN (
                            'DRAFT','ACTIVE','SEAL_BLOCKED','SEAL_READY','SEALED',
                            'INVALIDATED','QUARANTINED'
                        )),
                        paper_run_id TEXT NOT NULL DEFAULT '',
                        release_manifest TEXT,
                        release_manifest_sha256 TEXT NOT NULL DEFAULT '',
                        runtime_pause_policy TEXT NOT NULL DEFAULT '{}',
                        updated_at TEXT NOT NULL
                    );
                    INSERT INTO evidence_epochs(
                        epoch_id,deployment_id,started_at,activated_at,code_commit_sha,
                        model_version,artifact_sha256,feature_schema_version,
                        analysis_universe,analysis_universe_hash,evidence_policy_version,
                        risk_policy_version,runtime_schema_version,status,
                        paper_run_id,release_manifest,release_manifest_sha256,
                        runtime_pause_policy,updated_at
                    ) SELECT
                        epoch_id,deployment_id,started_at,activated_at,code_commit_sha,
                        model_version,artifact_sha256,feature_schema_version,
                        analysis_universe,analysis_universe_hash,evidence_policy_version,
                        risk_policy_version,runtime_schema_version,status,
                        '', NULL, '', runtime_pause_policy, updated_at
                    FROM evidence_epochs_legacy;
                    DROP TABLE evidence_epochs_legacy;
                    CREATE UNIQUE INDEX uq_one_active_evidence_epoch
                        ON evidence_epochs((1))
                        WHERE status IN ('ACTIVE','SEAL_BLOCKED','SEAL_READY');
                """)
            db.execute(f"PRAGMA user_version={GLOBAL_EVIDENCE_INDEX_SCHEMA_VERSION}")

    @contextmanager
    def _global_transaction(self) -> Iterator[sqlite3.Connection]:
        db = self._global_connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _insert_audit_event_db(self, db: sqlite3.Connection, event: Mapping[str, Any]) -> None:
        event = self._with_runtime_metadata(event)
        payload = _canonical(event)
        db.execute(
            "INSERT INTO audit_events(event_type,payload,payload_sha256,written_at) VALUES (?,?,?,?)",
            (str(event.get("event_type", "unknown")), payload, payload_sha256(event), self._now().isoformat()),
        )

    def _find_existing_invalidation_audit(
        self,
        db: sqlite3.Connection,
        epoch_id: str,
        reason_code: str,
    ) -> bool:
        row = db.execute(
            "SELECT 1 FROM audit_events WHERE event_type=? "
            "AND json_extract(payload,'$.epoch_id')=? "
            "AND json_extract(payload,'$.reason_code')=?",
            (EPOCH_INVALIDATION_AUDIT_EVENT, str(epoch_id), str(reason_code)),
        ).fetchone()
        return row is not None

    def _find_existing_activation_audit(
        self,
        db: sqlite3.Connection,
        epoch_id: str,
        new_status: str,
    ) -> bool:
        row = db.execute(
            "SELECT 1 FROM audit_events WHERE event_type=? "
            "AND json_extract(payload,'$.epoch_id')=? "
            "AND json_extract(payload,'$.new_status')=?",
            (EPOCH_ACTIVATION_AUDIT_EVENT, str(epoch_id), str(new_status)),
        ).fetchone()
        return row is not None

    def _partition_date_for_path(self, path: Path) -> str:
        if path == self.path:
            return "legacy"
        prefix = f"{self.path.stem}_"
        return path.stem.removeprefix(prefix)

    def _path_for_partition_date(self, partition_date: str) -> Path:
        return self.path if partition_date == "legacy" else self.partition_path(partition_date)

    def _backfill_global_index(self) -> None:
        """Register schema-v3/legacy predictions without changing partition data."""
        with self._global_connect() as db:
            marker = db.execute(
                "SELECT value FROM global_index_metadata WHERE key='legacy_backfill_v1'"
            ).fetchone()
        if marker:
            return
        registrations: list[tuple[str, str, str, str]] = []
        for path in sorted(self.partition_paths(), key=lambda item: item.name):
            with self._connect(path) as db:
                rows = db.execute("SELECT prediction_id, payload FROM predictions").fetchall()
            for prediction_id, raw_payload in rows:
                try:
                    prediction = json.loads(str(raw_payload))
                except (TypeError, json.JSONDecodeError):
                    continue
                prediction_id = str(prediction_id)
                requested_key = str(
                    prediction.get("idempotency_key")
                    or f"prediction_id:{prediction_id}"
                )
                registrations.append((
                    requested_key,
                    prediction_id,
                    self._partition_date_for_path(path),
                    idempotency_payload_sha256(prediction),
                ))
        with self._global_transaction() as db:
            for requested_key, prediction_id, partition_date, payload_hash in registrations:
                owner = db.execute(
                    "SELECT prediction_id FROM prediction_global_idempotency "
                    "WHERE idempotency_key=?",
                    (requested_key,),
                ).fetchone()
                key = (
                    requested_key
                    if owner is None or str(owner[0]) == prediction_id
                    else f"legacy_conflict:{prediction_id}"
                )
                db.execute(
                    "INSERT OR IGNORE INTO prediction_global_idempotency "
                    "VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        key, prediction_id, partition_date, "COMMITTED",
                        payload_hash, self._now().isoformat(),
                        self._now().isoformat(), "legacy-backfill",
                        None if key == requested_key else "legacy_duplicate_idempotency_key",
                    ),
                )
            db.execute(
                "INSERT OR REPLACE INTO global_index_metadata VALUES "
                "('legacy_backfill_v1', ?)",
                (self._now().isoformat(),),
            )

    def _reconcile_global_index_locations(self) -> None:
        """Repair catalog locations after a legacy DB copy/partition migration."""
        locations: dict[str, list[str]] = {}
        for path in self.partition_paths():
            with self._connect(path) as db:
                prediction_ids = db.execute(
                    "SELECT prediction_id FROM predictions"
                ).fetchall()
            partition_date = self._partition_date_for_path(path)
            for (prediction_id,) in prediction_ids:
                locations.setdefault(str(prediction_id), []).append(partition_date)
        with self._global_transaction() as db:
            rows = db.execute(
                "SELECT idempotency_key,prediction_id,partition_date "
                "FROM prediction_global_idempotency WHERE state='COMMITTED'"
            ).fetchall()
            for idempotency_key, prediction_id, partition_date in rows:
                candidates = locations.get(str(prediction_id), [])
                if str(partition_date) not in candidates and len(candidates) == 1:
                    db.execute(
                        "UPDATE prediction_global_idempotency SET partition_date=? "
                        "WHERE idempotency_key=?",
                        (candidates[0], str(idempotency_key)),
                    )

    @staticmethod
    def _epoch_from_row(row: tuple[Any, ...]) -> EvidenceEpoch:
        release_manifest = None
        if row[15] not in (None, ""):
            release_manifest = json.loads(str(row[15]))
        return EvidenceEpoch(
            epoch_id=str(row[0]),
            deployment_id=str(row[1]),
            started_at=str(row[2]),
            activated_at=str(row[3]) if row[3] is not None else None,
            code_commit_sha=str(row[4]),
            model_version=str(row[5]),
            artifact_sha256=str(row[6]),
            feature_schema_version=str(row[7]),
            analysis_universe=tuple(json.loads(str(row[8]))),
            analysis_universe_hash=str(row[9]),
            evidence_policy_version=str(row[10]),
            risk_policy_version=str(row[11]),
            runtime_schema_version=int(row[12]),
            status=str(row[13]),
            paper_run_id=str(row[14] or ""),
            release_manifest=release_manifest,
            release_manifest_sha256=str(row[16] or ""),
            runtime_pause_policy=json.loads(str(row[17]) or "{}"),
        )

    def _normalize_release_manifest(self, manifest: Mapping[str, Any], epoch: EvidenceEpoch) -> dict[str, Any]:
        normalized_manifest = dict(manifest)
        normalized_manifest["manifest_schema_version"] = RELEASE_MANIFEST_SCHEMA_VERSION
        normalized_manifest["release_sha"] = str(epoch.code_commit_sha)
        normalized_manifest["artifact_sha256"] = str(epoch.artifact_sha256)
        normalized_manifest["deployment_id"] = str(epoch.deployment_id)
        normalized_manifest["paper_run_id"] = str(epoch.paper_run_id or epoch.deployment_id).strip()
        normalized_manifest["feature_schema_version"] = str(epoch.feature_schema_version)
        normalized_manifest["analysis_universe"] = ",".join(str(symbol).strip().upper() for symbol in epoch.analysis_universe)
        normalized_manifest["decision_contract"] = "side-probability-v2"
        normalized_manifest["probability_semantics"] = "P(up)"
        return normalized_manifest

    @staticmethod
    def _release_manifest_sha256(manifest: Mapping[str, Any]) -> str:
        canonical = json.dumps(dict(manifest), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _epoch_payload_signature(self, epoch: EvidenceEpoch) -> str:
        payload = {
            "epoch_id": epoch.epoch_id,
            "deployment_id": epoch.deployment_id,
            "activated_at": epoch.activated_at,
            "code_commit_sha": epoch.code_commit_sha,
            "model_version": epoch.model_version,
            "artifact_sha256": epoch.artifact_sha256,
            "feature_schema_version": epoch.feature_schema_version,
            "analysis_universe": tuple(epoch.analysis_universe),
            "analysis_universe_hash": epoch.analysis_universe_hash,
            "paper_run_id": epoch.paper_run_id or epoch.deployment_id,
            "release_manifest_sha256": epoch.release_manifest_sha256,
            "status": epoch.status,
            "runtime_schema_version": epoch.runtime_schema_version,
            "runtime_pause_policy": epoch.runtime_pause_policy,
        }
        return payload_sha256(payload)

    def _validate_release_manifest(self, manifest: Mapping[str, Any], epoch: EvidenceEpoch) -> None:
        if not isinstance(manifest, Mapping):
            raise ValueError("release_manifest must be a mapping")
        required_manifest_fields = (
            "manifest_schema_version",
            "release_sha",
            "artifact_sha256",
            "metadata_sha256",
            "registry_sha256",
            "deployment_id",
            "paper_run_id",
            "feature_schema_version",
            "analysis_universe",
            "decision_contract",
            "probability_semantics",
        )
        missing = [
            field_name for field_name in required_manifest_fields
            if not str(manifest.get(field_name) or "").strip()
        ]
        if missing:
            raise ValueError("release_manifest missing fields: " + ",".join(missing))
        if str(manifest.get("manifest_schema_version") or "") != RELEASE_MANIFEST_SCHEMA_VERSION:
            raise ValueError("release_manifest manifest_schema_version mismatch")
        if str(manifest.get("release_sha") or "") != str(epoch.code_commit_sha):
            raise ValueError("release_manifest release_sha mismatch")
        if str(manifest.get("artifact_sha256") or "") != str(epoch.artifact_sha256):
            raise ValueError("release_manifest artifact_sha256 mismatch")
        if str(manifest.get("deployment_id") or "") != str(epoch.deployment_id):
            raise ValueError("release_manifest deployment_id mismatch")
        if str(manifest.get("paper_run_id") or "") != str(epoch.paper_run_id or epoch.deployment_id).strip():
            raise ValueError("release_manifest paper_run_id mismatch")
        if str(manifest.get("feature_schema_version") or "") != str(epoch.feature_schema_version):
            raise ValueError("release_manifest feature_schema_version mismatch")
        analysis_universe = manifest.get("analysis_universe")
        if isinstance(analysis_universe, list):
            analysis_universe = ",".join(
                str(symbol).strip().upper() for symbol in analysis_universe
            )
        if str(analysis_universe or "") != ",".join(str(symbol).strip().upper() for symbol in epoch.analysis_universe):
            raise ValueError("release_manifest analysis_universe mismatch")
        if str(manifest.get("decision_contract") or "") != "side-probability-v2":
            raise ValueError("release_manifest decision_contract mismatch")
        if str(manifest.get("probability_semantics") or "") != "P(up)":
            raise ValueError("release_manifest probability_semantics mismatch")

    def create_evidence_epoch(
        self,
        epoch: EvidenceEpoch | Mapping[str, Any],
    ) -> EvidenceEpoch:
        value = epoch if isinstance(epoch, EvidenceEpoch) else EvidenceEpoch.from_mapping(epoch)
        value = replace(
            value,
            paper_run_id=str(value.paper_run_id or "").strip(),
        )
        if value.release_manifest is None:
            raise ValueError("release_manifest is required")
        self._validate_release_manifest(value.release_manifest, value)
        normalized_manifest = self._normalize_release_manifest(value.release_manifest, value)
        value = replace(
            value,
            release_manifest=normalized_manifest,
            release_manifest_sha256=self._release_manifest_sha256(normalized_manifest),
        )
        value.validate()
        existing = self.get_evidence_epoch(value.epoch_id)
        if existing is not None:
            if self._epoch_payload_signature(existing) == self._epoch_payload_signature(value):
                return existing
            raise ValueError(f"evidence epoch conflict for {value.epoch_id}")
        with self._global_transaction() as db:
            db.execute(
                "INSERT INTO evidence_epochs("
                "epoch_id,deployment_id,started_at,activated_at,code_commit_sha,model_version,"
                "artifact_sha256,feature_schema_version,analysis_universe,"
                "analysis_universe_hash,evidence_policy_version,risk_policy_version,"
                "runtime_schema_version,status,paper_run_id,release_manifest,release_manifest_sha256,runtime_pause_policy,updated_at"
                ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    value.epoch_id, value.deployment_id, value.started_at,
                    value.activated_at,
                    value.code_commit_sha, value.model_version,
                    value.artifact_sha256, value.feature_schema_version,
                    json.dumps(list(value.analysis_universe), separators=(",", ":")),
                    value.analysis_universe_hash,
                    value.evidence_policy_version, value.risk_policy_version,
                    value.runtime_schema_version, value.status,
                    value.paper_run_id or value.deployment_id,
                    json.dumps(value.release_manifest, separators=(",", ":"), sort_keys=True, default=str)
                    if value.release_manifest is not None else None,
                    value.release_manifest_sha256,
                    json.dumps(value.runtime_pause_policy, separators=(",", ":"), sort_keys=True),
                    self._now().isoformat(),
                ),
            )
        return value

    def get_evidence_epoch(self, epoch_id: str) -> EvidenceEpoch | None:
        with self._global_connect() as db:
            row = db.execute(
                "SELECT epoch_id,deployment_id,started_at,activated_at,code_commit_sha,"
                "model_version,artifact_sha256,feature_schema_version,"
                "analysis_universe,analysis_universe_hash,"
                "evidence_policy_version,risk_policy_version,"
                "runtime_schema_version,status,paper_run_id,release_manifest,release_manifest_sha256,runtime_pause_policy "
                "FROM evidence_epochs WHERE epoch_id=?",
                (str(epoch_id),),
            ).fetchone()
        return self._epoch_from_row(row) if row else None

    def get_active_evidence_epoch(self) -> EvidenceEpoch | None:
        with self._global_connect() as db:
            row = db.execute(
                "SELECT epoch_id,deployment_id,started_at,activated_at,code_commit_sha,"
                "model_version,artifact_sha256,feature_schema_version,"
                "analysis_universe,analysis_universe_hash,"
                "evidence_policy_version,risk_policy_version,"
                "runtime_schema_version,status,paper_run_id,release_manifest,release_manifest_sha256,runtime_pause_policy "
                "FROM evidence_epochs WHERE status='ACTIVE'"
            ).fetchone()
        return self._epoch_from_row(row) if row else None

    def transition_evidence_epoch(
        self,
        epoch_id: str,
        status: str,
    ) -> EvidenceEpoch:
        target = str(status).upper()
        allowed = {
            ("DRAFT", "ACTIVE"),
            ("DRAFT", "INVALIDATED"),
            ("DRAFT", "QUARANTINED"),
            ("ACTIVE", "SEAL_BLOCKED"),
            ("ACTIVE", "SEAL_READY"),
            ("SEAL_BLOCKED", "ACTIVE"),
            ("SEAL_BLOCKED", "SEAL_READY"),
            ("SEAL_READY", "ACTIVE"),
            ("SEAL_READY", "SEALED"),
            ("ACTIVE", "INVALIDATED"),
            ("ACTIVE", "QUARANTINED"),
            ("SEAL_BLOCKED", "INVALIDATED"),
            ("SEAL_BLOCKED", "QUARANTINED"),
            ("SEAL_READY", "INVALIDATED"),
            ("SEAL_READY", "QUARANTINED"),
        }
        with self._global_transaction() as db:
            row = db.execute(
                "SELECT status FROM evidence_epochs WHERE epoch_id=?",
                (str(epoch_id),),
            ).fetchone()
            if row is None:
                raise ValueError("unknown evidence epoch")
            current = str(row[0])
            if current == target:
                # Re-load the epoch within the same transaction and validate integrity
                row2 = db.execute(
                    "SELECT epoch_id,deployment_id,started_at,activated_at,code_commit_sha,"
                    "model_version,artifact_sha256,feature_schema_version,"
                    "analysis_universe,analysis_universe_hash,"
                    "evidence_policy_version,risk_policy_version,"
                    "runtime_schema_version,status,paper_run_id,release_manifest,release_manifest_sha256,runtime_pause_policy "
                    "FROM evidence_epochs WHERE epoch_id=?",
                    (str(epoch_id),),
                ).fetchone()
                epoch_current = self._epoch_from_row(row2) if row2 else None
                assert epoch_current is not None
                # validate stored epoch integrity before returning
                epoch_current.validate()
                return epoch_current
            if (current, target) not in allowed:
                raise ValueError(f"invalid evidence epoch transition: {current}->{target}")
            if target == "ACTIVE":
                # load epoch within transaction for validation and to build payload
                row3 = db.execute(
                    "SELECT epoch_id,deployment_id,started_at,activated_at,code_commit_sha,"
                    "model_version,artifact_sha256,feature_schema_version,"
                    "analysis_universe,analysis_universe_hash,"
                    "evidence_policy_version,risk_policy_version,"
                    "runtime_schema_version,status,paper_run_id,release_manifest,release_manifest_sha256,runtime_pause_policy "
                    "FROM evidence_epochs WHERE epoch_id=?",
                    (str(epoch_id),),
                ).fetchone()
                epoch = self._epoch_from_row(row3) if row3 else None
                assert epoch is not None
                self.validate_runtime_epoch(epoch)
            transitioned_at = self._now().isoformat()
            if target == "ACTIVE":
                # Attempt atomic update only if currently DRAFT to avoid races
                cur = db.execute(
                    "UPDATE evidence_epochs SET status=?,activated_at=?,updated_at=? "
                    "WHERE epoch_id=? AND status='DRAFT'",
                    (target, transitioned_at, transitioned_at, str(epoch_id)),
                )
                if cur.rowcount == 0:
                    # Another transaction won the race — re-load and validate integrity
                    row4 = db.execute(
                        "SELECT epoch_id,deployment_id,started_at,activated_at,code_commit_sha,"
                        "model_version,artifact_sha256,feature_schema_version,"
                        "analysis_universe,analysis_universe_hash,"
                        "evidence_policy_version,risk_policy_version,"
                        "runtime_schema_version,status,paper_run_id,release_manifest,release_manifest_sha256,runtime_pause_policy "
                        "FROM evidence_epochs WHERE epoch_id=?",
                        (str(epoch_id),),
                    ).fetchone()
                    epoch_after = self._epoch_from_row(row4) if row4 else None
                    if epoch_after is None:
                        raise ValueError("evidence epoch disappeared during activation")
                    if epoch_after.status == 'ACTIVE':
                        # ensure stored ACTIVE epoch integrity
                        epoch_after.validate()
                        return epoch_after
                    raise ValueError("failed to activate evidence epoch due to concurrent transition")
                event = {
                    "event_type": EPOCH_ACTIVATION_AUDIT_EVENT,
                    "epoch_id": epoch.epoch_id,
                    "deployment_id": epoch.deployment_id,
                    "previous_status": current,
                    "new_status": target,
                    "activated_at": transitioned_at,
                    "code_commit_sha": epoch.code_commit_sha,
                    "artifact_sha256": epoch.artifact_sha256,
                    "feature_schema_version": epoch.feature_schema_version,
                    "analysis_universe": ",".join(epoch.analysis_universe),
                    "analysis_universe_hash": epoch.analysis_universe_hash,
                    "paper_run_id": epoch.paper_run_id or epoch.deployment_id,
                    "release_manifest_sha256": epoch.release_manifest_sha256,
                }
                if not self._find_existing_activation_audit(db, epoch.epoch_id, target):
                    self._insert_audit_event_db(db, event)
            else:
                db.execute(
                    "UPDATE evidence_epochs SET status=?,updated_at=? WHERE epoch_id=?",
                    (target, transitioned_at, str(epoch_id)),
                )
        result = self.get_evidence_epoch(str(epoch_id))
        assert result is not None
        result.validate()
        return result

    def invalidate_evidence_epoch(
        self,
        epoch_id: str,
        reason_code: str,
        reason_detail: str,
        contributing_reasons: list[str] | None = None,
        *,
        evidence_action: str = "PRESERVED",
        retroactive_audit: bool = True,
    ) -> EvidenceEpoch:
        if not reason_code:
            raise ValueError("reason_code is required for invalidate")
        if not reason_detail:
            raise ValueError("reason_detail is required for invalidate")
        epoch_id = str(epoch_id)
        with self._global_transaction() as db:
            row = db.execute(
                "SELECT status,deployment_id,activated_at,code_commit_sha,artifact_sha256,updated_at "
                "FROM evidence_epochs WHERE epoch_id=?",
                (epoch_id,),
            ).fetchone()
            if row is None:
                raise ValueError("unknown evidence epoch")
            current_status, deployment_id, activated_at, code_commit_sha, artifact_sha256, updated_at = (
                str(row[0]), str(row[1]), row[2], str(row[3]), str(row[4]), str(row[5])
            )
            if current_status == "INVALIDATED":
                if self._find_existing_invalidation_audit(db, epoch_id, reason_code):
                    return self.get_evidence_epoch(epoch_id)
                existing = db.execute(
                    "SELECT 1 FROM audit_events WHERE event_type=? "
                    "AND json_extract(payload,'$.epoch_id')=?",
                    (EPOCH_INVALIDATION_AUDIT_EVENT, epoch_id),
                ).fetchone()
                if existing is not None:
                    raise ValueError("epoch already invalidated with a different reason")
                invalidated_at = updated_at
                event = {
                    "event_type": EPOCH_INVALIDATION_AUDIT_EVENT,
                    "epoch_id": epoch_id,
                    "deployment_id": deployment_id,
                    "previous_status": current_status,
                    "new_status": "INVALIDATED",
                    "reason_code": reason_code,
                    "reason_detail": reason_detail,
                    "contributing_reasons": contributing_reasons or [],
                    "evidence_action": evidence_action,
                    "invalidated_at": invalidated_at,
                    "audit_recorded_at": self._now().isoformat(),
                    "code_commit_sha": code_commit_sha,
                    "artifact_sha256": artifact_sha256,
                    "retroactive_audit": retroactive_audit,
                }
                self._insert_audit_event_db(db, event)
                return self.get_evidence_epoch(epoch_id)
            if (current_status, "INVALIDATED") not in {
                ("DRAFT", "INVALIDATED"),
                ("ACTIVE", "INVALIDATED"),
                ("SEAL_BLOCKED", "INVALIDATED"),
                ("SEAL_READY", "INVALIDATED"),
            }:
                raise ValueError(f"invalid evidence epoch transition: {current_status}->INVALIDATED")
            invalidated_at = self._now().isoformat()
            db.execute(
                "UPDATE evidence_epochs SET status=?,updated_at=? WHERE epoch_id=?",
                ("INVALIDATED", invalidated_at, epoch_id),
            )
            event = {
                "event_type": EPOCH_INVALIDATION_AUDIT_EVENT,
                "epoch_id": epoch_id,
                "deployment_id": deployment_id,
                "previous_status": current_status,
                "new_status": "INVALIDATED",
                "reason_code": reason_code,
                "reason_detail": reason_detail,
                "contributing_reasons": contributing_reasons or [],
                "evidence_action": evidence_action,
                "invalidated_at": invalidated_at,
                "audit_recorded_at": self._now().isoformat(),
                "code_commit_sha": code_commit_sha,
                "artifact_sha256": artifact_sha256,
                "retroactive_audit": retroactive_audit,
            }
            self._insert_audit_event_db(db, event)
        result = self.get_evidence_epoch(epoch_id)
        assert result is not None
        result.validate()
        return result

    def validate_runtime_epoch(self, epoch: EvidenceEpoch) -> None:
        epoch.validate()
        if epoch.deployment_id != runtime_deployment_id():
            raise RuntimeError("epoch deployment_id mismatch runtime deployment")
        runtime_universe = get_runtime_universe()
        if tuple(epoch.analysis_universe) != runtime_universe.analysis_symbols:
            raise RuntimeError("epoch analysis_universe mismatch runtime universe")

    def assert_runtime_epoch_ready(self, require_active: bool = True) -> EvidenceEpoch | None:
        epoch = self.get_active_evidence_epoch()
        if epoch is None:
            if require_active:
                raise RuntimeError("ACTIVE epoch required")
            return None
        try:
            self.validate_runtime_epoch(epoch)
        except RuntimeError as exc:
            raise RuntimeError("epoch analysis_universe mismatch runtime universe") from exc
        return epoch

    def _validate_active_epoch_for_prediction(
        self,
        prediction: Mapping[str, Any],
    ) -> EvidenceEpoch | None:
        if prediction.get("evidence_eligible") is not True:
            return None
        epoch = self.get_active_evidence_epoch()
        if epoch is None:
            raise RuntimeError("eligible evidence requires an ACTIVE epoch")
        epoch.validate()
        self.validate_runtime_epoch(epoch)
        runtime_universe = get_runtime_universe()
        expected = {
            "deployment_id": epoch.deployment_id,
            "model_version": epoch.model_version,
            "artifact_sha256": epoch.artifact_sha256,
            "feature_schema_version": epoch.feature_schema_version,
            "git_commit": epoch.code_commit_sha,
            "analysis_universe_hash": epoch.analysis_universe_hash,
        }
        mismatches = [
            field for field, value in expected.items()
            if str(prediction.get(field) or "") != str(value)
        ]
        if prediction.get("epoch_id") and str(prediction["epoch_id"]) != epoch.epoch_id:
            mismatches.append("epoch_id")
        symbol = str(prediction.get("symbol") or "").strip().upper()
        base_symbol = symbol[:-4] if symbol.endswith("USDT") else symbol
        if base_symbol not in runtime_universe.analysis_symbols:
            mismatches.append("symbol_outside_analysis_universe")
        if epoch.evidence_policy_version != EVIDENCE_POLICY_VERSION:
            mismatches.append("evidence_policy_version")
        if epoch.risk_policy_version != RISK_POLICY_VERSION:
            mismatches.append("risk_policy_version")
        if epoch.runtime_schema_version != RUNTIME_EVIDENCE_SCHEMA_VERSION:
            mismatches.append("runtime_schema_version")
        try:
            predicted_at = datetime.fromisoformat(
                str(
                    prediction.get("predicted_at")
                    or prediction.get("event_time")
                    or prediction.get("timestamp")
                    or ""
                ).replace("Z", "+00:00")
            )
            activated_at = datetime.fromisoformat(
                str(epoch.activated_at or "").replace("Z", "+00:00")
            )
            predicted_at = (
                predicted_at.replace(tzinfo=timezone.utc)
                if predicted_at.tzinfo is None
                else predicted_at.astimezone(timezone.utc)
            )
            activated_at = (
                activated_at.replace(tzinfo=timezone.utc)
                if activated_at.tzinfo is None
                else activated_at.astimezone(timezone.utc)
            )
            if predicted_at < activated_at:
                mismatches.append("prediction_before_epoch_activation")
        except ValueError:
            mismatches.append("prediction_activation_timestamp")
        if mismatches:
            raise RuntimeError(
                "active evidence epoch mismatch:" + ",".join(sorted(set(mismatches)))
            )
        return epoch

    def _initialize_path(self, path: Path) -> None:
        with self._connect_path(path) as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS predictions (
                    prediction_id TEXT PRIMARY KEY, payload TEXT NOT NULL,
                    payload_sha256 TEXT NOT NULL, written_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS prediction_idempotency (
                    idempotency_key TEXT PRIMARY KEY,
                    prediction_id TEXT NOT NULL UNIQUE REFERENCES predictions(prediction_id)
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
                DROP INDEX IF EXISTS uq_prediction_idempotency_key;
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
        if table == "audit_events":
            with self._global_connect() as db:
                yield from db.execute(f"SELECT {columns} FROM {table}").fetchall()
            for path in self.partition_paths():
                with self._connect(path) as db:
                    yield from db.execute(f"SELECT {columns} FROM {table}").fetchall()
            return
        for path in self.partition_paths():
            with self._connect(path) as db:
                yield from db.execute(f"SELECT {columns} FROM {table}").fetchall()

    @staticmethod
    def _global_row(row: tuple[Any, ...]) -> dict[str, Any]:
        keys = (
            "idempotency_key", "prediction_id", "partition_date", "state",
            "payload_hash", "reserved_at", "committed_at", "owner_id",
            "error_reason",
        )
        return dict(zip(keys, row))

    def _get_global_reservation(self, idempotency_key: str) -> dict[str, Any] | None:
        with self._global_connect() as db:
            row = db.execute(
                "SELECT idempotency_key,prediction_id,partition_date,state,"
                "payload_hash,reserved_at,committed_at,owner_id,error_reason "
                "FROM prediction_global_idempotency WHERE idempotency_key=?",
                (str(idempotency_key),),
            ).fetchone()
        return self._global_row(row) if row else None

    def _reserve_global_prediction(
        self,
        *,
        idempotency_key: str,
        prediction_id: str,
        payload_hash: str,
    ) -> dict[str, Any]:
        now = self._now().isoformat()
        partition_date = self._now().date().isoformat()
        conflict = False
        reservation: dict[str, Any] | None = None
        with self._global_transaction() as db:
            row = db.execute(
                "SELECT idempotency_key,prediction_id,partition_date,state,"
                "payload_hash,reserved_at,committed_at,owner_id,error_reason "
                "FROM prediction_global_idempotency WHERE idempotency_key=?",
                (idempotency_key,),
            ).fetchone()
            if row:
                reservation = self._global_row(row)
                if reservation["payload_hash"] != payload_hash:
                    db.execute(
                        "UPDATE prediction_global_idempotency SET error_reason=? "
                        "WHERE idempotency_key=?",
                        ("conflicting_payload_hash", idempotency_key),
                    )
                    conflict = True
                elif reservation["state"] == "ABORTED":
                    db.execute(
                        "UPDATE prediction_global_idempotency SET state='RESERVED',"
                        "reserved_at=?,committed_at=NULL,owner_id=?,error_reason=NULL "
                        "WHERE idempotency_key=?",
                        (now, str(runtime_owner_metadata()["process_id"]), idempotency_key),
                    )
                    reservation.update({
                        "state": "RESERVED",
                        "reserved_at": now,
                        "committed_at": None,
                        "error_reason": None,
                    })
            else:
                db.execute(
                    "INSERT INTO prediction_global_idempotency VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        idempotency_key, prediction_id, partition_date, "RESERVED",
                        payload_hash, now, None,
                        str(runtime_owner_metadata()["process_id"]), None,
                    ),
                )
        if conflict:
            raise ValueError("non-idempotent duplicate prediction")
        if reservation is not None:
            return reservation
        return {
            "idempotency_key": idempotency_key,
            "prediction_id": prediction_id,
            "partition_date": partition_date,
            "state": "RESERVED",
            "payload_hash": payload_hash,
            "reserved_at": now,
            "committed_at": None,
            "owner_id": str(runtime_owner_metadata()["process_id"]),
            "error_reason": None,
        }

    def _mark_global_committed(self, idempotency_key: str) -> None:
        with self._global_transaction() as db:
            updated = db.execute(
                "UPDATE prediction_global_idempotency SET state='COMMITTED',"
                "committed_at=?,error_reason=NULL "
                "WHERE idempotency_key=? AND state='RESERVED'",
                (self._now().isoformat(), idempotency_key),
            ).rowcount
            if updated == 0:
                row = db.execute(
                    "SELECT state FROM prediction_global_idempotency "
                    "WHERE idempotency_key=?",
                    (idempotency_key,),
                ).fetchone()
                if row is None or str(row[0]) != "COMMITTED":
                    raise RuntimeError("global idempotency commit lost reservation")

    def _mark_global_aborted(self, idempotency_key: str, reason: str) -> None:
        with self._global_transaction() as db:
            db.execute(
                "UPDATE prediction_global_idempotency SET state='ABORTED',"
                "error_reason=? WHERE idempotency_key=? AND state='RESERVED'",
                (reason, idempotency_key),
            )

    def _prediction_from_reservation(
        self,
        reservation: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        path = self._path_for_partition_date(str(reservation["partition_date"]))
        if not path.exists():
            return None
        with self._connect(path) as db:
            row = db.execute(
                "SELECT payload FROM predictions WHERE prediction_id=?",
                (str(reservation["prediction_id"]),),
            ).fetchone()
        return json.loads(row[0]) if row else None

    def get_prediction_by_idempotency_key(self, idempotency_key: str) -> dict[str, Any] | None:
        reservation = self._get_global_reservation(str(idempotency_key))
        if reservation is None or reservation["state"] == "ABORTED":
            return None
        prediction = self._prediction_from_reservation(reservation)
        if prediction is None:
            if reservation["state"] == "COMMITTED":
                raise RuntimeError("global committed prediction is missing")
            return None
        if idempotency_payload_sha256(prediction) != reservation["payload_hash"]:
            raise RuntimeError("global prediction payload hash mismatch")
        if reservation["state"] == "RESERVED":
            self._mark_global_committed(str(idempotency_key))
        return prediction

    def recover_global_reservations(
        self,
        *,
        stale_after_seconds: float = GLOBAL_RESERVATION_STALE_SECONDS,
    ) -> dict[str, int]:
        with self._global_connect() as db:
            rows = db.execute(
                "SELECT idempotency_key,prediction_id,partition_date,state,"
                "payload_hash,reserved_at,committed_at,owner_id,error_reason "
                "FROM prediction_global_idempotency WHERE state='RESERVED'"
            ).fetchall()
        recovered = aborted = pending = 0
        for raw_row in rows:
            reservation = self._global_row(raw_row)
            prediction = self._prediction_from_reservation(reservation)
            if prediction is not None:
                if idempotency_payload_sha256(prediction) != reservation["payload_hash"]:
                    self._mark_global_aborted(
                        str(reservation["idempotency_key"]),
                        "recovery_payload_hash_mismatch",
                    )
                    aborted += 1
                    continue
                self._mark_global_committed(str(reservation["idempotency_key"]))
                recovered += 1
                continue
            try:
                reserved_at = datetime.fromisoformat(
                    str(reservation["reserved_at"]).replace("Z", "+00:00")
                )
                reserved_at = (
                    reserved_at.replace(tzinfo=timezone.utc)
                    if reserved_at.tzinfo is None
                    else reserved_at.astimezone(timezone.utc)
                )
                age = (self._now() - reserved_at).total_seconds()
            except ValueError:
                age = stale_after_seconds
            if age >= stale_after_seconds:
                self._mark_global_aborted(
                    str(reservation["idempotency_key"]),
                    "stale_reservation_without_prediction",
                )
                aborted += 1
            else:
                pending += 1
        return {"recovered": recovered, "aborted": aborted, "pending": pending}

    def write_prediction_evidence(
        self,
        prediction: Mapping[str, Any],
        snapshot: Mapping[str, Any],
    ) -> dict[str, Any]:
        prediction = self._with_runtime_metadata(prediction)
        snapshot = self._with_runtime_metadata(snapshot)
        epoch = self._validate_active_epoch_for_prediction(prediction)
        if epoch is not None:
            prediction = {**prediction, "epoch_id": epoch.epoch_id}
            snapshot = {**snapshot, "epoch_id": epoch.epoch_id}
        prediction_id = str(prediction["prediction_id"])
        if str(snapshot.get("prediction_id")) != prediction_id:
            raise ValueError("prediction/snapshot identity mismatch")
        idempotency_key = str(
            prediction.get("idempotency_key")
            or f"prediction_id:{prediction_id}"
        )
        semantic_hash = idempotency_payload_sha256(prediction)
        try:
            reservation = self._reserve_global_prediction(
                idempotency_key=idempotency_key,
                prediction_id=prediction_id,
                payload_hash=semantic_hash,
            )
        except ValueError as exc:
            self._record_incident(
                "duplicate_conflicting_payload",
                "predictions",
                prediction_id,
                str(exc),
            )
            raise

        prediction_id = str(reservation["prediction_id"])
        prediction = {**prediction, "prediction_id": prediction_id}
        snapshot = {**snapshot, "prediction_id": prediction_id}
        stored_payload = self._prediction_from_reservation(reservation)
        if stored_payload is not None:
            if idempotency_payload_sha256(stored_payload) != semantic_hash:
                raise ValueError("non-idempotent duplicate prediction")
            self._mark_global_committed(idempotency_key)
            return stored_payload

        pred_json, snap_json = _canonical(prediction), _canonical(snapshot)
        written_at = self._now().isoformat()
        target_path = self._path_for_partition_date(str(reservation["partition_date"]))
        try:
            with self.transaction(target_path) as db:
                existing = db.execute("SELECT payload_sha256 FROM predictions WHERE prediction_id=?", (prediction_id,)).fetchone()
                digest = payload_sha256(prediction)
                if existing and existing[0] != digest:
                    stored = db.execute(
                        "SELECT payload FROM predictions WHERE prediction_id=?",
                        (prediction_id,),
                    ).fetchone()
                    stored_payload = json.loads(stored[0]) if stored else {}
                    if idempotency_payload_sha256(stored_payload) != semantic_hash:
                        raise ValueError("non-idempotent duplicate prediction")
                existing_snapshot = db.execute(
                    "SELECT payload_sha256 FROM feature_snapshots WHERE prediction_id=?", (prediction_id,)
                ).fetchone()
                snapshot_digest = payload_sha256(snapshot)
                if existing_snapshot and existing_snapshot[0] != snapshot_digest:
                    stored_snapshot = db.execute(
                        "SELECT payload FROM feature_snapshots WHERE prediction_id=?",
                        (prediction_id,),
                    ).fetchone()
                    stored_snapshot_payload = (
                        json.loads(stored_snapshot[0]) if stored_snapshot else {}
                    )
                    if (
                        idempotency_payload_sha256(stored_snapshot_payload)
                        != idempotency_payload_sha256(snapshot)
                    ):
                        raise ValueError("non-idempotent duplicate feature snapshot")
                db.execute(
                    "INSERT OR IGNORE INTO predictions VALUES (?, ?, ?, ?)",
                    (prediction_id, pred_json, digest, written_at),
                )
                db.execute(
                    "INSERT OR IGNORE INTO feature_snapshots VALUES (?, ?, ?)",
                    (prediction_id, snap_json, snapshot_digest),
                )
                partition_key = str(prediction.get("idempotency_key") or "")
                if partition_key:
                    db.execute(
                        "INSERT OR IGNORE INTO prediction_idempotency VALUES (?, ?)",
                        (partition_key, prediction_id),
                    )
                    owner = db.execute(
                        "SELECT prediction_id FROM prediction_idempotency WHERE idempotency_key=?",
                        (partition_key,),
                    ).fetchone()
                    if owner and str(owner[0]) != prediction_id:
                        raise ValueError("non-idempotent duplicate prediction")
        except Exception as exc:
            self._mark_global_aborted(
                idempotency_key,
                f"partition_write_failed:{type(exc).__name__}",
            )
            if "non-idempotent" in str(exc):
                self._record_incident("duplicate_conflicting_payload", "predictions", prediction_id, str(exc))
            raise
        self._mark_global_committed(idempotency_key)
        return dict(prediction)

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

    def get_committed_final_decision(self, prediction_id: str) -> dict[str, Any] | None:
        """Return the canonical decision plus its immutable storage digest.

        ``decision_sha256`` is metadata about the stored payload and is not part
        of that payload.  Execution callers must present this digest and the
        execution boundary must reload it before creating a reservation.
        """
        path = self._find_partition("final_decisions", "prediction_id", prediction_id)
        if path is None:
            return None
        with self._connect(path) as db:
            row = db.execute(
                "SELECT payload,payload_sha256 FROM final_decisions WHERE prediction_id=?",
                (prediction_id,),
            ).fetchone()
        if row is None:
            return None
        return {**json.loads(row[0]), "decision_sha256": str(row[1])}

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
        universe = get_runtime_universe()
        result.setdefault("environment", runtime_environment())
        result.setdefault("deployment_id", runtime_deployment_id())
        result.setdefault("runtime_id", runtime_id())
        result.setdefault("evidence_eligible", runtime_evidence_eligible())
        result.setdefault("paper_run_id", runtime_paper_run_id())
        result["analysis_universe"] = list(universe.analysis_symbols)
        result["analysis_universe_hash"] = universe.analysis_hash
        owner = runtime_owner_metadata()
        result.setdefault("process_id", owner["process_id"])
        result.setdefault("hostname", owner["hostname"])
        result.setdefault("started_at", owner["started_at"])
        return result

    def latest_outcomes(self) -> list[dict[str, Any]]:
        """Return only the highest valid amendment revision for each position."""
        latest: dict[str, tuple[int, dict[str, Any]]] = {}
        seen_outcome_ids: set[str] = set()
        quarantined_outcome_ids = {
            str(record_id)
            for table_name, record_id in self._all_rows(
                "evidence_quarantine", "table_name, record_id",
            )
            if str(table_name) == "outcome_links"
        }
        rows = sorted(
            self._all_rows("outcome_links", "outcome_id, payload, written_at"),
            key=lambda row: (str(row[2]), str(row[0])),
        )
        for outcome_id, raw_payload, _ in rows:
            if str(outcome_id) in seen_outcome_ids or str(outcome_id) in quarantined_outcome_ids:
                continue
            seen_outcome_ids.add(str(outcome_id))
            try:
                payload = json.loads(raw_payload)
            except (TypeError, json.JSONDecodeError):
                continue
            position_id = str(payload.get("position_id") or "")
            revision = int(payload.get("outcome_revision") or 0)
            current = latest.get(position_id)
            if position_id and revision > 0 and (current is None or revision > current[0]):
                latest[position_id] = (revision, payload)
        return [row for _, row in latest.values()]

    def get_latest_outcome_for_position(self, position_id: str) -> dict[str, Any] | None:
        latest: tuple[int, dict[str, Any]] | None = None
        seen_outcome_ids: set[str] = set()
        quarantined_outcome_ids = {
            str(record_id)
            for table_name, record_id in self._all_rows(
                "evidence_quarantine", "table_name, record_id",
            )
            if str(table_name) == "outcome_links"
        }
        for outcome_id, raw_payload in self._all_rows(
            "outcome_links",
            "outcome_id, payload",
        ):
            if str(outcome_id) in seen_outcome_ids or str(outcome_id) in quarantined_outcome_ids:
                continue
            seen_outcome_ids.add(str(outcome_id))
            try:
                payload = json.loads(raw_payload)
            except (TypeError, json.JSONDecodeError):
                continue
            if str(payload.get("position_id") or "") != str(position_id):
                continue
            revision = int(payload.get("outcome_revision") or 0)
            if latest is None or revision > latest[0]:
                latest = (revision, payload)
        return latest[1] if latest else None

    def shadow_evidence_rows(self) -> dict[str, list[dict[str, Any]]]:
        """Read canonical JSON payloads used by the derived shadow gate."""
        result: dict[str, list[dict[str, Any]]] = {}
        quarantined = {
            (str(table), str(record_id))
            for table, record_id in self._all_rows(
                "evidence_quarantine",
                "table_name, record_id",
            )
        }
        identity_columns = {
            "predictions": "prediction_id",
            "feature_snapshots": "prediction_id",
            "final_decisions": "decision_id",
            "audit_events": "event_type || ':' || payload_sha256 || ':' || written_at",
        }
        for table, identity in identity_columns.items():
            unique: dict[str, dict[str, Any]] = {}
            for record_id, payload in self._all_rows(table, f"{identity}, payload"):
                if (table, str(record_id)) in quarantined:
                    continue
                unique.setdefault(str(record_id), json.loads(payload))
            result[table] = list(unique.values())
        result["outcomes"] = self.latest_outcomes()
        result["quarantine"] = [
            {
                "table_name": str(table),
                "record_id": str(record_id),
                "reason": str(reason),
                "detected_at": str(detected_at),
            }
            for table, record_id, reason, detected_at in self._all_rows(
                "evidence_quarantine",
                "table_name, record_id, reason, detected_at",
            )
        ]
        return result

    def health(self, *, quarantine_corrupt: bool = True) -> dict[str, Any]:
        # Evaluators such as ``--check-only`` must remain logically read-only.
        # Quarantine is an explicit remediation action, not a health-read side
        # effect.  The default preserves the legacy administrative behavior.
        corrupt_payloads = (
            self.verify_and_quarantine()
            if quarantine_corrupt
            else self.count_corrupt_payloads()
        )
        raw_prediction_rows: list[tuple[Any, Any, str]] = []
        for prediction_path in self.partition_paths():
            with self._connect(prediction_path) as prediction_db:
                raw_prediction_rows.extend(
                    (
                        prediction_id,
                        payload,
                        self._partition_date_for_path(prediction_path),
                    )
                    for prediction_id, payload in prediction_db.execute(
                        "SELECT prediction_id, payload FROM predictions"
                    ).fetchall()
                )
        prediction_payloads: dict[str, dict[str, Any]] = {}
        prediction_payload_variants: dict[str, set[str]] = {}
        prediction_locations: dict[str, set[str]] = {}
        idempotency_owners: dict[str, set[str]] = {}
        invalid_lineage_predictions: set[str] = set()
        unknown_symbol_predictions: set[str] = set()
        universe_mismatch_predictions: set[str] = set()
        for prediction_id, raw_payload, partition_date in raw_prediction_rows:
            prediction_id = str(prediction_id)
            prediction_payload_variants.setdefault(prediction_id, set()).add(str(raw_payload))
            prediction_locations.setdefault(prediction_id, set()).add(partition_date)
            try:
                payload = json.loads(str(raw_payload))
            except (TypeError, json.JSONDecodeError):
                continue
            prediction_payloads.setdefault(prediction_id, payload)
            if payload.get("event_type") != "prediction_created":
                continue
            if any(not payload.get(field) for field in REQUIRED_PREDICTION_LINEAGE_FIELDS):
                invalid_lineage_predictions.add(prediction_id)
            if str(payload.get("symbol") or "").upper() == "UNKNOWN":
                unknown_symbol_predictions.add(prediction_id)
            universe = tuple(
                str(symbol).strip().upper()
                for symbol in (payload.get("analysis_universe") or ())
            )
            symbol = str(payload.get("symbol") or "").strip().upper()
            base_symbol = symbol[:-4] if symbol.endswith("USDT") else symbol
            if (
                not universe
                or len(set(universe)) != len(universe)
                or payload.get("analysis_universe_hash")
                != analysis_universe_hash(universe)
                or base_symbol not in universe
            ):
                universe_mismatch_predictions.add(prediction_id)
            idempotency_key = str(payload.get("idempotency_key") or "")
            if idempotency_key:
                idempotency_owners.setdefault(idempotency_key, set()).add(prediction_id)

        prediction_ids = {str(row[0]) for row in self._all_rows("predictions", "prediction_id")}
        with self._global_connect() as global_db:
            global_rows = global_db.execute(
                "SELECT idempotency_key,prediction_id,partition_date,state,"
                "payload_hash,reserved_at,committed_at,owner_id,error_reason "
                "FROM prediction_global_idempotency"
            ).fetchall()
            global_integrity = str(
                global_db.execute("PRAGMA integrity_check").fetchone()[0]
            )
        global_reservations = [self._global_row(row) for row in global_rows]
        committed_global_prediction_ids = {
            str(row["prediction_id"])
            for row in global_reservations
            if row["state"] == "COMMITTED"
        }
        committed_without_prediction = sum(
            str(row["prediction_id"]) not in prediction_locations
            or str(row["partition_date"])
            not in prediction_locations[str(row["prediction_id"])]
            for row in global_reservations
            if row["state"] == "COMMITTED"
        )
        predictions_without_global_commit = len(
            prediction_ids - committed_global_prediction_ids
        )
        pending_global_reservations = sum(
            row["state"] == "RESERVED" for row in global_reservations
        )
        aborted_global_reservations = sum(
            row["state"] == "ABORTED" for row in global_reservations
        )
        global_error_reservations = sum(
            bool(row["error_reason"]) for row in global_reservations
        )
        snapshot_ids = {str(row[0]) for row in self._all_rows("feature_snapshots", "prediction_id")}
        raw_decision_rows = list(self._all_rows(
            "final_decisions",
            "decision_id, prediction_id, payload, written_at",
        ))
        decisions = {
            (str(decision_id), str(prediction_id or ""))
            for decision_id, prediction_id, _, _ in raw_decision_rows
        }
        decision_written_at = {
            str(prediction_id or ""): str(written_at)
            for _, prediction_id, _, written_at in raw_decision_rows
            if prediction_id
        }
        decision_payloads: dict[str, dict[str, Any]] = {}
        for _, prediction_id, raw_payload, _ in raw_decision_rows:
            if not prediction_id:
                continue
            try:
                decision_payloads.setdefault(
                    str(prediction_id), json.loads(str(raw_payload)),
                )
            except (TypeError, json.JSONDecodeError):
                continue
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
        duplicate_prediction_ids = sum(
            len(payloads) > 1 for payloads in prediction_payload_variants.values()
        )
        duplicate_idempotency_keys = sum(len(owners) > 1 for owners in idempotency_owners.values())
        duplicate_predictions = duplicate_prediction_ids + duplicate_idempotency_keys
        orphan_outcomes = sum(prediction_id not in prediction_ids for _, prediction_id in outcomes)
        latest_outcome_prediction_ids = {
            str(row.get("prediction_id") or "") for row in self.latest_outcomes()
        }
        trade_prediction_ids: set[str] = set()
        for _, prediction_id in decisions:
            decision = decision_payloads.get(prediction_id)
            if str((decision or {}).get("action") or "").upper() in {
                "BUY", "SELL", "TRADE", "AUTHORIZED", "SUBMITTED", "FILLED",
            }:
                trade_prediction_ids.add(prediction_id)
        # A TRADE decision alone does not imply that a position existed.  The
        # execution-aware canary gate owns acceptance/position/outcome coverage.
        # Keep this store-level metric limited to outcomes that can actually be
        # inferred from evidence rows; do not label rejected execution as a
        # missing outcome.
        trade_decisions_without_outcome = len(
            trade_prediction_ids - latest_outcome_prediction_ids
        )
        missing_outcomes = 0
        production_prediction_count = sum(
            payload.get("event_type") == "prediction_created"
            for payload in prediction_payloads.values()
        )
        invalid_lineage_count = len(invalid_lineage_predictions)
        unknown_symbol_count = len(unknown_symbol_predictions)
        universe_mismatch_count = len(universe_mismatch_predictions)
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
            and invalid_lineage_count == 0 and unknown_symbol_count == 0
            and universe_mismatch_count == 0
            and duplicate_predictions == 0
            and missing_outcomes == 0
            and global_integrity == "ok"
            and committed_without_prediction == 0
            and predictions_without_global_commit == 0
            and pending_global_reservations == 0
            and aborted_global_reservations == 0
            and global_error_reservations == 0
        )
        critical = (
            integrity != "ok"
            or global_integrity != "ok"
            or foreign_key_violations > 0
            or duplicate_predictions > 0
            or orphan_decisions > 0
            or decisions_without_prediction > 0
            or committed_without_prediction > 0
            or predictions_without_global_commit > 0
            or universe_mismatch_count > 0
        )
        return {
            "status": "healthy" if healthy else "degraded",
            "severity": "HEALTHY" if healthy else ("UNHEALTHY" if critical else "DEGRADED"),
            "integrity": integrity, "orphan_snapshots": orphan_snapshots, "missing_snapshots": missing_snapshots,
            "global_index_integrity": global_integrity,
            "global_committed_without_prediction": committed_without_prediction,
            "predictions_without_global_commit": predictions_without_global_commit,
            "pending_global_reservations": pending_global_reservations,
            "aborted_global_reservations": aborted_global_reservations,
            "global_error_reservations": global_error_reservations,
            "orphan_decisions": orphan_decisions, "orphan_outcomes": orphan_outcomes,
            "decisions_without_prediction": decisions_without_prediction,
            "duplicate_decision_predictions": duplicate_decision_predictions,
            "invalid_lineage_count": invalid_lineage_count,
            "invalid_lineage_rate": (
                invalid_lineage_count / production_prediction_count
                if production_prediction_count else 0.0
            ),
            "unknown_symbol_count": unknown_symbol_count,
            "unknown_symbol_rate": (
                unknown_symbol_count / production_prediction_count
                if production_prediction_count else 0.0
            ),
            "universe_mismatch_count": universe_mismatch_count,
            "duplicate_predictions": duplicate_predictions,
            "duplicate_prediction_rate": (
                duplicate_predictions / production_prediction_count
                if production_prediction_count else 0.0
            ),
            "orphan_decision_rate": (
                (orphan_decisions + decisions_without_prediction) / len(decisions)
                if decisions else 0.0
            ),
            "missing_outcomes": missing_outcomes,
            "missing_outcome_rate": (
                missing_outcomes / len(trade_prediction_ids)
                if trade_prediction_ids else 0.0
            ),
            "trade_decisions_without_outcome": trade_decisions_without_outcome,
            "executed_positions_missing_outcome": 0,
            "closed_positions_missing_outcome": 0,
            "foreign_key_violations": foreign_key_violations,
            "unresolved_incidents": unresolved_incidents,
            "quarantined_records": quarantined_records,
            "quarantined_corrupt_payloads": corrupt_payloads,
        }

    def count_corrupt_payloads(self) -> int:
        """Count digest mismatches without mutating evidence or quarantine."""
        corrupt: set[tuple[str, str]] = set()
        table_keys = {
            "predictions": "prediction_id", "feature_snapshots": "prediction_id",
            "final_decisions": "decision_id", "outcome_links": "outcome_id",
        }
        for path in self.partition_paths():
            with self._connect(path) as db:
                for table, key in table_keys.items():
                    for record_id, payload, digest in db.execute(
                        f"SELECT {key}, payload, payload_sha256 FROM {table}"
                    ):
                        actual = hashlib.sha256(str(payload).encode("utf-8")).hexdigest()
                        if actual != str(digest):
                            corrupt.add((table, str(record_id)))
        return len(corrupt)

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
                            continue
                        if table == "predictions":
                            try:
                                prediction = json.loads(str(payload))
                            except (TypeError, json.JSONDecodeError):
                                continue
                            if prediction.get("event_type") != "prediction_created":
                                continue
                            invalid = (
                                any(not prediction.get(field) for field in REQUIRED_PREDICTION_LINEAGE_FIELDS)
                                or str(prediction.get("symbol")).upper() == "UNKNOWN"
                            )
                            if invalid:
                                db.execute(
                                    "INSERT OR IGNORE INTO evidence_quarantine VALUES (?, ?, ?, ?)",
                                    (
                                        table,
                                        str(record_id),
                                        "invalid_prediction_lineage",
                                        self._now().isoformat(),
                                    ),
                                )
        return len(corrupt)


_STORE: RuntimeEvidenceStore | None = None


def get_runtime_evidence_store() -> RuntimeEvidenceStore:
    global _STORE
    if _STORE is None:
        _STORE = RuntimeEvidenceStore()
    return _STORE
