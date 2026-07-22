"""Shared domain contract for the Alternative.me Fear & Greed index."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional


@dataclass(frozen=True)
class FearGreedObservation:
    raw_value: int
    normalized_score: float
    classification: str
    observed_at: datetime
    source: str = "alternative.me"

    @property
    def observation_date(self) -> str:
        return self.observed_at.astimezone(timezone.utc).date().isoformat()


def normalize_fear_greed(raw_value: int | float) -> float:
    """Normalize a raw 0..100 index value to the canonical -1..1 range."""
    raw = float(raw_value)
    if not 0.0 <= raw <= 100.0:
        raise ValueError("Fear & Greed value must be in [0, 100]")
    return (raw - 50.0) / 50.0


def first_not_none(*values: Any) -> Any:
    """Return the first present value while preserving valid numeric zeroes."""
    return next((value for value in values if value is not None), None)


def resolve_fear_greed_value(*values: Any, default: Optional[float] = 50.0) -> Optional[float]:
    value = first_not_none(*values)
    if value is None:
        return default
    return float(value)


def parse_fear_greed_record(record: dict[str, Any]) -> FearGreedObservation:
    raw = int(record["value"])
    timestamp = int(record["timestamp"])
    return FearGreedObservation(
        raw_value=raw,
        normalized_score=normalize_fear_greed(raw),
        classification=str(record.get("value_classification") or "Unknown"),
        observed_at=datetime.fromtimestamp(timestamp, tz=timezone.utc),
    )
