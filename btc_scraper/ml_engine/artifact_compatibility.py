"""P6-G2 artifact compatibility manifest and fail-closed validator."""
from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Sequence

from .artifact_resolver import ROOT, sha256_file
from .evaluation_contracts import canonical_hash
from .inference_contract import feature_schema_hash


ARTIFACT_COMPATIBILITY_CONTRACT_VERSION = "artifact-compatibility/v1"


class CompatibilityStatus(str, Enum):
    READY = "READY"
    INCOMPATIBLE_ARTIFACT = "INCOMPATIBLE_ARTIFACT"
    INVALID_INPUT = "INVALID_INPUT"


@dataclass(frozen=True)
class RuntimeFeatureSchema:
    feature_names: tuple[str, ...]
    feature_dtypes: tuple[str, ...]
    nullable: tuple[bool, ...]
    schema_version: str

    @classmethod
    def from_names(
        cls,
        feature_names: Sequence[str],
        *,
        schema_version: str,
        dtype: str = "float",
        nullable: bool = False,
    ) -> "RuntimeFeatureSchema":
        names = tuple(str(name) for name in feature_names)
        return cls(
            feature_names=names,
            feature_dtypes=tuple(dtype for _ in names),
            nullable=tuple(nullable for _ in names),
            schema_version=str(schema_version),
        )

    @property
    def fields(self) -> tuple[dict[str, Any], ...]:
        return tuple(
            {"name": name, "dtype": dtype, "nullable": nullable}
            for name, dtype, nullable in zip(
                self.feature_names, self.feature_dtypes, self.nullable
            )
        )

    @property
    def schema_hash(self) -> str:
        return canonical_hash(
            {"schema_version": self.schema_version, "features": list(self.fields)}
        )

    @property
    def order_hash(self) -> str:
        return canonical_hash(list(self.feature_names))


@dataclass(frozen=True)
class CompatibilityResult:
    status: CompatibilityStatus
    reason_code: str | None = None
    compatibility_hash: str | None = None
    artifact_sha256: str | None = None

    @property
    def ready(self) -> bool:
        return self.status is CompatibilityStatus.READY


def compatibility_hash_payload(manifest: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "contract_version": manifest.get("contract_version"),
        "artifact": manifest.get("artifact"),
        "feature_schema": manifest.get("feature_schema"),
        "dataset_identities": manifest.get("dataset_identities"),
        "model_config": manifest.get("model_config"),
        "preprocessing": manifest.get("preprocessing"),
        "calibration": manifest.get("calibration"),
    }


def compute_compatibility_hash(manifest: Mapping[str, Any]) -> str:
    return canonical_hash(compatibility_hash_payload(manifest))


def load_compatibility_manifest(path: Path | str) -> dict[str, Any]:
    target = Path(path)
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError("MANIFEST_MISSING") from exc
    except Exception as exc:
        raise ValueError("MANIFEST_INVALID") from exc
    if not isinstance(value, dict):
        raise ValueError("MANIFEST_INVALID")
    return value


def compatibility_manifest_path_for_artifact(path: Path | str) -> Path:
    artifact_path = Path(path)
    tracked = ROOT / "config" / "artifact_compatibility" / f"{artifact_path.stem}.compatibility.json"
    if tracked.exists():
        return tracked
    return artifact_path.with_name(f"{artifact_path.stem}.compatibility.json")


def _symbol_keys(value: Any) -> tuple[str, ...]:
    if not isinstance(value, Mapping):
        return ()
    return tuple(sorted(str(key) for key in value))


