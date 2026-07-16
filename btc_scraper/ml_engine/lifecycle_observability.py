"""Lifecycle ID coverage reports by producer."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping


PRODUCER_REQUIRED_IDS = {
    "prediction": ("prediction_id",),
    "entry_decision": ("prediction_id", "signal_id", "entry_decision_id"),
    "reservation": ("entry_decision_id", "reservation_id", "idempotency_key"),
    "submitted_order": ("entry_decision_id", "reservation_id", "client_order_id"),
    "fill": ("client_order_id", "fill_id", "position_id"),
    "open_position": ("prediction_id", "signal_id", "position_id"),
    "closed_outcome": ("position_id", "outcome_id", "outcome_revision"),
}


@dataclass(frozen=True)
class ProducerCoverage:
    producer: str
    total_records: int
    fully_covered_records: int
    coverage_rate: float
    required_ids: tuple[str, ...]
    missing_counts: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def producer_coverage_report(events_by_producer: Mapping[str, Iterable[Mapping[str, Any]]]) -> dict[str, Any]:
    rows = []
    for producer, required in PRODUCER_REQUIRED_IDS.items():
        events = [dict(event) for event in events_by_producer.get(producer, [])]
        rows.append(_coverage(producer, events, required))
    return {
        "status": "producer_lifecycle_coverage",
        "producers": {row.producer: row.to_dict() for row in rows},
        "all_required_coverage_rate": min((row.coverage_rate for row in rows), default=0.0),
    }


def _coverage(producer: str, events: list[Mapping[str, Any]], required: tuple[str, ...]) -> ProducerCoverage:
    missing_counts = {field: 0 for field in required}
    fully_covered = 0
    for event in events:
        missing = [field for field in required if _missing(event.get(field))]
        for field in missing:
            missing_counts[field] += 1
        if not missing:
            fully_covered += 1
    total = len(events)
    return ProducerCoverage(
        producer=producer,
        total_records=total,
        fully_covered_records=fully_covered,
        coverage_rate=0.0 if total == 0 else fully_covered / total,
        required_ids=required,
        missing_counts=missing_counts,
    )


def _missing(value: Any) -> bool:
    return value is None or value == ""
