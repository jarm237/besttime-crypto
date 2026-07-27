"""Crash-boundary recovery helpers for execution/runtime replay evidence."""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from btc_scraper.execution.order_fill_ledger import OrderFillLedger
from btc_scraper.execution.reservation_store import ReservationRecord, ReservationStore
from btc_scraper.ml_engine.runtime_evidence_store import RuntimeEvidenceStore
from btc_scraper.trading.decision_types import ReservationStatus


@dataclass(frozen=True)
class RecoveryResult:
    status: str
    boundary: str
    record_id: str
    changed: bool = False
    details: dict[str, Any] = field(default_factory=dict)


class RecoveryCoordinator:
    """Idempotent recovery operations around the trade lifecycle boundaries."""

    def __init__(
        self,
        *,
        evidence_store: RuntimeEvidenceStore,
        reservation_store: ReservationStore,
        ledger: OrderFillLedger,
    ) -> None:
        self.evidence_store = evidence_store
        self.reservation_store = reservation_store
        self.ledger = ledger

    def recover_final_decision(
        self,
        prediction_id: str,
        decision_factory: Callable[[Mapping[str, Any]], Mapping[str, Any]],
    ) -> RecoveryResult:
        existing = self.evidence_store.get_final_decision_for_prediction(prediction_id)
        if existing:
            return RecoveryResult("already_recovered", "prediction_to_decision", prediction_id, details=existing)

        prediction = self.evidence_store.get_prediction(prediction_id)
        if prediction is None:
            self.evidence_store.quarantine_record("predictions", prediction_id, "missing_prediction_for_recovery")
            return RecoveryResult("quarantined", "prediction_to_decision", prediction_id)

        decision = dict(decision_factory(prediction))
        decision.setdefault("decision_id", _stable_id("ed", prediction_id))
        decision["prediction_id"] = prediction_id
        for key in ("model_name", "model_version", "artifact_sha256", "feature_schema_version", "symbol", "timeframe", "side"):
            if prediction.get(key) is not None:
                decision.setdefault(key, prediction.get(key))
        self.evidence_store.append_final_decision(decision)
        self._audit("prediction_to_decision", "decision_recovered", decision["decision_id"])
        return RecoveryResult("recovered", "prediction_to_decision", decision["decision_id"], changed=True, details=decision)

    def recover_reservation_for_decision(
        self,
        decision: Mapping[str, Any],
        *,
        symbol: str,
        side: str,
        notional_usdt: float,
        ttl_seconds: int = 60,
    ) -> RecoveryResult:
        decision_id = str(decision.get("entry_decision_id") or decision.get("decision_id") or "")
        if not decision_id:
            raise ValueError("decision_id required for reservation recovery")
        decision_status = str(decision.get("status") or "").lower()
        if decision_status in {"rejected", "expired", "cancelled"}:
            self._audit("decision_to_reservation", "decision_not_executable", decision_id)
            return RecoveryResult("skipped_non_executable_decision", "decision_to_reservation", decision_id)

        existing_for_decision = self.reservation_store.get_by_entry_decision_id(decision_id)
        if existing_for_decision:
            return RecoveryResult(
                "already_recovered",
                "decision_to_reservation",
                existing_for_decision.reservation_id,
                details=existing_for_decision.to_dict(),
            )

        idempotency_key = str(decision.get("idempotency_key") or _stable_id("idem", decision_id))
        reservation_id = str(decision.get("reservation_id") or _stable_id("res", idempotency_key))
        record, created = self.reservation_store.reserve(
            reservation_id=reservation_id,
            idempotency_key=idempotency_key,
            entry_decision_id=decision_id,
            symbol=symbol,
            side=side.lower(),
            reserved_notional=float(notional_usdt),
            ttl_seconds=ttl_seconds,
        )
        self._audit("decision_to_reservation", "reservation_recovered" if created else "reservation_reused", record.reservation_id)
        return RecoveryResult(
            "recovered" if created else "already_recovered",
            "decision_to_reservation",
            record.reservation_id,
            changed=created,
            details=record.to_dict(),
        )

    def recover_pending_reservation(self, reservation_id: str, *, now: datetime | None = None) -> RecoveryResult:
        record = self.reservation_store.get_reservation(reservation_id)
        if record is None:
            return RecoveryResult("missing", "reservation_to_submit", reservation_id)
        if record.status != ReservationStatus.PENDING:
            return RecoveryResult("already_terminal", "reservation_to_submit", reservation_id, details=record.to_dict())

        observed_at = now or datetime.now(timezone.utc)
        expires_at = datetime.fromisoformat(record.expires_at)
        if expires_at <= observed_at:
            released = self.reservation_store.release(reservation_id)
            self._audit("reservation_to_submit", "expired_reservation_released", reservation_id)
            return RecoveryResult("released_expired", "reservation_to_submit", reservation_id, changed=True, details=released.to_dict() if released else {})
        return RecoveryResult("ready_to_resume_submit", "reservation_to_submit", reservation_id, details=record.to_dict())

    def reconcile_ambiguous_submit(
        self,
        *,
        reservation_id: str,
        client_order_id: str,
        exchange_lookup: Callable[[str], Sequence[Mapping[str, Any]]],
    ) -> RecoveryResult:
        candidates = [dict(row) for row in exchange_lookup(client_order_id)]
        if not candidates:
            self._audit("ambiguous_submit", "retry_deferred_no_exchange_match", client_order_id)
            return RecoveryResult("retry_deferred", "ambiguous_submit", client_order_id)
        if len(candidates) > 1:
            self.evidence_store.quarantine_record("audit_events", client_order_id, "ambiguous_submit_multiple_candidates")
            self._audit("ambiguous_submit", "quarantined_multiple_exchange_matches", client_order_id, {"candidate_count": len(candidates)})
            return RecoveryResult("quarantined", "ambiguous_submit", client_order_id, details={"candidate_count": len(candidates)})

        order = candidates[0]
        order.setdefault("client_order_id", client_order_id)
        self.ledger.record_order(order)
        attached = self.reservation_store.attach_order(
            reservation_id,
            client_order_id=client_order_id,
            exchange_order_id=_string_or_none(order.get("exchange_order_id") or order.get("id")),
        )
        self._audit("ambiguous_submit", "exchange_order_attached", client_order_id)
        return RecoveryResult("attached", "ambiguous_submit", client_order_id, changed=True, details=attached.to_dict() if attached else {})

    def replay_fill(self, fill: Mapping[str, Any]) -> RecoveryResult:
        result = self.ledger.record_fill(fill)
        status = str(result.get("status"))
        changed = status in {"pending_order", "linked", "quarantined_conflict"}
        self._audit("partial_fill_replay", status, str(result.get("fill_key")))
        return RecoveryResult(status, "partial_fill_replay", str(result.get("fill_key")), changed=changed, details=dict(result))

    def apply_fill_to_position(
        self,
        *,
        projection_store: "PositionProjectionStore",
        position_id: str,
        order: Mapping[str, Any],
        fill: Mapping[str, Any],
    ) -> RecoveryResult:
        result = projection_store.apply_fill_once(position_id=position_id, order=order, fill=fill)
        self._audit("fill_to_position", result["status"], position_id)
        return RecoveryResult(result["status"], "fill_to_position", position_id, changed=result["changed"], details=result)

    def recover_outcome(self, outcome: Mapping[str, Any]) -> RecoveryResult:
        outcome_id = str(outcome["outcome_id"])
        self.evidence_store.append_outcome_link(outcome)
        self._audit("position_to_outcome", "outcome_linked", outcome_id)
        return RecoveryResult("linked", "position_to_outcome", outcome_id, changed=True)

    def _audit(self, boundary: str, status: str, record_id: str, extra: Mapping[str, Any] | None = None) -> None:
        self.evidence_store.append_audit_event({
            "event_type": "recovery_event",
            "boundary": boundary,
            "status": status,
            "record_id": record_id,
            **dict(extra or {}),
        })


