"""Append-only local model registry with atomic promotion and rollback."""
from __future__ import annotations

import json
import logging
import os
import sys
import fcntl
import hashlib
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .artifact_resolver import ROOT, sha256_file
from btc_scraper.core.paths import get_runtime_paths

VALID_STATUSES = {"candidate", "shadow", "production", "archive", "rejected", "disabled"}


class RegistryConflictError(RuntimeError):
    pass


def default_registry_path() -> Path:
    raw = os.getenv("BTC_MODEL_REGISTRY_PATH")
    if raw:
        path = Path(raw).expanduser()
        return path if path.is_absolute() else ROOT / path
    return ROOT / "logs" / "model_registry.json"


class ModelRegistry:
    def __init__(self, path: Path | str | None = None, promotion_guard_path: Path | str | None = None,
                 approved_root: Path | str | None = None) -> None:
        self.approved_root = Path(approved_root).resolve() if approved_root is not None else ROOT
        self.path = Path(path) if path is not None else default_registry_path()
        self.lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        self.promotion_guard_path = Path(promotion_guard_path) if promotion_guard_path is not None else self.approved_root / "config" / "ml_engine_readiness.json"
        self._thread_lock = threading.RLock()

    @contextmanager
    def _locked(self, *, exclusive: bool):
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self._thread_lock:
            with self.lock_path.open("a+") as lock_file:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
                try:
                    yield
                finally:
                    try:
                        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
                    except Exception as err:
                        logging.debug("flock unlock ignored: %s", err)

    def _read(self) -> dict[str, list[dict[str, Any]]]:
        if not self.path.exists():
            return {"records": []}
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) and isinstance(raw.get("records"), list) else {"records": []}

    def revision(self) -> str:
        """Content-addressed registry revision used by runtime lineage events."""
        with self._locked(exclusive=False):
            data = self._read()
        canonical = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _write(self, data: dict[str, list[dict[str, Any]]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        unique_suffix = f".{os.getpid()}_{threading.get_ident()}_{uuid.uuid4().hex}.tmp"
        tmp = self.path.with_suffix(self.path.suffix + unique_suffix)
        try:
            with tmp.open("w", encoding="utf-8") as handle:
                handle.write(json.dumps(data, ensure_ascii=False, indent=2))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, self.path)
            if sys.platform != "win32":
                try:
                    directory_fd = os.open(self.path.parent, os.O_RDONLY)
                    try:
                        os.fsync(directory_fd)
                    finally:
                        os.close(directory_fd)
                except Exception as err:
                    logging.debug("directory fsync ignored: %s", err)
        finally:
            if tmp.exists():
                try:
                    tmp.unlink()
                except Exception as err:
                    logging.debug("unlink tmp ignored: %s", err)

    def _assert_promotion_unfrozen(self) -> None:
        if not self.promotion_guard_path.exists() or os.getenv("ML_MODEL_PROMOTION_OVERRIDE", "false").lower() in {"1", "true", "yes"}:
            return
        try:
            guard = json.loads(self.promotion_guard_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise RegistryConflictError(f"promotion_guard_unreadable:{exc}") from exc
        if guard.get("status") != "AUTHORIZED":
            raise RegistryConflictError("promotion_frozen_during_remediation")

    @staticmethod
    def _assert_runtime_evidence_healthy() -> None:
        evidence_path = get_runtime_paths().runtime_evidence_path
        partition_pattern = f"{evidence_path.stem}_????-??-??{evidence_path.suffix}"
        if not evidence_path.exists() and not any(evidence_path.parent.glob(partition_pattern)):
            return
        from .runtime_evidence_store import RuntimeEvidenceStore
        health = RuntimeEvidenceStore(evidence_path).health()
        if health.get("status") != "healthy":
            raise RegistryConflictError("promotion_blocked_by_runtime_evidence_health")

    def assert_production_registration_allowed(self) -> None:
        self._assert_promotion_unfrozen()
        self._assert_runtime_evidence_healthy()

    def register(self, record: dict[str, Any]) -> dict[str, Any]:
        name, version, status = record.get("model_name"), record.get("version"), record.get("status", "candidate")
        if not name or not version or status not in VALID_STATUSES:
            raise ValueError("model_name, version and valid status are required")
        result = dict(record)
        artifact_path = result.get("artifact_path")
        if artifact_path:
            root = getattr(self, "approved_root", ROOT)
            artifact = (root / artifact_path).resolve() if not Path(artifact_path).is_absolute() else Path(artifact_path)
            if not artifact.exists():
                raise FileNotFoundError(f"cannot register missing artifact: {artifact}")
            result["artifact_path"] = str(artifact.relative_to(root))
            result.setdefault("sha256", sha256_file(artifact))
        result.setdefault("registered_at", datetime.now(timezone.utc).isoformat())
        if status == "production":
            self.assert_production_registration_allowed()
        with self._locked(exclusive=True):
            data = self._read()
            if any(r.get("model_name") == name and r.get("version") == version for r in data["records"]):
                raise ValueError("model version already registered; artifacts are immutable")
            if status == "production":
                for existing in data["records"]:
                    if existing.get("model_name") == name and existing.get("status") == "production":
                        existing["status"] = "archive"
                        existing["archived_at"] = result["registered_at"]
                        result.setdefault("previous_production_version", existing.get("version"))
            data["records"].append(result)
            self._write(data)
        return result

    def active(self, model_name: str, allowed_statuses: tuple[str, ...] = ("production",)) -> dict[str, Any] | None:
        with self._locked(exclusive=False):
            records = [r for r in self._read()["records"] if r.get("model_name") == model_name and r.get("status") in allowed_statuses]
        return records[-1] if records else None

    def rollback(self, model_name: str, version: str) -> dict[str, Any]:
        with self._locked(exclusive=True):
            data = self._read()
            target = next((r for r in data["records"] if r.get("model_name") == model_name and r.get("version") == version), None)
            if target is None:
                raise KeyError("rollback version not found")
            for item in data["records"]:
                if item.get("model_name") == model_name and item.get("status") == "production":
                    item["status"] = "archive"
            target["status"] = "production"
            target["rolled_back_at"] = datetime.now(timezone.utc).isoformat()
            self._write(data)
        return target

    def promote(self, model_name: str, candidate_id: str, expected_current_production_id: str | None) -> dict[str, Any]:
        """CAS promotion: fail if the production slot changed since review."""
        self._assert_promotion_unfrozen()
        self._assert_runtime_evidence_healthy()
        with self._locked(exclusive=True):
            data = self._read()
            productions = [r for r in data["records"] if r.get("model_name") == model_name and r.get("status") == "production"]
            current = productions[-1] if productions else None
            current_id = None if current is None else str(current.get("artifact_id") or current.get("version"))
            if current_id != expected_current_production_id:
                from .operational_health import increment
                increment("registry_conflict_total")
                raise RegistryConflictError(f"production_changed:{current_id}:{expected_current_production_id}")
            target = next(
                (r for r in data["records"] if r.get("model_name") == model_name
                 and str(r.get("artifact_id") or r.get("version")) == candidate_id), None,
            )
            if target is None or target.get("status") not in {"candidate", "shadow"}:
                raise ValueError("promotion target must be an active candidate or shadow artifact")
            evidence = target.get("metrics") or target.get("metadata") or {}
            if evidence.get("holdout_used_for_selection") is not False and str(model_name).startswith("meta_model"):
                raise ValueError("promotion blocked: holdout isolation is not proven")
            if str(model_name).startswith("rl_") and evidence.get("promotion_gate_passed") is not True:
                raise ValueError("promotion blocked: RL multi-criterion gate is not proven")
            now = datetime.now(timezone.utc).isoformat()
            if current is not None:
                current["status"], current["archived_at"] = "archive", now
            target["status"], target["promoted_at"] = "production", now
            target["previous_production_id"] = current_id
            self._write(data)
            return dict(target)

    def permits_artifact(self, model_name: str, artifact_path: Path, sha256: str | None,
                         allowed_statuses: tuple[str, ...] = ("production", "shadow")) -> bool:
        try:
            record = self.active(model_name, allowed_statuses)
            if record is None:
                return False
            expected_path = str(artifact_path.resolve().relative_to(ROOT)).replace("/", "\\")
            registered_path = str(record.get("artifact_path", "")).replace("/", "\\")
            return registered_path == expected_path and (not record.get("sha256") or record.get("sha256") == sha256)
        except (ValueError, OSError):
            return False