def validate_artifact_compatibility(
    artifact_path: Path | str,
    manifest: Mapping[str, Any] | None,
    runtime_schema: RuntimeFeatureSchema,
    *,
    artifact_obj: Any | None = None,
    metadata: Mapping[str, Any] | None = None,
    artifact_sha256: str | None = None,
) -> CompatibilityResult:
    if manifest is None:
        return CompatibilityResult(
            CompatibilityStatus.INCOMPATIBLE_ARTIFACT, "MANIFEST_MISSING"
        )
    if not isinstance(manifest, Mapping):
        return CompatibilityResult(CompatibilityStatus.INVALID_INPUT, "MANIFEST_INVALID")
    if manifest.get("contract_version") != ARTIFACT_COMPATIBILITY_CONTRACT_VERSION:
        return CompatibilityResult(
            CompatibilityStatus.INVALID_INPUT, "MANIFEST_VERSION_UNSUPPORTED"
        )

    expected_hash = manifest.get("compatibility_hash")
    actual_hash = compute_compatibility_hash(manifest)
    if expected_hash != actual_hash:
        return CompatibilityResult(
            CompatibilityStatus.INVALID_INPUT,
            "MANIFEST_HASH_MISMATCH",
            actual_hash,
        )

    actual_sha = str(artifact_sha256 or sha256_file(Path(artifact_path))).lower()
    artifact = manifest.get("artifact")
    if not isinstance(artifact, Mapping):
        return CompatibilityResult(
            CompatibilityStatus.INVALID_INPUT, "MANIFEST_INVALID", actual_hash, actual_sha
        )
    if str(artifact.get("sha256", "")).lower() != actual_sha:
        return CompatibilityResult(
            CompatibilityStatus.INCOMPATIBLE_ARTIFACT,
            "ARTIFACT_HASH_MISMATCH",
            actual_hash,
            actual_sha,
        )

    feature_schema = manifest.get("feature_schema")
    if not isinstance(feature_schema, Mapping):
        return CompatibilityResult(
            CompatibilityStatus.INVALID_INPUT, "MANIFEST_INVALID", actual_hash, actual_sha
        )
    manifest_names = tuple(str(name) for name in feature_schema.get("ordered_names", ()))
    if manifest_names != runtime_schema.feature_names:
        return CompatibilityResult(
            CompatibilityStatus.INCOMPATIBLE_ARTIFACT,
            "FEATURE_ORDER_MISMATCH",
            actual_hash,
            actual_sha,
        )
    if str(feature_schema.get("schema_version")) != runtime_schema.schema_version:
        return CompatibilityResult(
            CompatibilityStatus.INCOMPATIBLE_ARTIFACT,
            "FEATURE_SCHEMA_MISMATCH",
            actual_hash,
            actual_sha,
        )
    if str(feature_schema.get("schema_hash")) != runtime_schema.schema_hash:
        return CompatibilityResult(
            CompatibilityStatus.INCOMPATIBLE_ARTIFACT,
            "FEATURE_SCHEMA_MISMATCH",
            actual_hash,
            actual_sha,
        )
    if str(feature_schema.get("order_hash")) != runtime_schema.order_hash:
        return CompatibilityResult(
            CompatibilityStatus.INCOMPATIBLE_ARTIFACT,
            "FEATURE_ORDER_MISMATCH",
            actual_hash,
            actual_sha,
        )
    if str(feature_schema.get("inference_feature_schema_hash")) != feature_schema_hash(
        runtime_schema.feature_names
    ):
        return CompatibilityResult(
            CompatibilityStatus.INCOMPATIBLE_ARTIFACT,
            "FEATURE_SCHEMA_MISMATCH",
            actual_hash,
            actual_sha,
        )

    dataset = manifest.get("dataset_identities")
    if not isinstance(dataset, Mapping) or dataset.get("provenance_verdict") != "DATASET_PROVENANCE_RECOVERED":
        return CompatibilityResult(
            CompatibilityStatus.INCOMPATIBLE_ARTIFACT,
            "PROVENANCE_INCOMPLETE",
            actual_hash,
            actual_sha,
        )

    model_config = manifest.get("model_config")
    preprocessing = manifest.get("preprocessing")
    calibration = manifest.get("calibration")
    if not isinstance(model_config, Mapping) or not isinstance(preprocessing, Mapping) or not isinstance(calibration, Mapping):
        return CompatibilityResult(
            CompatibilityStatus.INVALID_INPUT, "MANIFEST_INVALID", actual_hash, actual_sha
        )
    if calibration.get("status") != "PROVEN_NOT_APPLICABLE":
        return CompatibilityResult(
            CompatibilityStatus.INCOMPATIBLE_ARTIFACT,
            "CALIBRATION_MISMATCH",
            actual_hash,
            actual_sha,
        )

    if metadata:
        metadata_features = tuple(str(name) for name in metadata.get("features", ()))
        if metadata_features and metadata_features != runtime_schema.feature_names:
            return CompatibilityResult(
                CompatibilityStatus.INCOMPATIBLE_ARTIFACT,
                "FEATURE_SCHEMA_MISMATCH",
                actual_hash,
                actual_sha,
            )
        if metadata.get("n_features") is not None and int(metadata["n_features"]) != len(runtime_schema.feature_names):
            return CompatibilityResult(
                CompatibilityStatus.INCOMPATIBLE_ARTIFACT,
                "FEATURE_SCHEMA_MISMATCH",
                actual_hash,
                actual_sha,
            )

    if artifact_obj is not None:
        bundle_features = ()
        model_obj = artifact_obj
        if isinstance(artifact_obj, Mapping):
            bundle_features = tuple(str(name) for name in artifact_obj.get("features", ()))
            model_obj = artifact_obj.get("model")
        if bundle_features and bundle_features != runtime_schema.feature_names:
            return CompatibilityResult(
                CompatibilityStatus.INCOMPATIBLE_ARTIFACT,
                "FEATURE_ORDER_MISMATCH",
                actual_hash,
                actual_sha,
            )
        expected_wrapper = str(model_config.get("runtime_wrapper_class"))
        observed_wrapper = f"{model_obj.__class__.__module__}.{model_obj.__class__.__name__}"
        if expected_wrapper and observed_wrapper != expected_wrapper:
            return CompatibilityResult(
                CompatibilityStatus.INCOMPATIBLE_ARTIFACT,
                "MODEL_METADATA_MISMATCH",
                actual_hash,
                actual_sha,
            )
        expected_symbols = tuple(model_config.get("symbols", ()))
        if expected_symbols and _symbol_keys(getattr(model_obj, "model_params", None)) != expected_symbols:
            return CompatibilityResult(
                CompatibilityStatus.INCOMPATIBLE_ARTIFACT,
                "MODEL_METADATA_MISMATCH",
                actual_hash,
                actual_sha,
            )
        if expected_symbols and _symbol_keys(getattr(model_obj, "preprocessing_params", None)) != expected_symbols:
            return CompatibilityResult(
                CompatibilityStatus.INCOMPATIBLE_ARTIFACT,
                "PREPROCESSING_MISMATCH",
                actual_hash,
                actual_sha,
            )
        preprocessing_symbols = tuple(preprocessing.get("required_parameter_sets", ()))
        if preprocessing_symbols and _symbol_keys(getattr(model_obj, "preprocessing_params", None)) != preprocessing_symbols:
            return CompatibilityResult(
                CompatibilityStatus.INCOMPATIBLE_ARTIFACT,
                "PREPROCESSING_MISMATCH",
                actual_hash,
                actual_sha,
            )

    return CompatibilityResult(
        CompatibilityStatus.READY,
        None,
        actual_hash,
        actual_sha,
    )
