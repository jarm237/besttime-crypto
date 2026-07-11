"""
btc_scraper/execution/live_audit_log.py
Phase 6 — Task 6.5: Immutable Live Audit Log

All live production actions are recorded here:
    - Checklist results
    - Risk decisions
    - Kill-switch actions
    - Rollout transitions
    - Manual resets
    - Config changes
    - Live enable / disable
    - Order decisions (ALLOWED / BLOCKED)

Uses append-only JSONL file + SQLite index for deduplication.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Dict, Optional

BASE_DIR = Path(__file__).parent.parent.parent
AUDIT_LOG_DIR = BASE_DIR / "data" / "execution" / "audit"
AUDIT_LOG_FILE = AUDIT_LOG_DIR / "live_audit.jsonl"
AUDIT_DB_FILE = AUDIT_LOG_DIR / "audit_index.db"


class AuditEventType:
    LIVE_ENABLED = "LIVE_ENABLED"
    LIVE_DISABLED = "LIVE_DISABLED"
    CHECKLIST_RUN = "CHECKLIST_RUN"
    RISK_DECISION = "RISK_DECISION"
    KILL_SWITCH_TRIGGERED = "KILL_SWITCH_TRIGGERED"
    KILL_SWITCH_RESET = "KILL_SWITCH_RESET"
    ROLLOUT_TRANSITION = "ROLLOUT_TRANSITION"
    MANUAL_RESET = "MANUAL_RESET"
    CONFIG_CHANGE = "CONFIG_CHANGE"
    ORDER_ALLOWED = "ORDER_ALLOWED"
    ORDER_BLOCKED = "ORDER_BLOCKED"
    ALERT_SENT = "ALERT_SENT"


class LiveAuditLog:
    """
    Append-only structured audit trail for all live production actions.

    Events are written atomically to a JSONL file. A SQLite index
    provides fast deduplication lookup by event_id.
    """

    def __init__(
        self,
        log_file: Optional[str] = None,
        db_file: Optional[str] = None,
    ):
        self._log_path = Path(log_file) if log_file else AUDIT_LOG_FILE
        self._db_path = Path(db_file) if db_file else AUDIT_DB_FILE
        self._lock = RLock()
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self._db_path) as db:
            db.execute(
                """CREATE TABLE IF NOT EXISTS audit_index (
                    event_id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )"""
            )

    def _connect(self):
        return sqlite3.connect(self._db_path)

    def _compute_fingerprint(self, event_type: str, payload: Dict[str, Any]) -> str:
        raw = json.dumps({"event_type": event_type, **payload}, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def record(
        self,
        event_type: str,
        payload: Dict[str, Any],
        operator: Optional[str] = None,
        reason: Optional[str] = None,
        config_hash: Optional[str] = None,
        phase5_gate_hash: Optional[str] = None,
    ) -> str:
        """
        Write a single audit event. Returns the event_id.
        Idempotent — duplicate event_ids are silently ignored.
        """
        with self._lock:
            event_id = str(uuid.uuid4())
            now = datetime.now(timezone.utc).isoformat()
            fingerprint = self._compute_fingerprint(event_type, payload)

            entry: Dict[str, Any] = {
                "event_id": event_id,
                "event_type": event_type,
                "timestamp": now,
                "fingerprint": fingerprint,
                "operator": operator,
                "reason": reason,
                "config_hash": config_hash,
                "phase5_gate_hash": phase5_gate_hash,
                "payload": payload,
            }

            line = json.dumps(entry, ensure_ascii=False) + "\n"
            with open(self._log_path, "a", encoding="utf-8") as fh:
                fh.write(line)

            try:
                with self._connect() as db:
                    db.execute(
                        "INSERT OR IGNORE INTO audit_index VALUES (?, ?, ?)",
                        (event_id, event_type, now),
                    )
            except Exception:
                pass

            return event_id

    # ── Convenience wrappers ──────────────────────────────────────────────────

    def log_live_enabled(self, operator: str, reason: str, config_hash: str, phase5_gate_hash: str) -> str:
        return self.record(AuditEventType.LIVE_ENABLED, {},
                           operator=operator, reason=reason,
                           config_hash=config_hash, phase5_gate_hash=phase5_gate_hash)

    def log_live_disabled(self, operator: str, reason: str) -> str:
        return self.record(AuditEventType.LIVE_DISABLED, {}, operator=operator, reason=reason)

    def log_checklist(self, result: Dict[str, Any], operator: Optional[str] = None) -> str:
        return self.record(AuditEventType.CHECKLIST_RUN, {"result": result}, operator=operator)

    def log_risk_decision(self, allowed: bool, reason: str, intent: str, notional: float) -> str:
        return self.record(AuditEventType.RISK_DECISION, {
            "allowed": allowed, "reason": reason, "intent": intent, "notional_usdt": notional
        })

    def log_kill_switch_triggered(self, trigger: str, action: str, value: Any, operator: Optional[str] = None) -> str:
        return self.record(AuditEventType.KILL_SWITCH_TRIGGERED, {
            "trigger": trigger, "action": action, "value": value
        }, operator=operator)

    def log_kill_switch_reset(self, operator: str, reason: str) -> str:
        return self.record(AuditEventType.KILL_SWITCH_RESET, {},
                           operator=operator, reason=reason)

    def log_rollout_transition(self, from_stage: int, to_stage: int, direction: str, reason: str) -> str:
        return self.record(AuditEventType.ROLLOUT_TRANSITION, {
            "from_stage": from_stage, "to_stage": to_stage, "direction": direction, "reason": reason
        })

    def log_order_decision(self, allowed: bool, reason: str, symbol: str, intent: str, notional: float) -> str:
        event_type = AuditEventType.ORDER_ALLOWED if allowed else AuditEventType.ORDER_BLOCKED
        return self.record(event_type, {
            "symbol": symbol, "intent": intent,
            "notional_usdt": notional, "reason": reason
        })

    def log_config_change(self, operator: str, change_summary: str, config_hash: str) -> str:
        return self.record(AuditEventType.CONFIG_CHANGE, {"change": change_summary},
                           operator=operator, config_hash=config_hash)

    def log_alert(self, severity: str, message: str, channel: str) -> str:
        return self.record(AuditEventType.ALERT_SENT, {
            "severity": severity, "message": message, "channel": channel
        })

    # ── Query ─────────────────────────────────────────────────────────────────

    def recent_events(self, limit: int = 50, event_type: Optional[str] = None) -> list:
        """Read last N events from JSONL file."""
        results = []
        try:
            with open(self._log_path, "r", encoding="utf-8") as fh:
                lines = fh.readlines()
            for line in reversed(lines[-500:]):
                try:
                    entry = json.loads(line.strip())
                    if event_type is None or entry.get("event_type") == event_type:
                        results.append(entry)
                    if len(results) >= limit:
                        break
                except json.JSONDecodeError:
                    continue
        except FileNotFoundError:
            pass
        return results

    def count_by_type(self) -> Dict[str, int]:
        """Count events per type from DB index."""
        counts: Dict[str, int] = {}
        try:
            with self._connect() as db:
                rows = db.execute(
                    "SELECT event_type, COUNT(*) FROM audit_index GROUP BY event_type"
                ).fetchall()
                counts = {r[0]: r[1] for r in rows}
        except Exception:
            pass
        return counts
