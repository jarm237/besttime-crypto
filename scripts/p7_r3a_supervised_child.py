#!/usr/bin/env python3
"""External child supervision contract for P7-R3A.

This module is intentionally outside the pinned runtime release.  It observes a
single child process, captures stdout/stderr to files, records lifecycle
timestamps, classifies exit status, and never retries or restarts the child.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


SUPERVISED_CHILD_CONTRACT_VERSION = "p7-supervised-child/v1"
G8_LIVENESS_CONTRACT_VERSION = "p7-g8-identity-and-sustained-liveness/v1"


class SupervisionContractError(RuntimeError):
    """Fail-closed supervision validation error raised before child creation."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def classify_returncode(returncode: int | None) -> dict[str, Any]:
    if returncode is None:
        return {
            "classification": "STILL_RUNNING",
            "exit_code": None,
            "signal_number": None,
            "signal_name": None,
        }
    if returncode == 0:
        return {
            "classification": "NORMAL_EXIT",
            "exit_code": 0,
            "signal_number": None,
            "signal_name": None,
        }
    if returncode > 0:
        return {
            "classification": "NONZERO_EXIT",
            "exit_code": returncode,
            "signal_number": None,
            "signal_name": None,
        }
    signal_number = abs(returncode)
    try:
        signal_name = signal.Signals(signal_number).name
    except ValueError:
        signal_name = "UNKNOWN_SIGNAL"
    return {
        "classification": "SIGNAL_EXIT",
        "exit_code": None,
        "signal_number": signal_number,
        "signal_name": signal_name,
    }


@dataclass(frozen=True)
class SupervisedChildRequest:
    argv: tuple[str, ...]
    cwd: Path
    env: Mapping[str, str]
    stdout_path: Path
    stderr_path: Path
    lifecycle_path: Path
    authorization_sha256: str | None = None
    launcher_sha256: str | None = None
    runtime_release_commit: str | None = None
    runtime_release_tree: str | None = None
    spawn_budget: int = 1
    restart_budget: int = 0
    automatic_retry: bool = False
    start_new_session: bool = True
    close_fds: bool = True

    def validate(self) -> None:
        if not self.argv:
            raise SupervisionContractError("argv_empty")
        if self.spawn_budget != 1:
            raise SupervisionContractError("spawn_budget_must_equal_one")
        if self.restart_budget != 0:
            raise SupervisionContractError("restart_budget_must_equal_zero")
        if self.automatic_retry:
            raise SupervisionContractError("automatic_retry_not_allowed")
        if self.stdout_path == self.stderr_path:
            raise SupervisionContractError("stdout_stderr_paths_must_differ")
        if self.lifecycle_path in {self.stdout_path, self.stderr_path}:
            raise SupervisionContractError("lifecycle_path_must_be_distinct")
        if not self.cwd.is_dir():
            raise SupervisionContractError("cwd_missing")
        for path in (self.stdout_path, self.stderr_path, self.lifecycle_path):
            path.parent.mkdir(parents=True, exist_ok=True)

    def to_contract_dict(self) -> dict[str, Any]:
        return {
            "contract": SUPERVISED_CHILD_CONTRACT_VERSION,
            "authorization_sha256": self.authorization_sha256,
            "launcher_sha256": self.launcher_sha256,
            "runtime_release_commit": self.runtime_release_commit,
            "runtime_release_tree": self.runtime_release_tree,
            "argv": list(self.argv),
            "cwd": str(self.cwd),
            "env": dict(self.env),
            "stdout_path": str(self.stdout_path),
            "stderr_path": str(self.stderr_path),
            "lifecycle_path": str(self.lifecycle_path),
            "spawn_budget": self.spawn_budget,
            "restart_budget": self.restart_budget,
            "automatic_retry": self.automatic_retry,
            "start_new_session": self.start_new_session,
            "close_fds": self.close_fds,
        }


