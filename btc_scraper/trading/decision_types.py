"""
btc_scraper/trading/decision_types.py
Canonical decision types for the Live Entry Safety Remediation.

All enums, dataclasses, and type definitions used across signal scoring,
auto-trading, execution guard, and reservation subsystems.

Design principles:
    - Enum values are stable strings used in logs/tests/dashboard.
    - Dataclasses are frozen for thread-safety and replay integrity.
    - Fields not yet computed (due to early rejection) are None, with
      decision_stage indicating how far the pipeline progressed.
    - EntryDecision carries traceability metadata (decision_id, model_version, etc.)
      from PR 1 to avoid structural changes in later PRs.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional

from .event_risk_policy import (
    DEFAULT_EVENT_RISK_POLICY_VERSION,
    EntryPermission,
    EventRiskContractError,
    EventRiskDecision,
    EventRiskLevel,
    EventRiskPolicyReason,
    OrderIntent,
    PositionAction,
    RiskEvaluationResult,
    RiskPolicyEvaluator,
    StaleSnapshotPolicy,
    compute_snapshot_hash,
)


# ── Trade action ──────────────────────────────────────────────────────────────

class TradeAction(str, Enum):
    """Canonical trade action derived from directional score."""
    BUY = "BUY"
    SELL = "SELL"
    NEUTRAL = "NEUTRAL"


# ── Rejection / authorization reasons ─────────────────────────────────────────

class EntryRejectionReason(str, Enum):
    """Stable reason codes for signal-level rejection (eligibility)."""
    LOW_META_CONFIDENCE = "low_meta_confidence"
    INSUFFICIENT_STATISTICAL_EDGE = "insufficient_statistical_edge"
    RR_BELOW_MINIMUM = "rr_below_minimum"
    NON_POSITIVE_KELLY = "non_positive_kelly"
    ACTION_DISAGREEMENT = "action_disagreement"
    CAUSAL_REGIME_VETO = "causal_regime_veto"
    DIRECTION_ENCODING_INCONSISTENT = "direction_encoding_inconsistent"
    INVALID_SIZING_INPUT = "invalid_sizing_input"
    WEAK_SIGNAL = "weak_signal"
    COIN_NOT_ALLOWED = "coin_not_allowed"
    CIRCUIT_BREAKER = "circuit_breaker"
    CORRELATION_FILTER = "correlation_filter"
    EXISTING_POSITION = "existing_position"
    DAILY_LIMIT = "daily_limit"
    MISSING_FINAL_DECISION = "missing_final_decision"
    NON_EXECUTABLE_FINAL_DECISION = "non_executable_final_decision"
    FINAL_DECISION_LINEAGE_MISMATCH = "final_decision_lineage_mismatch"
    FINAL_DECISION_SUPERSEDED = "final_decision_superseded"
    COOLDOWN_ACTIVE = "cooldown_active"
    MAX_CONCURRENT_POSITIONS = "max_concurrent_positions"
    CAPITAL_CAPACITY_EXCEEDED = "capital_capacity_exceeded"
    NO_VIABLE_ECONOMIC_CANDIDATE = "no_viable_economic_candidate"
    RISK_MANAGER_BLOCKED = "risk_manager_blocked"
    PORTFOLIO_WEIGHT_ZERO = "portfolio_weight_zero"
    EVENT_RISK_BLOCKED = "event_risk_blocked"
    INVALID_EVENT_RISK_SNAPSHOT = "invalid_event_risk_snapshot"


class AuthorizationReason(str, Enum):
    """Stable reason codes for live-authorization rejection."""
    PHASE5_GATE_CLOSED = "phase5_gate_closed"
    LIVE_MODE_DISABLED = "live_mode_disabled"
    KILL_SWITCH = "kill_switch"
    ROLLOUT_STAGE = "rollout_stage"
    HARD_RISK_LIMITS = "hard_risk_limits"
    SYSTEM_HEALTH = "system_health"
    EXECUTION_RISK = "execution_risk"
    STALE_ACCOUNT_STATE = "stale_account_state"
    STALE_MARKET_DATA = "stale_market_data"
    STALE_MODEL_FEATURES = "stale_model_features"
    STALE_ORDERBOOK = "stale_orderbook"


# ── Status enums ──────────────────────────────────────────────────────────────

class ReservationStatus(str, Enum):
    """Lifecycle status of a pre-trade reservation."""
    PENDING = "pending"
    COMMITTED = "committed"
    PARTIALLY_COMMITTED = "partially_committed"
    RELEASED = "released"
    EXPIRED = "expired"


class FinalDecisionStatus(str, Enum):
    """Terminal status of an entry decision."""
    ELIGIBLE = "eligible"
    REJECTED = "rejected"
    AUTHORIZED = "authorized"
    SUBMITTED = "submitted"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"


class DecisionStage(str, Enum):
    """Pipeline stage at which a decision was finalized (or rejected).

    Allows downstream consumers to know which fields are meaningful:
        NORMALIZATION  — only raw score / action fields are populated
        ELIGIBILITY    — meta_probability, RR, Kelly checked
        EDGE           — EV computed
        SIZING         — position size computed
        AUTHORIZATION  — live guard evaluated
        RESERVATION    — slot reserved
        EXECUTION      — order submitted to exchange
    """
    NORMALIZATION = "normalization"
    ELIGIBILITY = "eligibility"
    EDGE = "edge"
    SIZING = "sizing"
    AUTHORIZATION = "authorization"
    RESERVATION = "reservation"
    EXECUTION = "execution"


# ── Normalized signal score ───────────────────────────────────────────────────

@dataclass(frozen=True)
class NormalizedSignalScore:
    """Result of normalizing a raw 0-100 directional score.

    Attributes:
        raw_score:          Original 0-100 score (0=strong SELL, 100=strong BUY).
        directional_score:  Signed score in [-100, +100].
        strength:           Side-agnostic signal magnitude [0, 100].
        action:             Canonical action derived from directional_score
                            and action_threshold.
    """
    raw_score: float
    directional_score: int
    strength: int
    action: TradeAction


# ── Decision breakdown ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class DecisionBreakdown:
    """Full numeric breakdown of an entry decision for replay/audit.

    Fields that are None were not computed because the decision was
    rejected at an earlier stage.  The ``decision_stage`` field indicates
    how far the pipeline progressed.
    """
    decision_stage: DecisionStage

    # Signal normalization (always present)
    technical_score: int
    directional_score: int
    signal_strength: int
    signal_action: TradeAction
    approved_action: Optional[TradeAction] = None

    # Statistical edge (None if rejected before EDGE stage)
    meta_probability: Optional[float] = None
    rr_ratio: Optional[float] = None
    gross_expected_value: Optional[float] = None
    estimated_cost: Optional[float] = None
    net_expected_value: Optional[float] = None

    # Kelly (None if rejected before EDGE stage)
    kelly_raw: Optional[float] = None
    kelly_applied: Optional[float] = None

    # Sizing (None if rejected before SIZING stage)
    risk_pct_applied: Optional[float] = None
    risk_notional: Optional[float] = None
    size_before_caps: Optional[float] = None
    var_cap: Optional[float] = None
    exposure_cap: Optional[float] = None
    max_trade_cap: Optional[float] = None
    min_notional: Optional[float] = None
    final_notional: Optional[float] = None

    # Risk & Portfolio governance (P0-A & P0-B)
    risk_multiplier: Optional[float] = None
    risk_status: Optional[str] = None
    risk_blocked: Optional[bool] = None
    portfolio_weight: Optional[float] = None
    portfolio_cap: Optional[float] = None
    event_risk: Optional[EventRiskDecision] = None
    event_risk_result: Optional[RiskEvaluationResult] = None

    # Rejection
    rejection_reason: Optional[EntryRejectionReason] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for JSON logging.  Enum values become their string value."""
        d: Dict[str, Any] = {}
        d["decision_stage"] = self.decision_stage.value
        d["technical_score"] = self.technical_score
        d["directional_score"] = self.directional_score
        d["signal_strength"] = self.signal_strength
        d["signal_action"] = self.signal_action.value
        d["approved_action"] = self.approved_action.value if self.approved_action else None
        d["meta_probability"] = self.meta_probability
        d["rr_ratio"] = self.rr_ratio
        d["gross_expected_value"] = self.gross_expected_value
        d["estimated_cost"] = self.estimated_cost
        d["net_expected_value"] = self.net_expected_value
        d["kelly_raw"] = self.kelly_raw
        d["kelly_applied"] = self.kelly_applied
        d["risk_pct_applied"] = self.risk_pct_applied
        d["risk_notional"] = self.risk_notional
        d["size_before_caps"] = self.size_before_caps
        d["var_cap"] = self.var_cap
        d["exposure_cap"] = self.exposure_cap
        d["max_trade_cap"] = self.max_trade_cap
        d["min_notional"] = self.min_notional
        d["final_notional"] = self.final_notional
        d["risk_multiplier"] = self.risk_multiplier
        d["risk_status"] = self.risk_status
        d["risk_blocked"] = self.risk_blocked
        d["portfolio_weight"] = self.portfolio_weight
        d["portfolio_cap"] = self.portfolio_cap
        d["event_risk"] = self.event_risk.to_dict() if self.event_risk else None
        d["event_risk_result"] = self.event_risk_result.to_dict() if self.event_risk_result else None
        d["rejection_reason"] = self.rejection_reason.value if self.rejection_reason else None
        return d


