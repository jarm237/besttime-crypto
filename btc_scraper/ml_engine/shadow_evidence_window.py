"""Shadow evidence window state for runtime linkage rollout gates."""
from __future__ import annotations

import json
import os
import math
import uuid
import hashlib
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping


RESET_PRODUCER_COVERAGE_BELOW_GATE = "producer_coverage_below_gate_a"
RESET_DUPLICATE_OUTCOME = "duplicate_outcome"
RESET_MIXED_ARTIFACT_SCHEMA = "mixed_artifact_schema"
RESET_CRITICAL_ORPHAN = "critical_orphan_unresolved"
RESET_LINKER_SCHEMA_CHANGED = "linker_logic_or_schema_changed"
RESET_INCOMPATIBLE_BACKFILL = "incompatible_calibration_backfill"
RESET_OUTCOME_COVERAGE_BELOW_GATE = "outcome_coverage_below_gate_a"
RESET_LIFECYCLE_E2E_NOT_PASSED = "lifecycle_e2e_not_passed"
RESET_RECOVERY_TESTS_NOT_PASSED = "recovery_tests_not_passed"
RESET_GATE_SNAPSHOT_STALE = "gate_snapshot_stale"

HARD_RESET_REASONS = {
    RESET_DUPLICATE_OUTCOME,
    RESET_MIXED_ARTIFACT_SCHEMA,
    RESET_CRITICAL_ORPHAN,
    RESET_LINKER_SCHEMA_CHANGED,
    RESET_INCOMPATIBLE_BACKFILL,
}


