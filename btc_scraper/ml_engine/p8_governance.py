"""P8 Economic Evaluation & Governance Core Definitions and Attestation.

Provides centralized attestation policy, exact canonical path resolution,
multi-partition raw SQLite evidence verification, snapshot manifest hashing,
and versioned cost policy definitions.
"""
from __future__ import annotations

from enum import Enum
import hashlib
import json
import os
import sqlite3
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Immutable expected constants for P8 sealed attestation
SEALED_COMMIT_SHA = "4efed1fd43e1f014b61d7d74d3ed574ddb010aab"
SEALED_ARTIFACT_SHA = "8781aeee0b4ed4b84b18332600572bc9deaf5fdab896f945923d948df6c48b26"
EXPECTED_DEPLOYMENT_ID = "paper-canary-win-tsfix-20260901-01"
EXPECTED_PAPER_RUN_ID = "paper-canary-win-tsfix-20260901-01"
EXPECTED_EPOCH_ID = "p8-readiness-r2-20260902-01"
EXPECTED_UNIVERSE_HASH = "c965c9e001020849c1390553023d8259253fd28728c2679f7f52fb4fda66d2e3"

EXPECTED_MODEL_VERSION = "windows-v5-filter-1.0.0"
EXPECTED_FEATURE_SCHEMA_VERSION = "meta-v3.1-43f"
EXPECTED_EVIDENCE_POLICY_VERSION = "evidence-v4"
EXPECTED_RISK_POLICY_VERSION = "risk-fail-closed-v1"
EXPECTED_RUNTIME_SCHEMA_VERSION = "6"
EXPECTED_RELEASE_MANIFEST_SHA256 = "00ed0667799df5157ec7fb2fb940828b1c88fafaad09b0a4e79ec6d20bff643e"

SEALED_WORKTREE_PATH = PROJECT_ROOT / "runtime" / "worktrees" / "timestamp-remediation-20260901-01"

MIN_RATE_COVERAGE_RATIO = 1.0
MIN_COST_COVERAGE_RATIO = 1.0
ABSOLUTE_USD_TOLERANCE = Decimal("0.02")  # 2 cents tolerance for cent-rounded accounting identity


class GovernanceError(RuntimeError):
    """Exception raised when governance constraints are violated or evidence store state is invalid."""


class P8CostPolicy(str, Enum):
    """Cost policy version for economic evaluation."""
    V1_PAPER_ROUNDTRIP_FEE = "V1_PAPER_ROUNDTRIP_FEE"
    V2_EXPLICIT_COMPONENTS = "V2_EXPLICIT_COMPONENTS"