# ── Sizing decision ───────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SizingDecision:
    """Detailed result of position sizing computation.

    Replaces the previous ``compute_position_size() -> float`` return
    to ensure dangerous fallbacks (e.g. defaulting to min_notional when
    SL is missing) are explicitly rejected rather than silently swallowed.
    """
    entry_price: float
    sl_price: float
    stop_distance_pct: float
    risk_pct: float
    risk_notional: float
    raw_notional: float
    kelly_adjusted: Optional[float] = None
    var_capped: Optional[float] = None
    exposure_capped: Optional[float] = None
    max_trade_capped: Optional[float] = None
    risk_adjusted_notional: Optional[float] = None
    final_notional: float = 0.0
    rejected: bool = False
    rejection_reason: Optional[EntryRejectionReason] = None
    portfolio_weight: Optional[float] = None
    portfolio_capped: Optional[float] = None
    risk_multiplier: float = 1.0

    @property
    def kelly_fraction(self) -> Optional[float]:
        """Kelly recommendation; never the authoritative final exposure."""
        if self.raw_notional <= 0 or self.kelly_adjusted is None:
            return None
        return max(0.0, min(1.0, self.kelly_adjusted / self.raw_notional))

    @property
    def raw_position_size(self) -> float:
        return max(0.0, float(self.raw_notional))

    @property
    def risk_adjusted_size(self) -> float:
        value = (
            self.risk_adjusted_notional
            if self.risk_adjusted_notional is not None
            else self.final_notional
        )
        return max(0.0, float(value))

    @property
    def final_position_size(self) -> float:
        return 0.0 if self.rejected else max(0.0, float(self.final_notional))

    @property
    def gated(self) -> bool:
        return bool(self.rejected)

    @property
    def governing_constraint(self) -> str:
        if self.rejected:
            if self.rejection_reason == EntryRejectionReason.CAPITAL_CAPACITY_EXCEEDED:
                return "min_trade_cap"
            if self.rejection_reason == EntryRejectionReason.PORTFOLIO_WEIGHT_ZERO:
                return "portfolio_weight_zero"
            if self.rejection_reason == EntryRejectionReason.RISK_MANAGER_BLOCKED:
                return "risk_manager_blocked"
            if self.rejection_reason == EntryRejectionReason.NON_POSITIVE_KELLY:
                return "non_positive_kelly"
            return "rejected"
        if self.max_trade_capped is not None and abs(self.final_notional - self.max_trade_capped) < 1e-4:
            return "max_trade_cap"
        if self.exposure_capped is not None and abs(self.final_notional - self.exposure_capped) < 1e-4:
            return "exposure_cap"
        if self.var_capped is not None and abs(self.final_notional - self.var_capped) < 1e-4:
            return "var_cap"
        if self.portfolio_capped is not None and abs(self.final_notional - self.portfolio_capped) < 1e-4:
            return "portfolio_allocation_cap"
        if self.kelly_adjusted is not None and abs(self.final_notional - self.kelly_adjusted) < 1e-4:
            return "kelly_cap"
        return "raw_risk_sizing"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entry_price": self.entry_price,
            "sl_price": self.sl_price,
            "stop_distance_pct": self.stop_distance_pct,
            "risk_pct": self.risk_pct,
            "risk_notional": self.risk_notional,
            "raw_notional": self.raw_notional,
            "kelly_adjusted": self.kelly_adjusted,
            "portfolio_weight": self.portfolio_weight,
            "portfolio_capped": self.portfolio_capped,
            "var_capped": self.var_capped,
            "exposure_capped": self.exposure_capped,
            "max_trade_capped": self.max_trade_capped,
            "risk_adjusted_notional": self.risk_adjusted_notional,
            "final_notional": self.final_notional,
            "kelly_fraction": self.kelly_fraction,
            "raw_position_size": self.raw_position_size,
            "risk_adjusted_size": self.risk_adjusted_size,
            "final_position_size": self.final_position_size,
            "risk_multiplier": self.risk_multiplier,
            "gated": self.gated,
            "sizing_contract_version": "risk-sizing/v1",
            "rejected": self.rejected,
            "rejection_reason": self.rejection_reason.value if self.rejection_reason else None,
            "governing_constraint": self.governing_constraint,
        }