@dataclass(frozen=True)
class GateSnapshot:
    producer_coverage: Mapping[str, float]
    closed_outcome_coverage: float
    duplicate_outcomes: int
    mixed_artifact_schema_samples: int
    unresolved_critical_orphans: int
    lifecycle_e2e_passed: bool
    recovery_tests_passed: bool
    evaluated_at: datetime
    closed_trade_prediction_to_outcome_rate: float | None = None

    def gate_a_payload(self) -> dict[str, Any]:
        return {
            "required_lifecycle_id_coverage": self.min_producer_coverage,
            "closed_position_outcome_coverage": self.closed_outcome_coverage,
        }

    def linkage_payload(self) -> dict[str, Any]:
        return {
            "closed_trade_prediction_to_outcome_rate": self.closed_trade_prediction_to_outcome_rate,
            "duplicate_outcome_count": self.duplicate_outcomes,
            "mixed_artifact_schema_count": self.mixed_artifact_schema_samples,
            "critical_orphans": [{} for _ in range(self.unresolved_critical_orphans)],
        }

    def metrics_snapshot(self) -> dict[str, Any]:
        return {
            "closed_trade_prediction_to_outcome_rate": self.closed_trade_prediction_to_outcome_rate,
            "producer_coverage": dict(self.producer_coverage),
            "required_lifecycle_id_coverage": self.min_producer_coverage,
            "closed_position_outcome_coverage": self.closed_outcome_coverage,
            "duplicate_outcome_count": self.duplicate_outcomes,
            "mixed_artifact_schema_count": self.mixed_artifact_schema_samples,
            "critical_orphan_count": self.unresolved_critical_orphans,
            "lifecycle_e2e_passed": self.lifecycle_e2e_passed,
            "recovery_tests_passed": self.recovery_tests_passed,
            "evaluated_at": self.evaluated_at.isoformat(),
        }

    @property
    def min_producer_coverage(self) -> float:
        if not self.producer_coverage:
            return 0.0
        return min(float(value) for value in self.producer_coverage.values())

    def start_block_reason(self, *, now: datetime, max_age: timedelta = timedelta(minutes=15)) -> str | None:
        if self.duplicate_outcomes > 0:
            return RESET_DUPLICATE_OUTCOME
        if self.mixed_artifact_schema_samples > 0:
            return RESET_MIXED_ARTIFACT_SCHEMA
        if self.unresolved_critical_orphans > 0:
            return RESET_CRITICAL_ORPHAN
        if not self.lifecycle_e2e_passed:
            return RESET_LIFECYCLE_E2E_NOT_PASSED
        if not self.recovery_tests_passed:
            return RESET_RECOVERY_TESTS_NOT_PASSED
        if self.min_producer_coverage < 0.99:
            return RESET_PRODUCER_COVERAGE_BELOW_GATE
        if self.closed_outcome_coverage < 0.98:
            return RESET_OUTCOME_COVERAGE_BELOW_GATE
        if self.evaluated_at > now or now - self.evaluated_at > max_age:
            return RESET_GATE_SNAPSHOT_STALE
        return None

    def snapshot_hash(self) -> str:
        payload = json.dumps(self.metrics_snapshot(), sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ShadowWindowStartResult:
    started: bool
    reason: str | None
    window: ShadowEvidenceWindow

    def to_dict(self) -> dict[str, Any]:
        return {"started": self.started, "reason": self.reason, "window": self.window.to_dict()}


@dataclass(frozen=True)
class ShadowEvidenceWindow:
    shadow_window_started_at: str | None
    shadow_window_valid: bool
    shadow_window_reset_reason: str | None = None
    last_evaluated_at: str | None = None
    consecutive_valid_days: float = 0.0
    linker_schema_version: str | None = None
    calibration_schema_version: str | None = None
    producer_contract_version: str | None = None
    start_gate_snapshot_hash: str | None = None
    start_gate_evaluated_at: str | None = None
    start_gate_metrics: Mapping[str, Any] | None = None
    required_days: int = 7

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def elapsed_days(self, *, now: datetime | None = None) -> float:
        if not self.shadow_window_started_at or not self.shadow_window_valid:
            return 0.0
        start = _parse_dt(self.shadow_window_started_at)
        if start is None:
            return 0.0
        current = now or datetime.now(timezone.utc)
        return max(0.0, (current - start).total_seconds() / 86400.0)

    def complete(self, *, now: datetime | None = None) -> bool:
        return self.elapsed_days(now=now) >= self.required_days

    @property
    def hard_reset(self) -> bool:
        return self.shadow_window_reset_reason in HARD_RESET_REASONS


def evaluate_shadow_evidence_window(
    *,
    current_window: ShadowEvidenceWindow | None,
    gate_a: Mapping[str, Any],
    linkage: Mapping[str, Any],
    linker_schema_changed: bool = False,
    incompatible_backfill: bool = False,
    schema_versions: Mapping[str, str] | None = None,
    now: datetime | None = None,
) -> ShadowEvidenceWindow:
    current = now or datetime.now(timezone.utc)
    versions = dict(schema_versions or {})
    if _schema_versions_changed(current_window, versions):
        linker_schema_changed = True
    reset_reason = _reset_reason(gate_a, linkage, linker_schema_changed, incompatible_backfill)
    if reset_reason:
        return ShadowEvidenceWindow(
            None,
            False,
            reset_reason,
            last_evaluated_at=current.isoformat(),
            linker_schema_version=versions.get("linker_schema_version"),
            calibration_schema_version=versions.get("calibration_schema_version"),
            producer_contract_version=versions.get("producer_contract_version"),
        )

    if current_window and current_window.shadow_window_valid and current_window.shadow_window_started_at:
        _validate_monotonic(current_window, current)
        elapsed = current_window.elapsed_days(now=current)
        return ShadowEvidenceWindow(
            current_window.shadow_window_started_at,
            True,
            None,
            last_evaluated_at=current.isoformat(),
            consecutive_valid_days=math.floor(elapsed),
            linker_schema_version=versions.get("linker_schema_version") or current_window.linker_schema_version,
            calibration_schema_version=versions.get("calibration_schema_version") or current_window.calibration_schema_version,
            producer_contract_version=versions.get("producer_contract_version") or current_window.producer_contract_version,
            required_days=current_window.required_days,
        )

    return ShadowEvidenceWindow(
        current.isoformat(),
        True,
        None,
        last_evaluated_at=current.isoformat(),
        consecutive_valid_days=0.0,
        linker_schema_version=versions.get("linker_schema_version"),
        calibration_schema_version=versions.get("calibration_schema_version"),
        producer_contract_version=versions.get("producer_contract_version"),
    )


class ShadowEvidenceWindowStore:
    """Persist shadow window state and append-only reset history."""

    def __init__(self, state_path: str | Path, reset_history_path: str | Path | None = None):
        self.state_path = Path(state_path)
        self.reset_history_path = Path(reset_history_path) if reset_history_path else self.state_path.with_suffix(".resets.jsonl")
        self.reset_lock_path = self.reset_history_path.with_suffix(self.reset_history_path.suffix + ".lock")

    def load(self) -> ShadowEvidenceWindow | None:
        if not self.state_path.exists():
            return None
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
            return ShadowEvidenceWindow(**payload)
        except Exception:
            return None

    def start(
        self,
        gate_snapshot: GateSnapshot,
        *,
        schema_versions: Mapping[str, str] | None = None,
        now: datetime | None = None,
    ) -> ShadowWindowStartResult:
        current = self.load()
        current_time = now or datetime.now(timezone.utc)
        block_reason = gate_snapshot.start_block_reason(now=current_time)
        if block_reason:
            window = ShadowEvidenceWindow(
                None,
                False,
                block_reason,
                last_evaluated_at=current_time.isoformat(),
            )
            self.save(window, previous_window=current, metrics_snapshot=gate_snapshot.metrics_snapshot(), schema_versions=schema_versions or {})
            return ShadowWindowStartResult(False, window.shadow_window_reset_reason, window)

        window = evaluate_shadow_evidence_window(
            current_window=current,
            gate_a=gate_snapshot.gate_a_payload(),
            linkage=gate_snapshot.linkage_payload(),
            schema_versions=schema_versions,
            now=current_time,
        )
        if window.shadow_window_valid:
            window = ShadowEvidenceWindow(
                window.shadow_window_started_at,
                window.shadow_window_valid,
                window.shadow_window_reset_reason,
                last_evaluated_at=window.last_evaluated_at,
                consecutive_valid_days=window.consecutive_valid_days,
                linker_schema_version=window.linker_schema_version,
                calibration_schema_version=window.calibration_schema_version,
                producer_contract_version=window.producer_contract_version,
                start_gate_snapshot_hash=current.start_gate_snapshot_hash if current and current.start_gate_snapshot_hash else gate_snapshot.snapshot_hash(),
                start_gate_evaluated_at=current.start_gate_evaluated_at if current and current.start_gate_evaluated_at else gate_snapshot.evaluated_at.isoformat(),
                start_gate_metrics=current.start_gate_metrics if current and current.start_gate_metrics else gate_snapshot.metrics_snapshot(),
                required_days=window.required_days,
            )
        self.save(window, previous_window=current, metrics_snapshot=gate_snapshot.metrics_snapshot(), schema_versions=schema_versions or {})
        return ShadowWindowStartResult(window.shadow_window_valid, window.shadow_window_reset_reason, window)

    def save(
        self,
        window: ShadowEvidenceWindow,
        *,
        previous_window: ShadowEvidenceWindow | None = None,
        metrics_snapshot: Mapping[str, Any] | None = None,
        schema_versions: Mapping[str, str] | None = None,
    ) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        _validate_window(window)
        if window.shadow_window_reset_reason:
            self._append_reset(window, previous_window, metrics_snapshot or {}, schema_versions or {})
        _atomic_write_json(self.state_path, window.to_dict())

    def _append_reset(
        self,
        window: ShadowEvidenceWindow,
        previous_window: ShadowEvidenceWindow | None,
        metrics_snapshot: Mapping[str, Any],
        schema_versions: Mapping[str, str],
    ) -> None:
        self.reset_history_path.parent.mkdir(parents=True, exist_ok=True)
        reset_at = window.last_evaluated_at or datetime.now(timezone.utc).isoformat()
        previous_started_at = previous_window.shadow_window_started_at if previous_window else None
        previous_valid_days = math.floor(previous_window.elapsed_days(now=_parse_dt(reset_at) or datetime.now(timezone.utc))) if previous_window else 0
        _validate_reset_event_times(reset_at, previous_started_at)
        event = {
            "reset_event_id": _reset_event_id(reset_at, previous_started_at, window.shadow_window_reset_reason, schema_versions),
            "reset_at": reset_at,
            "previous_started_at": previous_started_at,
            "previous_valid_days": previous_valid_days,
            "reason": window.shadow_window_reset_reason,
            "hard_reset": window.hard_reset,
            "linkage_rate": metrics_snapshot.get("closed_trade_prediction_to_outcome_rate") or metrics_snapshot.get("prediction_to_outcome_link_rate"),
            "producer_coverage": metrics_snapshot.get("producer_coverage") or metrics_snapshot.get("producer_coverage_by_producer") or {},
            "outcome_coverage": metrics_snapshot.get("closed_position_outcome_coverage"),
            "duplicate_outcomes": metrics_snapshot.get("duplicate_outcome_count", 0),
            "critical_orphans": metrics_snapshot.get("critical_orphan_count", len(metrics_snapshot.get("critical_orphans") or [])),
            "linker_schema_version": schema_versions.get("linker_schema_version"),
            "calibration_schema_version": schema_versions.get("calibration_schema_version"),
            "producer_contract_version": schema_versions.get("producer_contract_version"),
            "metrics_snapshot": dict(metrics_snapshot),
            "schema_versions": dict(schema_versions),
        }
        with self.reset_lock_path.open("a+", encoding="utf-8") as lock_handle:
            _lock_file(lock_handle)
            try:
                if event["reset_event_id"] in _existing_reset_event_ids(self.reset_history_path):
                    return
                with self.reset_history_path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
                    handle.flush()
                    os.fsync(handle.fileno())
            finally:
                _unlock_file(lock_handle)


def _reset_reason(
    gate_a: Mapping[str, Any],
    linkage: Mapping[str, Any],
    linker_schema_changed: bool,
    incompatible_backfill: bool,
) -> str | None:
    producer_coverage = float(gate_a.get("required_lifecycle_id_coverage") or gate_a.get("producer_coverage") or 0.0)
    closed_outcome_coverage = float(gate_a.get("closed_position_outcome_coverage") or 0.0)
    if producer_coverage < 0.99 or closed_outcome_coverage < 0.98:
        return RESET_PRODUCER_COVERAGE_BELOW_GATE
    if int(linkage.get("duplicate_outcome_count") or 0) > 0:
        return RESET_DUPLICATE_OUTCOME
    if int(linkage.get("mixed_artifact_schema_count") or 0) > 0:
        return RESET_MIXED_ARTIFACT_SCHEMA
    if len(linkage.get("critical_orphans") or []) > 0:
        return RESET_CRITICAL_ORPHAN
    if linker_schema_changed:
        return RESET_LINKER_SCHEMA_CHANGED
    if incompatible_backfill:
        return RESET_INCOMPATIBLE_BACKFILL
    return None


def _parse_dt(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except ValueError:
        return None


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    temp = path.with_name(f".{path.name}.tmp")
    with temp.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)
    try:
        dir_fd = os.open(str(path.parent), os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except Exception:
        return


def _validate_window(window: ShadowEvidenceWindow) -> None:
    if window.consecutive_valid_days < 0:
        raise ValueError("consecutive_valid_days must be non-negative")
    start = _parse_dt(window.shadow_window_started_at or "")
    evaluated = _parse_dt(window.last_evaluated_at or "")
    if start and evaluated and evaluated < start:
        raise ValueError("last_evaluated_at must be >= shadow_window_started_at")


def _validate_monotonic(window: ShadowEvidenceWindow, current: datetime) -> None:
    previous = _parse_dt(window.last_evaluated_at or "")
    if previous and current < previous:
        raise ValueError("evaluation timestamp moved backwards")


def _validate_reset_event_times(reset_at: str, previous_started_at: str | None) -> None:
    reset_time = _parse_dt(reset_at)
    previous_start = _parse_dt(previous_started_at or "")
    if reset_time and previous_start and reset_time < previous_start:
        raise ValueError("reset_at must be >= previous_started_at")


def _schema_versions_changed(window: ShadowEvidenceWindow | None, versions: Mapping[str, str]) -> bool:
    if not window or not window.shadow_window_valid:
        return False
    comparisons = (
        ("linker_schema_version", window.linker_schema_version),
        ("calibration_schema_version", window.calibration_schema_version),
        ("producer_contract_version", window.producer_contract_version),
    )
    for key, previous in comparisons:
        current = versions.get(key)
        if previous and current and previous != current:
            return True
    return False


def _reset_event_id(reset_at: str, previous_started_at: str | None, reason: str | None, schema_versions: Mapping[str, str]) -> str:
    payload = json.dumps(
        {
            "reset_at": reset_at,
            "previous_started_at": previous_started_at,
            "reason": reason,
            "schema_versions": dict(sorted(schema_versions.items())),
        },
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return str(uuid.uuid5(uuid.NAMESPACE_URL, payload))


def _existing_reset_event_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    event_ids: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        event_id = payload.get("reset_event_id")
        if event_id:
            event_ids.add(str(event_id))
    return event_ids


def _lock_file(handle: Any) -> None:
    try:
        import fcntl
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
    except Exception:
        return


def _unlock_file(handle: Any) -> None:
    try:
        import fcntl
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except Exception:
        return
