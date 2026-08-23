"""Runtime schema contracts for P6-G3 schema closure.

The helpers here validate representation boundaries only.  They do not derive
features, fill missing values, or make trading decisions.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from numbers import Real
from typing import Any, Mapping, Sequence

from .evaluation_contracts import EvaluationContractError, canonical_hash


SCHEMA_CONTRACT_VERSION = "runtime-schema/v1"
CANONICAL_CANDLE_SCHEMA_VERSION = "canonical-candle/v1"
CANONICAL_WINDOW_SCHEMA_VERSION = "canonical-window/v1"
TECHNICAL_OUTPUT_SCHEMA_VERSION = "technical-output/v1"
MODEL_FEATURE_VECTOR_SCHEMA_VERSION = "model-feature-vector/v1"
INFERENCE_RESULT_SCHEMA_VERSION = "inference-result/v1"
EVALUATION_RESULT_SCHEMA_VERSION = "evaluation-result/v1"
CANONICAL_MODEL_FEATURES = ("return_8", "return_32", "return_72", "abs_move_72")


@dataclass(frozen=True)
class SchemaField:
    name: str
    dtype: str
    required: bool = True
    nullable: bool = False
    ordered: bool = True

    def to_contract(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "dtype": self.dtype,
            "required": self.required,
            "nullable": self.nullable,
            "ordered": self.ordered,
        }


@dataclass(frozen=True)
class RuntimeSchema:
    name: str
    version: str
    fields: tuple[SchemaField, ...]
    allow_extra: bool = False
    ordered: bool = True

    def __post_init__(self) -> None:
        names = tuple(field.name for field in self.fields)
        if not self.name or not self.version or not names:
            raise EvaluationContractError("schema_definition_invalid")
        if len(set(names)) != len(names):
            raise EvaluationContractError("schema_duplicate_field")

    def to_contract(self) -> dict[str, Any]:
        fields = [field.to_contract() for field in self.fields]
        if not self.ordered:
            fields = sorted(fields, key=lambda item: item["name"])
        return {
            "contract": SCHEMA_CONTRACT_VERSION,
            "name": self.name,
            "version": self.version,
            "fields": fields,
            "allow_extra": self.allow_extra,
            "ordered": self.ordered,
        }

    @property
    def fingerprint(self) -> str:
        return canonical_hash(self.to_contract())

    @property
    def order_hash(self) -> str:
        return canonical_hash([field.name for field in self.fields])


MODEL_FEATURE_VECTOR_SCHEMA = RuntimeSchema(
    name="model_feature_vector",
    version=MODEL_FEATURE_VECTOR_SCHEMA_VERSION,
    fields=tuple(SchemaField(name, "float", required=True, nullable=False) for name in CANONICAL_MODEL_FEATURES),
    allow_extra=True,
    ordered=True,
)


CANONICAL_CANDLE_SCHEMA = RuntimeSchema(
    name="canonical_candle",
    version=CANONICAL_CANDLE_SCHEMA_VERSION,
    fields=(
        SchemaField("open_time", "utc_datetime"),
        SchemaField("close_time", "utc_datetime"),
        SchemaField("open", "float"),
        SchemaField("high", "float"),
        SchemaField("low", "float"),
        SchemaField("close", "float"),
        SchemaField("volume", "float"),
        SchemaField("closed", "bool"),
    ),
    allow_extra=False,
    ordered=True,
)


CANONICAL_WINDOW_SCHEMA = RuntimeSchema(
    name="canonical_window",
    version=CANONICAL_WINDOW_SCHEMA_VERSION,
    fields=(
        SchemaField("symbol", "str"),
        SchemaField("timeframe", "str"),
        SchemaField("candles", "canonical_candle[]"),
    ),
    allow_extra=False,
    ordered=True,
)


@dataclass(frozen=True)
class ModelFeatureVector:
    schema: RuntimeSchema
    values: tuple[float, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema.version,
            "schema_fingerprint": self.schema.fingerprint,
            "feature_order_hash": self.schema.order_hash,
            "feature_names": [field.name for field in self.schema.fields],
            "values": list(self.values),
        }

    @property
    def semantic_hash(self) -> str:
        return canonical_hash(self.to_dict())


def _canonical_float(value: Any, field_name: str) -> float:
    if value is None:
        raise EvaluationContractError(f"NULL_NOT_ALLOWED:{field_name}")
    if isinstance(value, bool):
        raise EvaluationContractError(f"DTYPE_MISMATCH:{field_name}:float")
    if not isinstance(value, Real):
        raise EvaluationContractError(f"DTYPE_MISMATCH:{field_name}:float")
    result = float(value)
    if not math.isfinite(result):
        raise EvaluationContractError(f"NON_FINITE_VALUE:{field_name}")
    return result


def build_model_feature_vector(
    feature_map: Mapping[str, Any],
    *,
    feature_names: Sequence[str] = CANONICAL_MODEL_FEATURES,
    source_map: Mapping[str, Any] | None = None,
) -> ModelFeatureVector:
    """Validate and build the ordered model feature vector.

    ``source_map`` can be supplied to prove a required feature came from the
    upstream observation rather than from a legacy default-fill path.
    """
    names = tuple(str(name) for name in feature_names)
    if names != CANONICAL_MODEL_FEATURES:
        raise EvaluationContractError("FEATURE_ORDER_MISMATCH")
    proof = source_map if source_map is not None else feature_map
    values: list[float] = []
    for name in names:
        if name not in proof:
            raise EvaluationContractError(f"MISSING_REQUIRED_FIELD:{name}")
        if name not in feature_map:
            raise EvaluationContractError(f"MISSING_REQUIRED_FIELD:{name}")
        values.append(_canonical_float(feature_map[name], name))
    return ModelFeatureVector(MODEL_FEATURE_VECTOR_SCHEMA, tuple(values))


def canonical_timestamp(value: datetime | str | int | float) -> str:
    if isinstance(value, datetime):
        resolved = value
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        numeric = float(value)
        if numeric > 10_000_000_000:
            numeric /= 1000.0
        resolved = datetime.fromtimestamp(numeric, tz=timezone.utc)
    else:
        try:
            resolved = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
        except Exception as exc:
            raise EvaluationContractError("TIMESTAMP_INVALID") from exc
    if resolved.tzinfo is None:
        raise EvaluationContractError("TIMESTAMP_NAIVE")
    return resolved.astimezone(timezone.utc).isoformat()


def classify_persisted_schema_identity(record: Mapping[str, Any]) -> str:
    required = ("feature_schema_hash", "feature_schema_version")
    if all(record.get(field) for field in required):
        return "CURRENT_SCHEMA_IDENTIFIED"
    return "LEGACY_UNVERIFIED_SCHEMA"