# ── Risk & Portfolio Adapter Types (P0-A) ────────────────────────────────────

@dataclass(frozen=True)
class RiskPortfolioItem:
    """Canonical adapter between Multi-Agent context and AutoTrader entry decision pipeline."""
    coin: str
    action: str = "NEUTRAL"
    approved_action: str = "NEUTRAL"
    risk_blocked: bool = False
    risk_status: str = "OK"
    risk_failure_reason: Optional[str] = None
    risk_multiplier: float = 1.0
    portfolio_weight: Optional[float] = None
    kelly_fraction: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "coin": self.coin,
            "action": self.action,
            "approved_action": self.approved_action,
            "risk_blocked": self.risk_blocked,
            "risk_status": self.risk_status,
            "risk_failure_reason": self.risk_failure_reason,
            "risk_multiplier": self.risk_multiplier,
            "portfolio_weight": self.portfolio_weight,
            "kelly_fraction": self.kelly_fraction,
        }


def build_risk_portfolio_map(
    signals_info: Optional[Any] = None,
    risk_metrics: Optional[Dict[str, Any]] = None,
) -> Dict[str, RiskPortfolioItem]:
    """Map multi-agent signals_info and risk_metrics to structured per-coin governance objects."""
    res: Dict[str, RiskPortfolioItem] = {}
    is_globally_blocked = bool(risk_metrics and risk_metrics.get("blocked", False))
    global_status = str(risk_metrics.get("status", "UNAVAILABLE") if risk_metrics else "OK")
    global_failure = str(risk_metrics.get("failure_reason") or "") if is_globally_blocked else None
    global_mult = float(risk_metrics.get("risk_multiplier", 1.0) if risk_metrics else 1.0)

    if signals_info:
        # Handle dict or list form
        iterable = signals_info.values() if isinstance(signals_info, dict) else signals_info
        for s in iterable:
            if not isinstance(s, dict):
                continue
            coin = str(s.get("coin", "")).upper()
            if not coin:
                continue
            raw_act = str(s.get("action", "NEUTRAL")).upper()
            if is_globally_blocked:
                act = raw_act
                approved = "NEUTRAL"
                status = global_status
                failure = global_failure
                mult = 0.0
                blocked = True
            else:
                blocked = bool(s.get("risk_blocked", False))
                status = str(s.get("risk_status") or "OK")
                failure = s.get("risk_failure_reason")
                raw_approved = s.get("approved_action")
                if blocked:
                    approved = "NEUTRAL"
                elif raw_approved is not None:
                    approved = str(raw_approved).upper()
                else:
                    approved = raw_act

                # approved_action can only be the unchanged raw action or NEUTRAL to block
                # Never allow flipping BUY to SELL or SELL to BUY
                if approved not in ("NEUTRAL", raw_act):
                    approved = "NEUTRAL"
                    blocked = True

                mult = float(s.get("risk_multiplier", global_mult)) if not blocked else 0.0
                act = raw_act

            pw = s.get("portfolio_weight")
            kf = s.get("kelly_fraction")

            res[coin] = RiskPortfolioItem(
                coin=coin,
                action=act,
                approved_action=approved,
                risk_blocked=blocked,
                risk_status=status,
                risk_failure_reason=failure,
                risk_multiplier=mult,
                portfolio_weight=float(pw) if pw is not None else None,
                kelly_fraction=float(kf) if kf is not None else None,
            )
    return res


