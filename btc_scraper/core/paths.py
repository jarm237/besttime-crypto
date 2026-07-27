from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _resolve_env_path(env_name: str, default: Path) -> Path:
    raw = os.getenv(env_name)
    path = Path(raw).expanduser() if raw else default
    return path if path.is_absolute() else REPO_ROOT / path


def runtime_environment() -> str:
    return os.getenv("BTC_RUNTIME_ENVIRONMENT") or os.getenv("BTC_ENVIRONMENT") or "production"


def runtime_evidence_eligible() -> bool:
    explicit = os.getenv("BTC_EVIDENCE_ELIGIBLE")
    if explicit is not None:
        return explicit.strip().lower() in {"1", "true", "yes", "on"}
    return runtime_environment() != "test"


def runtime_paper_run_id() -> str | None:
    return os.getenv("BTC_PAPER_RUN_ID") or os.getenv("PYTEST_XDIST_WORKER")


@dataclass(frozen=True)
class RuntimePaths:
    environment: str
    data_root: Path
    logs_root: Path
    model_root: Path
    execution_data_root: Path
    prediction_audit_dir: Path
    runtime_evidence_path: Path
    catboost_info_dir: Path
    evidence_eligible: bool
    paper_run_id: str | None


def get_runtime_paths() -> RuntimePaths:
    data_root = _resolve_env_path("BTC_DATA_DIR", REPO_ROOT / "data")
    logs_root = _resolve_env_path("BTC_LOG_DIR", REPO_ROOT / "logs")
    model_root = _resolve_env_path("BTC_MODEL_DIR", logs_root)
    execution_data_root = _resolve_env_path("BTC_EXECUTION_DATA_DIR", data_root / "execution")
    prediction_audit_dir = _resolve_env_path("BTC_PREDICTION_AUDIT_DIR", logs_root / "prediction_audit")
    runtime_evidence_path = _resolve_env_path("BTC_RUNTIME_EVIDENCE_PATH", logs_root / "runtime_evidence.sqlite")
    catboost_info_dir = _resolve_env_path("CATBOOST_INFO_DIR", REPO_ROOT / "catboost_info")
    return RuntimePaths(
        environment=runtime_environment(),
        data_root=data_root,
        logs_root=logs_root,
        model_root=model_root,
        execution_data_root=execution_data_root,
        prediction_audit_dir=prediction_audit_dir,
        runtime_evidence_path=runtime_evidence_path,
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


def build_prediction_audit_path(*parts: str | Path) -> Path:
    """Return a path under the configured prediction audit directory."""
    return get_runtime_paths().prediction_audit_dir.joinpath(*[Path(part) for part in parts])


def build_scripts_path(*parts: str | Path) -> Path:
    """Return a path under the repository scripts directory."""
    return build_repo_path("scripts", *parts)
