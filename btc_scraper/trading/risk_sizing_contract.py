"""Canonical risk-gate and position-sizing exposure contracts."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any


RISK_SIZING_CONTRACT_VERSION = "risk-sizing/v1"
NON_ACTIONABLE_ACTIONS = frozenset({"NEUTRAL", "BLOCKED", "BLOCK_ENTRY", "IGNORE", "HOLD"})


@dataclass(frozen=True)
class RiskGateResult:
    eligible: bool
    gated: bool
    reason: str | None
    risk_multiplier: float


@dataclass(frozen=True)
class SizingAdjustment:
    reason: str
    value_before: float
    value_after: float


@dataclass(frozen=True)
class PositionSizingResult:
    kelly_fraction: float | None
    raw_position_size: float
    risk_adjusted_size: float
    final_position_size: float
    gated: bool
    gate_reason: str | None
    sizing_method: str
    minimum_cap_applied: bool
    maximum_cap_applied: bool
    zeroed_by_gate: bool
    adjustments: tuple[SizingAdjustment, ...]
    sizing_contract_version: str = RISK_SIZING_CONTRACT_VERSION

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["adjustments"] = [asdict(item) for item in self.adjustments]
        return result


def _finite_non_negative(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number if math.isfinite(number) and number > 0.0 else 0.0


def evaluate_risk_gate(
    *,
    action: str,
    risk_approved: bool,
    risk_multiplier: float = 1.0,
    reason: str | None = None,
) -> RiskGateResult:
    normalized_action = str(action or "NEUTRAL").upper()
    actionable = normalized_action in {"BUY", "SELL"}
    multiplier = _finite_non_negative(risk_multiplier)
    if not actionable:
        return RiskGateResult(False, False, "non_actionable", 0.0)
    if not risk_approved or multiplier <= 0.0:
        return RiskGateResult(False, True, reason or "risk_rejected", 0.0)
    return RiskGateResult(True, False, None, multiplier)


def finalize_position_size(
    *,
    action: str,
    risk_result: RiskGateResult,
    raw_position_size: float,
    kelly_fraction: float | None = None,
    minimum_size: float = 0.0,
    maximum_size: float | None = None,
    sizing_method: str = "unspecified",
) -> PositionSizingResult:
    """Produce the sole authoritative exposure while preserving a true zero."""
    raw = _finite_non_negative(raw_position_size)
    adjustments: list[SizingAdjustment] = []
    risk_adjusted = raw * risk_result.risk_multiplier if risk_result.eligible else 0.0
    if risk_adjusted != raw:
        adjustments.append(SizingAdjustment("RISK_MULTIPLIER", raw, risk_adjusted))

    normalized_action = str(action or "NEUTRAL").upper()
    zeroed = normalized_action in NON_ACTIONABLE_ACTIONS or not risk_result.eligible
    final = 0.0 if zeroed else risk_adjusted
    if zeroed and final != risk_adjusted:
        adjustments.append(SizingAdjustment(risk_result.reason or "NON_ACTIONABLE", risk_adjusted, 0.0))

    minimum = _finite_non_negative(minimum_size)
    minimum_applied = False
    if final > 0.0 and final < minimum:
        adjustments.append(SizingAdjustment("POSITIVE_MINIMUM_FLOOR", final, minimum))
        final = minimum
        minimum_applied = True

    maximum_applied = False
    maximum = _finite_non_negative(maximum_size) if maximum_size is not None else None
    if maximum is not None and final > maximum:
        adjustments.append(SizingAdjustment("MAXIMUM_CAP", final, maximum))
        final = maximum
        maximum_applied = True

    try:
        normalized_kelly = float(kelly_fraction) if kelly_fraction is not None else None
        if normalized_kelly is not None and not math.isfinite(normalized_kelly):
            normalized_kelly = None
    except (TypeError, ValueError):
        normalized_kelly = None

    return PositionSizingResult(
        kelly_fraction=normalized_kelly,
        raw_position_size=raw,
        risk_adjusted_size=risk_adjusted,
        final_position_size=final,
        gated=risk_result.gated,
        gate_reason=risk_result.reason,
        sizing_method=str(sizing_method),
        minimum_cap_applied=minimum_applied,
        maximum_cap_applied=maximum_applied,
        zeroed_by_gate=zeroed,
        adjustments=tuple(adjustments),
    )
