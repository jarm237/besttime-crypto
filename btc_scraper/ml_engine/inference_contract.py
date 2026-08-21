"""Explicit, immutable model-inference request and result contracts."""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Sequence

from btc_scraper.core.config import get_analysis_universe
from btc_scraper.ml_engine.model_governance import schema_hash


INFERENCE_CONTRACT_VERSION = "explicit-inference/v1"
META_MODEL_FAMILY = "meta_model"


class InferenceContractError(ValueError):
    """Raised before inference when routing or identity is unresolved."""


def normalize_inference_symbol(
    value: object,
    *,
    supported_symbols: Iterable[str] | None = None,
) -> str:
    """Normalize an explicit symbol without consulting ambient runtime state."""
    if not isinstance(value, str):
        raise InferenceContractError("inference_symbol_must_be_string")
    raw = value.strip().upper().replace("/", "").replace("-", "")
    if not raw:
        raise InferenceContractError("inference_symbol_missing")
    symbol = raw.removesuffix("USDT")
    supported = {
        str(item).strip().upper().replace("/", "").replace("-", "").removesuffix("USDT")
        for item in (supported_symbols or get_analysis_universe())
    }
    if symbol in {"", "UNKNOWN", "NONE", "NULL"} or symbol not in supported:
        raise InferenceContractError(f"inference_symbol_unsupported:{symbol or raw}")
    return symbol


def feature_schema_hash(feature_names: Iterable[str]) -> str:
    """Hash the exact ordered feature names consumed by the predictor."""
    names = tuple(str(name) for name in feature_names)
    if not names or any(not name for name in names):
        raise InferenceContractError("feature_schema_names_missing")
    return schema_hash(names)


def artifact_set_hash(paths: Sequence[Path | str]) -> str:
    """Hash an ordered artifact set, including filenames and exact bytes."""
    digest = hashlib.sha256()
    resolved = tuple(Path(path) for path in paths)
    if not resolved:
        raise InferenceContractError("artifact_set_empty")
    for path in resolved:
        if not path.is_file():
            raise InferenceContractError(f"artifact_file_missing:{path}")
        name = path.name.encode("utf-8")
        digest.update(len(name).to_bytes(4, "big"))
        digest.update(name)
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    return digest.hexdigest()


ProbabilityPredictor = Callable[[str, tuple[float, ...]], float]


@dataclass(frozen=True)
class InferenceArtifact:
    """Identity and callable bound to the exact artifact used for inference."""

    model_family: str
    artifact_version: str
    artifact_hash: str
    feature_schema_hash: str
    feature_names: tuple[str, ...]
    predictor: ProbabilityPredictor = field(repr=False, compare=False)
    feature_schema_version: str | None = None
    artifact_metadata_consistent: bool | None = None
    calibration_method: str | None = None
    supported_symbols: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        if not self.model_family.strip():
            raise InferenceContractError("artifact_model_family_missing")
        if not self.artifact_version.strip():
            raise InferenceContractError("artifact_version_missing")
        if len(self.artifact_hash) != 64 or any(ch not in "0123456789abcdef" for ch in self.artifact_hash.lower()):
            raise InferenceContractError("artifact_hash_invalid")
        actual_schema_hash = feature_schema_hash(self.feature_names)
        if self.feature_schema_hash != actual_schema_hash:
            raise InferenceContractError("feature_schema_hash_mismatch")
        if not callable(self.predictor):
            raise InferenceContractError("artifact_predictor_missing")
        normalized_supported = frozenset(
            normalize_inference_symbol(item)
            for item in (self.supported_symbols or frozenset(get_analysis_universe()))
        )
        object.__setattr__(self, "supported_symbols", normalized_supported)


@dataclass(frozen=True)
class InferenceRequest:
    symbol: str
    features: tuple[float, ...]
    artifact: InferenceArtifact
    inference_contract_version: str = INFERENCE_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if self.inference_contract_version != INFERENCE_CONTRACT_VERSION:
            raise InferenceContractError("inference_contract_version_unsupported")
        normalized = normalize_inference_symbol(
            self.symbol,
            supported_symbols=self.artifact.supported_symbols,
        )
        values = tuple(float(value) for value in self.features)
        if len(values) != len(self.artifact.feature_names):
            raise InferenceContractError("inference_feature_count_mismatch")
        if any(not math.isfinite(value) for value in values):
            raise InferenceContractError("inference_features_non_finite")
        object.__setattr__(self, "symbol", normalized)
        object.__setattr__(self, "features", values)


@dataclass(frozen=True)
class InferenceResult:
    symbol: str
    artifact_version: str
    artifact_hash: str
    feature_schema_hash: str
    model_family: str
    prediction: float
    inference_contract_version: str = INFERENCE_CONTRACT_VERSION
    feature_schema_version: str | None = None
    artifact_metadata_consistent: bool | None = None


def predict(
    *,
    symbol: str,
    features: Sequence[float],
    artifact: InferenceArtifact,
) -> InferenceResult:
    """Run inference solely from the explicit symbol, features and artifact."""
    request = InferenceRequest(
        symbol=symbol,
        features=tuple(features),
        artifact=artifact,
    )
    prediction = float(artifact.predictor(request.symbol, request.features))
    if not math.isfinite(prediction) or not 0.0 <= prediction <= 1.0:
        raise InferenceContractError("inference_prediction_out_of_range")
    return InferenceResult(
        symbol=request.symbol,
        artifact_version=artifact.artifact_version,
        artifact_hash=artifact.artifact_hash,
        feature_schema_hash=artifact.feature_schema_hash,
        model_family=artifact.model_family,
        prediction=prediction,
        feature_schema_version=artifact.feature_schema_version,
        artifact_metadata_consistent=artifact.artifact_metadata_consistent,
    )
