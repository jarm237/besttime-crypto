"""Canonical, fail-closed resolver for ML artifacts.

The config deliberately keeps a small YAML subset so the runtime does not gain
a mandatory PyYAML dependency.  It accepts only the mapping structure used by
``config/model_artifacts.yaml``.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = ROOT / "config" / "model_artifacts.yaml"


@dataclass(frozen=True)
class ArtifactLoadResult:
    model_name: str
    path: Path | None
    metadata_path: Path | None
    available: bool
    healthy: bool
    reason: str | None = None
    sha256: str | None = None
    schema_version: str | None = None
    status: str | None = None
    metadata: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["path"] = str(self.path) if self.path else None
        data["metadata_path"] = str(self.metadata_path) if self.metadata_path else None
        return data


def project_root() -> Path:
    return ROOT


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_simple_yaml(path: Path) -> dict[str, dict[str, Any]]:
    """Read the restricted mapping-only YAML used by this project's config."""
    result: dict[str, dict[str, Any]] = {}
    current: dict[str, Any] | None = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        if not line.startswith((" ", "\t")) and line.endswith(":"):
            current = {}
            result[line[:-1].strip()] = current
            continue
        if current is None or ":" not in line:
            raise ValueError(f"Unsupported YAML syntax: {raw}")
        key, value = line.strip().split(":", 1)
        value = value.strip().strip('"\'')
        if value.lower() in {"true", "false"}:
            current[key] = value.lower() == "true"
        else:
            current[key] = value
    return result


class ArtifactResolver:
    def __init__(self, config_path: Path | str = DEFAULT_CONFIG) -> None:
        self.config_path = Path(config_path)
        self._config: dict[str, dict[str, Any]] | None = None

    @property
    def config(self) -> dict[str, dict[str, Any]]:
        if self._config is None:
            if not self.config_path.exists():
                raise FileNotFoundError(f"artifact config missing: {self.config_path}")
            self._config = _read_simple_yaml(self.config_path)
        return self._config

    def specification(self, model_name: str) -> dict[str, Any]:
        try:
            return self.config[model_name]
        except KeyError as exc:
            raise KeyError(f"unknown model artifact: {model_name}") from exc

    def resolve(self, model_name: str, require_metadata: bool = False) -> ArtifactLoadResult:
        try:
            spec = self.specification(model_name)
        except Exception as exc:
            return ArtifactLoadResult(model_name, None, None, False, False, str(exc))
        path = (ROOT / str(spec["production_path"])).resolve()
        metadata_path = (ROOT / str(spec.get("metadata_path", ""))).resolve() if spec.get("metadata_path") else None
        schema = spec.get("schema_version") or spec.get("observation_schema_version")
        status = str(spec.get("status", "disabled"))
        if not path.exists():
            return ArtifactLoadResult(model_name, path, metadata_path, False, False, "artifact_missing", schema_version=schema, status=status)
        metadata: dict[str, Any] | None = None
        if metadata_path and metadata_path.exists():
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            except Exception as exc:
                return ArtifactLoadResult(model_name, path, metadata_path, True, False, f"metadata_invalid:{exc}", schema_version=schema, status=status)
        elif require_metadata:
            return ArtifactLoadResult(model_name, path, metadata_path, True, False, "metadata_missing", schema_version=schema, status=status)
        digest = sha256_file(path)
        if metadata:
            expected = metadata.get("artifact_sha256") or metadata.get("sha256")
            if expected and expected != digest:
                return ArtifactLoadResult(model_name, path, metadata_path, True, False, "sha256_mismatch", digest, schema, status, metadata)
            expected_schema = metadata.get("feature_schema_version") or metadata.get("observation_schema_version")
            if expected_schema and schema and expected_schema != schema:
                return ArtifactLoadResult(model_name, path, metadata_path, True, False, "schema_version_mismatch", digest, schema, status, metadata)
        return ArtifactLoadResult(model_name, path, metadata_path, True, True, None, digest, schema, status, metadata)

    def health(self) -> dict[str, dict[str, Any]]:
        return {name: self.resolve(name).to_dict() for name in self.config}


def get_artifact_resolver() -> ArtifactResolver:
    return ArtifactResolver()