def infer_startup_stages(
    *,
    child_pid: int | None,
    running_observed: bool,
    process_result: Mapping[str, Any],
    runtime_lock_acquired_at: str | None = None,
    runtime_lock_released_at: str | None = None,
    active_epoch_observed: bool = False,
    runtime_marked_running: bool = False,
    async_main_evidence: bool = False,
    scheduler_started_evidence: bool = False,
    first_runtime_heartbeat: bool = False,
    first_cycle_evidence: bool = False,
) -> list[dict[str, Any]]:
    rows = [
        ("S0", "CHILD_SPAWNED", child_pid is not None, "DIRECT", "subprocess_pid"),
        ("S1", "PROCESS_VISIBLE", running_observed, "DIRECT", "poll_observation"),
        ("S2", "RUNTIME_LOCK_ACQUIRED", bool(runtime_lock_acquired_at), "DIRECT", "runtime_lock_log"),
        ("S3", "ACTIVE_EPOCH_OBSERVED", active_epoch_observed, "DERIVED", "runtime_evidence_store"),
        ("S4", "RUNTIME_MARKED_RUNNING", runtime_marked_running, "DIRECT", "runtime_pause_state"),
        ("S5", "ASYNC_MAIN_EVIDENCE", async_main_evidence, "DIRECT", "runtime_log_or_marker"),
        ("S6", "SCHEDULER_STARTED_EVIDENCE", scheduler_started_evidence, "DIRECT", "scheduler_marker"),
        ("S7", "FIRST_RUNTIME_HEARTBEAT", first_runtime_heartbeat, "DIRECT", "heartbeat"),
        ("S8", "FIRST_CYCLE_EVIDENCE", first_cycle_evidence, "DIRECT", "cycle_evidence"),
    ]
    stages: list[dict[str, Any]] = []
    for code, name, present, evidence_type, source in rows:
        stages.append(
            {
                "code": code,
                "stage": name,
                "status": "CONFIRMED" if present else "UNOBSERVED",
                "evidence_type": evidence_type if present else "UNOBSERVED",
                "source": source if present else None,
            }
        )
    if runtime_lock_released_at:
        stages.append(
            {
                "code": "S2R",
                "stage": "RUNTIME_LOCK_RELEASED",
                "status": "CONFIRMED",
                "evidence_type": "DIRECT",
                "source": "runtime_lock_log",
            }
        )
    if process_result.get("classification") in {"NORMAL_EXIT", "NONZERO_EXIT", "SIGNAL_EXIT"}:
        stages.append(
            {
                "code": "SX",
                "stage": "CHILD_EXITED",
                "status": "CONFIRMED",
                "evidence_type": "DIRECT",
                "source": "subprocess_returncode",
            }
        )
    return stages


def last_observed_stage(stages: Sequence[Mapping[str, Any]]) -> str | None:
    confirmed = [str(stage["stage"]) for stage in stages if stage.get("status") == "CONFIRMED"]
    return confirmed[-1] if confirmed else None