@dataclass
class AttestationResult:
    """Dataclass holding P8 attestation status and details."""
    is_valid: bool
    active_epoch_id: str | None = None
    attestation_errors: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class P8AttestationPolicy:
    """Policy engine for verifying P8 store canonicality, epoch metadata, and artifact integrity."""

    def __init__(self, sealed_root: Path | None = None):
        self.sealed_root = Path(sealed_root) if sealed_root is not None else SEALED_WORKTREE_PATH

    @property
    def canonical_evidence_log(self) -> Path:
        return (self.sealed_root / "runtime" / "paper" / EXPECTED_DEPLOYMENT_ID / "logs" / "runtime_evidence.sqlite").resolve()

    @property
    def canonical_global_index(self) -> Path:
        return (self.sealed_root / "runtime" / "paper" / EXPECTED_DEPLOYMENT_ID / "logs" / "global_evidence_index.sqlite").resolve()

    @property
    def canonical_reservation_db(self) -> Path:
        return (self.sealed_root / "runtime" / "paper" / EXPECTED_DEPLOYMENT_ID / "data" / "execution" / "reservations.db").resolve()

    @property
    def exact_artifact_path(self) -> Path:
        return (self.sealed_root / "logs" / "meta_model.joblib").resolve()

    def validate_store_paths(self, evidence_path: Path, reservation_path: Path | None = None) -> bool:
        """Check exact path equality against sealed worktree canonical locations."""
        res_evidence = Path(evidence_path).resolve()
        if res_evidence != self.canonical_evidence_log:
            return False

        if reservation_path is not None:
            res_reservation = Path(reservation_path).resolve()
            if res_reservation != self.canonical_reservation_db:
                return False

        global_index = res_evidence.parent / "global_evidence_index.sqlite"
        if global_index.resolve() != self.canonical_global_index:
            return False

        return True

    def attest_store(self, evidence_path: Path, reservation_path: Path | None = None) -> AttestationResult:
        """Perform full 13-field metadata attestation and path canonicality check."""
        errors: list[str] = []
        if not self.validate_store_paths(evidence_path, reservation_path):
            errors.append(f"Store path is not canonical sealed store path: {evidence_path}")
            return AttestationResult(is_valid=False, attestation_errors=errors)

        res_evidence = Path(evidence_path).resolve()
        global_index = res_evidence.parent / "global_evidence_index.sqlite"

        if not global_index.exists():
            errors.append(f"Global index database not found at {global_index}")
            return AttestationResult(is_valid=False, attestation_errors=errors)

        # Query global_evidence_index.sqlite for evidence_epochs
        rows = _load_active_epoch_rows(global_index)
        if len(rows) != 1:
            errors.append(f"Expected exactly 1 ACTIVE epoch in {global_index}, found {len(rows)}")
            return AttestationResult(is_valid=False, attestation_errors=errors)

        row = dict(rows[0])
        epoch_id = str(row.get("epoch_id") or "")

        # Mandatory 13-field attestation check
        field_checks = [
            ("epoch_id", EXPECTED_EPOCH_ID),
            ("status", "ACTIVE"),
            ("code_commit_sha", SEALED_COMMIT_SHA),
            ("artifact_sha256", SEALED_ARTIFACT_SHA),
            ("deployment_id", EXPECTED_DEPLOYMENT_ID),
            ("paper_run_id", EXPECTED_PAPER_RUN_ID),
            ("analysis_universe_hash", EXPECTED_UNIVERSE_HASH),
            ("model_version", EXPECTED_MODEL_VERSION),
            ("feature_schema_version", EXPECTED_FEATURE_SCHEMA_VERSION),
            ("evidence_policy_version", EXPECTED_EVIDENCE_POLICY_VERSION),
            ("risk_policy_version", EXPECTED_RISK_POLICY_VERSION),
            ("runtime_schema_version", EXPECTED_RUNTIME_SCHEMA_VERSION),
            ("release_manifest_sha256", EXPECTED_RELEASE_MANIFEST_SHA256),
        ]
        for f_name, expected_val in field_checks:
            actual_val = str(row.get(f_name) or "")
            if not actual_val:
                errors.append(f"Attestation mandatory field '{f_name}' is missing or empty in active epoch metadata")
            elif actual_val != expected_val:
                errors.append(f"Attestation field '{f_name}' mismatch: expected '{expected_val}', got '{actual_val}'")

        # Sealed artifact file MUST exist
        if not self.exact_artifact_path.exists():
            errors.append(f"Sealed artifact file not found at canonical location {self.exact_artifact_path}")
        else:
            artifact_sha = compute_file_sha256(self.exact_artifact_path)
            if artifact_sha != SEALED_ARTIFACT_SHA:
                errors.append(f"Exact artifact hash mismatch on {self.exact_artifact_path}: expected {SEALED_ARTIFACT_SHA}, got {artifact_sha}")

        is_valid = len(errors) == 0
        return AttestationResult(
            is_valid=is_valid,
            active_epoch_id=epoch_id,
            attestation_errors=errors,
            metadata=row,
        )


