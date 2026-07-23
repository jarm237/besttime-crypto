"""Fail-closed model artifact loading after registry, hash and schema verification."""
from __future__ import annotations

import json
import os
import platform
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version as package_version
from pathlib import Path
from typing import Any

from .artifact_resolver import ArtifactResolver, ROOT
from .model_registry import ModelRegistry
from .operational_health import record_degradation, record_healthy


class ArtifactGovernanceError(RuntimeError):
    pass


@dataclass(frozen=True)
class LoadedArtifact:
    model: object
    artifact_id: str
    artifact_sha256: str
    model_version: str
    feature_schema_version: str
    lifecycle_status: str
    registry_revision: str
    deployment_slot: str
    loaded_at: str
    runtime_versions: dict[str, str]
    path: Path
    metadata: dict[str, Any]


class GovernedArtifactLoader:
    def __init__(self, resolver: ArtifactResolver | None = None, registry: ModelRegistry | None = None,
                 approved_root: Path | str = ROOT) -> None:
        self.resolver = resolver or ArtifactResolver()
        self.registry = registry or ModelRegistry()
        self.approved_root = Path(approved_root).resolve()

    def load_production(
        self,
        model_family: str,
        expected_schema_version: str,
        *,
        allowed_statuses: tuple[str, ...] = ("production",),
        model_class: Any = None,
        device: str | None = None,
    ) -> LoadedArtifact:
        started = time.perf_counter()
        try:
            resolved = self.resolver.resolve(model_family, require_metadata=True)
            if not resolved.healthy or resolved.path is None or resolved.metadata is None:
                raise ArtifactGovernanceError(resolved.reason or "artifact_unhealthy")
            path = resolved.path.resolve()
            approved_root = self.approved_root
            if not path.is_relative_to(approved_root):
                raise ArtifactGovernanceError("artifact_path_outside_approved_root")
            if resolved.status not in allowed_statuses:
                raise ArtifactGovernanceError(f"lifecycle_status_not_allowed:{resolved.status}")
            if not self.registry.permits_artifact(model_family, path, resolved.sha256, allowed_statuses):
                raise ArtifactGovernanceError("artifact_not_permitted_by_registry")
            registry_record = self.registry.active(model_family, allowed_statuses)
            if registry_record is None:
                raise ArtifactGovernanceError("registry_record_disappeared_during_load")
            metadata = resolved.metadata
            metadata_status = str(metadata.get("status", resolved.status))
            if metadata_status not in allowed_statuses:
                raise ArtifactGovernanceError(f"metadata_status_not_allowed:{metadata_status}")
            actual_schema = str(
                metadata.get("feature_schema_version")
                or metadata.get("observation_schema_version")
                or resolved.schema_version
                or ""
            )
            if actual_schema != expected_schema_version:
                raise ArtifactGovernanceError(f"schema_mismatch:{actual_schema}:{expected_schema_version}")
            self._verify_runtime_compatibility(metadata, path)
            model = self._deserialize(path, model_class=model_class, device=device)
            version = str(metadata.get("model_version") or metadata.get("version") or "unknown")
            artifact_id = str(metadata.get("artifact_id") or f"{model_family}:{version}:{resolved.sha256[:12]}")
            registry_revision = self.registry.revision()
            loaded = LoadedArtifact(
                model=model, artifact_id=artifact_id, artifact_sha256=str(resolved.sha256),
                model_version=version, feature_schema_version=actual_schema,
                lifecycle_status=metadata_status, registry_revision=registry_revision,
                deployment_slot=str(registry_record.get("deployment_slot") or registry_record.get("status") or metadata_status),
                loaded_at=datetime.now(timezone.utc).isoformat(),
                runtime_versions=self._runtime_versions(),
                path=path, metadata=metadata,
            )
            try:
                self._audit(model_family, loaded, (time.perf_counter() - started) * 1000)
            except Exception as audit_exc:
                record_degradation("prediction_audit", "prediction_audit_write_failure_total", audit_exc)
            record_healthy("artifact_loader")
            return loaded
        except Exception as exc:
            record_degradation("artifact_loader", "artifact_load_rejected_total", exc)
            if isinstance(exc, ArtifactGovernanceError):
                raise
            raise ArtifactGovernanceError(str(exc)) from exc

    def load_test_artifact(self, path: Path | str) -> Any:
        """Explicit test-only deserialization for isolated fixtures outside the registry."""
        if not os.getenv("PYTEST_CURRENT_TEST"):
            raise ArtifactGovernanceError("test_artifact_load_outside_pytest")
        return self._deserialize(Path(path))

    @staticmethod
    def _verify_runtime_compatibility(metadata: dict[str, Any], path: Path) -> None:
        supported_contracts = {"sklearn-joblib-v1", "stable-baselines-v1", "pytorch-state-dict-v1"}
        runtime_contract = metadata.get("runtime_contract")
        if runtime_contract not in supported_contracts:
            raise ArtifactGovernanceError(f"unsupported_runtime_contract:{runtime_contract}")
        expected_by_suffix = {
            ".joblib": "sklearn-joblib-v1", ".pkl": "sklearn-joblib-v1", ".pickle": "sklearn-joblib-v1",
            ".zip": "stable-baselines-v1", ".pt": "pytorch-state-dict-v1", ".pth": "pytorch-state-dict-v1",
        }
        expected_contract = expected_by_suffix.get(path.suffix.lower())
        if expected_contract and runtime_contract != expected_contract:
            raise ArtifactGovernanceError(f"runtime_contract_format_mismatch:{runtime_contract}:{path.suffix.lower()}")
        required_python = metadata.get("python_major_minor")
        current = f"{platform.python_version_tuple()[0]}.{platform.python_version_tuple()[1]}"
        if required_python and str(required_python) != current:
            raise ArtifactGovernanceError(f"python_runtime_mismatch:{required_python}:{current}")

    @staticmethod
    def _deserialize(path: Path, *, model_class: Any = None, device: str | None = None) -> Any:
        suffix = path.suffix.lower()
        if suffix in {".joblib", ".pkl", ".pickle"}:
            import joblib
            return joblib.load(path)
        if suffix in {".pt", ".pth"}:
            import torch
            return torch.load(path, map_location=device or "cpu", weights_only=True)
        if suffix == ".zip" and model_class is not None:
            return model_class.load(path, device=device or "auto")
        raise ArtifactGovernanceError(f"unsupported_artifact_format:{suffix}")

    @staticmethod
    def _runtime_versions() -> dict[str, str]:
        versions = {"python": platform.python_version()}
        for distribution in ("numpy", "scikit-learn", "joblib", "torch", "stable-baselines3"):
            try:
                versions[distribution] = package_version(distribution)
            except PackageNotFoundError:
                continue
        return versions

    @staticmethod
    def _audit(model_family: str, loaded: LoadedArtifact, latency_ms: float) -> None:
        from .runtime_evidence_store import get_runtime_evidence_store
        get_runtime_evidence_store().append_audit_event({
            "event_type": "artifact_loaded", "model_family": model_family,
            "artifact_id": loaded.artifact_id, "artifact_sha256": loaded.artifact_sha256,
            "model_version": loaded.model_version, "feature_schema_version": loaded.feature_schema_version,
            "lifecycle_status": loaded.lifecycle_status,
            "registry_revision": loaded.registry_revision, "deployment_slot": loaded.deployment_slot,
            "loaded_at": loaded.loaded_at, "runtime_versions": loaded.runtime_versions,
            "latency_ms": round(latency_ms, 4),
        })


