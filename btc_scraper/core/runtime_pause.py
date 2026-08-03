"""Durable runtime pause/recovery policy independent from evidence-epoch state.

External availability failures are represented here.  They must never be
translated into an evidence-epoch invalidation by callers.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from btc_scraper.core.operational_resilience import atomic_write_json


RUNTIME_STATES = {
    "STARTING",
    "RUNNING",
    "PAUSED_EXTERNAL",
    "PAUSED_SYSTEM_SLEEP",
    "PAUSED_NETWORK",
    "PAUSED_DEPENDENCY",
    "RECOVERING",
    "STOPPED_MANUAL",
    "FAILED_INTERNAL",
}

PAUSABLE_REASON_CODES = (
    "RUNTIME_PAUSED_NETWORK_UNAVAILABLE",
    "RUNTIME_PAUSED_DNS_UNAVAILABLE",
    "RUNTIME_PAUSED_MONGODB_UNAVAILABLE",
    "RUNTIME_PAUSED_MARKET_PROVIDER_UNAVAILABLE",
    "RUNTIME_PAUSED_EXTERNAL_API_UNAVAILABLE",
    "RUNTIME_PAUSED_SYSTEM_SLEEP_DETECTED",
    "RUNTIME_PAUSED_CLOCK_GAP_DETECTED",
)

TERMINAL_REASON_CODES = (
    "MODEL_ARTIFACT_HASH_MISMATCH",
    "DECISION_CONTRACT_MISMATCH",
    "CANONICAL_EVIDENCE_CONFLICT",
    "DEPLOYMENT_LINEAGE_MISMATCH",
    "EXECUTION_FINAL_DECISION_MISMATCH",
    "DUPLICATE_CONFLICTING_ECONOMIC_EVIDENCE",
    "EPOCH_TERMINAL_RISK_POLICY_BREACH",
    "MANUAL_INVALIDATION_AUTHORIZED",
)


class ExternalDependencyUnavailable(RuntimeError):
    """A recoverable external failure that pauses runtime availability only."""

    def __init__(self, reason_code: str, detail: str = "") -> None:
        if reason_code not in PAUSABLE_REASON_CODES:
            raise ValueError(f"reason is not pausable: {reason_code}")
        self.reason_code = reason_code
        self.detail = detail
        super().__init__(f"{reason_code}:{detail}" if detail else reason_code)


@dataclass(frozen=True)
class RuntimePausePolicy:
    policy_version: str = "runtime-pause-v1"
    resume_policy_version: str = "runtime-resume-v1"
    pausable_reason_codes: tuple[str, ...] = PAUSABLE_REASON_CODES
    terminal_reason_codes: tuple[str, ...] = TERMINAL_REASON_CODES
    dependency_probe_backoff_seconds: tuple[float, ...] = (5.0, 15.0, 30.0, 60.0)
    recovery_success_threshold: int = 3
    recovery_stabilization_seconds: float = 30.0
    maximum_pause_duration_seconds: float | None = None
    lease_behavior_on_pause: str = "REACQUIRE_AFTER_CLOCK_GAP"
    incomplete_cycle_behavior: str = "RECOVER_OR_INTERRUPT_EXTERNAL"
    resume_catch_up_policy: str = "CURRENT_SESSION_ONLY"
    maximum_clock_gap_before_recovery_seconds: float = 90.0
    dependency_health_policy: str = "REQUIRED_DEPENDENCIES_FAIL_CLOSED"

    def validate(self) -> None:
        if not self.policy_version or not self.resume_policy_version:
            raise ValueError("runtime pause policy version is required")
        if not self.pausable_reason_codes:
            raise ValueError("runtime pause policy requires pausable reasons")
        if set(self.pausable_reason_codes) & set(self.terminal_reason_codes):
            raise ValueError("pausable and terminal reasons must be disjoint")
        if self.recovery_success_threshold < 1:
            raise ValueError("recovery success threshold must be positive")
        if self.recovery_stabilization_seconds < 0:
            raise ValueError("recovery stabilization must be non-negative")
        if not self.dependency_probe_backoff_seconds or any(
            value <= 0 for value in self.dependency_probe_backoff_seconds
        ):
            raise ValueError("dependency probe backoff must be positive")
        if self.resume_catch_up_policy not in {
            "SKIP_MISSED_CYCLES",
            "CURRENT_SESSION_ONLY",
            "ALLOW_WITHIN_N_CYCLES",
            "MANUAL_REPLAY_ONLY",
        }:
            raise ValueError("invalid resume catch-up policy")
        if self.maximum_clock_gap_before_recovery_seconds <= 0:
            raise ValueError("maximum clock gap must be positive")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "RuntimePausePolicy":
        if not value:
            result = cls()
        else:
            payload = dict(value)
            for key in (
                "pausable_reason_codes",
                "terminal_reason_codes",
                "dependency_probe_backoff_seconds",
            ):
                if key in payload:
                    payload[key] = tuple(payload[key])
            result = cls(**payload)
        result.validate()
        return result

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def external_reason_for_exception(exc: BaseException) -> str | None:
    """Classify connectivity failures without treating data conflicts as outages."""
    if isinstance(exc, ExternalDependencyUnavailable):
        return exc.reason_code
    name = type(exc).__name__.lower()
    message = str(exc).lower()
    combined = f"{name} {message}"
    if any(token in combined for token in ("duplicate", "conflict", "corrupt", "hash mismatch")):
        return None
    if any(token in combined for token in ("dns", "name resolution", "gaierror")):
        return "RUNTIME_PAUSED_DNS_UNAVAILABLE"
    if any(token in combined for token in (
        "mongo", "serverselectiontimeout", "autoreconnect", "connectionfailure",
    )):
        return "RUNTIME_PAUSED_MONGODB_UNAVAILABLE"
    if any(token in combined for token in (
        "clientconnector", "connectionerror", "connect timeout", "network is unreachable",
        "temporary failure", "connection refused", "tls", "ssl",
    )):
        return "RUNTIME_PAUSED_NETWORK_UNAVAILABLE"
    if any(token in combined for token in ("timeout", "http", "api unavailable")):
        return "RUNTIME_PAUSED_EXTERNAL_API_UNAVAILABLE"
    return None


class RuntimePauseController:
    """Persist runtime availability while leaving the evidence epoch untouched."""

    def __init__(
        self,
        state_root: str | Path,
        *,
        policy: RuntimePausePolicy | None = None,
        wall_clock: Callable[[], datetime] | None = None,
        monotonic_clock: Callable[[], float] | None = None,
    ) -> None:
        self.root = Path(state_root)
        self.state_path = self.root / "runtime_pause_state.json"
        self.events_path = self.root / "runtime_pause_events.jsonl"
        self.policy = policy or RuntimePausePolicy()
        self.policy.validate()
        self._wall_clock = wall_clock or (lambda: datetime.now(timezone.utc))
        self._monotonic = monotonic_clock or time.monotonic
        self._state = self._load_state()

    def _now(self) -> datetime:
        value = self._wall_clock()
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def _load_state(self) -> dict[str, Any]:
        if self.state_path.exists():
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
            if payload.get("policy_version") != self.policy.policy_version:
                raise RuntimeError("runtime pause policy changed without a new activation boundary")
            if payload.get("runtime_state") not in RUNTIME_STATES:
                raise RuntimeError("invalid persisted runtime pause state")
            return payload
        now = self._now().isoformat()
        payload = {
            "runtime_state": "STARTING",
            "epoch_state": "ACTIVE",
            "policy_version": self.policy.policy_version,
            "resume_policy_version": self.policy.resume_policy_version,
            "reason_code": None,
            "reason_detail": None,
            "paused_at": None,
            "healthy_since": None,
            "consecutive_healthy_probes": 0,
            "failed_probes": 0,
            "pause_intervals": [],
            "scheduled_cycle_missed_external_pause": 0,
            "last_wall_heartbeat": now,
            "last_monotonic_heartbeat": self._monotonic(),
            "updated_at": now,
        }
        self._persist(payload, event_type="runtime_starting")
        return payload

    @property
    def runtime_state(self) -> str:
        return str(self._state["runtime_state"])

    @property
    def is_paused(self) -> bool:
        return self.runtime_state.startswith("PAUSED") or self.runtime_state == "RECOVERING"

    def snapshot(self) -> dict[str, Any]:
        return json.loads(json.dumps(self._state))

    def mark_running(self, *, detail: str = "startup_preflight_complete") -> None:
        if self.runtime_state not in {"STARTING", "RECOVERING", "RUNNING"}:
            raise RuntimeError(f"cannot mark running from {self.runtime_state}")
        self._state.update({
            "runtime_state": "RUNNING",
            "reason_code": None,
            "reason_detail": detail,
            "healthy_since": None,
            "consecutive_healthy_probes": 0,
            "failed_probes": 0,
        })
        self._persist(self._state, event_type="runtime_running")

    def fail_internal(self, detail: str) -> None:
        self._state.update({
            "runtime_state": "FAILED_INTERNAL",
            "reason_code": None,
            "reason_detail": detail,
        })
        self._persist(self._state, event_type="runtime_failed_internal")

    def stop_manual(self, detail: str = "operator_stop") -> None:
        self._state.update({
            "runtime_state": "STOPPED_MANUAL",
            "reason_code": None,
            "reason_detail": detail,
        })
        self._persist(self._state, event_type="runtime_stopped_manual")

    def pause(
        self,
        reason_code: str,
        *,
        detail: str = "",
        context: Mapping[str, Any] | None = None,
    ) -> None:
        if reason_code not in self.policy.pausable_reason_codes:
            raise ValueError(f"reason is not pausable by pinned policy: {reason_code}")
        now = self._now().isoformat()
        if not self.is_paused:
            self._state["paused_at"] = now
            self._state.setdefault("pause_intervals", []).append({
                "started_at": now,
                "ended_at": None,
                "reason_code": reason_code,
            })
        self._state.update({
            "runtime_state": self._pause_state(reason_code),
            "epoch_state": "ACTIVE",
            "reason_code": reason_code,
            "reason_detail": detail,
            "healthy_since": None,
            "consecutive_healthy_probes": 0,
            "failed_probes": int(self._state.get("failed_probes") or 0) + 1,
        })
        if context:
            self._state["pause_context"] = dict(context)
        self._persist(
            self._state,
            event_type="runtime_paused_external",
            extra={"epoch_action": "PRESERVED"},
        )

    def observe_recovery_probe(self, healthy: bool, *, detail: str = "") -> bool:
        if not self.is_paused:
            return self.runtime_state == "RUNNING"
        now = self._now()
        if not healthy:
            self._state.update({
                "runtime_state": self._pause_state(str(self._state.get("reason_code") or "")),
                "healthy_since": None,
                "consecutive_healthy_probes": 0,
                "failed_probes": int(self._state.get("failed_probes") or 0) + 1,
                "reason_detail": detail or self._state.get("reason_detail"),
            })
            self._persist(self._state, event_type="runtime_recovery_failed_transient")
            return False
        if self.runtime_state != "RECOVERING":
            self._state["runtime_state"] = "RECOVERING"
            self._state["healthy_since"] = now.isoformat()
            self._state["consecutive_healthy_probes"] = 0
            self._persist(self._state, event_type="runtime_recovery_dependencies_healthy")
        self._state["consecutive_healthy_probes"] = int(
            self._state.get("consecutive_healthy_probes") or 0
        ) + 1
        healthy_since = datetime.fromisoformat(str(self._state["healthy_since"]))
        stable_seconds = (now - healthy_since).total_seconds()
        ready = (
            self._state["consecutive_healthy_probes"] >= self.policy.recovery_success_threshold
            and stable_seconds >= self.policy.recovery_stabilization_seconds
        )
        if not ready:
            self._persist(self._state, event_type="runtime_recovery_stabilization_pending")
            return False
        intervals = self._state.setdefault("pause_intervals", [])
        if intervals and intervals[-1].get("ended_at") is None:
            intervals[-1]["ended_at"] = now.isoformat()
        self._state.update({
            "runtime_state": "RUNNING",
            "reason_code": None,
            "reason_detail": detail or "recovery_completed",
            "paused_at": None,
            "healthy_since": None,
            "consecutive_healthy_probes": 0,
            "failed_probes": 0,
            "pause_context": None,
        })
        self._persist(self._state, event_type="runtime_recovery_completed")
        return True

    def recovery_probe_delay(self) -> float:
        index = max(0, int(self._state.get("failed_probes") or 1) - 1)
        values = self.policy.dependency_probe_backoff_seconds
        return float(values[min(index, len(values) - 1)])

    def heartbeat(self) -> float:
        now = self._now()
        monotonic_now = self._monotonic()
        previous_wall = datetime.fromisoformat(str(self._state["last_wall_heartbeat"]))
        previous_monotonic = float(self._state["last_monotonic_heartbeat"])
        wall_elapsed = (now - previous_wall).total_seconds()
        clock_gap = max(
            0.0,
            wall_elapsed - (monotonic_now - previous_monotonic),
        )
        self._state["last_wall_heartbeat"] = now.isoformat()
        self._state["last_monotonic_heartbeat"] = monotonic_now
        if clock_gap > self.policy.maximum_clock_gap_before_recovery_seconds:
            self.pause(
                "RUNTIME_PAUSED_SYSTEM_SLEEP_DETECTED",
                detail=f"clock_gap_seconds={clock_gap:.3f}",
            )
        elif wall_elapsed >= 30.0:
            self._persist(self._state)
        return clock_gap

    def record_missed_cycles(self, count: int) -> None:
        if count <= 0:
            return
        self._state["scheduled_cycle_missed_external_pause"] = int(
            self._state.get("scheduled_cycle_missed_external_pause") or 0
        ) + int(count)
        self._persist(
            self._state,
            event_type="scheduled_cycle_missed_external_pause",
            extra={"count": int(count)},
        )

    def excluded_seconds_between(self, started_at: datetime, ended_at: datetime) -> float:
        start = started_at.astimezone(timezone.utc)
        end = ended_at.astimezone(timezone.utc)
        total = 0.0
        for interval in self._state.get("pause_intervals") or []:
            interval_start = datetime.fromisoformat(str(interval["started_at"]))
            raw_end = interval.get("ended_at")
            interval_end = datetime.fromisoformat(str(raw_end)) if raw_end else self._now()
            overlap_start = max(start, interval_start)
            overlap_end = min(end, interval_end)
            if overlap_end > overlap_start:
                total += (overlap_end - overlap_start).total_seconds()
        return total

    @staticmethod
    def _pause_state(reason_code: str) -> str:
        if "SYSTEM_SLEEP" in reason_code or "CLOCK_GAP" in reason_code:
            return "PAUSED_SYSTEM_SLEEP"
        if "NETWORK" in reason_code or "DNS" in reason_code:
            return "PAUSED_NETWORK"
        if reason_code:
            return "PAUSED_DEPENDENCY"
        return "PAUSED_EXTERNAL"

    def _persist(
        self,
        payload: Mapping[str, Any],
        *,
        event_type: str | None = None,
        extra: Mapping[str, Any] | None = None,
    ) -> None:
        value = dict(payload)
        value["updated_at"] = self._now().isoformat()
        self.root.mkdir(parents=True, exist_ok=True)
        atomic_write_json(self.state_path, value)
        self._state = value
        if event_type:
            event = {
                "event_type": event_type,
                "written_at": value["updated_at"],
                "runtime_state": value["runtime_state"],
                "epoch_state": "ACTIVE",
                "reason_code": value.get("reason_code"),
                "policy_version": self.policy.policy_version,
                **dict(extra or {}),
            }
            with self.events_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
