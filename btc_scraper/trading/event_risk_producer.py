"""
btc_scraper/trading/event_risk_producer.py
P0-D — Deterministic Event Snapshot Producer.

Builds immutable point-in-time event snapshots from historical and fixture data
for deterministic replay, backtesting, and paper decision verification.

Guarantees:
    1. Point-in-time fidelity: an event record is included if and only if
       available_at <= decision_time. No future information leakage.
    2. Strict determinism: same inputs and configuration yield identical
       snapshot representation and SHA-256 digest regardless of execution
       time, machine timezone, process ID, or iteration order.
    3. Conflict resolution: hard BLOCK and CRITICAL severity strictly dominate;
       no less severe event can overwrite a hard risk restriction.
    4. Sizing safety: multiple REDUCE events select the most restrictive
       (minimum) multiplier without compounding or duplicate reduction.
    5. Zero network dependency: replay operates purely in-memory on normalized fixtures.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from btc_scraper.trading.event_risk_policy import (
    DEFAULT_EVENT_RISK_POLICY_VERSION,
    EntryPermission,
    EventRiskContractError,
    EventRiskDecision,
    EventRiskLevel,
    OrderIntent,
    PositionAction,
    RiskEvaluationResult,
    RiskPolicyEvaluator,
    compute_snapshot_hash,
)


def _ensure_utc(dt: datetime) -> datetime:
    """Ensure datetime is aware and in UTC."""
    if not isinstance(dt, datetime):
        raise EventRiskContractError(f"Expected datetime, got {type(dt).__name__}")
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        raise EventRiskContractError("Datetime must be timezone-aware (UTC)")
    return dt.astimezone(timezone.utc)


def _parse_iso_utc(value: str | datetime) -> datetime:
    """Parse ISO datetime string to aware UTC datetime."""
    if isinstance(value, datetime):
        return _ensure_utc(value)
    if not isinstance(value, str) or not value.strip():
        raise EventRiskContractError("Datetime string must be a non-empty string")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return _ensure_utc(dt)
    except Exception as exc:
        raise EventRiskContractError(f"Invalid ISO datetime string '{value}': {exc}") from exc


@dataclass(frozen=True)
class NormalizedEventRecord:
    """Immutable normalized point-in-time external risk event representation."""
    event_id: str
    source_id: str
    event_type: str
    affected_symbols: Tuple[str, ...]
    event_time: datetime
    published_at: datetime
    available_at: datetime
    ingested_at: datetime
    revised_at: Optional[datetime] = None
    source_version: str = "v1"
    payload_hash: str = ""
    confidence: float = 1.0
    severity: EventRiskLevel = EventRiskLevel.NORMAL
    permission: EntryPermission = EntryPermission.ALLOW
    action: PositionAction = PositionAction.NONE
    risk_multiplier: Decimal = Decimal("1.0")
    expires_at: Optional[datetime] = None
    reason_codes: Tuple[str, ...] = ()
    uncertain_availability: bool = False
    raw_payload: Optional[Dict[str, Any]] = None

    def __post_init__(self) -> None:
        if not self.event_id or not str(self.event_id).strip():
            raise EventRiskContractError("event_id must be a non-empty string")
        if not self.source_id or not str(self.source_id).strip():
            raise EventRiskContractError("source_id must be a non-empty string")
        if not self.event_type or not str(self.event_type).strip():
            raise EventRiskContractError("event_type must be a non-empty string")

        # Datetime UTC awareness
        object.__setattr__(self, "event_time", _ensure_utc(self.event_time))
        object.__setattr__(self, "published_at", _ensure_utc(self.published_at))
        object.__setattr__(self, "available_at", _ensure_utc(self.available_at))
        object.__setattr__(self, "ingested_at", _ensure_utc(self.ingested_at))
        if self.revised_at is not None:
            object.__setattr__(self, "revised_at", _ensure_utc(self.revised_at))
        if self.expires_at is not None:
            object.__setattr__(self, "expires_at", _ensure_utc(self.expires_at))
            if self.expires_at < self.available_at:
                raise EventRiskContractError(
                    f"expires_at ({self.expires_at.isoformat()}) cannot be earlier than "
                    f"available_at ({self.available_at.isoformat()})"
                )

        # Symbols normalization (uppercase tuple)
        norm_syms = tuple(sorted(str(s).strip().upper() for s in self.affected_symbols if str(s).strip()))
        if not norm_syms:
            raise EventRiskContractError("affected_symbols must contain at least one non-empty symbol")
        object.__setattr__(self, "affected_symbols", norm_syms)

        # Enums
        if not isinstance(self.severity, EventRiskLevel):
            object.__setattr__(self, "severity", EventRiskLevel(str(self.severity).upper()))
        if not isinstance(self.permission, EntryPermission):
            object.__setattr__(self, "permission", EntryPermission(str(self.permission).upper()))
        if not isinstance(self.action, PositionAction):
            object.__setattr__(self, "action", PositionAction(str(self.action).upper()))

        # Multiplier
        mult = self.risk_multiplier if isinstance(self.risk_multiplier, Decimal) else Decimal(str(self.risk_multiplier))
        if mult.is_nan() or mult.is_infinite() or mult < Decimal("0.0") or mult > Decimal("1.0"):
            raise EventRiskContractError(f"risk_multiplier must be finite Decimal in [0, 1], got: {mult}")
        object.__setattr__(self, "risk_multiplier", mult)

        # Confidence
        conf = float(self.confidence)
        if conf < 0.0 or conf > 1.0:
            raise EventRiskContractError(f"confidence must be in [0, 1], got: {conf}")
        object.__setattr__(self, "confidence", conf)

        # Auto-compute payload_hash if empty
        if not self.payload_hash:
            canonical_data = {
                "event_id": self.event_id,
                "source_id": self.source_id,
                "event_type": self.event_type,
                "affected_symbols": self.affected_symbols,
                "event_time": self.event_time.isoformat(),
                "available_at": self.available_at,
                "severity": self.severity.value,
                "permission": self.permission.value,
                "risk_multiplier": str(self.risk_multiplier),
                "raw_payload": self.raw_payload,
            }
            raw_hash = hashlib.sha256(
                json.dumps(canonical_data, sort_keys=True, default=str).encode("utf-8")
            ).hexdigest()
            object.__setattr__(self, "payload_hash", raw_hash)

    def is_available_as_of(self, as_of_time: datetime) -> bool:
        """Check point-in-time availability."""
        if self.uncertain_availability:
            return False
        utc_as_of = _ensure_utc(as_of_time)
        return self.available_at <= utc_as_of

    def is_expired_as_of(self, as_of_time: datetime) -> bool:
        """Check if event has expired by decision time."""
        if self.expires_at is None:
            return False
        utc_as_of = _ensure_utc(as_of_time)
        return utc_as_of > self.expires_at

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "source_id": self.source_id,
            "event_type": self.event_type,
            "affected_symbols": list(self.affected_symbols),
            "event_time": self.event_time.isoformat(),
            "published_at": self.published_at.isoformat(),
            "available_at": self.available_at.isoformat(),
            "ingested_at": self.ingested_at.isoformat(),
            "revised_at": self.revised_at.isoformat() if self.revised_at else None,
            "source_version": self.source_version,
            "payload_hash": self.payload_hash,
            "confidence": self.confidence,
            "severity": self.severity.value,
            "permission": self.permission.value,
            "action": self.action.value,
            "risk_multiplier": str(self.risk_multiplier),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "reason_codes": list(self.reason_codes),
            "uncertain_availability": self.uncertain_availability,
            "raw_payload": self.raw_payload,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> NormalizedEventRecord:
        return cls(
            event_id=str(data["event_id"]),
            source_id=str(data["source_id"]),
            event_type=str(data["event_type"]),
            affected_symbols=tuple(data["affected_symbols"]),
            event_time=_parse_iso_utc(data["event_time"]),
            published_at=_parse_iso_utc(data["published_at"]),
            available_at=_parse_iso_utc(data["available_at"]),
            ingested_at=_parse_iso_utc(data.get("ingested_at") or data["available_at"]),
            revised_at=_parse_iso_utc(data["revised_at"]) if data.get("revised_at") else None,
            source_version=str(data.get("source_version", "v1")),
            payload_hash=str(data.get("payload_hash", "")),
            confidence=float(data.get("confidence", 1.0)),
            severity=EventRiskLevel(str(data.get("severity", "NORMAL")).upper()),
            permission=EntryPermission(str(data.get("permission", "ALLOW")).upper()),
            action=PositionAction(str(data.get("action", "NONE")).upper()),
            risk_multiplier=Decimal(str(data.get("risk_multiplier", "1.0"))),
            expires_at=_parse_iso_utc(data["expires_at"]) if data.get("expires_at") else None,
            reason_codes=tuple(data.get("reason_codes", ())),
            uncertain_availability=bool(data.get("uncertain_availability", False)),
            raw_payload=data.get("raw_payload"),
        )


@dataclass(frozen=True)
class DeterministicEventSnapshot:
    """Immutable point-in-time aggregate snapshot representing event risk at decision time."""
    snapshot_id: str
    as_of_time: datetime
    policy_version: str
    symbol: str
    selected_event_ids: Tuple[str, ...]
    snapshot_hash: str
    decision: EventRiskDecision
    missingness_status: str  # "AVAILABLE", "EMPTY", "DEGRADED", "STALE"
    uncertain_events_dropped: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "as_of_time": self.as_of_time.isoformat(),
            "policy_version": self.policy_version,
            "symbol": self.symbol,
            "selected_event_ids": list(self.selected_event_ids),
            "snapshot_hash": self.snapshot_hash,
            "decision": self.decision.to_dict(),
            "missingness_status": self.missingness_status,
            "uncertain_events_dropped": self.uncertain_events_dropped,
        }


class DeterministicEventSnapshotProducer:
    """Pure, deterministic point-in-time event snapshot builder.

    Evaluates event risk from historical/fixture event records strictly
    as of a specified decision timestamp without future leakage.
    """

    def __init__(
        self,
        policy_version: str = DEFAULT_EVENT_RISK_POLICY_VERSION,
        evaluator: Optional[RiskPolicyEvaluator] = None,
    ) -> None:
        self.policy_version = policy_version
        self.evaluator = evaluator or RiskPolicyEvaluator(current_policy_version=policy_version)

    def build_snapshot(
        self,
        events: Sequence[NormalizedEventRecord],
        as_of_time: datetime,
        symbol: str,
        *,
        window_seconds: Optional[float] = None,
    ) -> DeterministicEventSnapshot:
        """Produce deterministic EventRiskDecision snapshot for a symbol as of as_of_time."""
        utc_as_of = _ensure_utc(as_of_time)
        norm_sym = symbol.strip().upper()

        # 1. Filter events by Point-In-Time (PIT) availability and symbol match
        qualifying_events: List[NormalizedEventRecord] = []
        uncertain_dropped = 0

        # Group by event_id to resolve point-in-time revisions
        events_by_id: Dict[str, List[NormalizedEventRecord]] = {}
        for ev in events:
            if ev.uncertain_availability:
                uncertain_dropped += 1
                continue
            if not ev.is_available_as_of(utc_as_of):
                # Future information: available after decision time -> exclude
                continue
            events_by_id.setdefault(ev.event_id, []).append(ev)

        # For each event_id, pick the latest valid revision as of decision time
        active_revisions: List[NormalizedEventRecord] = []
        for eid, rev_list in events_by_id.items():
            # Sort revisions by revised_at ascending, using available_at if revised_at is None
            valid_revs = [
                r for r in rev_list
                if (r.revised_at is None or r.revised_at <= utc_as_of)
            ]
            if not valid_revs:
                continue
            valid_revs.sort(key=lambda r: (r.revised_at or r.available_at, r.ingested_at))
            active_revisions.append(valid_revs[-1])

        # Symbol & Window & Expiry filtering
        for ev in active_revisions:
            # Check symbol overlap: symbol match or market-wide wildcard (*, ALL)
            sym_match = (
                norm_sym in ev.affected_symbols
                or "*" in ev.affected_symbols
                or "ALL" in ev.affected_symbols
            )
            if not sym_match:
                continue

            # Check expiration
            if ev.is_expired_as_of(utc_as_of):
                continue

            # Check event window if provided
            if window_seconds is not None:
                if (utc_as_of - ev.event_time).total_seconds() > window_seconds:
                    continue

            qualifying_events.append(ev)

        # 2. Stable deterministic sort of qualifying events:
        # Sort by (event_time, available_at, event_id, payload_hash)
        qualifying_events.sort(key=lambda e: (e.event_time, e.available_at, e.event_id, e.payload_hash))

        # 3. Deduplicate exact duplicate event records
        deduped: List[NormalizedEventRecord] = []
        seen_keys: Set[Tuple[str, str]] = set()
        for e in qualifying_events:
            k = (e.event_id, e.payload_hash)
            if k not in seen_keys:
                seen_keys.add(k)
                deduped.append(e)

        selected_ids = tuple(e.event_id for e in deduped)

        # 4. Deterministic Aggregation
        if not deduped:
            decision = EventRiskDecision(
                risk_level=EventRiskLevel.NORMAL,
                entry_permission=EntryPermission.ALLOW,
                position_action=PositionAction.NONE,
                max_risk_multiplier=Decimal("1.0"),
                risk_state_version=f"pit-{utc_as_of.strftime('%Y%m%d%H%M%S')}",
                risk_policy_version=self.policy_version,
                evaluated_at=utc_as_of,
                reason_codes=("no_active_events",),
            )
            missingness = "EMPTY"
        else:
            missingness = "AVAILABLE"
            has_block = any(
                e.permission == EntryPermission.BLOCK or e.severity == EventRiskLevel.CRITICAL
                for e in deduped
            )
            has_reduce = any(
                e.permission == EntryPermission.REDUCE_SIZE
                for e in deduped
            )

            all_reasons: List[str] = []
            for e in deduped:
                all_reasons.extend(e.reason_codes)

            if has_block:
                # Precedence: Hard BLOCK strictly dominates
                entry_perm = EntryPermission.BLOCK
                sev = EventRiskLevel.CRITICAL
                action = PositionAction.REDUCE_ONLY if any(e.action == PositionAction.REDUCE_ONLY for e in deduped) else PositionAction.NONE
                mult = Decimal("0.0")
                if "event_risk_blocked" not in all_reasons:
                    all_reasons.append("event_risk_blocked")
            elif has_reduce:
                entry_perm = EntryPermission.REDUCE_SIZE
                # Sizing: most restrictive multiplier wins (minimum)
                mult = min(e.risk_multiplier for e in deduped)
                # Severity: highest severity wins
                sev_order = [EventRiskLevel.NORMAL, EventRiskLevel.ELEVATED, EventRiskLevel.HIGH, EventRiskLevel.CRITICAL]
                sev = max((e.severity for e in deduped), key=lambda s: sev_order.index(s))
                action = PositionAction.REDUCE_ONLY if any(e.action == PositionAction.REDUCE_ONLY for e in deduped) else (
                    PositionAction.REVIEW if any(e.action == PositionAction.REVIEW for e in deduped) else PositionAction.NONE
                )
                if "event_risk_reduced" not in all_reasons:
                    all_reasons.append("event_risk_reduced")
            else:
                entry_perm = EntryPermission.ALLOW
                mult = min((e.risk_multiplier for e in deduped), default=Decimal("1.0"))
                sev_order = [EventRiskLevel.NORMAL, EventRiskLevel.ELEVATED, EventRiskLevel.HIGH, EventRiskLevel.CRITICAL]
                sev = max((e.severity for e in deduped), key=lambda s: sev_order.index(s))
                action = PositionAction.REVIEW if any(e.action == PositionAction.REVIEW for e in deduped) else PositionAction.NONE
                if "event_risk_allowed" not in all_reasons:
                    all_reasons.append("event_risk_allowed")

            sorted_unique_reasons = tuple(sorted(set(all_reasons))) if all_reasons else ("event_risk_evaluated",)

            # Earliest expiry among qualifying events
            expiries = [e.expires_at for e in deduped if e.expires_at is not None]
            min_expiry = min(expiries) if expiries else None

            decision = EventRiskDecision(
                risk_level=sev,
                entry_permission=entry_perm,
                position_action=action,
                max_risk_multiplier=mult,
                risk_state_version=f"pit-{utc_as_of.strftime('%Y%m%d%H%M%S')}",
                risk_policy_version=self.policy_version,
                evaluated_at=utc_as_of,
                expires_at=min_expiry,
                reason_codes=sorted_unique_reasons,
            )

        # 5. Deterministic Snapshot Hash Calculation
        canonical_digest_payload = {
            "as_of_time": utc_as_of.isoformat(),
            "policy_version": self.policy_version,
            "symbol": norm_sym,
            "selected_event_ids": list(selected_ids),
            "events_digest": [
                {
                    "event_id": e.event_id,
                    "payload_hash": e.payload_hash,
                    "available_at": e.available_at.isoformat(),
                    "severity": e.severity.value,
                    "permission": e.permission.value,
                    "risk_multiplier": str(e.risk_multiplier),
                }
                for e in deduped
            ],
            "decision": decision.to_dict(),
        }
        snap_hash = compute_snapshot_hash(canonical_digest_payload)
        snapshot_id = f"snap-{snap_hash[:16]}"

        return DeterministicEventSnapshot(
            snapshot_id=snapshot_id,
            as_of_time=utc_as_of,
            policy_version=self.policy_version,
            symbol=norm_sym,
            selected_event_ids=selected_ids,
            snapshot_hash=snap_hash,
            decision=decision,
            missingness_status=missingness,
            uncertain_events_dropped=uncertain_dropped,
        )


class DeterministicEventReplayAdapter:
    """In-memory zero-network fixture replay adapter.

    Loads and replays external event manifests without issuing any network calls.
    """

    def __init__(
        self,
        events: Sequence[NormalizedEventRecord],
        producer: Optional[DeterministicEventSnapshotProducer] = None,
    ) -> None:
        self.events = list(events)
        self.producer = producer or DeterministicEventSnapshotProducer()

    @classmethod
    def from_fixture_dicts(cls, fixture_rows: Sequence[Dict[str, Any]]) -> DeterministicEventReplayAdapter:
        records = [NormalizedEventRecord.from_dict(row) for row in fixture_rows]
        return cls(events=records)

    def snapshot_as_of(
        self,
        as_of_time: datetime,
        symbol: str,
        *,
        window_seconds: Optional[float] = None,
    ) -> DeterministicEventSnapshot:
        """Produce snapshot purely in-memory."""
        return self.producer.build_snapshot(
            events=self.events,
            as_of_time=as_of_time,
            symbol=symbol,
            window_seconds=window_seconds,
        )

    def enhance_analysis(
        self,
        analysis: Dict[str, Any],
        as_of_time: datetime,
        symbol: str,
    ) -> Dict[str, Any]:
        """Attach deterministic event risk snapshot directly to an analysis dictionary."""
        snapshot = self.snapshot_as_of(as_of_time, symbol)
        analysis["event_risk"] = snapshot.decision
        analysis["event_risk_snapshot_hash"] = snapshot.snapshot_hash
        analysis["event_risk_snapshot_id"] = snapshot.snapshot_id
        analysis["event_risk_selected_event_ids"] = list(snapshot.selected_event_ids)
        return analysis
