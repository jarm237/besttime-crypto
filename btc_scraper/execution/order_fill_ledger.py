"""Persistent order/fill ledger for out-of-order execution events.

This ledger is intentionally small: it preserves fills that arrive before their
order event, then reconciles them by stable exchange/client IDs after restart.
"""
from __future__ import annotations

import json
import os
from json import JSONDecodeError
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


class LedgerStateCorruptError(ValueError):
    pass


class OrderFillLedger:
    single_writer_only = True

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._state = self._load()

    def record_fill(self, fill: Mapping[str, Any]) -> dict[str, Any]:
        row = dict(fill)
        fill_key = _fill_key(row)
        order_key = _order_key(row)
        existing = self._state["fills"].get(fill_key)
        if existing:
            return {"status": existing["status"], "fill_key": fill_key, "order_key": existing.get("order_key")}

        stored = {
            **row,
            "fill_key": fill_key,
            "order_key": order_key,
            "status": "pending_order",
            "recorded_at": _now(),
        }
        matching_order_keys = self._matching_order_keys(stored)
        if len(matching_order_keys) > 1:
            stored["status"] = "quarantined_conflict"
            stored["conflict_order_keys"] = sorted(matching_order_keys)
            self._state["fills"][fill_key] = stored
            self._state["conflicts"][fill_key] = stored
            self._save()
            return {"status": stored["status"], "fill_key": fill_key, "conflict_order_keys": stored["conflict_order_keys"]}
        if matching_order_keys:
            resolved_order_key = next(iter(matching_order_keys))
            stored["order_key"] = resolved_order_key
            stored["status"] = "linked"
            self._state["orders"][resolved_order_key].setdefault("fill_keys", []).append(fill_key)
        else:
            self._state["pending_fills"][fill_key] = stored

        self._state["fills"][fill_key] = stored
        self._dedupe_order_fills()
        self._save()
        return {"status": stored["status"], "fill_key": fill_key, "order_key": order_key}

    def record_order(self, order: Mapping[str, Any]) -> dict[str, Any]:
        row = dict(order)
        order_key = _order_key(row)
        existing = self._state["orders"].get(order_key)
        if existing is None:
            existing = {**row, "order_key": order_key, "fill_keys": [], "recorded_at": _now()}
            self._state["orders"][order_key] = existing
        else:
            existing.update({key: value for key, value in row.items() if value not in (None, "")})

        resolved = 0
        for fill_key, fill in list(self._state["pending_fills"].items()):
            matching_order_keys = self._matching_order_keys(fill)
            if len(matching_order_keys) > 1:
                fill["status"] = "quarantined_conflict"
                fill["conflict_order_keys"] = sorted(matching_order_keys)
                self._state["fills"][fill_key] = fill
                self._state["conflicts"][fill_key] = fill
                del self._state["pending_fills"][fill_key]
                continue
            if order_key in matching_order_keys:
                fill["status"] = "linked"
                fill["order_key"] = order_key
                self._state["fills"][fill_key] = fill
                existing.setdefault("fill_keys", []).append(fill_key)
                del self._state["pending_fills"][fill_key]
                resolved += 1

        self._dedupe_order_fills()
        self._save()
        return {"status": "linked" if existing.get("fill_keys") else "order_recorded", "order_key": order_key, "resolved_fill_count": resolved}

    def snapshot(self) -> dict[str, Any]:
        return {
            "order_count": len(self._state["orders"]),
            "fill_count": len(self._state["fills"]),
            "pending_fill_count": len(self._state["pending_fills"]),
            "conflict_count": len(self._state["conflicts"]),
            "single_writer_only": self.single_writer_only,
            "orders": json.loads(json.dumps(self._state["orders"])),
            "fills": json.loads(json.dumps(self._state["fills"])),
            "pending_fills": json.loads(json.dumps(self._state["pending_fills"])),
            "conflicts": json.loads(json.dumps(self._state["conflicts"])),
        }

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return _empty_state()
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except JSONDecodeError as exc:
            raise LedgerStateCorruptError(f"Corrupt order/fill ledger state: {self.path}") from exc
        return {
            "orders": dict(payload.get("orders") or {}),
            "fills": dict(payload.get("fills") or {}),
            "pending_fills": dict(payload.get("pending_fills") or {}),
            "conflicts": dict(payload.get("conflicts") or {}),
        }

    def _save(self) -> None:
        tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        with tmp_path.open("w", encoding="utf-8") as handle:
            json.dump(self._state, handle, ensure_ascii=False, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, self.path)

    def _dedupe_order_fills(self) -> None:
        for order in self._state["orders"].values():
            seen: set[str] = set()
            fill_keys = []
            for fill_key in order.get("fill_keys") or []:
                if fill_key not in seen:
                    seen.add(fill_key)
                    fill_keys.append(fill_key)
            order["fill_keys"] = fill_keys

    def _matching_order_keys(self, row: Mapping[str, Any]) -> set[str]:
        return {key for key, order in self._state["orders"].items() if _same_order(order, row)}


def _empty_state() -> dict[str, Any]:
    return {"orders": {}, "fills": {}, "pending_fills": {}, "conflicts": {}}


def _fill_key(row: Mapping[str, Any]) -> str:
    for field in ("exchange_trade_id", "trade_id", "fill_id"):
        value = _string_or_none(row.get(field))
        if value:
            return f"{field}:{value}"
    order_key = _order_key(row)
    timestamp = _string_or_none(row.get("timestamp") or row.get("event_time"))
    return f"{order_key}:fill:{timestamp or 'unknown'}"


def _order_key(row: Mapping[str, Any]) -> str:
    for field in ("exchange_order_id", "client_order_id"):
        value = _string_or_none(row.get(field))
        if value:
            return f"{field}:{value}"
    value = _string_or_none(row.get("order_id"))
    if value:
        return f"order_id:{value}"
    raise ValueError("missing_order_business_key")


def _same_order(order: Mapping[str, Any], fill: Mapping[str, Any]) -> bool:
    for field in ("exchange_order_id", "client_order_id", "order_id"):
        left = _string_or_none(order.get(field))
        right = _string_or_none(fill.get(field))
        if left and right and left == right:
            return True
    return False


def _string_or_none(value: Any) -> str | None:
    if value is None or value == "":
        return None
    return str(value)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
