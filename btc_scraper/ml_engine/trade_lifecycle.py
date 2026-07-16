"""Canonical lifecycle IDs for runtime outcome linkage."""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Mapping


LIFECYCLE_SCHEMA_VERSION = "trade-lifecycle-v1"


@dataclass(frozen=True)
class TradeLifecycleContext:
    prediction_id: str | None = None
    signal_id: str | None = None
    entry_decision_id: str | None = None
    reservation_id: str | None = None
    idempotency_key: str | None = None
    client_order_id: str | None = None
    exchange_order_id: str | None = None
    fill_id: str | None = None
    position_id: str | None = None
    outcome_id: str | None = None
    schema_version: str = LIFECYCLE_SCHEMA_VERSION

    @classmethod
    def new(
        cls,
        *,
        prediction_id: str | None = None,
        signal_id: str | None = None,
        entry_decision_id: str | None = None,
        position_id: str | None = None,
    ) -> "TradeLifecycleContext":
        return cls(
            prediction_id=prediction_id or _prefixed_id("pred"),
            signal_id=signal_id or _prefixed_id("sig"),
            entry_decision_id=entry_decision_id or _prefixed_id("ed"),
            position_id=position_id,
        )

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "TradeLifecycleContext":
        data = {field: payload.get(field) for field in cls.__dataclass_fields__}
        data["schema_version"] = payload.get("lifecycle_schema_version") or payload.get("schema_version") or LIFECYCLE_SCHEMA_VERSION
        return cls(**data)

    def with_updates(self, **updates: Any) -> "TradeLifecycleContext":
        data = self.to_dict()
        data.update(updates)
        return TradeLifecycleContext(**{field: data.get(field) for field in self.__dataclass_fields__})

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def metadata(self) -> dict[str, Any]:
        data = self.to_dict()
        data["lifecycle_schema_version"] = data.pop("schema_version")
        data["lifecycle_hash"] = lifecycle_hash(self)
        return data

    def require(self, *fields: str) -> None:
        missing = [field for field in fields if not getattr(self, field, None)]
        if missing:
            raise ValueError(f"missing lifecycle ids: {', '.join(missing)}")
        if self.schema_version != LIFECYCLE_SCHEMA_VERSION:
            raise ValueError(f"unsupported lifecycle schema: {self.schema_version}")


def lifecycle_hash(context: TradeLifecycleContext) -> str:
    payload = json.dumps(context.to_dict(), sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def make_event_metadata(*, event_type: str, schema_version: str, producer: str, event_time: str | None = None) -> dict[str, str]:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "event_type": event_type,
        "schema_version": schema_version,
        "event_id": str(uuid.uuid4()),
        "event_time": event_time or now,
        "ingest_time": now,
        "producer": producer,
    }


def _prefixed_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"
