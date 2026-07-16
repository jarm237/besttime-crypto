"""Operational health gates for runtime linkage and calibration."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping


@dataclass(frozen=True)
class RuntimeHealthDecision:
    state: str
    reasons: tuple[str, ...] = ()
    actions: tuple[str, ...] = ()
    metrics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_runtime_health(
    *,
    linkage: Mapping[str, Any],
    producer_coverage: Mapping[str, Any] | None = None,
    calibration: Mapping[str, Any] | None = None,
    now: datetime | None = None,
    linkage_floor: float = 0.90,
    producer_coverage_floor: float = 0.99,
    calibration_stale_hours: int = 24,
) -> RuntimeHealthDecision:
    """Return operational state and safety actions without stopping scoring."""
    current = now or datetime.now(timezone.utc)
    reasons: list[str] = []
    actions = {"freeze_promotion", "keep_sizing_clamp"}

    critical_orphans = len(linkage.get("critical_orphans") or [])
    duplicate_outcomes = int(linkage.get("duplicate_outcome_count") or 0)
    mixed_artifact_schema = int(linkage.get("mixed_artifact_schema_count") or 0)
    link_rate = float(
        linkage.get("closed_trade_prediction_to_outcome_rate")
        if linkage.get("closed_trade_prediction_to_outcome_rate") is not None
        else linkage.get("prediction_to_outcome_link_rate") or 0.0
    )

    if critical_orphans > 0:
        reasons.append("critical_orphan_gt_0")
    if duplicate_outcomes > 0:
        reasons.append("duplicate_outcome_gt_0")
        actions.add("freeze_calibration")
    if mixed_artifact_schema > 0:
        reasons.append("mixed_artifact_schema_gt_0")
        actions.add("quarantine_samples")
    if link_rate < linkage_floor:
        reasons.append("linkage_below_floor")
        actions.add("mark_calibration_degraded")

    coverage_rate = None
    if producer_coverage:
        coverage_rate = producer_coverage.get("all_required_coverage_rate")
        if coverage_rate is not None and float(coverage_rate) < producer_coverage_floor:
            reasons.append("producer_coverage_below_floor")

    if calibration:
        generated_at = _parse_dt(str(calibration.get("generated_at") or ""))
        if generated_at is None or generated_at < current - timedelta(hours=calibration_stale_hours):
            reasons.append("calibration_report_stale")
            actions.add("mark_calibration_stale")

    state = "HEALTHY" if not reasons else "DEGRADED_LINKAGE"
    if duplicate_outcomes or mixed_artifact_schema:
        state = "SCHEMA_MISMATCH"
    elif "calibration_report_stale" in reasons:
        state = "CALIBRATION_STALE"
    elif link_rate < linkage_floor:
        state = "DEGRADED_LINKAGE"

    if not reasons:
        actions = set()

    return RuntimeHealthDecision(
        state=state,
        reasons=tuple(reasons),
        actions=tuple(sorted(actions)),
        metrics={
            "closed_trade_prediction_to_outcome_rate": link_rate,
            "critical_orphan_count": critical_orphans,
            "duplicate_outcome_count": duplicate_outcomes,
            "mixed_artifact_schema_count": mixed_artifact_schema,
            "producer_coverage_rate": coverage_rate,
        },
    )


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
