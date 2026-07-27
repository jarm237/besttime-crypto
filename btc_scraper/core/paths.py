from __future__ import annotations

import socket
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
_PROCESS_STARTED_AT = datetime.now(timezone.utc).isoformat()
_PROCESS_RUNTIME_ID: str | None = None


def _resolve_env_path(env_name: str, default: Path) -> Path:
    raw = os.getenv(env_name)
    path = Path(raw).expanduser() if raw else default
    return path if path.is_absolute() else REPO_ROOT / path


def runtime_environment() -> str:
    return os.getenv("BTC_RUNTIME_ENVIRONMENT") or os.getenv("BTC_ENVIRONMENT") or "production"


def runtime_lock_disabled() -> bool:
    return os.getenv("BTC_DISABLE_RUNTIME_LOCK", "").strip().lower() in {"1", "true", "yes", "on"}


def runtime_lock_bypass_reason() -> str:
    return os.getenv("BTC_RUNTIME_LOCK_BYPASS_REASON", "").strip() or "unspecified"


def runtime_evidence_eligible() -> bool:
    if runtime_lock_disabled():
        return False
    explicit = os.getenv("BTC_EVIDENCE_ELIGIBLE")
    if explicit is not None:
        return explicit.strip().lower() in {"1", "true", "yes", "on"}
    return runtime_environment() != "test"


def runtime_paper_run_id() -> str | None:
    return os.getenv("BTC_PAPER_RUN_ID") or os.getenv("PYTEST_XDIST_WORKER")


def runtime_deployment_id() -> str:
    return os.getenv("BTC_DEPLOYMENT_ID") or f"local-{runtime_environment()}"


def runtime_id() -> str:
    global _PROCESS_RUNTIME_ID
    explicit = os.getenv("BTC_RUNTIME_ID")
    if explicit:
        return explicit
    if _PROCESS_RUNTIME_ID is None:
        started = datetime.fromisoformat(_PROCESS_STARTED_AT).strftime("%Y%m%dT%H%M%SZ")
        _PROCESS_RUNTIME_ID = f"{started}-{os.getpid()}"
    return _PROCESS_RUNTIME_ID


def runtime_owner_metadata() -> dict[str, str | int]:
    paths = get_runtime_paths()
    return {
        "environment": paths.environment,
        "deployment_id": paths.deployment_id,
        "runtime_id": paths.runtime_id,
        "process_id": paths.process_id,
        "hostname": paths.hostname,
        "started_at": paths.started_at,
        "data_root": str(paths.data_root),
        "log_root": str(paths.logs_root),
    }


@dataclass(frozen=True)
class RuntimePaths:
    environment: str
    deployment_id: str
    runtime_id: str
    process_id: int
    hostname: str
    started_at: str
    runtime_root: Path
    data_root: Path
    logs_root: Path
    model_root: Path
    state_root: Path
    execution_data_root: Path
    prediction_audit_dir: Path
    runtime_evidence_path: Path
    reservation_db_path: Path
    runtime_lock_path: Path
    catboost_info_dir: Path
    evidence_eligible: bool
    paper_run_id: str | None


def get_runtime_paths() -> RuntimePaths:
    environment = runtime_environment()
    deployment_id = runtime_deployment_id()
    runtime_root = _resolve_env_path(
        "BTC_RUNTIME_ROOT",
        REPO_ROOT / "runtime" / environment / deployment_id,
    )
    data_root = _resolve_env_path("BTC_DATA_DIR", runtime_root / "data")
    logs_root = _resolve_env_path("BTC_LOG_DIR", runtime_root / "logs")
    model_root = _resolve_env_path("BTC_MODEL_DIR", runtime_root / "models")
    state_root = _resolve_env_path("BTC_STATE_DIR", runtime_root / "state")
    execution_data_root = _resolve_env_path("BTC_EXECUTION_DATA_DIR", data_root / "execution")
    prediction_audit_dir = _resolve_env_path("BTC_PREDICTION_AUDIT_DIR", logs_root / "prediction_audit")
    runtime_evidence_path = _resolve_env_path("BTC_RUNTIME_EVIDENCE_PATH", logs_root / "runtime_evidence.sqlite")
    reservation_db_path = _resolve_env_path("BTC_RESERVATION_DB_PATH", execution_data_root / "reservations.db")
    runtime_lock_path = _resolve_env_path("BTC_RUNTIME_LOCK_PATH", state_root / "runtime.lock")
    catboost_info_dir = _resolve_env_path("CATBOOST_INFO_DIR", runtime_root / "catboost_info")
    return RuntimePaths(
        environment=environment,
        deployment_id=deployment_id,
        runtime_id=runtime_id(),
        process_id=os.getpid(),
        hostname=socket.gethostname(),
        started_at=_PROCESS_STARTED_AT,
        runtime_root=runtime_root,
        data_root=data_root,
        logs_root=logs_root,
        model_root=model_root,
        state_root=state_root,
        execution_data_root=execution_data_root,
        prediction_audit_dir=prediction_audit_dir,
        runtime_evidence_path=runtime_evidence_path,
        reservation_db_path=reservation_db_path,
        runtime_lock_path=runtime_lock_path,
        catboost_info_dir=catboost_info_dir,
        evidence_eligible=runtime_evidence_eligible(),
        paper_run_id=runtime_paper_run_id(),
    )


def build_repo_path(*parts: str | Path) -> Path:
    """Return a path rooted at the repository directory."""
    return REPO_ROOT.joinpath(*[Path(part) for part in parts])


def build_data_path(*parts: str | Path) -> Path:
    """Return a path under the configured runtime data directory."""
    return get_runtime_paths().data_root.joinpath(*[Path(part) for part in parts])


def build_logs_path(*parts: str | Path) -> Path:
    """Return a path under the configured runtime logs directory."""
    return get_runtime_paths().logs_root.joinpath(*[Path(part) for part in parts])


def build_model_path(*parts: str | Path) -> Path:
    """Return a path under the configured runtime model/artifact directory."""
    return get_runtime_paths().model_root.joinpath(*[Path(part) for part in parts])


def build_execution_data_path(*parts: str | Path) -> Path:
    """Return a path under the configured execution data directory."""
    return get_runtime_paths().execution_data_root.joinpath(*[Path(part) for part in parts])


def build_state_path(*parts: str | Path) -> Path:
    """Return a path under the configured runtime state directory."""
    return get_runtime_paths().state_root.joinpath(*[Path(part) for part in parts])


def build_prediction_audit_path(*parts: str | Path) -> Path:
    """Return a path under the configured prediction audit directory."""
    return get_runtime_paths().prediction_audit_dir.joinpath(*[Path(part) for part in parts])


def build_scripts_path(*parts: str | Path) -> Path:
    """Return a path under the repository scripts directory."""
    return build_repo_path("scripts", *parts)
