"""
btc_scraper/trading/event_risk_policy.py
Canonical Event Risk Policy Contract (P0-B).

Defines deterministic, pure policy evaluation for shared event-driven risk.
Separates semantic concerns:
    - risk_level: qualitative severity (NORMAL, ELEVATED, HIGH, CRITICAL)
    - entry_permission: gate on new risk allocation (ALLOW, REDUCE_SIZE, BLOCK)
    - position_action: instructions for existing exposure (NONE, REVIEW, REDUCE_ONLY)
    - OrderIntent: caller's purpose (ENTRY, ADD_POSITION, REDUCE, EXIT, EMERGENCY_EXIT)
    - EventRiskPolicyReason: stable policy outcome reasons
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, Optional, Tuple


class EventRiskContractError(ValueError):
    """Raised when an EventRiskDecision or related contract violates structural/semantic rules."""


class EventRiskLevel(str, Enum):
    """Qualitative severity assessment of external or macro events."""
    NORMAL = "NORMAL"
    ELEVATED = "ELEVATED"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class EntryPermission(str, Enum):
    """Authoritative gate on new entry orders."""
    ALLOW = "ALLOW"
    REDUCE_SIZE = "REDUCE_SIZE"
    BLOCK = "BLOCK"


class PositionAction(str, Enum):
    """Instruction for managing existing positions under event conditions."""
    NONE = "NONE"
    REVIEW = "REVIEW"
    REDUCE_ONLY = "REDUCE_ONLY"


class OrderIntent(str, Enum):
    """Intent of the order to be evaluated against risk policy."""
    ENTRY = "ENTRY"
    ADD_POSITION = "ADD_POSITION"
    REDUCE = "REDUCE"
    EXIT = "EXIT"
    EMERGENCY_EXIT = "EMERGENCY_EXIT"


class StaleSnapshotPolicy(str, Enum):
    """Handling strategy when snapshot is expired or unavailable."""
    BLOCK = "BLOCK"
    DEGRADE = "DEGRADE"


class EventRiskPolicyReason(str, Enum):
    """Stable reason codes for event risk policy evaluation outcomes."""
    INVALID_REQUESTED_MULTIPLIER = "invalid_requested_multiplier"
    INVALID_EVENT_RISK_MULTIPLIER = "invalid_event_risk_multiplier"
    INVALID_EVENT_RISK_SNAPSHOT = "invalid_event_risk_snapshot"
    POLICY_VERSION_MISMATCH = "policy_version_mismatch"
    STALE_SNAPSHOT_BLOCK = "stale_snapshot_block"
    STALE_SNAPSHOT_DEGRADE = "stale_snapshot_degrade"
    MISSING_EVENT_RISK_SNAPSHOT = "missing_event_risk_snapshot"
    MISSING_SNAPSHOT_DEGRADE = "missing_snapshot_degrade"
    EVENT_RISK_BLOCKED = "event_risk_blocked"
    EVENT_RISK_SIZE_REDUCED = "event_risk_size_reduced"
    EVENT_RISK_ALLOWED = "event_risk_allowed"
    EXIT_INTENT_UNBLOCKED = "exit_intent_unblocked"


DEFAULT_EVENT_RISK_POLICY_VERSION = "event-risk-v1"


def compute_snapshot_hash(payload: Dict[str, Any]) -> str:
    """Compute deterministic SHA-256 digest of canonicalized snapshot dict."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class EventRiskDecision:
    """Immutable snapshot of event-driven risk evaluation with contract validation."""
    risk_level: EventRiskLevel
    entry_permission: EntryPermission
    position_action: PositionAction
    max_risk_multiplier: Decimal
    risk_state_version: str
    risk_policy_version: str
    evaluated_at: datetime
    expires_at: Optional[datetime] = None
    reason_codes: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        # 0. Validate enum instances when constructor called directly
        if not isinstance(self.risk_level, EventRiskLevel):
            raise EventRiskContractError(
                f"risk_level must be an EventRiskLevel enum, got {type(self.risk_level).__name__}: {self.risk_level!r}"
            )
        if not isinstance(self.entry_permission, EntryPermission):
            raise EventRiskContractError(
                f"entry_permission must be an EntryPermission enum, got {type(self.entry_permission).__name__}: {self.entry_permission!r}"
            )
        if not isinstance(self.position_action, PositionAction):
            raise EventRiskContractError(
                f"position_action must be a PositionAction enum, got {type(self.position_action).__name__}: {self.position_action!r}"
            )

        # 1. Validate max_risk_multiplier: finite Decimal in [0, 1]
        mult = self.max_risk_multiplier
        if not isinstance(mult, Decimal):
            try:
                mult = Decimal(str(mult))
                object.__setattr__(self, "max_risk_multiplier", mult)
            except Exception as e:
                raise EventRiskContractError(f"max_risk_multiplier must be a valid Decimal: {e}") from e

        if mult.is_nan() or mult.is_infinite():
            raise EventRiskContractError(f"max_risk_multiplier must be finite, got: {mult}")
        if mult < Decimal("0.0") or mult > Decimal("1.0"):
            raise EventRiskContractError(
                f"max_risk_multiplier must be in range [0, 1], got: {mult}"
            )

        # 2. Validate version strings: strictly non-empty str (no numeric/None coercion)
        if not isinstance(self.risk_state_version, str) or not self.risk_state_version.strip():
            raise EventRiskContractError("risk_state_version must be a non-empty string")
        if not isinstance(self.risk_policy_version, str) or not self.risk_policy_version.strip():
            raise EventRiskContractError("risk_policy_version must be a non-empty string")

        # 3. Validate evaluated_at: timezone-aware datetime
        if (
            not isinstance(self.evaluated_at, datetime)
            or self.evaluated_at.tzinfo is None
            or self.evaluated_at.tzinfo.utcoffset(self.evaluated_at) is None
        ):
            raise EventRiskContractError("evaluated_at must be a timezone-aware datetime")

        # 4. Validate expires_at: timezone-aware datetime and >= evaluated_at
        if self.expires_at is not None:
            if (
                not isinstance(self.expires_at, datetime)
                or self.expires_at.tzinfo is None
                or self.expires_at.tzinfo.utcoffset(self.expires_at) is None
            ):
                raise EventRiskContractError("expires_at must be a timezone-aware datetime")
            if self.expires_at < self.evaluated_at:
                raise EventRiskContractError(
                    f"expires_at ({self.expires_at.isoformat()}) cannot be earlier than "
                    f"evaluated_at ({self.evaluated_at.isoformat()})"
                )

        # 5. Validate reason_codes: sequence of strictly non-empty strings
        if not isinstance(self.reason_codes, (tuple, list)):
            raise EventRiskContractError("reason_codes must be a tuple or list of strings")
        for code in self.reason_codes:
            if not isinstance(code, str) or not code.strip():
                raise EventRiskContractError("reason_codes entries must be non-empty strings")
        if isinstance(self.reason_codes, list):
            object.__setattr__(self, "reason_codes", tuple(self.reason_codes))

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for audit logs, evidence store, and transport."""
        return {
            "risk_level": self.risk_level.value,
            "entry_permission": self.entry_permission.value,
            "position_action": self.position_action.value,
            "max_risk_multiplier": str(self.max_risk_multiplier),
            "risk_state_version": self.risk_state_version,
            "risk_policy_version": self.risk_policy_version,
            "evaluated_at": self.evaluated_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at is not None else None,
            "reason_codes": list(self.reason_codes),
        }

    @classmethod
    def from_dict(cls, data: Any) -> EventRiskDecision:
        """Deserialize from audit log or JSON representation with contract validation."""
        if not isinstance(data, dict):
            raise EventRiskContractError(f"Expected dict for EventRiskDecision, got {type(data).__name__}")

        required_keys = {
            "risk_level", "entry_permission", "position_action",
            "max_risk_multiplier", "risk_state_version", "risk_policy_version",
            "evaluated_at",
        }
        missing = required_keys - set(data.keys())
        if missing:
            raise EventRiskContractError(f"Missing required EventRiskDecision keys: {sorted(missing)}")

        rl_raw = data["risk_level"]
        if not isinstance(rl_raw, (str, EventRiskLevel)):
            raise EventRiskContractError(f"risk_level must be str or EventRiskLevel, got {type(rl_raw).__name__}")
        try:
            risk_level = rl_raw if isinstance(rl_raw, EventRiskLevel) else EventRiskLevel(str(rl_raw).upper())
        except Exception as e:
            raise EventRiskContractError(f"Invalid risk_level '{rl_raw}': {e}") from e

        ep_raw = data["entry_permission"]
        if not isinstance(ep_raw, (str, EntryPermission)):
            raise EventRiskContractError(f"entry_permission must be str or EntryPermission, got {type(ep_raw).__name__}")
        try:
            entry_permission = ep_raw if isinstance(ep_raw, EntryPermission) else EntryPermission(str(ep_raw).upper())
        except Exception as e:
            raise EventRiskContractError(f"Invalid entry_permission '{ep_raw}': {e}") from e

        pa_raw = data["position_action"]
        if not isinstance(pa_raw, (str, PositionAction)):
            raise EventRiskContractError(f"position_action must be str or PositionAction, got {type(pa_raw).__name__}")
        try:
            position_action = pa_raw if isinstance(pa_raw, PositionAction) else PositionAction(str(pa_raw).upper())
        except Exception as e:
            raise EventRiskContractError(f"Invalid position_action '{pa_raw}': {e}") from e

        mult_raw = data["max_risk_multiplier"]
        if not isinstance(mult_raw, (int, float, str, Decimal)):
            raise EventRiskContractError(f"max_risk_multiplier must be numeric/Decimal, got {type(mult_raw).__name__}")
        try:
            max_risk_multiplier = Decimal(str(mult_raw))
        except Exception as e:
            raise EventRiskContractError(f"Invalid max_risk_multiplier '{mult_raw}': {e}") from e

        # Validate version strings strictly without coercing None or numbers
        r_state_ver = data["risk_state_version"]
        if not isinstance(r_state_ver, str) or not r_state_ver.strip():
            raise EventRiskContractError("risk_state_version must be a non-empty string")

        r_pol_ver = data["risk_policy_version"]
        if not isinstance(r_pol_ver, str) or not r_pol_ver.strip():
            raise EventRiskContractError("risk_policy_version must be a non-empty string")

        evaluated_at_raw = data["evaluated_at"]
        if isinstance(evaluated_at_raw, str):
            try:
                evaluated_at = datetime.fromisoformat(evaluated_at_raw)
            except Exception as e:
                raise EventRiskContractError(f"Invalid evaluated_at format '{evaluated_at_raw}': {e}") from e
        elif isinstance(evaluated_at_raw, datetime):
            evaluated_at = evaluated_at_raw
        else:
            raise EventRiskContractError(f"evaluated_at must be str or datetime, got {type(evaluated_at_raw).__name__}")

        expires_at_raw = data.get("expires_at")
        expires_at: Optional[datetime] = None
        if expires_at_raw is not None:
            if isinstance(expires_at_raw, str):
                try:
                    expires_at = datetime.fromisoformat(expires_at_raw)
                except Exception as e:
                    raise EventRiskContractError(f"Invalid expires_at format '{expires_at_raw}': {e}") from e
            elif isinstance(expires_at_raw, datetime):
                expires_at = expires_at_raw
            else:
                raise EventRiskContractError(f"expires_at must be str, datetime, or None, got {type(expires_at_raw).__name__}")

        raw_reasons = data.get("reason_codes")
        if raw_reasons is None:
            reason_codes: Tuple[str, ...] = ()
        elif isinstance(raw_reasons, (list, tuple)):
            for r in raw_reasons:
                if not isinstance(r, str) or not r.strip():
                    raise EventRiskContractError(
                        f"reason_codes entries must be non-empty strings, got {type(r).__name__}: {r!r}"
                    )
            reason_codes = tuple(raw_reasons)
        else:
            raise EventRiskContractError(f"reason_codes must be a list/tuple, got {type(raw_reasons).__name__}")

        return cls(
            risk_level=risk_level,
            entry_permission=entry_permission,
            position_action=position_action,
            max_risk_multiplier=max_risk_multiplier,
            risk_state_version=r_state_ver,
            risk_policy_version=r_pol_ver,
            evaluated_at=evaluated_at,
            expires_at=expires_at,
            reason_codes=reason_codes,
        )


@dataclass(frozen=True)
class RiskEvaluationResult:
    """Full immutable result of evaluating an order intent against event risk policy."""
    allowed: bool
    approved_multiplier: Decimal
    reason: EventRiskPolicyReason | str
    intent: OrderIntent
    evaluation_timestamp: datetime
    risk_state_version: str
    risk_policy_version: str
    snapshot_payload: Optional[Dict[str, Any]] = None
    snapshot_hash: Optional[str] = None
    decision: Optional[EventRiskDecision] = None

    def to_dict(self) -> Dict[str, Any]:
        reason_val = self.reason.value if hasattr(self.reason, "value") else str(self.reason)
        intent_val = self.intent.value if hasattr(self.intent, "value") else str(self.intent)
        return {
            "allowed": self.allowed,
            "approved_multiplier": str(self.approved_multiplier),
            "reason": reason_val,
            "intent": intent_val,
            "evaluation_timestamp": self.evaluation_timestamp.isoformat() if self.evaluation_timestamp else None,
            "risk_state_version": self.risk_state_version,
            "risk_policy_version": self.risk_policy_version,
            "snapshot_payload": self.snapshot_payload,
            "snapshot_hash": self.snapshot_hash,
            "decision": self.decision.to_dict() if self.decision else None,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> RiskEvaluationResult:
        reason_raw = data["reason"]
        try:
            reason = EventRiskPolicyReason(reason_raw)
        except Exception:
            reason = str(reason_raw)

        intent_raw = data.get("intent", "ENTRY")
        try:
            intent = OrderIntent(intent_raw)
        except Exception:
            intent = OrderIntent.ENTRY

        ts_raw = data["evaluation_timestamp"]
        ts = datetime.fromisoformat(ts_raw) if isinstance(ts_raw, str) else ts_raw

        dec = EventRiskDecision.from_dict(data["decision"]) if data.get("decision") else None
        return cls(
            allowed=bool(data["allowed"]),
            approved_multiplier=Decimal(str(data["approved_multiplier"])),
            reason=reason,
            intent=intent,
            evaluation_timestamp=ts,
            risk_state_version=str(data.get("risk_state_version", "unknown")),
            risk_policy_version=str(data.get("risk_policy_version", "unknown")),
            snapshot_payload=data.get("snapshot_payload"),
            snapshot_hash=data.get("snapshot_hash"),
            decision=dec,
        )


class RiskPolicyEvaluator:
    """Deterministic, pure evaluator for event risk policy contracts.

    Contract guarantees:
        1. Pure function: NO internal wall-clock calls. evaluation_timestamp is mandatory.
        2. evaluation_timestamp must be a timezone-aware datetime.
        3. Exits and position reductions are NEVER blocked (EXIT_INTENT_UNBLOCKED).
        4. approved_multiplier is strictly <= requested_multiplier (event overlay never expands size).
        5. Malformed multipliers fail-closed.
        6. Same (snapshot, intent, multiplier, timestamp) -> identical result.
    """

    def __init__(
        self,
        current_policy_version: str = DEFAULT_EVENT_RISK_POLICY_VERSION,
        stale_policy: StaleSnapshotPolicy = StaleSnapshotPolicy.BLOCK,
    ) -> None:
        self.current_policy_version = current_policy_version
        self.stale_policy = stale_policy

    def evaluate(
        self,
        snapshot: Optional[EventRiskDecision],
        intent: OrderIntent,
        requested_multiplier: Decimal,
        evaluation_timestamp: datetime,
    ) -> RiskEvaluationResult:
        """Evaluate order intent against an EventRiskDecision snapshot deterministically.

        Contract Guarantees:
            1. Pure function: NO internal wall-clock calls. evaluation_timestamp is mandatory and aware.
            2. Protective intents (REDUCE, EXIT, EMERGENCY_EXIT) are NEVER blocked by event risk policy
               (reason=EXIT_INTENT_UNBLOCKED, allowed=True).
            3. For ENTRY/ADD_POSITION, approved_multiplier <= requested_multiplier in all cases.
            4. Version mismatches or expired snapshots fail-closed under BLOCK policy.
        """
        # 1. Validate evaluation_timestamp: required and timezone-aware
        if (
            not isinstance(evaluation_timestamp, datetime)
            or evaluation_timestamp.tzinfo is None
            or evaluation_timestamp.tzinfo.utcoffset(evaluation_timestamp) is None
        ):
            raise EventRiskContractError("evaluation_timestamp must be a timezone-aware datetime")

        snap_payload = snapshot.to_dict() if snapshot else None
        snap_hash = compute_snapshot_hash(snap_payload) if snap_payload else None
        state_ver = snapshot.risk_state_version if snapshot else "none"
        pol_ver = snapshot.risk_policy_version if snapshot else self.current_policy_version

        # 2. Protective intents are ALWAYS unblocked by event risk policy
        if intent in (OrderIntent.REDUCE, OrderIntent.EXIT, OrderIntent.EMERGENCY_EXIT):
            safe_mult = Decimal("1.0")
            try:
                m = requested_multiplier if isinstance(requested_multiplier, Decimal) else Decimal(str(requested_multiplier))
                if not (m.is_nan() or m.is_infinite()) and Decimal("0.0") <= m <= Decimal("1.0"):
                    safe_mult = m
            except Exception:
                safe_mult = Decimal("1.0")

            return RiskEvaluationResult(
                allowed=True,
                approved_multiplier=safe_mult,
                reason=EventRiskPolicyReason.EXIT_INTENT_UNBLOCKED,
                intent=intent,
                evaluation_timestamp=evaluation_timestamp,
                risk_state_version=state_ver,
                risk_policy_version=pol_ver,
                snapshot_payload=snap_payload,
                snapshot_hash=snap_hash,
                decision=snapshot,
            )

        # 3. Validate requested_multiplier for non-protective orders: finite Decimal in [0, 1]
        try:
            req_mult = requested_multiplier if isinstance(requested_multiplier, Decimal) else Decimal(str(requested_multiplier))
        except Exception:
            req_mult = None

        if req_mult is None or req_mult.is_nan() or req_mult.is_infinite() or req_mult < Decimal("0.0") or req_mult > Decimal("1.0"):
            return RiskEvaluationResult(
                allowed=False,
                approved_multiplier=Decimal("0.0"),
                reason=EventRiskPolicyReason.INVALID_REQUESTED_MULTIPLIER,
                intent=intent,
                evaluation_timestamp=evaluation_timestamp,
                risk_state_version=state_ver,
                risk_policy_version=self.current_policy_version,
                snapshot_payload=snap_payload,
                snapshot_hash=snap_hash,
                decision=snapshot,
            )

        # 4. Missing snapshot handling
        if snapshot is None:
            if self.stale_policy == StaleSnapshotPolicy.BLOCK:
                return RiskEvaluationResult(
                    allowed=False,
                    approved_multiplier=Decimal("0.0"),
                    reason=EventRiskPolicyReason.MISSING_EVENT_RISK_SNAPSHOT,
                    intent=intent,
                    evaluation_timestamp=evaluation_timestamp,
                    risk_state_version="none",
                    risk_policy_version=self.current_policy_version,
                    decision=None,
                )
            else:
                return RiskEvaluationResult(
                    allowed=True,
                    approved_multiplier=min(req_mult, Decimal("0.5")),
                    reason=EventRiskPolicyReason.MISSING_SNAPSHOT_DEGRADE,
                    intent=intent,
                    evaluation_timestamp=evaluation_timestamp,
                    risk_state_version="none",
                    risk_policy_version=self.current_policy_version,
                    decision=None,
                )

        # 5. Validate snapshot max_risk_multiplier
        snap_mult = snapshot.max_risk_multiplier
        if not isinstance(snap_mult, Decimal) or snap_mult.is_nan() or snap_mult.is_infinite() or snap_mult < Decimal("0.0") or snap_mult > Decimal("1.0"):
            return RiskEvaluationResult(
                allowed=False,
                approved_multiplier=Decimal("0.0"),
                reason=EventRiskPolicyReason.INVALID_EVENT_RISK_MULTIPLIER,
                intent=intent,
                evaluation_timestamp=evaluation_timestamp,
                risk_state_version=state_ver,
                risk_policy_version=pol_ver,
                snapshot_payload=snap_payload,
                snapshot_hash=snap_hash,
                decision=snapshot,
            )

        # 6. Policy version validation (fail-closed)
        if snapshot.risk_policy_version != self.current_policy_version:
            return RiskEvaluationResult(
                allowed=False,
                approved_multiplier=Decimal("0.0"),
                reason=EventRiskPolicyReason.POLICY_VERSION_MISMATCH,
                intent=intent,
                evaluation_timestamp=evaluation_timestamp,
                risk_state_version=state_ver,
                risk_policy_version=pol_ver,
                snapshot_payload=snap_payload,
                snapshot_hash=snap_hash,
                decision=snapshot,
            )

        # 7. Expiry / freshness validation (deterministic against evaluation_timestamp)
        if snapshot.expires_at is not None and evaluation_timestamp > snapshot.expires_at:
            if self.stale_policy == StaleSnapshotPolicy.BLOCK:
                return RiskEvaluationResult(
                    allowed=False,
                    approved_multiplier=Decimal("0.0"),
                    reason=EventRiskPolicyReason.STALE_SNAPSHOT_BLOCK,
                    intent=intent,
                    evaluation_timestamp=evaluation_timestamp,
                    risk_state_version=state_ver,
                    risk_policy_version=pol_ver,
                    snapshot_payload=snap_payload,
                    snapshot_hash=snap_hash,
                    decision=snapshot,
                )
            else:
                if snapshot.entry_permission == EntryPermission.BLOCK:
                    return RiskEvaluationResult(
                        allowed=False,
                        approved_multiplier=Decimal("0.0"),
                        reason=EventRiskPolicyReason.EVENT_RISK_BLOCKED,
                        intent=intent,
                        evaluation_timestamp=evaluation_timestamp,
                        risk_state_version=state_ver,
                        risk_policy_version=pol_ver,
                        snapshot_payload=snap_payload,
                        snapshot_hash=snap_hash,
                        decision=snapshot,
                    )
                degraded_mult = min(req_mult, Decimal("0.5"), snap_mult)
                return RiskEvaluationResult(
                    allowed=True,
                    approved_multiplier=degraded_mult,
                    reason=EventRiskPolicyReason.STALE_SNAPSHOT_DEGRADE,
                    intent=intent,
                    evaluation_timestamp=evaluation_timestamp,
                    risk_state_version=state_ver,
                    risk_policy_version=pol_ver,
                    snapshot_payload=snap_payload,
                    snapshot_hash=snap_hash,
                    decision=snapshot,
                )

        # 8. Evaluate entry permission (ensuring approved_multiplier <= req_mult)
        if snapshot.entry_permission == EntryPermission.BLOCK:
            return RiskEvaluationResult(
                allowed=False,
                approved_multiplier=Decimal("0.0"),
                reason=EventRiskPolicyReason.EVENT_RISK_BLOCKED,
                intent=intent,
                evaluation_timestamp=evaluation_timestamp,
                risk_state_version=state_ver,
                risk_policy_version=pol_ver,
                snapshot_payload=snap_payload,
                snapshot_hash=snap_hash,
                decision=snapshot,
            )

        if snapshot.entry_permission == EntryPermission.REDUCE_SIZE:
            approved = min(req_mult, snap_mult)
            return RiskEvaluationResult(
                allowed=True,
                approved_multiplier=approved,
                reason=EventRiskPolicyReason.EVENT_RISK_SIZE_REDUCED,
                intent=intent,
                evaluation_timestamp=evaluation_timestamp,
                risk_state_version=state_ver,
                risk_policy_version=pol_ver,
                snapshot_payload=snap_payload,
                snapshot_hash=snap_hash,
                decision=snapshot,
            )

        if snapshot.entry_permission == EntryPermission.ALLOW:
            approved = min(req_mult, snap_mult)
            return RiskEvaluationResult(
                allowed=True,
                approved_multiplier=approved,
                reason=EventRiskPolicyReason.EVENT_RISK_ALLOWED,
                intent=intent,
                evaluation_timestamp=evaluation_timestamp,
                risk_state_version=state_ver,
                risk_policy_version=pol_ver,
                snapshot_payload=snap_payload,
                snapshot_hash=snap_hash,
                decision=snapshot,
            )

        # Fallback fail-closed
        return RiskEvaluationResult(
            allowed=False,
            approved_multiplier=Decimal("0.0"),
            reason=EventRiskPolicyReason.EVENT_RISK_BLOCKED,
            intent=intent,
            evaluation_timestamp=evaluation_timestamp,
            risk_state_version=state_ver,
            risk_policy_version=pol_ver,
            snapshot_payload=snap_payload,
            snapshot_hash=snap_hash,
            decision=snapshot,
        )