# ── Entry decision ────────────────────────────────────────────────────────────

def _generate_decision_id() -> str:
    """Generate a unique decision ID for traceability."""
    return f"ed-{uuid.uuid4().hex[:12]}"


@dataclass(frozen=True)
class EntryDecision:
    """Canonical result of the entry decision pipeline.

    This is the single source of truth for whether a trade should be entered.
    ``should_trade()`` is a backward-compatible wrapper around this.

    Traceability fields (decision_id, model_version, etc.) are included
    from PR 1 to avoid schema changes in later PRs.
    """
    # Core decision
    eligible: bool
    action: TradeAction
    rejection_reason: Optional[EntryRejectionReason]
    final_status: FinalDecisionStatus
    breakdown: Optional[DecisionBreakdown]
    sizing: Optional[SizingDecision]
    event_risk: Optional[EventRiskDecision] = None
    event_risk_result: Optional[RiskEvaluationResult] = None

    # Eligibility vs authorization separation
    signal_eligible: bool = True
    live_authorized: bool = False
    eligibility_reason: Optional[EntryRejectionReason] = None
    authorization_reason: Optional[AuthorizationReason] = None

    # Traceability metadata
    decision_id: str = field(default_factory=_generate_decision_id)
    signal_id: Optional[str] = None
    prediction_id: Optional[str] = None
    model_version: Optional[str] = None
    artifact_hash: Optional[str] = None
    feature_schema_version: Optional[str] = None
    deployment_id: Optional[str] = None
    paper_run_id: Optional[str] = None
    cycle_id: Optional[str] = None
    decision_sha256: Optional[str] = None
    decision_context: Optional[str] = None
    caller_context: Optional[str] = None
    decision_timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    # Meta probability semantics annotation
    meta_probability_semantics: str = "P(win_given_proposed_trade)"

    @property
    def gated(self) -> bool:
        risk_reasons = {
            EntryRejectionReason.CIRCUIT_BREAKER,
            EntryRejectionReason.CORRELATION_FILTER,
            EntryRejectionReason.DAILY_LIMIT,
            EntryRejectionReason.RISK_MANAGER_BLOCKED,
            EntryRejectionReason.PORTFOLIO_WEIGHT_ZERO,
            EntryRejectionReason.EVENT_RISK_BLOCKED,
            EntryRejectionReason.INVALID_EVENT_RISK_SNAPSHOT,
        }
        return bool(
            (self.sizing and self.sizing.rejected)
            or self.rejection_reason in risk_reasons
        )

    @property
    def final_position_size(self) -> float:
        if not self.eligible or self.action not in {TradeAction.BUY, TradeAction.SELL}:
            return 0.0
        return self.sizing.final_position_size if self.sizing is not None else 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for JSON logging."""
        return {
            "eligible": self.eligible,
            "action": self.action.value,
            "rejection_reason": self.rejection_reason.value if self.rejection_reason else None,
            "final_status": self.final_status.value,
            "breakdown": self.breakdown.to_dict() if self.breakdown else None,
            "sizing": self.sizing.to_dict() if self.sizing else None,
            "event_risk": self.event_risk.to_dict() if self.event_risk else None,
            "event_risk_result": self.event_risk_result.to_dict() if self.event_risk_result else None,
            "signal_eligible": self.signal_eligible,
            "live_authorized": self.live_authorized,
            "eligibility_reason": self.eligibility_reason.value if self.eligibility_reason else None,
            "authorization_reason": self.authorization_reason.value if self.authorization_reason else None,
            "decision_id": self.decision_id,
            "signal_id": self.signal_id,
            "prediction_id": self.prediction_id,
            "model_version": self.model_version,
            "artifact_hash": self.artifact_hash,
            "model_artifact_sha256": self.artifact_hash,
            "feature_schema_version": self.feature_schema_version,
            "deployment_id": self.deployment_id,
            "paper_run_id": self.paper_run_id,
            "cycle_id": self.cycle_id,
            "decision_sha256": self.decision_sha256,
            "decision_context": self.decision_context,
            "caller_context": self.caller_context,
            "decision_timestamp": self.decision_timestamp,
            "meta_probability_semantics": self.meta_probability_semantics,
            "gated": self.gated,
            "final_position_size": self.final_position_size,
            "position_size": self.final_position_size,
            "sizing_contract_version": "risk-sizing/v1",
        }
