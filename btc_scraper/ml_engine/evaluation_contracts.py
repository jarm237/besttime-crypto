"""P6 contracts surrounding the canonical evaluator.

These contracts validate identity, schema, readiness and reconstruction.  They
contain no trading policy and deliberately run before semantic evaluation.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping, Sequence


P6_CONTRACT_VERSION = "evaluation-boundary/v1"
READINESS_CONTRACT_VERSION = "readiness-boundary/v1"
CANONICAL_ENTRY_TIMEFRAME = "15m"
CANONICAL_ENTRY_INTERVAL_SECONDS = 900


class EvaluationContractError(ValueError):
    """Fail-closed boundary rejection; never translated into HOLD."""


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def require_sha256(value: str, field: str) -> str:
    normalized = str(value).lower()
    if len(normalized) != 64 or any(ch not in "0123456789abcdef" for ch in normalized):
        raise EvaluationContractError(f"{field}_invalid")
    return normalized


@dataclass(frozen=True)
class ArtifactContract:
    artifact_id: str
    artifact_type: str
    artifact_version: str
    sha256: str
    schema_version: str
    feature_schema_hash: str
    feature_order_hash: str
    training_contract_hash: str
    calibration_contract_hash: str
    compatible_evaluator_version: str

    def __post_init__(self) -> None:
        for field in (
            "artifact_id", "artifact_type", "artifact_version", "schema_version",
            "compatible_evaluator_version",
        ):
            if not str(getattr(self, field)).strip():
                raise EvaluationContractError(f"{field}_missing")
        for field in (
            "sha256", "feature_schema_hash", "feature_order_hash",
            "training_contract_hash", "calibration_contract_hash",
        ):
            object.__setattr__(self, field, require_sha256(getattr(self, field), field))

    def assert_compatible(
        self, *, evaluator_version: str, feature_schema_hash: str,
        feature_order_hash: str,
    ) -> None:
        if self.compatible_evaluator_version != evaluator_version:
            raise EvaluationContractError("incompatible_evaluator_contract")
        if self.feature_schema_hash != require_sha256(feature_schema_hash, "feature_schema_hash"):
            raise EvaluationContractError("feature_schema_mismatch")
        if self.feature_order_hash != require_sha256(feature_order_hash, "feature_order_hash"):
            raise EvaluationContractError("feature_order_mismatch")

    @property
    def identity_hash(self) -> str:
        return canonical_hash(self.to_dict())

    def to_dict(self) -> dict[str, str]:
        return {field: str(getattr(self, field)) for field in self.__dataclass_fields__}


@dataclass(frozen=True)
class FieldContract:
    name: str
    dtype: str
    nullable: bool = False


@dataclass(frozen=True)
class SchemaContract:
    name: str
    version: str
    fields: tuple[FieldContract, ...]
    allow_extra: bool = False

    def __post_init__(self) -> None:
        names = tuple(field.name for field in self.fields)
        if not self.name or not self.version or not names or len(set(names)) != len(names):
            raise EvaluationContractError("schema_definition_invalid")

    @property
    def fingerprint(self) -> str:
        return canonical_hash({
            "name": self.name,
            "version": self.version,
            "fields": [field.__dict__ for field in self.fields],
            "allow_extra": self.allow_extra,
        })

    @property
    def order_hash(self) -> str:
        return canonical_hash([field.name for field in self.fields])

    def validate(self, payload: Mapping[str, Any]) -> None:
        expected = {field.name for field in self.fields}
        actual = set(payload)
        missing = expected - actual
        extra = actual - expected
        if missing:
            raise EvaluationContractError(f"schema_required_fields_missing:{sorted(missing)}")
        if extra and not self.allow_extra:
            raise EvaluationContractError(f"schema_extra_fields_forbidden:{sorted(extra)}")
        types = {"float": (float,), "int": (int,), "str": (str,), "bool": (bool,)}
        for field in self.fields:
            value = payload[field.name]
            if value is None:
                if field.nullable:
                    continue
                raise EvaluationContractError(f"schema_null_required:{field.name}")
            accepted = types.get(field.dtype)
            if accepted is None or isinstance(value, bool) != (field.dtype == "bool") or not isinstance(value, accepted):
                raise EvaluationContractError(f"schema_dtype_mismatch:{field.name}:{field.dtype}")
            if field.dtype == "float" and not math.isfinite(value):
                raise EvaluationContractError(f"schema_non_finite:{field.name}")


class ReadinessState(str, Enum):
    READY = "READY"
    WARMING_UP = "WARMING_UP"
    INVALID_INPUT = "INVALID_INPUT"
    INCOMPATIBLE_ARTIFACT = "INCOMPATIBLE_ARTIFACT"


@dataclass(frozen=True)
class ReadinessDependency:
    name: str
    timeframe: str
    lookback_offset: int
    minimum_observations: int
    source: str
    required: bool = True


CANONICAL_MODEL_READINESS_DEPENDENCIES: tuple[ReadinessDependency, ...] = (
    ReadinessDependency(
        "return_8", CANONICAL_ENTRY_TIMEFRAME, 8, 9,
        "btc_scraper.analysis.core:generate_signal_score_input",
    ),
    ReadinessDependency(
        "return_32", CANONICAL_ENTRY_TIMEFRAME, 32, 33,
        "btc_scraper.analysis.core:generate_signal_score_input",
    ),
    ReadinessDependency(
        "return_72", CANONICAL_ENTRY_TIMEFRAME, 72, 73,
        "btc_scraper.analysis.core:generate_signal_score_input",
    ),
    ReadinessDependency(
        "abs_move_72", CANONICAL_ENTRY_TIMEFRAME, 72, 73,
        "btc_scraper.analysis.core:generate_signal_score_input",
    ),
)


def canonical_readiness_minimum_observations(
    dependencies: Sequence[ReadinessDependency] = CANONICAL_MODEL_READINESS_DEPENDENCIES,
) -> int:
    values = tuple(
        int(item.minimum_observations)
        for item in dependencies
        if item.required and item.timeframe == CANONICAL_ENTRY_TIMEFRAME
    )
    if not values or min(values) < 1:
        raise EvaluationContractError("readiness_dependency_invalid")
    return max(values)


@dataclass(frozen=True)
class ReadinessDiagnosis:
    status: ReadinessState
    reason_code: str
    required_observations: int
    available_observations: int
    first_valid_timestamp: str | None
    blocking_dependency: str | None
    contract_version: str = READINESS_CONTRACT_VERSION

    @property
    def ready(self) -> bool:
        return self.status is ReadinessState.READY

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "reason_code": self.reason_code,
            "required_observations": self.required_observations,
            "available_observations": self.available_observations,
            "first_valid_timestamp": self.first_valid_timestamp,
            "blocking_dependency": self.blocking_dependency,
            "contract_version": self.contract_version,
        }


@dataclass(frozen=True)
class WarmupContract:
    minimum_bars: Mapping[str, int]
    expected_interval_seconds: int | None = None
    allow_sparse: bool = False

    @property
    def required_bars(self) -> int:
        values = tuple(int(value) for value in self.minimum_bars.values())
        if not values or min(values) < 1:
            raise EvaluationContractError("warmup_dependency_invalid")
        return max(values)

    @property
    def blocking_dependency(self) -> str | None:
        required = self.required_bars
        blockers = sorted(
            str(name) for name, value in self.minimum_bars.items()
            if int(value) == required
        )
        return blockers[0] if blockers else None

    def diagnose(self, candles: Sequence[Any], evaluation_time: datetime) -> ReadinessDiagnosis:
        required = self.required_bars
        available = len(candles)
        if evaluation_time.tzinfo is None:
            return ReadinessDiagnosis(
                ReadinessState.INVALID_INPUT, "EVALUATION_TIME_NOT_UTC_AWARE",
                required, available, None, None,
            )
        if available < required:
            return ReadinessDiagnosis(
                ReadinessState.WARMING_UP, "INSUFFICIENT_CANONICAL_HISTORY",
                required, available, None, self.blocking_dependency,
            )
        prior = None
        for candle in candles:
            if not candle.closed:
                return ReadinessDiagnosis(
                    ReadinessState.INVALID_INPUT, "PARTIAL_CANDLE",
                    required, available, None, None,
                )
            if candle.close_time > evaluation_time:
                return ReadinessDiagnosis(
                    ReadinessState.INVALID_INPUT, "FUTURE_OBSERVATION",
                    required, available, None, None,
                )
            if prior is not None:
                delta = (candle.open_time - prior).total_seconds()
                if delta == 0:
                    return ReadinessDiagnosis(
                        ReadinessState.INVALID_INPUT, "DUPLICATE_OBSERVATION",
                        required, available, None, None,
                    )
                if delta < 0:
                    return ReadinessDiagnosis(
                        ReadinessState.INVALID_INPUT, "OUT_OF_ORDER_OBSERVATION",
                        required, available, None, None,
                    )
                if (
                    self.expected_interval_seconds
                    and not self.allow_sparse
                    and delta != self.expected_interval_seconds
                ):
                    return ReadinessDiagnosis(
                        ReadinessState.INVALID_INPUT, "NON_CONTIGUOUS_CANONICAL_HISTORY",
                        required, available, None, None,
                    )
            prior = candle.open_time
        first_valid = candles[required - 1].close_time.isoformat()
        return ReadinessDiagnosis(
            ReadinessState.READY, "READY",
            required, available, first_valid, None,
        )

    def evaluate(self, candles: Sequence[Any], evaluation_time: datetime) -> ReadinessState:
        return self.diagnose(candles, evaluation_time).status


def canonical_entry_readiness_contract() -> WarmupContract:
    return WarmupContract(
        {
            item.name: item.minimum_observations
            for item in CANONICAL_MODEL_READINESS_DEPENDENCIES
            if item.required and item.timeframe == CANONICAL_ENTRY_TIMEFRAME
        },
        expected_interval_seconds=CANONICAL_ENTRY_INTERVAL_SECONDS,
    )


@dataclass(frozen=True)
class EvaluationProvenance:
    evaluation_time: str
    window_hash: str
    artifact_identity_hash: str
    artifact_hash: str
    feature_schema_hash: str
    decision_contract_hash: str
    evaluator_version: str
    result_hash: str

    def __post_init__(self) -> None:
        timestamp = datetime.fromisoformat(self.evaluation_time.replace("Z", "+00:00"))
        if timestamp.tzinfo is None or timestamp.utcoffset() != timezone.utc.utcoffset(timestamp):
            raise EvaluationContractError("provenance_timestamp_not_utc")
        for field in (
            "window_hash", "artifact_identity_hash", "artifact_hash",
            "feature_schema_hash", "decision_contract_hash", "result_hash",
        ):
            object.__setattr__(self, field, require_sha256(getattr(self, field), field))
        if not self.evaluator_version:
            raise EvaluationContractError("provenance_evaluator_version_missing")

    def to_dict(self) -> dict[str, str]:
        return {field: str(getattr(self, field)) for field in self.__dataclass_fields__}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "EvaluationProvenance":
        expected = set(cls.__dataclass_fields__)
        if set(value) != expected:
            raise EvaluationContractError("provenance_schema_mismatch")
        return cls(**{key: str(value[key]) for key in expected})