def compute_file_sha256(file_path: Path) -> str:
    """Compute SHA256 hex digest of exact file."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def _load_active_epoch_rows(global_index_path: Path) -> list[sqlite3.Row]:
    """P8-local read-only helper to load ACTIVE epoch rows from global_evidence_index.sqlite."""
    if not global_index_path.exists():
        raise GovernanceError(f"Global evidence index database not found at {global_index_path}")
    try:
        uri = f"file:{global_index_path.resolve().as_posix()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM evidence_epochs WHERE status='ACTIVE'")
        rows = cursor.fetchall()
        conn.close()
        if len(rows) != 1:
            raise GovernanceError(f"Expected exactly 1 ACTIVE epoch in {global_index_path}, found {len(rows)}")
        return rows
    except Exception as exc:
        if isinstance(exc, GovernanceError):
            raise
        raise GovernanceError(f"Failed read-only query on active epoch in {global_index_path}: {exc}") from exc


def get_cost_policy_metadata(policy: P8CostPolicy = P8CostPolicy.V1_PAPER_ROUNDTRIP_FEE) -> dict[str, Any]:
    """Return explicit cost policy metadata taxonomy."""
    if policy == P8CostPolicy.V1_PAPER_ROUNDTRIP_FEE:
        return {
            "cost_basis": "MODELED_PAPER",
            "fee_coverage_complete": True,
            "economic_verdict_scope": "PAPER_MODELED_COSTS",
            "policy_cost_coverage_ratio": 1.0,
            "component_status": {
                "entry_fee": "MODELED",
                "exit_fee": "MODELED",
                "funding": "NOT_APPLICABLE",
                "slippage": "UNMODELED_FOR_LIVE",
            },
        }
    return {
        "cost_basis": "EXPLICIT_MEASURED",
        "fee_coverage_complete": True,
        "economic_verdict_scope": "EXPLICIT_LINE_ITEM_COSTS",
        "policy_cost_coverage_ratio": 1.0,
        "component_status": {
            "entry_fee": "MEASURED",
            "exit_fee": "MEASURED",
            "funding": "MEASURED",
            "slippage": "MEASURED",
        },
    }


def _is_pid_alive(pid: int) -> bool:
    """Check whether process ID is currently running on the system."""
    if pid <= 0:
        return False
    try:
        if os.name == "nt":
            import ctypes
            kernel32 = ctypes.windll.kernel32
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if handle:
                exit_code = ctypes.c_ulong()
                STILL_ACTIVE = 259
                kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
                kernel32.CloseHandle(handle)
                return exit_code.value == STILL_ACTIVE
            return False
        else:
            os.kill(pid, 0)
            return True
    except Exception:
        return False


def check_runtime_lock_owner(logs_dir: Path) -> None:
    """Verify that no active foreground runner holds a live runtime lock in state/runtime.lock or logs_dir."""
    if not logs_dir.exists():
        return
    deployment_dir = logs_dir.parent
    lock_files = (
        list(logs_dir.glob("*.lock")) +
        list(deployment_dir.glob("*.lock")) +
        list((deployment_dir / "state").glob("*.lock"))
    )
    try:
        from btc_scraper.core.paths import get_runtime_paths
        lock_files.append(get_runtime_paths().runtime_lock_path)
    except Exception:
        pass

    for l_file in set(lock_files):
        if l_file.is_file() and l_file.stat().st_size > 0:
            try:
                content = l_file.read_text(encoding="utf-8").strip()
                if not content:
                    continue

                pid = None
                try:
                    data = json.loads(content)
                    pid = data.get("process_id") or data.get("pid") or data.get("owner_pid")
                except Exception:
                    pass

                if pid is not None:
                    try:
                        pid_int = int(pid)
                        if _is_pid_alive(pid_int):
                            raise GovernanceError(
                                f"LIVE_RUNNER_ACTIVE_CONFLICT: Active runtime lock detected at {l_file} "
                                f"held by live PID {pid_int}."
                            )
                    except ValueError:
                        pass

                if "ACTIVE" in content.upper() or "OWNER" in content.upper():
                    raise GovernanceError(
                        f"LIVE_RUNNER_ACTIVE_CONFLICT: Active runtime lock detected at {l_file}. "
                        "Governed evaluation requires runner to be stopped."
                    )
            except Exception as exc:
                if isinstance(exc, GovernanceError):
                    raise
                pass


def calculate_store_content_hash(logs_dir: Path) -> str:
    """Compute byte-level SHA256 digest across all database and WAL files for snapshot immutability."""
    if not logs_dir.exists():
        return "empty"

    db_files = sorted(
        list(logs_dir.glob("runtime_evidence*.sqlite")) +
        list(logs_dir.glob("global_evidence_index.sqlite")) +
        list(logs_dir.glob("*.sqlite-wal")) +
        list(logs_dir.glob("*.sqlite-shm"))
    )
    hasher = hashlib.sha256()

    for db_file in db_files:
        if not db_file.is_file():
            continue
        hasher.update(db_file.name.encode("utf-8"))
        with open(db_file, "rb") as f:
            while chunk := f.read(65536):
                hasher.update(chunk)

    return hasher.hexdigest()


def calculate_store_manifest_hash(logs_dir: Path) -> str:
    """Calculate deterministic stat manifest hash across partition files (name:size:mtime)."""
    if not logs_dir.exists():
        return "empty"

    partition_files = sorted(
        list(logs_dir.glob("runtime_evidence*.sqlite")) +
        list(logs_dir.glob("global_evidence_index.sqlite")) +
        list(logs_dir.glob("*.sqlite-wal"))
    )
    hasher = hashlib.sha256()

    for p_file in partition_files:
        if not p_file.is_file():
            continue
        stat = p_file.stat()
        entry = f"{p_file.name}:{stat.st_size}:{stat.st_mtime}"
        hasher.update(entry.encode("utf-8"))

    return hasher.hexdigest()


def _load_raw_partition_records(logs_dir: Path) -> list[dict[str, Any]]:
    """Multi-partition raw SQLite loader discovering runtime_evidence*.sqlite partition files (mode=ro).

    Computes canonical payload_sha256 directly from UTF-8 raw text before JSON parsing.
    Uses computed_hash as deduplication key across partitions (raising GovernanceError duplicate_conflict
    if the same ID has different payload content, even if payload_sha256 column is empty or missing).
    """
    if not logs_dir.exists():
        return []

    partition_files = sorted(list(logs_dir.glob("runtime_evidence*.sqlite")))
    raw_records: list[dict[str, Any]] = []
    seen_records: dict[tuple[str, str], str] = {}

    for p_file in partition_files:
        try:
            uri = f"file:{p_file.resolve().as_posix()}?mode=ro"
            conn = sqlite3.connect(uri, uri=True)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = {row[0] for row in cursor.fetchall()}

            for tbl in ("predictions", "final_decisions", "outcomes"):
                if tbl in tables:
                    cursor.execute(f"SELECT * FROM {tbl}")
                    for row in cursor.fetchall():
                        r_dict = dict(row)
                        rec_id = str(r_dict.get("prediction_id") or r_dict.get("decision_id") or r_dict.get("position_id") or r_dict.get("id") or "")
                        stored_hash = str(r_dict.get("payload_sha256") or "")
                        payload_text = str(r_dict.get("payload") or "")

                        # Canonical hash computed directly from raw text
                        computed_hash = hashlib.sha256(payload_text.encode("utf-8")).hexdigest() if payload_text else ""

                        # Validate stored hash if present and looks like a valid 64-char sha256
                        if stored_hash and len(stored_hash) == 64 and computed_hash:
                            if stored_hash != computed_hash:
                                conn.close()
                                raise GovernanceError(
                                    f"payload_corruption: Raw text SHA256 mismatch in {p_file.name} for record {rec_id}. "
                                    f"Stored {stored_hash}, computed {computed_hash}"
                                )

                        key = (tbl, rec_id)
                        effective_fingerprint = computed_hash or stored_hash

                        if rec_id and key in seen_records:
                            existing_fingerprint = seen_records[key]
                            if effective_fingerprint and existing_fingerprint != effective_fingerprint:
                                conn.close()
                                raise GovernanceError(
                                    f"duplicate_conflict: Record ID {rec_id} in {tbl} has conflicting payload content "
                                    f"across partitions ({existing_fingerprint} vs {effective_fingerprint})"
                                )
                            # Same ID + Same content fingerprint -> deduplicate replay
                            continue

                        if rec_id and effective_fingerprint:
                            seen_records[key] = effective_fingerprint

                        r_dict["_source_table"] = tbl
                        r_dict["_source_partition"] = p_file.name
                        raw_records.append(r_dict)

            conn.close()
        except Exception as exc:
            if isinstance(exc, GovernanceError):
                raise
            raise GovernanceError(f"Failed raw read-only loading on partition {p_file}: {exc}") from exc

    return raw_records

