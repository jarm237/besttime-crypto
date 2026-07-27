"""Live exchange outage recovery primitives.

These classes are deliberately small and deterministic so outage drills can run
without a real exchange. They persist every state transition that matters across
submit ambiguity, rate limiting, child-order replay, and operator quarantine.
"""
from __future__ import annotations

import hashlib
import json
import os
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from btc_scraper.execution.order_fill_ledger import OrderFillLedger
from btc_scraper.execution.reservation_store import ReservationStore
from btc_scraper.ml_engine.runtime_evidence_store import RuntimeEvidenceStore

SUBMIT_UNKNOWN = "SUBMIT_UNKNOWN"

MARKET_DATA_DEGRADED = "MARKET_DATA_DEGRADED"
ORDER_CHANNEL_DEGRADED = "ORDER_CHANNEL_DEGRADED"
RECONCILIATION_UNAVAILABLE = "RECONCILIATION_UNAVAILABLE"
EXCHANGE_UNAVAILABLE = "EXCHANGE_UNAVAILABLE"

REST_AUTHORITY = "REST_ORDER_DETAIL"
WS_FAST_PATH = "WEBSOCKET_FAST_PATH"

OPERATOR_ACTIONS = {
    "ACKNOWLEDGE",
    "ATTACH_EXISTING_ORDER",
    "CONFIRM_NOT_SUBMITTED",
    "MARK_CANCELED",
    "RECONCILE_FILL",
    "RELEASE_RESERVATION",
    "ESCALATE",
}

PRIORITY_ORDER = {
    "cancel_dangerous_order": 1,
    "query_open_order": 2,
    "query_position": 2,
    "protective_exit": 3,
    "reconciliation": 4,
    "new_entry": 5,
    "analytics": 6,
}


@dataclass(frozen=True)
class LiveOutageResult:
    status: str
    changed: bool = False
    details: dict[str, Any] = field(default_factory=dict)


class LiveOutageError(RuntimeError):
    pass


class ParentCompletedError(LiveOutageError):
    pass


class QuantityInvariantError(LiveOutageError):
    pass


class CancelReplaceAmbiguityError(LiveOutageError):
    pass


class JsonStateStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._state = self._load()

    def snapshot(self) -> dict[str, Any]:
        return json.loads(json.dumps(self._state, sort_keys=True))

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return self._empty_state()
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _save(self) -> None:
        tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        with tmp_path.open("w", encoding="utf-8") as handle:
            json.dump(self._state, handle, ensure_ascii=False, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, self.path)

    def _empty_state(self) -> dict[str, Any]:
        return {}