class PositionProjectionStore:
    """Small persistent projection used to prove fill replay idempotency."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._state = self._load()

    def apply_fill_once(self, *, position_id: str, order: Mapping[str, Any], fill: Mapping[str, Any]) -> dict[str, Any]:
        fill_key = _fill_key(fill)
        position = self._state["positions"].setdefault(position_id, {
            "position_id": position_id,
            "prediction_id": order.get("prediction_id") or fill.get("prediction_id"),
            "client_order_id": order.get("client_order_id") or fill.get("client_order_id"),
            "exchange_order_id": order.get("exchange_order_id") or fill.get("exchange_order_id"),
            "qty": 0.0,
            "notional": 0.0,
            "fee": 0.0,
            "avg_price": 0.0,
            "fill_keys": [],
        })
        if fill_key in self._state["applied_fills"]:
            return {"status": "already_applied", "changed": False, "fill_key": fill_key, "position": dict(position)}

        qty = float(fill.get("qty") or fill.get("quantity") or 0.0)
        price = float(fill.get("price") or 0.0)
        fee = float(fill.get("fee") or 0.0)
        position["qty"] = round(float(position.get("qty", 0.0)) + qty, 12)
        position["notional"] = round(float(position.get("notional", 0.0)) + qty * price, 12)
        position["fee"] = round(float(position.get("fee", 0.0)) + fee, 12)
        position["avg_price"] = position["notional"] / position["qty"] if position["qty"] else 0.0
        position.setdefault("fill_keys", []).append(fill_key)
        self._state["applied_fills"][fill_key] = {"position_id": position_id, "applied_at": _now()}
        self._save()
        return {"status": "applied", "changed": True, "fill_key": fill_key, "position": dict(position)}

    def snapshot(self) -> dict[str, Any]:
        return json.loads(json.dumps(self._state, sort_keys=True))

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"positions": {}, "applied_fills": {}}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _save(self) -> None:
        tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        with tmp_path.open("w", encoding="utf-8") as handle:
            json.dump(self._state, handle, ensure_ascii=False, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, self.path)


def _stable_id(prefix: str, value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"


def _fill_key(fill: Mapping[str, Any]) -> str:
    for field_name in ("exchange_trade_id", "trade_id", "fill_id"):
        value = _string_or_none(fill.get(field_name))
        if value:
            return f"{field_name}:{value}"
    return _stable_id("fill", json.dumps(dict(fill), sort_keys=True, default=str))


def _string_or_none(value: Any) -> str | None:
    if value is None or value == "":
        return None
    return str(value)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
