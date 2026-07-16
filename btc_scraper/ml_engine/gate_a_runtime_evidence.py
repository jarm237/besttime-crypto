"""Gate A runtime evidence builder for paper producer rollout."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from .lifecycle_observability import PRODUCER_REQUIRED_IDS, producer_coverage_report
from .runtime_outcome_linker import link_runtime_outcomes
from .shadow_evidence_window import GateSnapshot


@dataclass(frozen=True)
class GateAEvidenceResult:
    ready: bool
    blockers: tuple[str, ...]
    report: dict[str, Any]
    gate_snapshot: GateSnapshot | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "blockers": list(self.blockers),
            "report": self.report,
            "gate_snapshot": self.gate_snapshot.metrics_snapshot() if self.gate_snapshot else None,
            "gate_snapshot_hash": self.gate_snapshot.snapshot_hash() if self.gate_snapshot else None,
        }


def evaluate_gate_a_runtime_evidence(
    *,
    events_by_producer: Mapping[str, Iterable[Mapping[str, Any]]],
    predictions: Iterable[Mapping[str, Any]],
    outcomes: Iterable[Mapping[str, Any]],
    lifecycle_e2e_passed: bool,
    recovery_tests_passed: bool,
    evaluated_at: datetime | None = None,
    min_closed_positions: int = 20,
    producer_coverage_floor: float = 0.99,
    closed_outcome_coverage_floor: float = 0.98,
) -> GateAEvidenceResult:
    current = evaluated_at or datetime.now(timezone.utc)
    filtered_events = {
        producer: [_normalize_record(row) for row in rows if _is_paper_runtime_record(row)]
        for producer, rows in events_by_producer.items()
    }
    for producer in PRODUCER_REQUIRED_IDS:
        filtered_events.setdefault(producer, [])

    filtered_predictions = [_normalize_record(row) for row in predictions if _is_paper_runtime_record(row)]
    filtered_outcomes = [_normalize_record(row) for row in outcomes if _is_paper_runtime_record(row)]
    coverage = producer_coverage_report(filtered_events)
    linkage = link_runtime_outcomes(filtered_predictions, filtered_outcomes)
    linkage_payload = linkage.to_dict()
    producer_rates = {
        name: float(payload["coverage_rate"])
        for name, payload in coverage["producers"].items()
    }
    closed_outcome_coverage = producer_rates.get("closed_outcome", 0.0)
    duplicate_outcomes = int(linkage_payload.get("duplicate_outcome_count") or 0)
    mixed_artifact_schema_samples = int(linkage_payload.get("mixed_artifact_schema_count") or 0)
    unresolved_critical_orphans = len(linkage_payload.get("critical_orphans") or [])
    closed_position_count = len(filtered_events.get("closed_outcome") or [])

    blockers = _blockers(
        producer_rates=producer_rates,
        closed_outcome_coverage=closed_outcome_coverage,
        duplicate_outcomes=duplicate_outcomes,
        mixed_artifact_schema_samples=mixed_artifact_schema_samples,
        unresolved_critical_orphans=unresolved_critical_orphans,
        lifecycle_e2e_passed=lifecycle_e2e_passed,
        recovery_tests_passed=recovery_tests_passed,
        closed_position_count=closed_position_count,
        min_closed_positions=min_closed_positions,
        producer_coverage_floor=producer_coverage_floor,
        closed_outcome_coverage_floor=closed_outcome_coverage_floor,
    )

    report = {
        "status": "gate_a_runtime_evidence",
        "evaluated_at": current.isoformat(),
        "runtime_scope": "paper_only",
        "legacy_records_excluded": True,
        "minimum_closed_positions": min_closed_positions,
        "closed_position_count": closed_position_count,
        "producer_coverage": producer_rates,
        "prediction_coverage": producer_rates.get("prediction", 0.0),
        "entry_decision_coverage": producer_rates.get("entry_decision", 0.0),
        "reservation_coverage": producer_rates.get("reservation", 0.0),
        "submitted_order_coverage": producer_rates.get("submitted_order", 0.0),
        "fill_coverage": producer_rates.get("fill", 0.0),
        "open_position_coverage": producer_rates.get("open_position", 0.0),
        "closed_outcome_coverage": closed_outcome_coverage,
        "duplicate_outcomes": duplicate_outcomes,
        "mixed_artifact_schema_samples": mixed_artifact_schema_samples,
        "unresolved_critical_orphans": unresolved_critical_orphans,
        "closed_trade_prediction_to_outcome_rate": linkage_payload.get("closed_trade_prediction_to_outcome_rate"),
        "lifecycle_e2e_passed": lifecycle_e2e_passed,
        "recovery_tests_passed": recovery_tests_passed,
        "producer_coverage_detail": coverage,
        "linkage": linkage_payload,
        "blockers": blockers,
        "gate_a_ready": not blockers,
    }
    snapshot = None
    if not blockers:
        snapshot = GateSnapshot(
            producer_coverage=producer_rates,
            closed_outcome_coverage=closed_outcome_coverage,
            duplicate_outcomes=duplicate_outcomes,
            mixed_artifact_schema_samples=mixed_artifact_schema_samples,
            unresolved_critical_orphans=unresolved_critical_orphans,
            lifecycle_e2e_passed=lifecycle_e2e_passed,
            recovery_tests_passed=recovery_tests_passed,
            evaluated_at=current,
            closed_trade_prediction_to_outcome_rate=float(linkage_payload.get("closed_trade_prediction_to_outcome_rate") or 0.0),
        )
    return GateAEvidenceResult(not blockers, tuple(blockers), report, snapshot)


def write_gate_a_runtime_evidence(result: GateAEvidenceResult, output_dir: str | Path = "logs/runtime_linkage") -> Path:
    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    evaluated_at = _parse_dt(str(result.report.get("evaluated_at") or "")) or datetime.now(timezone.utc)
    path = target_dir / f"gate_a_runtime_evidence_{evaluated_at.strftime('%Y-%m-%dT%H%M%SZ')}.json"
    path.write_text(json.dumps(result.to_dict(), indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return path


def _blockers(
    *,
    producer_rates: Mapping[str, float],
    closed_outcome_coverage: float,
    duplicate_outcomes: int,
    mixed_artifact_schema_samples: int,
    unresolved_critical_orphans: int,
    lifecycle_e2e_passed: bool,
    recovery_tests_passed: bool,
    closed_position_count: int,
    min_closed_positions: int,
    producer_coverage_floor: float,
    closed_outcome_coverage_floor: float,
) -> list[str]:
    blockers: list[str] = []
    if min(producer_rates.values(), default=0.0) < producer_coverage_floor:
        blockers.append("producer_coverage_below_gate_a")
    if closed_outcome_coverage < closed_outcome_coverage_floor:
        blockers.append("closed_outcome_coverage_below_gate_a")
    if duplicate_outcomes > 0:
        blockers.append("duplicate_outcome")
    if mixed_artifact_schema_samples > 0:
        blockers.append("mixed_artifact_schema")
    if unresolved_critical_orphans > 0:
        blockers.append("critical_orphan_unresolved")
    if not lifecycle_e2e_passed:
        blockers.append("lifecycle_e2e_not_passed")
    if not recovery_tests_passed:
        blockers.append("recovery_tests_not_passed")
    if closed_position_count < min_closed_positions:
        blockers.append("insufficient_closed_paper_positions")
    return blockers


def _is_paper_runtime_record(row: Mapping[str, Any]) -> bool:
    source_fields = (
        row.get("execution_mode"),
        row.get("fill_source"),
        row.get("source"),
        row.get("trade_origin"),
    )
    text = " ".join(str(value).lower() for value in source_fields if value is not None)
    if any(token in text for token in ("legacy", "offline_only", "synthetic", "debug", "replay", "test")):
        return False
    return "paper" in text or not text


def _normalize_record(row: Mapping[str, Any]) -> dict[str, Any]:
    data = dict(row)
    if "position_id" not in data and data.get("id"):
        data["position_id"] = data["id"]
    return data


def _parse_dt(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except ValueError:
        return None