def supervise_child(
    request: SupervisedChildRequest,
    *,
    observation_timeout_seconds: float = 0.5,
    poll_interval_seconds: float = 0.01,
    popen: type[subprocess.Popen[Any]] = subprocess.Popen,
) -> dict[str, Any]:
    request.validate()
    timestamps: dict[str, Any] = {"supervisor_started_at": utc_now()}
    running_observed_at: list[str] = []
    spawn_attempt_count = 0
    restart_attempt_count = 0
    process_result: dict[str, Any]
    child_pid: int | None = None

    stdout_sha256: str | None = None
    stderr_sha256: str | None = None
    final_child_state = "NOT_STARTED"
    status = "OBSERVABILITY_FAILURE"

    try:
        with request.stdout_path.open("wb") as stdout_handle, request.stderr_path.open("wb") as stderr_handle:
            timestamps["spawn_called_at"] = utc_now()
            spawn_attempt_count = 1
            child = popen(
                list(request.argv),
                cwd=str(request.cwd),
                env=dict(request.env),
                stdin=subprocess.DEVNULL,
                stdout=stdout_handle,
                stderr=stderr_handle,
                start_new_session=request.start_new_session,
                close_fds=request.close_fds,
            )
            child_pid = child.pid
            timestamps["child_pid_observed_at"] = utc_now()
            final_child_state = "SPAWNED"
            deadline = time.monotonic() + observation_timeout_seconds
            while True:
                returncode = child.poll()
                if returncode is None:
                    observed_at = utc_now()
                    if not running_observed_at:
                        timestamps["child_running_observed_at"] = observed_at
                    running_observed_at.append(observed_at)
                    final_child_state = "RUNNING_OBSERVED"
                    if time.monotonic() >= deadline:
                        process_result = classify_returncode(None)
                        status = "STILL_RUNNING"
                        final_child_state = "STILL_RUNNING"
                        break
                    time.sleep(poll_interval_seconds)
                    continue
                timestamps["child_exit_observed_at"] = utc_now()
                process_result = classify_returncode(returncode)
                final_child_state = process_result["classification"]
                status = "EXITED"
                break
            stdout_handle.flush()
            stderr_handle.flush()
            os.fsync(stdout_handle.fileno())
            os.fsync(stderr_handle.fileno())
    except Exception as exc:
        process_result = {
            "classification": "OBSERVABILITY_FAILURE",
            "exit_code": None,
            "signal_number": None,
            "signal_name": None,
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
    finally:
        timestamps["supervisor_finished_at"] = utc_now()

    if request.stdout_path.exists():
        stdout_sha256 = sha256_file(request.stdout_path)
    if request.stderr_path.exists():
        stderr_sha256 = sha256_file(request.stderr_path)

    stages = infer_startup_stages(
        child_pid=child_pid,
        running_observed=bool(running_observed_at),
        process_result=process_result,
    )
    report = {
        "contract": SUPERVISED_CHILD_CONTRACT_VERSION,
        "status": status,
        "request": request.to_contract_dict(),
        "child_pid": child_pid,
        "timestamps": timestamps,
        "running_observed_at": running_observed_at,
        "process_result": process_result,
        "stdout_sha256": stdout_sha256,
        "stderr_sha256": stderr_sha256,
        "spawn_attempt_count": spawn_attempt_count,
        "restart_attempt_count": restart_attempt_count,
        "automatic_retry": False,
        "final_child_state": final_child_state,
        "startup_stages": stages,
        "last_observed_stage": last_observed_stage(stages),
    }
    request.lifecycle_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def evaluate_g8(
    *,
    identity_established: bool,
    immutable_inputs_unchanged: bool,
    execution_mode: str,
    semantic_progress_observed: bool,
    child_exited_before_liveness: bool,
) -> dict[str, Any]:
    g8a_pass = bool(identity_established and immutable_inputs_unchanged and execution_mode.upper() == "PAPER")
    g8b_pass = bool(g8a_pass and semantic_progress_observed and not child_exited_before_liveness)
    if g8a_pass and g8b_pass:
        overall = "ACTIVE"
    elif g8a_pass and child_exited_before_liveness:
        overall = "ACTIVATION_NOT_SUSTAINED"
    elif g8a_pass:
        overall = "IDENTITY_ESTABLISHED_LIVENESS_PENDING"
    else:
        overall = "IDENTITY_NOT_ESTABLISHED"
    return {
        "contract": G8_LIVENESS_CONTRACT_VERSION,
        "g8_a": "PASS" if g8a_pass else "FAIL",
        "g8_b": "PASS" if g8b_pass else "FAIL",
        "identity_establishment_separated": True,
        "sustained_liveness_required": True,
        "runtime_activation": overall,
        "paper_canary": "ACTIVE" if overall == "ACTIVE" else "NOT_ACTIVE",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--argv-json", required=True, help="JSON array command to supervise")
    parser.add_argument("--cwd", type=Path, required=True)
    parser.add_argument("--env-json", required=True, help="JSON object environment for child")
    parser.add_argument("--stdout-path", type=Path, required=True)
    parser.add_argument("--stderr-path", type=Path, required=True)
    parser.add_argument("--lifecycle-path", type=Path, required=True)
    parser.add_argument("--observation-timeout-seconds", type=float, default=0.5)
    args = parser.parse_args()

    argv = tuple(str(item) for item in json.loads(args.argv_json))
    env = {str(k): str(v) for k, v in json.loads(args.env_json).items()}
    request = SupervisedChildRequest(
        argv=argv,
        cwd=args.cwd.resolve(),
        env=env,
        stdout_path=args.stdout_path.resolve(),
        stderr_path=args.stderr_path.resolve(),
        lifecycle_path=args.lifecycle_path.resolve(),
    )
    result = supervise_child(request, observation_timeout_seconds=args.observation_timeout_seconds)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] in {"EXITED", "STILL_RUNNING"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
