"""Runtime ownership and process isolation helpers."""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from btc_scraper.core.paths import (
    RuntimePaths,
    get_runtime_paths,
    runtime_lock_bypass_reason,
    runtime_lock_disabled,
    runtime_owner_metadata,
)


class RuntimeLockError(RuntimeError):
    pass


class RuntimeOwnershipError(RuntimeLockError):
    pass


@dataclass(frozen=True)
class FileFingerprint:
    path: Path
    inode: int
    size: int
    mtime_ns: int
    sha256: str
    owner: dict[str, Any] | None = None

    def changed_from(self, other: "FileFingerprint | None") -> bool:
        return (
            other is None
            or self.inode != other.inode
            or self.size != other.size
            or self.mtime_ns != other.mtime_ns
            or self.sha256 != other.sha256
        )


class RuntimeLock:
    """A per-deployment process lock stored under the runtime state root."""

    def __init__(self, paths: RuntimePaths | None = None):
        self.paths = paths or get_runtime_paths()
        self.lock_path = self.paths.runtime_lock_path
        self.audit_path = self.paths.state_root / "runtime_lock_events.jsonl"
        self._acquired = False

    def acquire(self) -> dict[str, Any]:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        current = self._read_lock()
        if current and _pid_alive(current):
            raise RuntimeLockError(
                "runtime deployment already active: "
                f"environment={current.get('environment')} "
                f"deployment_id={current.get('deployment_id')} "
                f"runtime_id={current.get('runtime_id')} "
                f"process_id={current.get('process_id')}"
            )
        if current:
            self._audit("stale_lock_recovered", {"previous_lock": current})

        payload = {
            **runtime_owner_metadata(),
            "acquired_at": _now(),
            "lock_path": str(self.lock_path),
        }
        _atomic_write_json(self.lock_path, payload)
        self._audit("runtime_lock_acquired", {"lock": payload})
        self._acquired = True
        return payload

    def release(self) -> bool:
        current = self._read_lock()
        if not current:
            self._acquired = False
            return False
        if str(current.get("runtime_id")) != self.paths.runtime_id:
            raise RuntimeLockError(
                f"cannot release lock owned by runtime_id={current.get('runtime_id')}"
            )
        self.lock_path.unlink(missing_ok=True)
        self._audit("runtime_lock_released", {"runtime_id": self.paths.runtime_id})
        self._acquired = False
        return True

    def __enter__(self) -> "RuntimeLock":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._acquired:
            self.release()

    def _read_lock(self) -> dict[str, Any] | None:
        if not self.lock_path.exists():
            return None
        try:
            payload = json.loads(self.lock_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise RuntimeLockError(f"runtime lock is unreadable: {self.lock_path}") from exc
        return payload if isinstance(payload, dict) else None

    def _audit(self, event_type: str, payload: Mapping[str, Any]) -> None:
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        event = {
            "event_type": event_type,
            "written_at": _now(),
            "environment": self.paths.environment,
            "deployment_id": self.paths.deployment_id,
            "runtime_id": self.paths.runtime_id,
            "process_id": self.paths.process_id,
            **dict(payload),
        }
        with self.audit_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True, default=str) + "\n")


def assert_runtime_owned() -> dict[str, Any]:
    """Acquire the configured runtime deployment lock for process startup."""
    validate_runtime_lock_policy()
    return RuntimeLock().acquire()


def validate_runtime_lock_policy(paths: RuntimePaths | None = None) -> dict[str, Any]:
    paths = paths or get_runtime_paths()
    if not runtime_lock_disabled():
        return {"status": "enabled", "environment": paths.environment, "deployment_id": paths.deployment_id}
    if paths.environment == "live":
        raise RuntimeOwnershipError("BTC_DISABLE_RUNTIME_LOCK is forbidden in live environment")
    return {
        "status": "disabled",
        "severity": "CRITICAL",
        "environment": paths.environment,
        "deployment_id": paths.deployment_id,
        "runtime_id": paths.runtime_id,
        "process_id": paths.process_id,
        "reason": runtime_lock_bypass_reason(),
        "evidence_eligible": False,
    }


def audit_runtime_lock_bypass(paths: RuntimePaths | None = None, *, reason: str | None = None) -> dict[str, Any] | None:
    paths = paths or get_runtime_paths()
    status = validate_runtime_lock_policy(paths)
    if status["status"] != "disabled":
        return None
    event = {
        "event_type": "runtime_lock_bypass_enabled",
        "severity": "CRITICAL",
        "written_at": _now(),
        "environment": paths.environment,
        "deployment_id": paths.deployment_id,
        "runtime_id": paths.runtime_id,
        "process_id": paths.process_id,
        "hostname": paths.hostname,
        "reason": reason or runtime_lock_bypass_reason(),
        "evidence_eligible": False,
    }
    audit_path = paths.state_root / "runtime_lock_events.jsonl"
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    with audit_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True, default=str) + "\n")
    return event


def snapshot_runtime_roots(roots: Iterable[Path]) -> dict[Path, FileFingerprint]:
    snapshot: dict[Path, FileFingerprint] = {}
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.is_file():
                stat = path.stat()
                snapshot[path] = FileFingerprint(
                    path=path,
                    inode=stat.st_ino,
                    size=stat.st_size,
                    mtime_ns=stat.st_mtime_ns,
                    sha256=_sha256(path),
                    owner=_read_owner_sidecar(path),
                )
    return snapshot


def describe_runtime_changes(
    before: Mapping[Path, FileFingerprint],
    after: Mapping[Path, FileFingerprint],
    *,
    repo_root: Path,
) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    for path, current in sorted(after.items(), key=lambda item: str(item[0])):
        previous = before.get(path)
        if not current.changed_from(previous):
            continue
        changes.append({
            "path": str(path.relative_to(repo_root)),
            "before_hash": previous.sha256 if previous else None,
            "after_hash": current.sha256,
            "before_size": previous.size if previous else None,
            "after_size": current.size,
            "modified_at": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
            "suspected_writer_runtime_id": (current.owner or {}).get("runtime_id"),
            "suspected_writer_process_id": (current.owner or {}).get("process_id"),
        })
    for path, previous in sorted(before.items(), key=lambda item: str(item[0])):
        if path in after:
            continue
        changes.append({
            "path": str(path.relative_to(repo_root)),
            "before_hash": previous.sha256,
            "after_hash": None,
            "before_size": previous.size,
            "after_size": None,
            "modified_at": None,
            "suspected_writer_runtime_id": (previous.owner or {}).get("runtime_id"),
            "suspected_writer_process_id": (previous.owner or {}).get("process_id"),
        })
    return changes


def write_owner_sidecar(path: str | Path, owner: Mapping[str, Any] | None = None) -> Path:
    target = Path(path)
    sidecar = _owner_sidecar_path(target)
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_json(sidecar, dict(owner or runtime_owner_metadata()))
    return sidecar


def _pid_alive(lock: Mapping[str, Any]) -> bool:
    try:
        pid = int(lock.get("process_id") or -1)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _read_owner_sidecar(path: Path) -> dict[str, Any] | None:
    sidecar = _owner_sidecar_path(path)
    if not sidecar.exists():
        return None
    try:
        payload = json.loads(sidecar.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _owner_sidecar_path(path: Path) -> Path:
    return path.with_name(path.name + ".owner.json")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump(dict(payload), handle, ensure_ascii=False, sort_keys=True, default=str)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp_path, path)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
