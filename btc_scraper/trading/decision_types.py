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
    final_notional: float = 0.0
    rejected: bool = False
    rejection_reason: Optional[EntryRejectionReason] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entry_price": self.entry_price,
            "sl_price": self.sl_price,
            "stop_distance_pct": self.stop_distance_pct,
            "risk_pct": self.risk_pct,
            "risk_notional": self.risk_notional,
            "raw_notional": self.raw_notional,
            "kelly_adjusted": self.kelly_adjusted,
            "var_capped": self.var_capped,
            "exposure_capped": self.exposure_capped,
            "max_trade_capped": self.max_trade_capped,
            "final_notional": self.final_notional,
            "rejected": self.rejected,
            "rejection_reason": self.rejection_reason.value if self.rejection_reason else None,
        }


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

    # Eligibility vs authorization separation
    signal_eligible: bool = True
    live_authorized: bool = False
    eligibility_reason: Optional[EntryRejectionReason] = None
    authorization_reason: Optional[AuthorizationReason] = None

    # Traceability metadata
    decision_id: str = field(default_factory=_generate_decision_id)
    signal_id: Optional[str] = None
    model_version: Optional[str] = None
    artifact_hash: Optional[str] = None
    feature_schema_version: Optional[str] = None
    decision_timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    # Meta probability semantics annotation
    meta_probability_semantics: str = "P(win_given_proposed_trade)"

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for JSON logging."""
        return {
            "eligible": self.eligible,
            "action": self.action.value,
            "rejection_reason": self.rejection_reason.value if self.rejection_reason else None,
            "final_status": self.final_status.value,
            "breakdown": self.breakdown.to_dict() if self.breakdown else None,
            "sizing": self.sizing.to_dict() if self.sizing else None,
            "signal_eligible": self.signal_eligible,
            "live_authorized": self.live_authorized,
            "eligibility_reason": self.eligibility_reason.value if self.eligibility_reason else None,
            "authorization_reason": self.authorization_reason.value if self.authorization_reason else None,
            "decision_id": self.decision_id,
            "signal_id": self.signal_id,
            "model_version": self.model_version,
            "artifact_hash": self.artifact_hash,
            "feature_schema_version": self.feature_schema_version,
            "decision_timestamp": self.decision_timestamp,
            "meta_probability_semantics": self.meta_probability_semantics,
        }
