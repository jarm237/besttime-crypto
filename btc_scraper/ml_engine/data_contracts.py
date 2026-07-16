"""Runtime event contract registry for ML outcome linkage.

The registry is intentionally small and local-first: producers can validate
append-only JSON events before writing them, and downstream linkers can reject
schema drift with stable reason codes.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping


class ContractRejectReason(str, Enum):
    UNKNOWN_EVENT_TYPE = "unknown_event_type"
    SCHEMA_VERSION_MISMATCH = "schema_version_mismatch"
    MISSING_REQUIRED_FIELD = "missing_required_field"
    EMPTY_BUSINESS_KEY = "empty_business_key"
    EMPTY_IDEMPOTENCY_SCOPE = "empty_idempotency_scope"


@dataclass(frozen=True)
class ContractValidationError:
    reason: ContractRejectReason
    message: str
    field: str | None = None


@dataclass(frozen=True)
class EventContract:
    event_type: str
    schema_version: str
    producer: str
    required_fields: tuple[str, ...]
    business_key: str
    idempotency_scope: str

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "EventContract":
        return cls(
            event_type=str(payload["event_type"]),
            schema_version=str(payload["schema_version"]),
            producer=str(payload["producer"]),
            required_fields=tuple(str(field) for field in payload["required_fields"]),
            business_key=str(payload["business_key"]),
            idempotency_scope=str(payload["idempotency_scope"]),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type,
            "schema_version": self.schema_version,
            "producer": self.producer,
            "required_fields": list(self.required_fields),
            "business_key": self.business_key,
            "idempotency_scope": self.idempotency_scope,
        }


@dataclass(frozen=True)
class ContractValidationResult:
    ok: bool
    contract: EventContract | None = None
    errors: tuple[ContractValidationError, ...] = ()

    def raise_for_errors(self) -> None:
        if self.ok:
            return
        details = "; ".join(error.message for error in self.errors)
        raise ValueError(f"event contract validation failed: {details}")


class DataContractRegistry:
    def __init__(self, contracts: Mapping[str, EventContract] | None = None, *, version: str = "runtime-contracts-v1"):
        self.version = version
        self._contracts: dict[str, EventContract] = dict(contracts or {})

    def register(self, contract: EventContract) -> None:
        self._contracts[contract.event_type] = contract

    def get(self, event_type: str) -> EventContract | None:
        return self._contracts.get(event_type)

    def validate(self, event: Mapping[str, Any]) -> ContractValidationResult:
        event_type = event.get("event_type")
        contract = self._contracts.get(str(event_type)) if event_type is not None else None
        if contract is None:
            return ContractValidationResult(
                ok=False,
                errors=(ContractValidationError(
                    ContractRejectReason.UNKNOWN_EVENT_TYPE,
                    f"unknown event_type: {event_type!r}",
                    "event_type",
                ),),
            )

        errors: list[ContractValidationError] = []
        if event.get("schema_version") != contract.schema_version:
            errors.append(ContractValidationError(
                ContractRejectReason.SCHEMA_VERSION_MISMATCH,
                f"{contract.event_type} expected schema_version {contract.schema_version!r}",
                "schema_version",
            ))

        for field in contract.required_fields:
            if _is_missing(event.get(field)):
                errors.append(ContractValidationError(
                    ContractRejectReason.MISSING_REQUIRED_FIELD,
                    f"{contract.event_type} missing required field {field!r}",
                    field,
                ))

        if _is_missing(event.get(contract.business_key)):
            errors.append(ContractValidationError(
                ContractRejectReason.EMPTY_BUSINESS_KEY,
                f"{contract.event_type} has empty business key {contract.business_key!r}",
                contract.business_key,
            ))

        for field in contract.idempotency_scope.split("+"):
            if _is_missing(event.get(field)):
                errors.append(ContractValidationError(
                    ContractRejectReason.EMPTY_IDEMPOTENCY_SCOPE,
                    f"{contract.event_type} has empty idempotency field {field!r}",
                    field,
                ))

        return ContractValidationResult(ok=not errors, contract=contract, errors=tuple(errors))

    def to_dict(self) -> dict[str, Any]:
        return {
            "registry_version": self.version,
            "contracts": {event_type: contract.to_dict() for event_type, contract in sorted(self._contracts.items())},
        }


def _is_missing(value: Any) -> bool:
    return value is None or value == ""


DEFAULT_RUNTIME_CONTRACTS = DataContractRegistry({
    "prediction_created": EventContract(
        event_type="prediction_created",
        schema_version="prediction-created-v1",
        producer="prediction_logger",
        required_fields=(
            "event_id",
            "event_time",
            "ingest_time",
            "producer",
            "prediction_id",
            "timestamp",
            "model_name",
            "model_version",
            "feature_schema_version",
            "feature_hash",
            "raw_prediction",
            "calibrated_prediction",
            "decision_context",
        ),
        business_key="prediction_id",
        idempotency_scope="prediction_id",
    ),
    "position_closed": EventContract(
        event_type="position_closed",
        schema_version="position-closed-v1",
        producer="position_tracker",
        required_fields=(
            "event_id",
            "event_time",
            "ingest_time",
            "producer",
            "position_id",
            "closed_at",
            "net_pnl_pct",
            "outcome_revision",
        ),
        business_key="position_id",
        idempotency_scope="position_id+outcome_revision",
    ),
    "entry_decision_created": EventContract(
        event_type="entry_decision_created",
        schema_version="entry-decision-created-v1",
        producer="decision_engine",
        required_fields=(
            "event_id",
            "event_time",
            "ingest_time",
            "producer",
            "entry_decision_id",
            "prediction_id",
            "signal_id",
            "final_status",
        ),
        business_key="entry_decision_id",
        idempotency_scope="entry_decision_id",
    ),
    "reservation_created": EventContract(
        event_type="reservation_created",
        schema_version="reservation-created-v1",
        producer="reservation_store",
        required_fields=(
            "event_id",
            "event_time",
            "ingest_time",
            "producer",
            "reservation_id",
            "idempotency_key",
            "entry_decision_id",
        ),
        business_key="reservation_id",
        idempotency_scope="idempotency_key",
    ),
    "order_submitted": EventContract(
        event_type="order_submitted",
        schema_version="order-submitted-v1",
        producer="execution_engine",
        required_fields=(
            "event_id",
            "event_time",
            "ingest_time",
            "producer",
            "client_order_id",
            "entry_decision_id",
            "reservation_id",
        ),
        business_key="client_order_id",
        idempotency_scope="client_order_id",
    ),
    "fill_recorded": EventContract(
        event_type="fill_recorded",
        schema_version="fill-recorded-v1",
        producer="fill_tracker",
        required_fields=(
            "event_id",
            "event_time",
            "ingest_time",
            "producer",
            "fill_id",
            "client_order_id",
            "position_id",
            "qty",
            "price",
            "fee",
        ),
        business_key="fill_id",
        idempotency_scope="fill_id",
    ),
    "calibration_sample_created": EventContract(
        event_type="calibration_sample_created",
        schema_version="calibration-sample-v1",
        producer="runtime_outcome_linker",
        required_fields=(
            "event_id",
            "event_time",
            "ingest_time",
            "producer",
            "sample_id",
            "prediction_id",
            "position_id",
            "outcome_revision",
            "model_version",
            "artifact_sha256",
            "feature_schema_version",
            "predicted_probability",
            "label",
        ),
        business_key="sample_id",
        idempotency_scope="prediction_id+position_id+outcome_revision",
    ),
})


def validate_runtime_event(event: Mapping[str, Any]) -> ContractValidationResult:
    return DEFAULT_RUNTIME_CONTRACTS.validate(event)