class QuarantineStore(JsonStateStore):
    def __init__(self, path: str | Path, evidence_store: RuntimeEvidenceStore | None = None):
        self.evidence_store = evidence_store
        super().__init__(path)

    def create(
        self,
        *,
        reason_code: str,
        severity: str,
        symbol: str,
        client_order_id: str | None = None,
        exchange_order_candidates: Sequence[Mapping[str, Any]] | None = None,
        reservation_id: str | None = None,
        decision_id: str | None = None,
        prediction_id: str | None = None,
        local_state: Mapping[str, Any] | None = None,
        exchange_observations: Sequence[Mapping[str, Any]] | None = None,
        recommended_actions: Sequence[str] | None = None,
    ) -> dict[str, Any]:
        for action in recommended_actions or []:
            if action not in OPERATOR_ACTIONS:
                raise ValueError(f"unsupported operator action: {action}")
        quarantine_id = _stable_id("q", "|".join([
            reason_code,
            symbol,
            client_order_id or "",
            reservation_id or "",
            decision_id or "",
            prediction_id or "",
        ]))
        existing = self._state["records"].get(quarantine_id)
        if existing:
            existing["last_checked_at"] = _now()
            self._save()
            return dict(existing)

        record = {
            "quarantine_id": quarantine_id,
            "reason_code": reason_code,
            "severity": severity,
            "symbol": symbol,
            "client_order_id": client_order_id,
            "exchange_order_candidates": [dict(row) for row in exchange_order_candidates or []],
            "reservation_id": reservation_id,
            "decision_id": decision_id,
            "prediction_id": prediction_id,
            "local_state": dict(local_state or {}),
            "exchange_observations": [dict(row) for row in exchange_observations or []],
            "created_at": _now(),
            "last_checked_at": _now(),
            "recommended_actions": list(recommended_actions or ["ACKNOWLEDGE", "ESCALATE"]),
            "resolution_status": "OPEN",
            "resolved_by": None,
            "resolved_at": None,
            "resolution_note": None,
        }
        self._state["records"][quarantine_id] = record
        self._append_event("quarantine_created", quarantine_id, {"reason_code": reason_code, "severity": severity})
        return dict(record)

    def resolve(
        self,
        quarantine_id: str,
        *,
        action: str,
        operator: str,
        note: str = "",
        amendment: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if action not in OPERATOR_ACTIONS:
            raise ValueError(f"unsupported operator action: {action}")
        record = self._state["records"].get(quarantine_id)
        if record is None:
            raise KeyError(quarantine_id)
        record["resolution_status"] = action
        record["resolved_by"] = operator
        record["resolved_at"] = _now()
        record["resolution_note"] = note
        self._append_event("quarantine_resolved", quarantine_id, {
            "action": action,
            "operator": operator,
            "note": note,
            "amendment": dict(amendment or {}),
        })
        return dict(record)

    def unresolved(self) -> list[dict[str, Any]]:
        return [dict(row) for row in self._state["records"].values() if row.get("resolution_status") == "OPEN"]

    def blocks_entries(self, *, symbol: str | None = None) -> bool:
        for record in self.unresolved():
            if symbol and record.get("symbol") not in {symbol, "*"}:
                continue
            if str(record.get("severity", "")).lower() in {"medium", "high", "critical"}:
                return True
        return False

    def _append_event(self, event_type: str, quarantine_id: str, payload: Mapping[str, Any]) -> None:
        event = {"event_type": event_type, "quarantine_id": quarantine_id, **dict(payload), "written_at": _now()}
        self._state["audit_events"].append(event)
        self._save()
        if self.evidence_store is not None:
            self.evidence_store.append_audit_event(event)

    def _empty_state(self) -> dict[str, Any]:
        return {"records": {}, "audit_events": []}


class RateLimitBackoff(JsonStateStore):
    def __init__(
        self,
        path: str | Path,
        *,
        base_delay_seconds: float = 1.0,
        max_delay_seconds: float = 60.0,
        jitter: Callable[[], float] | None = None,
        now: Callable[[], datetime] | None = None,
    ):
        self.base_delay_seconds = base_delay_seconds
        self.max_delay_seconds = max_delay_seconds
        self.jitter = jitter or (lambda: random.uniform(0.0, 0.25))
        self.now = now or (lambda: datetime.now(timezone.utc))
        super().__init__(path)

    def record_rate_limit(
        self,
        *,
        scope: str,
        error_code: str = "HTTP_429",
        retry_after_seconds: float | None = None,
        weight: int | None = None,
    ) -> dict[str, Any]:
        row = self._state["scopes"].setdefault(scope, {"attempt": 0})
        row["attempt"] = int(row.get("attempt") or 0) + 1
        exponential = min(self.max_delay_seconds, self.base_delay_seconds * (2 ** (row["attempt"] - 1)))
        delay = exponential + float(self.jitter())
        if retry_after_seconds is not None:
            delay = max(delay, float(retry_after_seconds))
        retry_at = self.now() + timedelta(seconds=delay)
        row.update({
            "scope": scope,
            "error_code": error_code,
            "weight": weight,
            "delay_seconds": delay,
            "retry_after_seconds": retry_after_seconds,
            "retry_at": retry_at.isoformat(),
            "updated_at": _now(),
        })
        self._save()
        return dict(row)

    def clear(self, scope: str) -> None:
        if scope in self._state["scopes"]:
            del self._state["scopes"][scope]
            self._save()

    def is_rate_limited(self, scope: str) -> bool:
        row = self._state["scopes"].get(scope)
        if not row:
            return False
        return _parse_dt(str(row.get("retry_at"))) > self.now()

    def priority_allowed(self, *, scope: str, priority: str) -> bool:
        if not self.is_rate_limited(scope):
            return True
        return PRIORITY_ORDER.get(priority, 99) <= PRIORITY_ORDER["reconciliation"]

    def _empty_state(self) -> dict[str, Any]:
        return {"scopes": {}}


class ChildOrderStore(JsonStateStore):
    def create_parent(self, *, parent_order_id: str, symbol: str, requested_quantity: float) -> dict[str, Any]:
        parent = self._state["parents"].setdefault(parent_order_id, {
            "parent_order_id": parent_order_id,
            "symbol": symbol,
            "requested_quantity": float(requested_quantity),
            "filled_quantity": 0.0,
            "status": "OPEN",
            "child_order_ids": [],
            "created_at": _now(),
            "updated_at": _now(),
        })
        self._save()
        return dict(parent)

    def record_child(
        self,
        *,
        parent_order_id: str,
        child_order_id: str,
        child_sequence: int,
        client_order_id: str,
        requested_quantity: float,
        exchange_order_id: str | None = None,
        status: str = "PENDING",
        submitted_at: str | None = None,
        last_reconciled_at: str | None = None,
    ) -> dict[str, Any]:
        parent = self._require_parent(parent_order_id)
        if parent.get("status") == "COMPLETED" and child_order_id not in self._state["children"]:
            raise ParentCompletedError(parent_order_id)
        existing = self._state["children"].get(child_order_id)
        if existing:
            return dict(existing)
        child = {
            "parent_order_id": parent_order_id,
            "child_order_id": child_order_id,
            "child_sequence": int(child_sequence),
            "client_order_id": client_order_id,
            "exchange_order_id": exchange_order_id,
            "requested_quantity": float(requested_quantity),
            "filled_quantity": 0.0,
            "remaining_quantity": float(requested_quantity),
            "status": status,
            "submitted_at": submitted_at or _now(),
            "last_reconciled_at": last_reconciled_at or _now(),
        }
        self._state["children"][child_order_id] = child
        parent.setdefault("child_order_ids", []).append(child_order_id)
        parent["updated_at"] = _now()
        self._save()
        return dict(child)

    def record_child_fill(
        self,
        *,
        child_order_id: str,
        quantity: float,
        fill_id: str | None = None,
        exchange_trade_id: str | None = None,
        status: str = "PARTIALLY_FILLED",
    ) -> dict[str, Any]:
        child = self._state["children"][child_order_id]
        parent = self._require_parent(child["parent_order_id"])
        fill_key = exchange_trade_id or fill_id or _stable_id("child-fill", f"{child_order_id}:{quantity}")
        if fill_key in self._state["fills"]:
            return {"status": "duplicate_ignored", "fill_key": fill_key, "parent": dict(parent), "child": dict(child)}
        new_parent_qty = _round_qty(float(parent.get("filled_quantity") or 0.0) + float(quantity))
        if new_parent_qty > float(parent["requested_quantity"]) + 1e-12:
            raise QuantityInvariantError(
                f"parent fill quantity {new_parent_qty} exceeds requested {parent['requested_quantity']}"
            )
        self._state["fills"][fill_key] = {
            "fill_key": fill_key,
            "child_order_id": child_order_id,
            "parent_order_id": parent["parent_order_id"],
            "quantity": float(quantity),
            "recorded_at": _now(),
        }
        child["filled_quantity"] = _round_qty(float(child.get("filled_quantity") or 0.0) + float(quantity))
        child["remaining_quantity"] = max(0.0, _round_qty(float(child["requested_quantity"]) - child["filled_quantity"]))
        child["status"] = "FILLED" if child["remaining_quantity"] == 0.0 else status
        child["last_reconciled_at"] = _now()
        parent["filled_quantity"] = new_parent_qty
        if parent["filled_quantity"] >= float(parent["requested_quantity"]) - 1e-12:
            parent["status"] = "COMPLETED"
        parent["updated_at"] = _now()
        self._save()
        return {"status": "recorded", "fill_key": fill_key, "parent": dict(parent), "child": dict(child)}

    def _require_parent(self, parent_order_id: str) -> dict[str, Any]:
        parent = self._state["parents"].get(parent_order_id)
        if parent is None:
            raise KeyError(parent_order_id)
        return parent

    def _empty_state(self) -> dict[str, Any]:
        return {"parents": {}, "children": {}, "fills": {}}


class ExchangeObservationStore(JsonStateStore):
    def record(
        self,
        *,
        source: str,
        status: str,
        client_order_id: str | None = None,
        exchange_order_id: str | None = None,
        payload: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        order_key = _order_key(client_order_id=client_order_id, exchange_order_id=exchange_order_id)
        row = {
            "source": source,
            "status": status,
            "client_order_id": client_order_id,
            "exchange_order_id": exchange_order_id,
            "payload": dict(payload or {}),
            "observed_at": _now(),
        }
        self._state["observations"].setdefault(order_key, []).append(row)
        self._save()
        return dict(row)

    def authoritative_status(self, *, client_order_id: str | None = None, exchange_order_id: str | None = None) -> dict[str, Any] | None:
        observations = self._state["observations"].get(_order_key(client_order_id=client_order_id, exchange_order_id=exchange_order_id), [])
        for row in reversed(observations):
            if row.get("source") == "REST":
                return dict(row)
        return dict(observations[-1]) if observations else None

    def conflicts(self, *, client_order_id: str | None = None, exchange_order_id: str | None = None) -> list[dict[str, Any]]:
        observations = self._state["observations"].get(_order_key(client_order_id=client_order_id, exchange_order_id=exchange_order_id), [])
        rest_statuses = {row.get("status") for row in observations if row.get("source") == "REST"}
        if not rest_statuses:
            return []
        return [dict(row) for row in observations if row.get("source") != "REST" and row.get("status") not in rest_statuses]

    def _empty_state(self) -> dict[str, Any]:
        return {"observations": {}}


class CancelReplaceCoordinator(JsonStateStore):
    def request_cancel_unknown(self, *, original_order_id: str, target_quantity: float) -> dict[str, Any]:
        row = self._state["orders"].setdefault(original_order_id, {
            "original_order_id": original_order_id,
            "target_quantity": float(target_quantity),
            "original_filled_quantity": 0.0,
            "cancel_state": "CANCEL_UNKNOWN",
            "reconciled": False,
            "replacement_order_id": None,
            "events": [],
        })
        row["events"].append({"event_type": "cancel_request_unknown", "written_at": _now()})
        self._save()
        return dict(row)

    def record_original_fill(self, *, original_order_id: str, quantity: float, fill_id: str) -> dict[str, Any]:
        row = self._state["orders"][original_order_id]
        fill_key = f"{original_order_id}:{fill_id}"
        if fill_key not in self._state["fills"]:
            row["original_filled_quantity"] = _round_qty(float(row.get("original_filled_quantity") or 0.0) + float(quantity))
            self._state["fills"][fill_key] = {"quantity": float(quantity), "recorded_at": _now()}
            row["events"].append({"event_type": "late_original_fill", "fill_key": fill_key, "quantity": float(quantity), "written_at": _now()})
            self._save()
        return dict(row)

    def reconcile_original(self, *, original_order_id: str, status: str) -> dict[str, Any]:
        row = self._state["orders"][original_order_id]
        row["original_status"] = status
        row["reconciled"] = True
        row["events"].append({"event_type": "original_reconciled", "status": status, "written_at": _now()})
        self._save()
        return dict(row)

    def create_replacement(self, *, original_order_id: str, replacement_order_id: str) -> dict[str, Any]:
        row = self._state["orders"][original_order_id]
        if not row.get("reconciled"):
            raise CancelReplaceAmbiguityError(original_order_id)
        remaining = max(0.0, _round_qty(float(row["target_quantity"]) - float(row.get("original_filled_quantity") or 0.0)))
        row["replacement_order_id"] = replacement_order_id
        row["replacement_quantity"] = remaining
        row["events"].append({
            "event_type": "replacement_created",
            "replacement_order_id": replacement_order_id,
            "replacement_quantity": remaining,
            "written_at": _now(),
        })
        self._save()
        return dict(row)

    def _empty_state(self) -> dict[str, Any]:
        return {"orders": {}, "fills": {}}


class LiveOutageCoordinator:
    def __init__(
        self,
        *,
        evidence_store: RuntimeEvidenceStore,
        reservation_store: ReservationStore,
        ledger: OrderFillLedger,
        quarantine_store: QuarantineStore,
        backoff: RateLimitBackoff | None = None,
        observation_store: ExchangeObservationStore | None = None,
    ) -> None:
        self.evidence_store = evidence_store
        self.reservation_store = reservation_store
        self.ledger = ledger
        self.quarantine_store = quarantine_store
        self.backoff = backoff
        self.observation_store = observation_store
        self._degradations: set[str] = set()
        self._submit_unknown: dict[str, dict[str, Any]] = {}

    def mark_submit_unknown(self, *, reservation_id: str, client_order_id: str, symbol: str) -> LiveOutageResult:
        self._submit_unknown[client_order_id] = {
            "state": SUBMIT_UNKNOWN,
            "reservation_id": reservation_id,
            "client_order_id": client_order_id,
            "symbol": symbol,
            "updated_at": _now(),
        }
        self._audit("submit_unknown", client_order_id, self._submit_unknown[client_order_id])
        return LiveOutageResult(SUBMIT_UNKNOWN, changed=True, details=dict(self._submit_unknown[client_order_id]))

    def reconcile_submit_timeout(
        self,
        *,
        reservation_id: str,
        client_order_id: str,
        symbol: str,
        exchange_lookup: Callable[[str], Sequence[Mapping[str, Any]]],
        decision_id: str | None = None,
        prediction_id: str | None = None,
    ) -> LiveOutageResult:
        self.mark_submit_unknown(reservation_id=reservation_id, client_order_id=client_order_id, symbol=symbol)
        candidates = [dict(row) for row in exchange_lookup(client_order_id)]
        if not candidates:
            self._degradations.add(RECONCILIATION_UNAVAILABLE)
            self._audit("submit_timeout_reconcile", client_order_id, {"status": "retry_lookup_deferred"})
            return LiveOutageResult("retry_lookup_deferred", details={"client_order_id": client_order_id})
        if len(candidates) > 1:
            quarantine = self.quarantine_store.create(
                reason_code="submit_timeout_multiple_candidates",
                severity="critical",
                symbol=symbol,
                client_order_id=client_order_id,
                exchange_order_candidates=candidates,
                reservation_id=reservation_id,
                decision_id=decision_id,
                prediction_id=prediction_id,
                local_state=self._submit_unknown.get(client_order_id),
                exchange_observations=candidates,
                recommended_actions=["ACKNOWLEDGE", "ATTACH_EXISTING_ORDER", "CONFIRM_NOT_SUBMITTED", "ESCALATE"],
            )
            self._audit("submit_timeout_reconcile", client_order_id, {"status": "quarantined", "quarantine_id": quarantine["quarantine_id"]})
            return LiveOutageResult("quarantined", changed=True, details=quarantine)

        order = candidates[0]
        order.setdefault("client_order_id", client_order_id)
        self.ledger.record_order(order)
        reservation = self.reservation_store.attach_order(
            reservation_id,
            client_order_id=client_order_id,
            exchange_order_id=_string_or_none(order.get("exchange_order_id") or order.get("id")),
        )
        self._audit("submit_timeout_reconcile", client_order_id, {"status": "attached", "exchange_order": order})
        return LiveOutageResult("attached", changed=True, details=reservation.to_dict() if reservation else {})

    def classify_exchange_error(self, *, channel: str, error: BaseException | str) -> str:
        text = str(error).lower()
        if "market" in channel or "websocket" in channel or "stale" in text:
            state = MARKET_DATA_DEGRADED
        elif "reconcile" in channel or "open order" in channel or "rest" in channel:
            state = RECONCILIATION_UNAVAILABLE
        elif "order" in channel or "submit" in channel or "cancel" in channel:
            state = ORDER_CHANNEL_DEGRADED
        else:
            state = EXCHANGE_UNAVAILABLE if any(token in text for token in ("dns", "tls", "maintenance", "unavailable")) else ORDER_CHANNEL_DEGRADED
        self._degradations.add(state)
        self._audit("exchange_degradation", state, {"channel": channel, "error": str(error)})
        return state

    def record_rate_limit(self, *, scope: str, retry_after_seconds: float | None = None, error_code: str = "HTTP_429", weight: int | None = None) -> dict[str, Any]:
        if self.backoff is None:
            raise RuntimeError("rate-limit backoff store not configured")
        row = self.backoff.record_rate_limit(
            scope=scope,
            retry_after_seconds=retry_after_seconds,
            error_code=error_code,
            weight=weight,
        )
        self._degradations.add(ORDER_CHANNEL_DEGRADED)
        self._audit("rate_limit", scope, row)
        return row

    def record_observation(
        self,
        *,
        source: str,
        status: str,
        symbol: str,
        client_order_id: str | None = None,
        exchange_order_id: str | None = None,
        payload: Mapping[str, Any] | None = None,
    ) -> LiveOutageResult:
        if self.observation_store is None:
            raise RuntimeError("observation store not configured")
        row = self.observation_store.record(
            source=source,
            status=status,
            client_order_id=client_order_id,
            exchange_order_id=exchange_order_id,
            payload=payload,
        )
        conflicts = self.observation_store.conflicts(client_order_id=client_order_id, exchange_order_id=exchange_order_id)
        if conflicts:
            quarantine = self.quarantine_store.create(
                reason_code="ws_rest_order_state_conflict",
                severity="medium",
                symbol=symbol,
                client_order_id=client_order_id,
                exchange_observations=conflicts + [row],
                recommended_actions=["ACKNOWLEDGE", "RECONCILE_FILL", "ESCALATE"],
            )
            return LiveOutageResult("rest_authoritative_conflict_recorded", changed=True, details=quarantine)
        return LiveOutageResult("observation_recorded", changed=True, details=row)

    def health_snapshot(self, *, symbol: str = "BTCUSDT", rate_limit_scope: str = "exchange") -> dict[str, Any]:
        rate_limited = self.backoff.is_rate_limited(rate_limit_scope) if self.backoff is not None else False
        unresolved = self.quarantine_store.unresolved()
        entry_blocked = (
            bool(self._degradations)
            or self.quarantine_store.blocks_entries(symbol=symbol)
            or rate_limited
        )
        return {
            "entry_blocked": entry_blocked,
            "rate_limited": rate_limited,
            "degraded_components": sorted(self._degradations),
            "unresolved_quarantine_count": len(unresolved),
            "rate_limit_scope": rate_limit_scope,
            "authority": {"reconciliation": REST_AUTHORITY, "fast_updates": WS_FAST_PATH, "ledger": "APPEND_ONLY"},
            "priority_allowed": {
                priority: (self.backoff.priority_allowed(scope=rate_limit_scope, priority=priority) if self.backoff is not None else True)
                for priority in PRIORITY_ORDER
            },
        }

    def _audit(self, event_type: str, record_id: str, payload: Mapping[str, Any]) -> None:
        self.evidence_store.append_audit_event({
            "event_type": event_type,
            "record_id": record_id,
            **dict(payload),
        })


def _stable_id(prefix: str, value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"


def _order_key(*, client_order_id: str | None = None, exchange_order_id: str | None = None) -> str:
    if exchange_order_id:
        return f"exchange_order_id:{exchange_order_id}"
    if client_order_id:
        return f"client_order_id:{client_order_id}"
    raise ValueError("order observation requires client_order_id or exchange_order_id")


def _string_or_none(value: Any) -> str | None:
    if value is None or value == "":
        return None
    return str(value)


def _parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _round_qty(value: float) -> float:
    return round(value, 12)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