def get_governed_artifact_loader() -> GovernedArtifactLoader:
    return GovernedArtifactLoader()


def load_training_checkpoint(path: Path | str, *, device: str | None = None) -> Any:
    """Centralized non-runtime checkpoint reader used only by training/generation flows."""
    import torch
    return torch.load(Path(path), map_location=device or "cpu", weights_only=True)


def load_trusted_pickle(path: Path | str, *, approved_root: Path | str | None = None) -> Any:
    """Read a local cache/dataset after constraining it to an explicitly approved root."""
    import pickle
    target = Path(path).resolve()
    root = Path(approved_root).resolve() if approved_root is not None else ROOT.resolve()
    if not target.is_relative_to(root):
        raise ArtifactGovernanceError("pickle_path_outside_approved_root")
    with target.open("rb") as handle:
        return pickle.load(handle)


def load_offline_rl_artifact(
    path: Path | str, *, model_class: Any, approved_root: Path | str,
    env: Any = None, device: str | None = None, custom_objects: dict[str, Any] | None = None,
) -> Any:
    """Centralized historical-policy loading for offline training/evaluation only."""
    target = Path(path).resolve()
    root = Path(approved_root).resolve()
    if not target.is_relative_to(root):
        raise ArtifactGovernanceError("offline_rl_path_outside_approved_root")
    return model_class.load(target, env=env, device=device, custom_objects=custom_objects or {})


def load_offline_joblib_artifact(path: Path | str, *, approved_root: Path | str) -> Any:
    """Centralized joblib loading for offline audit/evaluation utilities."""
    import joblib
    target = Path(path).resolve()
    root = Path(approved_root).resolve()
    if not target.is_relative_to(root):
        raise ArtifactGovernanceError("offline_joblib_path_outside_approved_root")
    return joblib.load(target)
